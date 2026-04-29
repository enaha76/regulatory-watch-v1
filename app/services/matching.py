"""
M5 Alerting Engine — Semantic Matching Service.

Core function: ``match_event(event_id)``

After a ChangeEvent is scored by M3/M4, this service finds every active
UserSubscription whose embedding is semantically close to the event's
embedding, and inserts one Alert row per match.

How it works
------------
1. Load the ChangeEvent — skip if unscored or has no embedding.
2. Run one SQL query: compare the event embedding against every active
   subscription embedding using pgvector cosine distance (<=>).
   Only subscriptions whose embedding is within (1 - similarity_threshold)
   of the event embedding pass, PLUS the min_significance gate.
3. For each matching subscription, find which raw keywords literally
   appear in the document text (ILIKE) — stored as ``matched_keywords``
   on the Alert row for UI highlighting (XAI).
4. INSERT alert rows with ON CONFLICT DO NOTHING (idempotent on retry).

Zero extra LLM calls.  Runs in milliseconds at 200-user scale.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlmodel import Session, text

from app.database import engine
from app.logging_setup import get_logger

log = get_logger(__name__)


# Single SQL pass: cosine distance filter + min_significance gate.
# pgvector's <=> operator returns cosine *distance* (0 = identical, 2 = opposite).
# We convert to similarity: similarity = 1 - distance.
# Condition: distance < (1 - threshold)  ⟺  similarity > threshold.
_MATCH_SQL = text("""
    SELECT
        us.id              AS subscription_id,
        us.user_email,
        us.keywords,
        1 - (us.embedding <=> CAST(:doc_embedding AS vector)) AS similarity
    FROM user_subscriptions us
    WHERE us.is_active = TRUE
      AND us.embedding IS NOT NULL
      AND :event_score >= us.min_significance
      AND (us.embedding <=> CAST(:doc_embedding AS vector))
          < (1.0 - us.similarity_threshold)
""")

_INSERT_ALERT_SQL = text("""
    INSERT INTO alerts (id, subscription_id, change_event_id,
                        matched_keywords, status)
    VALUES (gen_random_uuid(), :sub_id, :event_id,
            CAST(:matched_kw AS json), 'unread')
    ON CONFLICT ON CONSTRAINT uq_alerts_subscription_event
    DO NOTHING
""")


def _pgvector_literal(embedding: list[float]) -> str:
    """Format a Python float list as a pgvector literal string '[x,y,…]'."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


def _find_matched_keywords(keywords: list, raw_text: str) -> list[str]:
    """Return which keywords from the subscription appear in the document."""
    if not keywords or not raw_text:
        return []
    text_lower = raw_text.lower()
    return [kw for kw in keywords if str(kw).lower() in text_lower]


def match_event(event_id: UUID) -> dict:
    """
    Find all active subscriptions that match the given ChangeEvent and
    insert alert rows.

    Returns {"status": ..., "event_id": ..., "alerts_created": N}.
    """
    from app.models import ChangeEvent, SourceVersion

    with Session(engine) as session:
        event = session.get(ChangeEvent, event_id)
        if event is None:
            log.warning("match_event_not_found", event_id=str(event_id))
            return {"status": "not_found", "event_id": str(event_id)}

        if event.significance_score is None:
            log.info("match_event_unscored", event_id=str(event_id))
            return {"status": "unscored", "event_id": str(event_id)}

        if event.embedding is None:
            log.info("match_event_no_embedding", event_id=str(event_id))
            return {"status": "no_embedding", "event_id": str(event_id)}

        # Fetch raw text for keyword XAI only — not used for matching.
        raw_text = ""
        if event.new_version_id:
            sv = session.get(SourceVersion, event.new_version_id)
            if sv and sv.raw_text:
                raw_text = sv.raw_text

        doc_embedding_str = _pgvector_literal(event.embedding)

        rows = session.exec(
            _MATCH_SQL,
            params={
                "doc_embedding": doc_embedding_str,
                "event_score": event.significance_score,
            },
        ).all()

        if not rows:
            log.info("match_event_no_matches",
                     event_id=str(event_id), score=event.significance_score)
            return {"status": "matched", "event_id": str(event_id),
                    "alerts_created": 0}

        alerts_created = 0
        for row in rows:
            keywords = row.keywords if isinstance(row.keywords, list) else []
            matched = _find_matched_keywords(keywords, raw_text)

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
                 score=event.significance_score)

        return {
            "status": "matched",
            "event_id": str(event_id),
            "alerts_created": alerts_created,
        }
