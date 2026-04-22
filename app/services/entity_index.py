"""
Entity index (M4).

Promotes the `change_events.affected_entities` JSON blob into a
queryable many-to-many index: `entities` × `change_event_entities`.

Why
---
The LLM scorer (L3) already extracts affected entities as a list of
free-text strings ("FCA", "19 CFR 149", "Importer Security Filing …").
That's good enough for a single-event display, but impossible to
query across events:

    SELECT e.display_name, COUNT(*)
    FROM   entities e
    JOIN   change_event_entities x ON x.entity_id = e.id
    JOIN   change_events c         ON c.id       = x.change_event_id
    WHERE  c.significance_score >= 0.8
      AND  c.detected_at > now() - interval '30 days'
    GROUP  BY e.id ORDER BY 2 DESC LIMIT 20;

This service is the *single writer* responsible for keeping that
index in sync with `ChangeEvent.affected_entities`.

Public API
----------
sync_entities_for_event(event_id: UUID) -> dict
    Upserts Entity rows for every string in
    ChangeEvent.affected_entities and materialises
    ChangeEventEntity join rows. Idempotent.

normalize(surface: str) -> tuple[str, str, str]
    (canonical_key, display_name, entity_type). Exposed mostly for
    testing + CLI tooling.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.database import engine
from app.logging_setup import get_logger
from app.models import ChangeEvent, ChangeEventEntity, Entity

logger = get_logger(__name__)


# ── Normalization ────────────────────────────────────────────────────────────
# A SMALL, HAND-CURATED synonym table. We do NOT try to build an ontology
# here — the goal is just to prevent obvious duplicates like
# "FCA" / "Financial Conduct Authority" / "UK FCA" showing up as 3
# separate entities. If an acronym maps to multiple real agencies
# (e.g. "SEC" = Securities and Exchange Commission OR Saudi Electricity
# Company), we keep the more frequent / regulatory interpretation.
_ACRONYM_EXPANSIONS: dict[str, str] = {
    "fca": "financial conduct authority",
    "sec": "securities and exchange commission",
    "cftc": "commodity futures trading commission",
    "cbp": "customs and border protection",
    "uscbp": "customs and border protection",
    "ofac": "office of foreign assets control",
    "fda": "food and drug administration",
    "ema": "european medicines agency",
    "ecb": "european central bank",
    "esma": "european securities and markets authority",
    "eba": "european banking authority",
    "fincen": "financial crimes enforcement network",
    "irs": "internal revenue service",
    "doj": "department of justice",
    "dol": "department of labor",
    "dhs": "department of homeland security",
    "epa": "environmental protection agency",
    "osha": "occupational safety and health administration",
    "nrc": "nuclear regulatory commission",
    "aml": "anti-money laundering",
    "kyc": "know your customer",
    "pra": "prudential regulation authority",
    "bafin": "bundesanstalt für finanzdienstleistungsaufsicht",
    "mas": "monetary authority of singapore",
    "hkma": "hong kong monetary authority",
    "rbi": "reserve bank of india",
    "pboc": "people's bank of china",
    "boe": "bank of england",
    "fdic": "federal deposit insurance corporation",
    "occ": "office of the comptroller of the currency",
    "frb": "federal reserve board",
    "ftc": "federal trade commission",
    "fcc": "federal communications commission",
    "fra": "federal railroad administration",
    "cdc": "centers for disease control and prevention",
    "cms": "centers for medicare and medicaid services",
    "nist": "national institute of standards and technology",
    "uspto": "united states patent and trademark office",
    "noaa": "national oceanic and atmospheric administration",
}

# Acronyms that name a *regulation / law / standard*, not an agency. Kept
# separate from _ACRONYM_EXPANSIONS so the type assignment is correct.
_REGULATION_ACRONYMS: dict[str, str] = {
    "gdpr": "general data protection regulation",
    "hipaa": "health insurance portability and accountability act",
    "ccpa": "california consumer privacy act",
    "sox": "sarbanes-oxley act",
    "fatca": "foreign account tax compliance act",
    "mifid": "markets in financial instruments directive",
    "mifid ii": "markets in financial instruments directive ii",
    "psd2": "payment services directive 2",
    "emir": "european market infrastructure regulation",
    "basel iii": "basel iii",
    "dodd-frank": "dodd-frank wall street reform act",
}

# Regex patterns for type inference. The list is processed in order and
# the FIRST hit wins, so high-specificity patterns must precede general ones.
# "agency" patterns are deliberately broad because the LLM tends to emit
# full agency names ("U.S. Customs and Border Protection") — anything
# containing a recognised governmental noun should resolve to "agency".
_AGENCY_KEYWORDS = (
    r"\b("
    r"agency|authority|commission|bureau|administration|department|ministry|"
    r"office|board|council|service|inspectorate|directorate|secretariat|"
    r"comptroller|registrar|prosecutor|"
    # Enforcement / regulatory verbs used as nouns in agency names
    r"protection|enforcement|patrol|customs|intelligence|tribunal|"
    r"supervisor|supervisory|regulator"
    r")\b"
)
# Note: we deliberately do NOT use a closing `\b` after `u\.?s\.?` because
# `\b` does not fire between two non-word characters (e.g. between `.` and
# ` `). Instead we anchor the prefix at a word boundary on the LEFT only.
_GOV_PREFIXES = (
    r"(?:^|\b)("
    r"u\.s\.|u\.s\b|us\b|united\s+states|federal|european|eu|state|national|"
    r"royal|her\s+majesty|royal\s+norwegian|hm|"
    r"ministry|ministerio|ministère|bundes|"
    r"people's\s+republic|government\s+of"
    r")"
)

_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Regulations / statutes
    ("regulation", re.compile(r"\b\d+\s*C\.?F\.?R\.?\b", re.IGNORECASE)),
    ("regulation", re.compile(r"\b\d+\s*U\.?S\.?C\.?\b", re.IGNORECASE)),
    ("regulation", re.compile(r"\b(?:eu|ec|eec)\s*\d+/\d+", re.IGNORECASE)),
    ("regulation", re.compile(r"\b(?:mifid|gdpr|ccpa|basel|solvency|dodd-frank|sox|hipaa|psd2|emir|fatca)\b", re.IGNORECASE)),
    ("regulation", re.compile(r"\b(?:regulation|directive|act|rule)\s+(?:no\.?\s*)?\d+\b", re.IGNORECASE)),
    ("regulation", re.compile(r"\bsection\s+\d", re.IGNORECASE)),
    ("regulation", re.compile(r"\btitle\s+\d", re.IGNORECASE)),
    # Codes / classifiers
    # 1. Named classifiers without a number: "HS code", "HTS", "HTSUS",
    #    "Schedule B", "NAICS", "SIC", "CN 8471"
    ("code",       re.compile(
        r"\bhs\s*codes?\b"
        r"|\bhts(?:us)?\b"
        r"|\bschedule\s*b\b"
        r"|\bcn\s*\d{4,}\b"
        r"|\bnaics\b|\bsic\b",
        re.IGNORECASE)),
    # 2. Dotted tariff codes: HS6 / HS8 / HS10, the normal way real
    #    CBP / EU / UK TARIC documents cite them. Examples:
    #       0304.29.00   9401.61.4010   0405.20.3000
    ("code",       re.compile(r"^\d{4}\.\d{2}(?:\.\d{2,4})?$")),
    # 3. Same dotted codes, but preceded by a classifier prefix (covers
    #    "HTS 9401.61", "HTSUS 0304.29.00", "Schedule B 0405.20.3000",
    #    "HS 3506" — the bare-4-digit form still counts).
    ("code",       re.compile(
        r"\b(?:hts(?:us)?|hs|schedule\s*b)\s*\d{4}(?:\.\d{2,4}){0,2}\b",
        re.IGNORECASE)),
    # 4. HS headings / chapters spelt out: "Heading 39.09", "Chapter 69.07"
    ("code",       re.compile(r"\b(?:chapter|heading)\s+\d{2}\.\d{2}\b", re.IGNORECASE)),
    # 5. Bare numeric classifications 6–10 digits (HS6/HS8/HS10 without dots)
    ("code",       re.compile(r"^\d{6,10}$")),
    # Agency — full names with characteristic gov nouns or prefixes
    ("agency",     re.compile(_AGENCY_KEYWORDS + r".+(?:of|for)\b", re.IGNORECASE)),
    ("agency",     re.compile(_GOV_PREFIXES + r"\s+\w.*" + _AGENCY_KEYWORDS, re.IGNORECASE)),
    ("agency",     re.compile(_AGENCY_KEYWORDS, re.IGNORECASE)),
    # Bare acronyms (FCA, SEC, EBA…). Lower priority than the keyword
    # patterns so "FDA Office of Drug Quality" still parses as agency
    # and "SEC" alone also resolves as agency.
    ("agency",     re.compile(r"^[A-Z]{2,6}$")),
    # Programs / schemes
    ("program",    re.compile(r"\b(?:program|programme|scheme|initiative|framework)\b", re.IGNORECASE)),
    # Industry sectors
    ("industry",   re.compile(r"\b(?:industry|sector|manufacturers?|providers?|exchanges?|institutions?|importers?|exporters?|operators?)\b", re.IGNORECASE)),
]

# Whitespace collapse — canonical_key MUST have single spaces, no tabs/newlines.
_WS_RE = re.compile(r"\s+")

# Max length to keep display_name + canonical_key bounded (matches DB cols).
_MAX_LEN = 255


def _infer_type(surface: str) -> str:
    """Best-effort entity-type heuristic. Falls back to 'other'."""
    for etype, pat in _TYPE_PATTERNS:
        if pat.search(surface):
            return etype
    return "other"


def normalize(surface: str) -> Optional[tuple[str, str, str]]:
    """
    Normalize a raw LLM-produced entity string into
    (canonical_key, display_name, entity_type).

    Returns None for strings that shouldn't be indexed (empty, too long,
    pure punctuation, etc.).
    """
    if not surface:
        return None
    trimmed = _WS_RE.sub(" ", surface).strip()
    if not trimmed or len(trimmed) < 2:
        return None
    # Defensive: truncate pathological long strings from the LLM.
    trimmed = trimmed[:_MAX_LEN]

    # Acronym expansion — map known agency acronyms to their full form so
    # "FCA" and "Financial Conduct Authority" collapse into one entity.
    lowered = trimmed.lower()
    if lowered in _ACRONYM_EXPANSIONS:
        canonical_name = _ACRONYM_EXPANSIONS[lowered].title()
        canonical_key = _ACRONYM_EXPANSIONS[lowered]
        return canonical_key[:_MAX_LEN], canonical_name[:_MAX_LEN], "agency"
    if lowered in _REGULATION_ACRONYMS:
        canonical_name = _REGULATION_ACRONYMS[lowered].title()
        canonical_key = _REGULATION_ACRONYMS[lowered]
        return canonical_key[:_MAX_LEN], canonical_name[:_MAX_LEN], "regulation"

    # Standard path: lowercase + whitespace-collapsed is the key, the
    # surface form is the display name.
    canonical_key = lowered
    etype = _infer_type(trimmed)
    return canonical_key[:_MAX_LEN], trimmed, etype


# ── Upsert logic ─────────────────────────────────────────────────────────────

def _upsert_entity(
    session: Session,
    canonical_key: str,
    display_name: str,
    entity_type: str,
    now: datetime,
) -> Entity:
    """Get-or-create an Entity by canonical_key, updating counters."""
    existing = session.exec(
        select(Entity).where(Entity.canonical_key == canonical_key)
    ).one_or_none()
    if existing is not None:
        existing.mention_count += 1
        existing.last_seen_at = now
        # If we previously guessed "other" but now have a better type,
        # upgrade. Never downgrade a confident type back to "other".
        if existing.entity_type == "other" and entity_type != "other":
            existing.entity_type = entity_type
        session.add(existing)
        return existing

    ent = Entity(
        canonical_key=canonical_key,
        display_name=display_name,
        entity_type=entity_type,
        mention_count=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(ent)
    session.flush()  # get the id without committing the whole txn
    return ent


def sync_entities_for_event(event_id: UUID) -> dict:
    """
    Read `ChangeEvent.affected_entities`, upsert Entity rows,
    materialise ChangeEventEntity rows. Idempotent: re-running on the
    same event updates `mention_count`s but never creates duplicate
    join rows thanks to the composite PK on (change_event_id, entity_id).

    Returns a summary dict suitable for logging / Celery return value.
    """
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        event = session.get(ChangeEvent, event_id)
        if event is None:
            return {"status": "missing", "event_id": str(event_id)}

        raw_entities: list[str] = event.affected_entities or []
        if not raw_entities:
            return {"status": "empty", "event_id": str(event_id), "indexed": 0}

        # Pull existing join rows so the composite PK can't bite us on
        # rescored events (idempotent re-runs).
        existing_joins = session.exec(
            select(ChangeEventEntity.entity_id).where(
                ChangeEventEntity.change_event_id == event_id
            )
        ).all()
        already_joined: set[UUID] = set(existing_joins)

        indexed = 0
        skipped = 0
        for raw in raw_entities:
            norm = normalize(raw)
            if norm is None:
                skipped += 1
                continue
            canonical_key, display_name, etype = norm

            ent = _upsert_entity(session, canonical_key, display_name, etype, now)
            if ent.id in already_joined:
                continue
            session.add(ChangeEventEntity(
                change_event_id=event_id,
                entity_id=ent.id,
                mention_text=raw[:_MAX_LEN],
                created_at=now,
            ))
            already_joined.add(ent.id)
            indexed += 1

        session.commit()

    logger.info("entity_index_synced",
                event_id=str(event_id),
                indexed=indexed,
                skipped=skipped)
    return {
        "status": "ok",
        "event_id": str(event_id),
        "indexed": indexed,
        "skipped": skipped,
    }


# ── Batch helpers (used by backfill script) ──────────────────────────────────

def iter_unindexed_events(
    session: Session,
    limit: Optional[int] = None,
) -> Iterable[UUID]:
    """
    Yield ids of scored events whose `affected_entities` have not yet
    been materialised into change_event_entities. Used by
    scripts/show_entities.py --backfill.
    """
    # An event is "unindexed" if it has a non-empty affected_entities
    # JSON and NO rows in change_event_entities yet.
    stmt = (
        select(ChangeEvent.id)
        .where(ChangeEvent.affected_entities.is_not(None))
        .where(ChangeEvent.scored_at.is_not(None))
        .where(~ChangeEvent.id.in_(  # noqa: E711
            select(ChangeEventEntity.change_event_id)
        ))
        .order_by(ChangeEvent.detected_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    for eid in session.exec(stmt).all():
        yield eid


def top_entities(
    session: Session,
    *,
    since: Optional[datetime] = None,
    min_score: Optional[float] = None,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> list[tuple[str, str, int]]:
    """
    Return top entities by mention count (filtered by event-level
    criteria). Used by the show_entities CLI.

    Each tuple: (display_name, entity_type, mention_count_in_window).
    """
    stmt = (
        select(
            Entity.display_name,
            Entity.entity_type,
            func.count(ChangeEventEntity.change_event_id).label("n"),
        )
        .join(ChangeEventEntity, ChangeEventEntity.entity_id == Entity.id)
        .join(ChangeEvent, ChangeEvent.id == ChangeEventEntity.change_event_id)
    )
    if since is not None:
        stmt = stmt.where(ChangeEvent.detected_at >= since)
    if min_score is not None:
        stmt = stmt.where(ChangeEvent.significance_score >= min_score)
    if entity_type is not None:
        stmt = stmt.where(Entity.entity_type == entity_type)
    stmt = (
        stmt.group_by(Entity.id, Entity.display_name, Entity.entity_type)
        .order_by(func.count(ChangeEventEntity.change_event_id).desc())
        .limit(limit)
    )
    return [(row[0], row[1], int(row[2])) for row in session.exec(stmt).all()]
