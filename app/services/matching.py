"""
M5 Alerting Engine — Matching Service.

Core function: ``match_event(event_id)``

When a ChangeEvent finishes M4 scoring, this service finds every active
UserSubscription that matches the event using a two-stage approach:

  Stage 1 — Deterministic metadata pre-filters (topic, countries,
            significance score).  Extremely fast — pure SQL WHERE clauses
            on indexed columns.

  Stage 2 — PostgreSQL full-text percolation.  The user's ``keyword_query``
            (stored as a raw ``tsquery`` string) is evaluated against the
            full document text using ``to_tsvector() @@ to_tsquery()``.
            This catches exact HS codes, chemical names, acronyms, and
            any specific term buried anywhere in the document.

Both stages execute in a **single SQL query** — no round-trips.  For each
matching subscription the engine inserts one row into the ``alerts`` table
(with ``ON CONFLICT DO NOTHING`` for idempotency).

Zero LLM cost.  Zero external infrastructure.  Runs on existing Postgres.
"""

from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

from sqlmodel import Session, text

from app.database import engine
from app.logging_setup import get_logger

log = get_logger(__name__)


# ── The core matching query ──────────────────────────────────────────────────
# This single SQL statement implements Stage 1 + Stage 2 in one pass.
#
# Stage 1 filters:
#   - topic overlap  (``&&`` array operator)
#   - origin_countries overlap
#   - destination_countries overlap
#   - significance score threshold
#
# Stage 2 percolation:
#   - full-text keyword match using ``to_tsvector @@ to_tsquery``
#
# NULL in any subscription column means "match any".
_MATCH_SQL = text("""
    SELECT
        us.id            AS subscription_id,
        us.user_email,
        us.keyword_query
    FROM user_subscriptions us
    WHERE us.is_active = TRUE
      -- Stage 1: structured metadata pre-filters
      AND (us.topics IS NULL
           OR us.topics && CAST(ARRAY[:event_topic] AS varchar[]))
      AND (us.origin_countries IS NULL
           OR :has_origins = FALSE
           OR us.origin_countries && CAST(STRING_TO_ARRAY(:event_origins_csv, ',') AS varchar[]))
      AND (us.destination_countries IS NULL
           OR :has_dests = FALSE
           OR us.destination_countries && CAST(STRING_TO_ARRAY(:event_dests_csv, ',') AS varchar[]))
      AND (:event_score >= us.min_significance)
      -- Stage 2: full-text keyword percolation
      AND (us.keyword_query IS NULL
           OR to_tsvector('english', :raw_text)
              @@ to_tsquery('english', us.keyword_query))
""")

# Insert an alert row; silently skip if the (sub, event) pair already exists.
_INSERT_ALERT_SQL = text("""
    INSERT INTO alerts (id, subscription_id, change_event_id,
                        matched_keywords, status)
    VALUES (gen_random_uuid(), :sub_id, :event_id,
            :matched_kw, 'unread')
    ON CONFLICT ON CONSTRAINT uq_alerts_subscription_event
    DO NOTHING
""")


def _extract_matched_terms(
    keyword_query: Optional[str],
    raw_text: str,
) -> list[str]:
    """
    Best-effort extraction of which user keywords actually appear in the
    document.  Used for XAI hit-highlighting in the UI.

    Parses the tsquery string for literal tokens and checks if they
    appear (case-insensitive) in the raw text.
    """
    if not keyword_query:
        return []

    # Pull bare words from the tsquery string.
    # "lithium & batteri:*" → ["lithium", "batteri"]
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_./-]*", keyword_query)
    text_lower = raw_text.lower()

    matched = []
    for token in tokens:
        # Skip tsquery operators that regex might have captured.
        if token.lower() in {"and", "or", "not"}:
            continue
        if token.lower() in text_lower:
            matched.append(token)
    return matched


def match_event(event_id: UUID) -> dict:
    """
    Find all active subscriptions that match the given ChangeEvent and
    insert alert rows.

    Returns ``{"status": "matched", "event_id": "...", "alerts_created": N}``.
    """
    import json
    from app.models import ChangeEvent, SourceVersion

    with Session(engine) as session:
        event = session.get(ChangeEvent, event_id)
        if event is None:
            log.warning("match_event_not_found", event_id=str(event_id))
            return {"status": "not_found", "event_id": str(event_id)}

        # Skip unscored events — M4 hasn't finished yet.
        if event.significance_score is None:
            log.info("match_event_unscored", event_id=str(event_id))
            return {"status": "unscored", "event_id": str(event_id)}

        # Fetch the raw text from the source version for keyword matching.
        raw_text = ""
        if event.new_version_id:
            sv = session.get(SourceVersion, event.new_version_id)
            if sv and sv.raw_text:
                raw_text = sv.raw_text

        # Fall back to summary + diff if no raw text is available.
        if not raw_text:
            parts = []
            if event.summary:
                parts.append(event.summary)
            if event.unified_diff:
                parts.append(event.unified_diff)
            raw_text = "\n".join(parts)

        if not raw_text:
            log.info("match_event_no_text", event_id=str(event_id))
            return {"status": "no_text", "event_id": str(event_id)}

        # ── Execute the matching query ───────────────────────────────
        event_topic = event.topic or ""
        event_origins = event.origin_countries or []
        event_dests = event.destination_countries or []
        event_score = event.significance_score or 0.0

        rows = session.exec(
            _MATCH_SQL,
            params={
                "event_topic": event_topic,
                "has_origins": bool(event_origins),
                "event_origins_csv": ",".join(event_origins) if event_origins else "",
                "has_dests": bool(event_dests),
                "event_dests_csv": ",".join(event_dests) if event_dests else "",
                "event_score": event_score,
                "raw_text": raw_text[:500_000],  # cap to prevent OOM
            },
        ).all()

        if not rows:
            log.info("match_event_no_matches",
                     event_id=str(event_id), score=event_score)
            return {
                "status": "matched",
                "event_id": str(event_id),
                "alerts_created": 0,
            }

        # ── Insert alert rows ────────────────────────────────────────
        alerts_created = 0
        for row in rows:
            matched = _extract_matched_terms(row.keyword_query, raw_text)

            session.exec(
                _INSERT_ALERT_SQL,
                params={
                    "sub_id": row.subscription_id,
                    "event_id": event_id,
                    "matched_kw": json.dumps(matched) if matched else None,
                },
            )
            alerts_created += 1

        session.commit()

        log.info("match_event_done",
                 event_id=str(event_id),
                 candidates=len(rows),
                 alerts_created=alerts_created,
                 score=event_score,
                 topic=event_topic)

        return {
            "status": "matched",
            "event_id": str(event_id),
            "alerts_created": alerts_created,
        }
