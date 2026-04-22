"""
Change detection.

`record_change(doc)` is called by the ingestion storage layer for every
RawDocument it persists. It maintains two tables:

  source_versions  — immutable history (one row per unique
                     `(source_url, content_hash)`)
  change_events    — one row per detected `created` / `modified`
                     transition between two source_versions

This module is deliberately *deterministic and LLM-free*. The
`ChangeEvent.summary` field is left null; a separate downstream worker
(out of scope here) will populate it using whatever LLM is configured.

Public API
----------
record_change(doc: RawDocument) -> Optional[ChangeEvent]
    Called per-document after upsert. Returns a newly-inserted
    ChangeEvent on state transition, or None if the content hash is
    already the latest known version (i.e. nothing changed).

record_changes(docs: Iterable[RawDocument]) -> dict
    Convenience wrapper that calls `record_change` for each doc and
    returns aggregate counters:
        {"created": int, "modified": int, "unchanged": int}
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime, timezone
from typing import Iterable, List, Optional
from uuid import uuid4

from sqlmodel import Session, select

from app.database import engine
from app.models import ChangeEvent, RawDocument, SourceVersion

logger = logging.getLogger(__name__)

# Cap unified-diff storage per event so huge PDF swaps don't bloat the DB.
MAX_DIFF_CHARS = 100_000
DIFF_CONTEXT_LINES = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compute_diff(old_text: str, new_text: str) -> tuple[str, int, int]:
    """
    Compute a unified diff between two texts.

    Returns
    -------
    (unified_diff, added_chars, removed_chars)
        unified_diff : possibly-truncated unified diff text
        added_chars  : total chars in `+` lines (excluding the `+` marker)
        removed_chars: total chars in `-` lines (excluding the `-` marker)
    """
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()

    diff_iter = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="previous",
        tofile="current",
        lineterm="",
        n=DIFF_CONTEXT_LINES,
    )
    lines = list(diff_iter)

    added = 0
    removed = 0
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += len(line) - 1
        elif line.startswith("-"):
            removed += len(line) - 1

    joined = "\n".join(lines)
    if len(joined) > MAX_DIFF_CHARS:
        # Keep head + tail so both sides of the diff are visible.
        head = joined[: MAX_DIFF_CHARS // 2]
        tail = joined[-MAX_DIFF_CHARS // 2 :]
        joined = f"{head}\n… [diff truncated — {len(joined)} chars total] …\n{tail}"

    return joined, added, removed


# ── Public API ────────────────────────────────────────────────────────────────

def record_change(doc: RawDocument) -> Optional[ChangeEvent]:
    """
    Persist version history for `doc` and emit a ChangeEvent on transitions.

    Returns the new ChangeEvent, or None when the doc's content_hash is
    identical to the latest known version for that source_url (i.e.
    nothing changed — we only bump `last_seen_at`).
    """
    if not doc.source_url or not doc.content_hash or not doc.raw_text:
        return None

    now = _utcnow()

    with Session(engine) as session:
        # Most-recent version on file for this URL (by last_seen_at desc)
        latest = session.exec(
            select(SourceVersion)
            .where(SourceVersion.source_url == doc.source_url)
            .order_by(SourceVersion.last_seen_at.desc())
        ).first()

        # If the exact same hash for this URL already exists, just refresh
        # its last_seen_at. No change event.
        existing_same_hash = session.exec(
            select(SourceVersion).where(
                (SourceVersion.source_url == doc.source_url)
                & (SourceVersion.content_hash == doc.content_hash)
            )
        ).first()

        if existing_same_hash is not None:
            existing_same_hash.last_seen_at = now
            session.add(existing_same_hash)
            session.commit()
            return None

        # New content hash for this URL. Create a new version row.
        new_version = SourceVersion(
            id=uuid4(),
            source_url=doc.source_url,
            source_type=doc.source_type,
            content_hash=doc.content_hash,
            raw_text=doc.raw_text,
            title=doc.title,
            language=doc.language,
            page_count=getattr(doc, "page_count", None),
            pages=getattr(doc, "pages", None),
            artifact_uri=getattr(doc, "artifact_uri", None),
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(new_version)
        session.flush()  # need new_version.id before linking

        # Build the ChangeEvent
        if latest is None:
            kind = "created"
            added_chars = len(doc.raw_text or "")
            removed_chars = 0
            diff_text: Optional[str] = None
        else:
            kind = "modified"
            diff_text, added_chars, removed_chars = _compute_diff(
                latest.raw_text or "", doc.raw_text or ""
            )

        event = ChangeEvent(
            id=uuid4(),
            source_url=doc.source_url,
            new_version_id=new_version.id,
            prev_version_id=latest.id if latest is not None else None,
            diff_kind=kind,
            added_chars=added_chars,
            removed_chars=removed_chars,
            unified_diff=diff_text,
            detected_at=now,
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        logger.info(
            "change_event: kind=%s url=%s +%d -%d",
            kind, doc.source_url, added_chars, removed_chars,
        )

        # ── Enqueue Layer-3 scoring (best-effort, non-blocking) ───────
        # Celery broker is not a hard ingestion dependency. If Redis is
        # down or the task import fails, we log and continue — the event
        # can be backfilled later via scripts/score_backlog.py.
        try:
            from app.celery_app import score_change_event  # local to avoid circular import
            score_change_event.delay(str(event.id))
        except Exception as enqueue_exc:
            logger.warning(
                "change_event %s emitted but scoring enqueue failed: %s",
                event.id, enqueue_exc,
            )

        return event


def record_changes(docs: Iterable[RawDocument]) -> dict:
    """Call record_change on each doc; return aggregate counters."""
    counts = {"created": 0, "modified": 0, "unchanged": 0}
    materialized: List[RawDocument] = list(docs)
    for doc in materialized:
        try:
            ev = record_change(doc)
        except Exception as exc:  # never let change-detection break ingestion
            logger.exception(
                "record_change failed for %s: %s", doc.source_url, exc,
            )
            continue
        if ev is None:
            counts["unchanged"] += 1
        else:
            counts[ev.diff_kind] = counts.get(ev.diff_kind, 0) + 1
    logger.info(
        "record_changes: created=%d modified=%d unchanged=%d",
        counts["created"], counts["modified"], counts["unchanged"],
    )
    return counts
