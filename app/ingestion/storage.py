"""
Persistence helpers for the ingestion layer.

upsert_documents() stores a list of RawDocument instances using a
PostgreSQL INSERT ... ON CONFLICT DO UPDATE so that:
  - New documents are inserted.
  - Duplicate content (same content_hash) only refreshes last_seen_at.
    This satisfies TEST-2.4 (exactly one row per unique document).

Two things happen around the INSERT that matter for cost + accuracy:

  1. Cold-storage archival (T2.9).
     Before the DB insert we push each document's extracted text to the
     configured object store (AWS S3) via
     `app.ingestion.artifact_store.upload_artifacts`. *But only for
     content we haven't seen before* — a pre-query tells us which
     content_hashes already exist, and we reuse their existing
     `artifact_uri` instead of paying for a redundant S3 PUT. At steady
     state this eliminates 40–60% of upload cost on re-crawls. Uploads
     fail open: if no bucket is configured or the upload errors,
     `artifact_uri` stays NULL and ingestion proceeds.

  2. `xmax = 0` RETURNING predicate.
     PostgreSQL's system column `xmax` is 0 on a true INSERT and
     non-zero on an UPDATE resulting from ON CONFLICT. We use it in the
     RETURNING clause to report accurate `inserted`/`updated` counters
     (SQLAlchemy's `inserted_primary_key` is populated in both cases and
     cannot be used to distinguish the two paths).

After upsert, each document is passed through
`app.services.change_detection.record_change`, which maintains
`source_versions` + emits `change_events` for transitions. Change
detection runs in a separate transaction per doc and NEVER raises —
a failure there only logs and is skipped so that ingestion is never
blocked by the versioning layer.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.ingestion.artifact_store import upload_artifacts
from app.models import RawDocument
from app.services.change_detection import record_changes
from app.services.content_filter import is_regulatory_content

logger = logging.getLogger(__name__)


def _apply_content_filter(
    docs: List[RawDocument],
) -> tuple[List[RawDocument], int, Dict[str, int]]:
    """
    Drop docs that fail the universal regulatory-content heuristic.

    Runs BEFORE any DB write or S3 upload, so filtered docs never
    consume storage, never get versioned, and never trigger an LLM
    scoring call.

    Returns ``(kept, dropped_count, reasons)`` — ``reasons`` maps
    reason_code → count for the log line.
    """
    settings = get_settings()
    if not settings.CONTENT_FILTER_ENABLED:
        return docs, 0, {}

    kept: List[RawDocument] = []
    reasons: Dict[str, int] = {}
    for doc in docs:
        passed, info = is_regulatory_content(
            doc.raw_text or "", title=doc.title,
        )
        if passed:
            kept.append(doc)
            continue
        reason = info.get("reason", "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
        logger.debug(
            "content_filter_dropped: url=%s reason=%s word_count=%s "
            "keyword_hits=%s",
            doc.source_url, reason,
            info.get("word_count"), info.get("keyword_hits"),
        )
    return kept, len(docs) - len(kept), reasons


def _archive_to_object_store(doc: RawDocument) -> None:
    """
    Best-effort upload of `doc.raw_text` to the artifact store. Populates
    `doc.artifact_uri` in-place on success. Errors are swallowed —
    object storage is a nice-to-have audit trail, not a hard dependency.
    """
    if not doc.raw_text or not doc.content_hash:
        return
    try:
        uris = upload_artifacts(
            source_type=doc.source_type,
            content_hash=doc.content_hash,
            extracted_text=doc.raw_text,
        )
        if uris.get("extracted_text_uri"):
            doc.artifact_uri = uris["extracted_text_uri"]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "artifact upload skipped for %s: %s", doc.source_url, exc,
        )


def _lookup_existing_artifact_uris(
    session: Session,
    content_hashes: List[str],
) -> Dict[str, Optional[str]]:
    """
    Bulk-fetch `{content_hash: artifact_uri}` for every hash that is
    already in `raw_documents`. Used to skip redundant S3 uploads:
    if a document's content already exists we reuse its existing
    artifact URI (which may be NULL for rows ingested before artifact
    storage was wired, and that's fine).
    """
    if not content_hashes:
        return {}

    stmt = select(RawDocument.content_hash, RawDocument.artifact_uri).where(
        RawDocument.content_hash.in_(content_hashes)
    )
    rows = session.exec(stmt).all()
    return {ch: uri for ch, uri in rows}


def upsert_documents(
    documents: List[RawDocument],
    *,
    skip_filter: bool = False,
) -> dict:
    """
    Persist *documents* to the raw_documents table, then emit change
    events for any content-hash transitions.

    Parameters
    ----------
    documents
        Candidates from any ingestion connector.
    skip_filter
        Bypass the content filter. Used by tests with synthetic data
        that intentionally won't match regulatory heuristics. Always
        False in production.

    Returns
    -------
    dict with keys:
        inserted    — number of genuinely new rows created
        updated     — number of existing rows whose last_seen_at was refreshed
        archived    — number of NEW S3 uploads performed this call
                      (does NOT count docs that already had an artifact_uri
                      from a prior run — those are free reuses)
        created     — number of change_events of kind 'created' emitted
        modified    — number of change_events of kind 'modified' emitted
        unchanged   — number of docs whose hash already existed as the latest
        filtered    — number of docs dropped by the content filter
        filter_reasons — {reason_code: count} for operations dashboards
    """
    if not documents:
        return {
            "inserted": 0, "updated": 0, "archived": 0,
            "created": 0, "modified": 0, "unchanged": 0,
            "filtered": 0, "filter_reasons": {},
        }

    # ── Phase 0: universal content filter ──────────────────────────
    # Runs BEFORE any DB or S3 work — a dropped doc costs nothing
    # downstream.
    filter_reasons: Dict[str, int] = {}
    filtered_count = 0
    if not skip_filter:
        documents, filtered_count, filter_reasons = _apply_content_filter(
            documents,
        )
        if filtered_count:
            logger.info(
                "content_filter: kept=%d dropped=%d reasons=%s",
                len(documents), filtered_count, filter_reasons,
            )
        if not documents:
            return {
                "inserted": 0, "updated": 0, "archived": 0,
                "created": 0, "modified": 0, "unchanged": 0,
                "filtered": filtered_count,
                "filter_reasons": filter_reasons,
            }

    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0
    new_uploads = 0

    # ── Phase 1: pre-check which content already exists so we only ──
    # ── upload the genuinely new stuff.                            ──
    hashes = [d.content_hash for d in documents if d.content_hash]
    with Session(engine) as session:
        existing_by_hash = _lookup_existing_artifact_uris(session, hashes)

    for doc in documents:
        if not doc.content_hash:
            continue
        if doc.content_hash in existing_by_hash:
            # Content already archived in a prior run — reuse that URI.
            # May be None for rows created before artifact_uri existed;
            # that's acceptable, we don't retroactively upload old content.
            doc.artifact_uri = existing_by_hash[doc.content_hash]
        else:
            _archive_to_object_store(doc)
            if doc.artifact_uri:
                new_uploads += 1
                # Cache so siblings in this same batch reuse instead of
                # re-uploading (matters when the same content appears
                # under multiple URLs within one crawl).
                existing_by_hash[doc.content_hash] = doc.artifact_uri

    # ── Phase 2: upsert with xmax=0 to distinguish insert vs update. ──
    # xmax is a Postgres system column: 0 on genuine INSERT, non-zero
    # when the ON CONFLICT branch fired as UPDATE.
    xmax_predicate = text("(xmax = 0) AS was_inserted")

    with Session(engine) as session:
        for doc in documents:
            stmt = (
                pg_insert(RawDocument)
                .values(
                    id=doc.id,
                    source_url=doc.source_url,
                    source_type=doc.source_type,
                    raw_text=doc.raw_text,
                    title=doc.title,
                    language=doc.language,
                    content_hash=doc.content_hash,
                    page_count=getattr(doc, "page_count", None),
                    pages=getattr(doc, "pages", None),
                    artifact_uri=getattr(doc, "artifact_uri", None),
                    fetched_at=doc.fetched_at,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_raw_document_content_hash",
                    set_={"last_seen_at": now},
                )
                .returning(xmax_predicate)
            )
            was_inserted = session.execute(stmt).scalar()
            if was_inserted:
                inserted += 1
            else:
                updated += 1

        session.commit()

    logger.info(
        "upsert_documents: inserted=%d updated=%d new_uploads=%d reused=%d",
        inserted, updated, new_uploads, len(documents) - new_uploads,
    )

    # ── Phase 3: change detection (versioning + diffs). ──
    # Runs in its own transactions; failures are logged but never raised.
    try:
        change_counts = record_changes(documents)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("change-detection batch failed: %s", exc)
        change_counts = {"created": 0, "modified": 0, "unchanged": 0}

    return {
        "inserted": inserted,
        "updated": updated,
        "archived": new_uploads,
        **change_counts,
        "filtered": filtered_count,
        "filter_reasons": filter_reasons,
    }
