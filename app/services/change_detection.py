"""
Change detection.

`record_changes(docs)` is called by the ingestion storage layer for every
batch of RawDocuments it persists. It maintains two tables:

  source_versions  — immutable history (one row per unique
                     `(source_url, content_hash)`)
  change_events    — one row per detected `created` / `modified`
                     transition between two source_versions

This module is deliberately *deterministic and LLM-free*. The
`ChangeEvent.summary` field is left null; a separate downstream worker
(the L3 significance scorer) will populate it.

Batch performance
-----------------
All persistence happens in ONE Session with two upfront batch prefetches
(same-hash check + latest-per-URL lookup), independent of batch size.
Per-doc SAVEPOINTs preserve the "one bad doc never aborts the batch"
guarantee. Scoring tasks are enqueued only AFTER commit so we never
enqueue work for events that haven't been durably persisted.

Public API
----------
record_changes(docs: Iterable[RawDocument]) -> dict
    Batch-process docs. Returns aggregate counters:
        {"created": int, "modified": int, "unchanged": int}
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime, timezone
from typing import Iterable, List, Optional
from uuid import uuid4

from sqlalchemy import tuple_
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

    Returns (unified_diff, added_chars, removed_chars).
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
        head = joined[: MAX_DIFF_CHARS // 2]
        tail = joined[-MAX_DIFF_CHARS // 2 :]
        joined = f"{head}\n… [diff truncated — {len(joined)} chars total] …\n{tail}"

    return joined, added, removed


def _prefetch_version_state(
    session: Session,
    docs: List[RawDocument],
) -> tuple[dict[str, SourceVersion], dict[tuple[str, str], SourceVersion]]:
    """
    Batch-load the version state needed to classify a whole batch of docs.

    Returns ``(latest_map, same_hash_map)``:
      * ``latest_map``    : {source_url: latest SourceVersion} — for diff base
      * ``same_hash_map`` : {(source_url, content_hash): SourceVersion} —
                            for "unchanged" detection

    Two queries total, regardless of batch size.
    """
    same_hash_keys = [(d.source_url, d.content_hash) for d in docs]
    same_hash_map: dict[tuple[str, str], SourceVersion] = {}
    if same_hash_keys:
        rows = session.exec(
            select(SourceVersion).where(
                tuple_(
                    SourceVersion.source_url,
                    SourceVersion.content_hash,
                ).in_(same_hash_keys)
            )
        ).all()
        same_hash_map = {(r.source_url, r.content_hash): r for r in rows}

    # Only docs whose hash is NEW to their URL need a latest-version lookup.
    urls_for_latest = list({
        d.source_url for d in docs
        if (d.source_url, d.content_hash) not in same_hash_map
    })
    latest_map: dict[str, SourceVersion] = {}
    if urls_for_latest:
        rows = session.exec(
            select(SourceVersion)
            .where(SourceVersion.source_url.in_(urls_for_latest))
            .order_by(
                SourceVersion.source_url,
                SourceVersion.last_seen_at.desc(),
            )
            .distinct(SourceVersion.source_url)  # PG DISTINCT ON
        ).all()
        latest_map = {r.source_url: r for r in rows}

    return latest_map, same_hash_map


def _apply_one(
    doc: RawDocument,
    session: Session,
    latest_map: dict[str, SourceVersion],
    same_hash_map: dict[tuple[str, str], SourceVersion],
    now: datetime,
    counts: dict[str, int],
) -> Optional[ChangeEvent]:
    """
    Process one doc within the caller's session using prefetch caches.

    Mutates ``counts`` and updates ``latest_map`` / ``same_hash_map`` so
    later docs in the same batch targeting the same URL see the
    just-inserted version.
    """
    key = (doc.source_url, doc.content_hash)
    existing = same_hash_map.get(key)
    if existing is not None:
        # Same content hash for this URL already on file — just bump
        # last_seen_at. No change event.
        existing.last_seen_at = now
        session.add(existing)
        counts["unchanged"] += 1
        return None

    latest = latest_map.get(doc.source_url)
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

    if latest is None:
        kind = "created"
        added_chars = len(doc.raw_text or "")
        removed_chars = 0
        diff_text: Optional[str] = None
    else:
        kind = "modified"
        diff_text, added_chars, removed_chars = _compute_diff(
            latest.raw_text or "", doc.raw_text or "",
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

    # Update prefetch caches so later docs in the same batch hitting
    # this URL or hash see the freshly-inserted version.
    latest_map[doc.source_url] = new_version
    same_hash_map[key] = new_version

    counts[kind] = counts.get(kind, 0) + 1
    logger.info(
        "change_event: kind=%s url=%s +%d -%d",
        kind, doc.source_url, added_chars, removed_chars,
    )
    return event


# ── Public API ────────────────────────────────────────────────────────────────

def record_changes(docs: Iterable[RawDocument]) -> dict:
    """
    Persist version history for a batch of docs and emit ChangeEvents
    for every content-hash transition.

    Returns aggregate counters::

        {"created": int, "modified": int, "unchanged": int}

    Safety guarantees
      * ONE session + ONE outer transaction for the whole batch.
      * Per-doc SAVEPOINTs isolate failures — one bad doc does not
        abort the batch.
      * Scoring tasks are enqueued only AFTER the batch commits. We
        never hand an event id to a worker before it is durable.
    """
    counts: dict[str, int] = {"created": 0, "modified": 0, "unchanged": 0}
    materialized: List[RawDocument] = [
        d for d in docs
        if d.source_url and d.content_hash and d.raw_text
    ]
    if not materialized:
        return counts

    now = _utcnow()
    new_event_ids: List[str] = []

    with Session(engine) as session:
        latest_map, same_hash_map = _prefetch_version_state(
            session, materialized,
        )

        for doc in materialized:
            try:
                with session.begin_nested():  # SAVEPOINT per doc
                    event = _apply_one(
                        doc, session,
                        latest_map, same_hash_map,
                        now, counts,
                    )
                    if event is not None:
                        new_event_ids.append(str(event.id))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "record_change failed for %s: %s", doc.source_url, exc,
                )
                continue

        session.commit()

    # ── Enqueue L3 scoring AFTER commit ──────────────────────────────
    # Best-effort. A Redis outage never blocks ingestion — events can
    # be backfilled later via scripts/score_backlog.py.
    if new_event_ids:
        try:
            from app.celery_app import score_change_event  # local: circular import
            for eid in new_event_ids:
                score_change_event.delay(eid)
        except Exception as enqueue_exc:  # noqa: BLE001
            logger.warning(
                "change_events emitted but scoring enqueue failed: %s",
                enqueue_exc,
            )

    logger.info(
        "record_changes: created=%d modified=%d unchanged=%d",
        counts["created"], counts["modified"], counts["unchanged"],
    )
    return counts
