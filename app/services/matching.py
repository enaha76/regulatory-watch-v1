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
#
# `hs_codes` and `countries` (added in migration 013) are pulled here but
# applied as Python pre-filters below. They could be pushed into SQL using
# json_array_elements but the candidate count after the embedding filter
# is already small (typically <200), so Python is simpler and fast enough.
_MATCH_SQL = text("""
    SELECT
        us.id              AS subscription_id,
        us.user_email,
        us.keywords,
        us.hs_codes,
        us.countries,
        1 - (us.embedding <=> CAST(:doc_embedding AS vector)) AS similarity
    FROM user_subscriptions us
    WHERE us.is_active = TRUE
      AND us.embedding IS NOT NULL
      AND :event_score >= us.min_significance
      AND (us.embedding <=> CAST(:doc_embedding AS vector))
          < (1.0 - us.similarity_threshold)
""")


_EVENT_HS_CODES_SQL = text("""
    SELECT e.canonical_key
    FROM change_event_entities cee
    JOIN entities e ON e.id = cee.entity_id
    WHERE cee.change_event_id = :event_id
      AND e.entity_type = 'code'
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


def _hs_overlap(sub_codes: list, event_codes: set[str]) -> bool:
    """
    Return True if any subscription HS code overlaps with the event's codes.

    Uses prefix matching so picking a parent code (e.g. "84") includes any
    child line (e.g. "8471", "847130"). Stripping non-digits first keeps
    formats consistent ("8541.40" matches "854140").
    """
    if not sub_codes:
        return True  # no filter set → pass

    def _normalize(code: str) -> str:
        return "".join(c for c in (code or "") if c.isalnum())

    norm_event = {_normalize(c) for c in event_codes if c}
    norm_event.discard("")
    if not norm_event:
        return False  # event has no codes; subscription requires some → no match

    for sc in sub_codes:
        s = _normalize(str(sc))
        if not s:
            continue
        # Match if a subscription code is a prefix of any event code, or
        # an event code is a prefix of the subscription code (in case the
        # event tagged a broader heading).
        for ec in norm_event:
            if ec.startswith(s) or s.startswith(ec):
                return True
    return False


def _country_overlap(sub_countries: list, event_countries: set[str]) -> bool:
    """True if any subscription country appears in the event's countries."""
    if not sub_countries:
        return True
    norm_sub = {str(c).upper() for c in sub_countries if c}
    norm_event = {str(c).upper() for c in event_countries if c}
    return bool(norm_sub & norm_event)


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

        # Pre-compute the event's HS codes + country set so we can run the
        # strict pre-filters cheaply per candidate subscription below.
        event_hs_codes: set[str] = set()
        for r in session.exec(_EVENT_HS_CODES_SQL, params={"event_id": event_id}).all():
            ck = r.canonical_key if hasattr(r, "canonical_key") else r[0]
            if ck:
                event_hs_codes.add(str(ck))
        event_countries: set[str] = set(event.origin_countries or []) | set(
            event.destination_countries or []
        )

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
        skipped_hs = 0
        skipped_country = 0
        for row in rows:
            keywords = row.keywords if isinstance(row.keywords, list) else []
            sub_hs = row.hs_codes if isinstance(row.hs_codes, list) else []
            sub_countries = row.countries if isinstance(row.countries, list) else []

            # Strict pre-filters: HS code + country must overlap with the
            # event when the user has set them. Empty list = pass-through.
            if not _hs_overlap(sub_hs, event_hs_codes):
                skipped_hs += 1
                continue
            if not _country_overlap(sub_countries, event_countries):
                skipped_country += 1
                continue

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
                 skipped_hs=skipped_hs,
                 skipped_country=skipped_country,
                 score=event.significance_score)

        return {
            "status": "matched",
            "event_id": str(event_id),
            "alerts_created": alerts_created,
        }
