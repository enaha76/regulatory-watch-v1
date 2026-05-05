"""
Adapter that reshapes backend Alert + ChangeEvent rows into the payload the
regwatch admin frontend expects.

The frontend was prototyped against a hand-crafted `mockAlerts` array (see
frontend/src/app/components/alerts-view.tsx). Its field names and value
shapes don't match our DB exactly — `relevanceScore` is 0–100 not 0–1,
`status` is new/read/archived not unread/read/dismissed, etc. Instead of
breaking the existing M5 contract on /api/alerts, this module derives /
translates the frontend payload on the fly.

Derived fields (no DB column, computed from related rows):
  - authority      → derived from source_url
  - regulationType → mapped from event.topic

`pinned` and `userFeedback` are persisted on `alerts` (migration 018) and
read straight from the row.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models import (
    Alert,
    ChangeEvent,
    ChangeEventEntity,
    Entity,
    SourceVersion,
)


# ── Vocabulary mapping ─────────────────────────────────────────────────

# Backend status values (alerts.status) ↔ frontend status values.
# DB CHECK constraint: status IN ('unread', 'read', 'dismissed')
# Frontend interface: "new" | "read" | "archived"
_STATUS_BE_TO_FE = {
    "unread": "new",
    "read": "read",
    "dismissed": "archived",
}
_STATUS_FE_TO_BE = {v: k for k, v in _STATUS_BE_TO_FE.items()}


def status_be_to_fe(status: Optional[str]) -> str:
    """Translate a DB status to what the frontend expects."""
    return _STATUS_BE_TO_FE.get(status or "unread", "new")


def status_fe_to_be(status: Optional[str]) -> str:
    """Translate a frontend status (PATCH body) to a DB-valid value."""
    if status is None:
        return "unread"
    if status not in _STATUS_FE_TO_BE:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: "
            f"{', '.join(_STATUS_FE_TO_BE)}",
        )
    return _STATUS_FE_TO_BE[status]


# Backend topic taxonomy (see migration 007) ↔ frontend display strings.
# DB CHECK: topic IN ('customs_trade','financial_services','data_privacy',
#   'environmental','healthcare_pharma','sanctions_export_control',
#   'labor_employment','tax_accounting','consumer_protection',
#   'corporate_governance','other')
_TOPIC_DISPLAY = {
    "customs_trade": "Tariff & Duties",
    "financial_services": "Financial Services",
    "data_privacy": "Data Privacy",
    "environmental": "Environmental",
    "healthcare_pharma": "Healthcare / Pharma",
    "sanctions_export_control": "Sanctions & Export Control",
    "labor_employment": "Labor & Employment",
    "tax_accounting": "Tax & Accounting",
    "consumer_protection": "Consumer Protection",
    "corporate_governance": "Corporate Governance",
    "other": "Other",
}


def topic_to_regulation_type(topic: Optional[str]) -> str:
    """Map a backend topic to the frontend's `regulationType` string."""
    if not topic:
        return "Other"
    return _TOPIC_DISPLAY.get(topic, topic.replace("_", " ").title())


# ── Score scaling ──────────────────────────────────────────────────────

def score_to_pct(score: Optional[float]) -> int:
    """Backend significance_score (0..1) → frontend relevanceScore (0..100)."""
    if score is None:
        return 0
    return int(round(max(0.0, min(1.0, score)) * 100))


# ── Authority derivation ──────────────────────────────────────────────

# Hostname → human-readable authority. Add more as you onboard sources.
_AUTHORITY_BY_HOST = {
    "eur-lex.europa.eu": "European Commission",
    "ec.europa.eu": "European Commission",
    "fca.org.uk": "Financial Conduct Authority (FCA)",
    "www.fca.org.uk": "Financial Conduct Authority (FCA)",
    "federalregister.gov": "US Federal Register",
    "www.federalregister.gov": "US Federal Register",
    "govinfo.gov": "US Government Publishing Office",
    "www.govinfo.gov": "US Government Publishing Office",
    "cbp.gov": "US Customs and Border Protection",
    "www.cbp.gov": "US Customs and Border Protection",
    "bis.doc.gov": "Bureau of Industry and Security (BIS)",
    "www.bis.doc.gov": "Bureau of Industry and Security (BIS)",
    "doc.gov": "US Department of Commerce",
    "www.doc.gov": "US Department of Commerce",
    "ustr.gov": "Office of the US Trade Representative (USTR)",
    "www.ustr.gov": "Office of the US Trade Representative (USTR)",
    "fcc.gov": "Federal Communications Commission (FCC)",
    "www.fcc.gov": "Federal Communications Commission (FCC)",
    "treasury.gov": "US Department of the Treasury",
    "www.treasury.gov": "US Department of the Treasury",
    "ofac.treasury.gov": "OFAC (US Treasury)",
    "dgft.gov.in": "Directorate General of Foreign Trade (DGFT)",
    "mofcom.gov.cn": "Ministry of Commerce (MOFCOM)",
    "meti.go.jp": "METI Japan",
    "wto.org": "WTO",
    "www.wto.org": "WTO",
    "mock-website.local": "ATCA Mock",
    "mock-website": "ATCA Mock",
    "localhost": "ATCA Mock",
}


def derive_authority(source_url: Optional[str]) -> str:
    """Best-effort guess at the issuing authority from the source URL."""
    if not source_url:
        return "Unknown"
    try:
        host = (urlparse(source_url).hostname or "").lower()
    except Exception:
        return "Unknown"
    if not host:
        return "Unknown"

    # Exact match wins
    if host in _AUTHORITY_BY_HOST:
        return _AUTHORITY_BY_HOST[host]

    # Strip the leading "www." for both lookup AND fallback so we never
    # return the literal string "WWW" as an authority.
    if host.startswith("www."):
        host = host[4:]
        if host in _AUTHORITY_BY_HOST:
            return _AUTHORITY_BY_HOST[host]

    # Fallback: take the most distinctive label from the hostname.
    # For "bis.doc.gov" → "BIS"; for "fca.org.uk" → "FCA";
    # for "mock-website.local" → "MOCK-WEBSITE".
    parts = [p for p in host.split(".") if p]
    if not parts:
        return "Unknown"
    # Skip generic prefixes ("api", "portal", "secure" etc.) if present
    SKIP = {"api", "www", "portal", "secure", "data", "open"}
    label = next((p for p in parts if p not in SKIP), parts[0])
    return label.upper()


# ── Country / trade lane derivation ───────────────────────────────────

# ISO-2 → display name. Frontend shows full names like "India".
# (Could grow into a CSV table; this dict covers the demo set.)
_COUNTRY_NAME = {
    "US": "United States",
    "EU": "European Union",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "CN": "China",
    "IN": "India",
    "JP": "Japan",
    "KR": "South Korea",
    "DE": "Germany",
    "FR": "France",
    "BR": "Brazil",
    "CA": "Canada",
    "AU": "Australia",
    "MX": "Mexico",
    "SG": "Singapore",
    "AE": "United Arab Emirates",
}


def country_display_name(code: Optional[str]) -> str:
    if not code:
        return ""
    return _COUNTRY_NAME.get(code.upper(), code.upper())


def pick_primary_country(event: ChangeEvent) -> str:
    """
    Choose ONE country to show on the alert card.

    For inbound rules the destination is what matters (where goods are
    going). For outbound, the origin is. Bilateral / global fall back
    to the first non-empty list.
    """
    direction = (event.trade_flow_direction or "").lower()
    dst = event.destination_countries or []
    org = event.origin_countries or []

    if direction == "inbound" and dst:
        return country_display_name(dst[0])
    if direction == "outbound" and org:
        return country_display_name(org[0])
    if direction in ("bilateral", "global"):
        return "Multiple"
    # No direction set — prefer destination then origin
    if dst:
        return country_display_name(dst[0])
    if org:
        return country_display_name(org[0])
    return "Unknown"


def derive_trade_lane(event: ChangeEvent) -> str:
    """
    Build a compact trade-lane string like "*->IN" or "IN->*".

    Wildcard "*" means "any country on that side". Direction:
        inbound  → "*->{dst}"   (anything -> dst)
        outbound → "{org}->*"   (org -> anything)
        bilateral / global → "*->*"
    """
    direction = (event.trade_flow_direction or "").lower()
    dst = (event.destination_countries or [None])[0]
    org = (event.origin_countries or [None])[0]

    if direction == "inbound" and dst:
        return f"*->{dst.upper()}"
    if direction == "outbound" and org:
        return f"{org.upper()}->*"
    if direction == "bilateral":
        return f"{(org or '*').upper()}<->{(dst or '*').upper()}"
    if direction == "global":
        return "*->*"
    if dst:
        return f"*->{dst.upper()}"
    if org:
        return f"{org.upper()}->*"
    return "*->*"


# ── HS code lookup ─────────────────────────────────────────────────────

def fetch_hs_codes(session: Session, change_event_id) -> list[str]:
    """
    Return the list of HS / commodity codes attached to a ChangeEvent.

    Backed by `change_event_entities` × `entities` where entity_type='code'.
    The display name (e.g. "HS 854140") is what we surface to the frontend.
    """
    stmt = (
        select(Entity.display_name)
        .join(ChangeEventEntity, ChangeEventEntity.entity_id == Entity.id)
        .where(ChangeEventEntity.change_event_id == change_event_id)
        .where(Entity.entity_type == "code")
    )
    return [row for row in session.exec(stmt).all() if row]


# ── Title / summary helpers ────────────────────────────────────────────

# Cap the title at this length. Most real document titles are shorter;
# the cap kicks in only on rare overlong ones (e.g. legal notices that
# repeat their reference number). Keeping it tight avoids ugly wrapping
# on alert cards.
_MAX_TITLE_CHARS = 120


def _truncate(text: str, limit: int) -> str:
    """Truncate at a word boundary if possible, append an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.- ")
    if not cut:
        cut = text[:limit].rstrip()
    return cut + "…"


def _looks_like_url(s: str) -> bool:
    """True if `s` is plausibly a URL (so we shouldn't use it as a title)."""
    s = s.strip().lower()
    return s.startswith(("http://", "https://", "ftp://", "//", "www."))


def _humanize_url_to_title(url: str) -> str:
    """
    Turn a URL into a human-readable title.

    "http://mock-website.local/documents/tariff-schedule-2026.pdf"
        → "Tariff Schedule 2026"
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1234"
        → "32024R1234"
    """
    try:
        from urllib.parse import urlparse, unquote

        path = unquote(urlparse(url).path or "")
    except Exception:
        path = url
    # Last meaningful segment of the path
    segs = [s for s in path.split("/") if s]
    last = segs[-1] if segs else ""
    # Drop file extension
    for ext in (".pdf", ".html", ".htm", ".xml", ".aspx", ".php"):
        if last.lower().endswith(ext):
            last = last[: -len(ext)]
            break
    last = last.strip()
    if not last:
        return ""
    # Replace separators with spaces, title-case the result
    return last.replace("-", " ").replace("_", " ").strip().title()


def fetch_source_title(session: Session, event: ChangeEvent) -> Optional[str]:
    """
    Look up the linked SourceVersion's title — the document's actual
    headline (HTML <title>, RSS item title, PDF metadata title…).

    If the stored title is empty, missing, or itself a URL (which can
    happen for PDFs without metadata), return None so the caller falls
    through to a smarter derivation.
    """
    version_id = getattr(event, "new_version_id", None)
    if not version_id:
        return None
    sv = session.get(SourceVersion, version_id)
    if sv is None:
        return None
    title = (sv.title or "").strip()
    if not title:
        return None
    # Don't surface raw URLs as the alert title — humanize them instead.
    if _looks_like_url(title):
        humanized = _humanize_url_to_title(title)
        return humanized or None
    return title


def derive_title(
    session: Session,
    event: ChangeEvent,
    fallback: str = "Regulatory change detected",
) -> str:
    """
    Pick a short, headline-style title for the alert card.

    Priority chain:
      1. SourceVersion.title  — the document's actual headline
      2. First sentence of event.summary — only if no source title
      3. A topic-based label (e.g. "Customs Trade update")
      4. Generic fallback ("Regulatory change detected")

    Title and summary now come from DIFFERENT fields, so they no
    longer duplicate each other.
    """
    # 1. Real document title (preferred)
    src_title = fetch_source_title(session, event)
    if src_title:
        return _truncate(src_title, _MAX_TITLE_CHARS)

    # 2. First sentence of LLM-produced summary
    if event.summary:
        first = _first_sentence(event.summary)
        if first:
            return _truncate(first, _MAX_TITLE_CHARS)

    # 3. Topic-derived synthetic title
    if event.topic:
        return f"{topic_to_regulation_type(event.topic)} update detected"

    # 4. Generic fallback
    return fallback


# Common abbreviations that end with a period but don't end a sentence.
# Compared lowercase. Extend if you see false-positive splits in the
# detail page for regulatory summaries.
_KNOWN_ABBREVS = frozenset({
    "mr", "mrs", "ms", "dr", "sr", "jr", "st", "rev", "hon", "prof",
    "etc", "vs", "viz", "cf",
    "co", "inc", "ltd", "corp", "llc", "plc", "bros",
    "no", "fig", "vol", "ch", "p", "pp",
})


def _is_real_sentence_end(text: str, idx: int) -> bool:
    """
    Heuristic: is `text[idx]` (a `.`, `!`, or `?`) a real sentence ending?

    Returns False for:
      - "U.S. Customs" — single-letter abbreviations
      - "U.S.S.R. is gone." — chained abbreviations + lowercase next
      - "Mrs. Jones" — known title abbreviations (see _KNOWN_ABBREVS)
      - "...lowercase next" — lowercase strongly implies non-boundary
    Returns True for "issued. Importers..." or "by 2026-08-15. Failure..."

    Numbers preceding the period (e.g. "15.", "2026.") are treated as
    real sentence ends since people don't abbreviate numbers.
    """
    ch = text[idx]
    if ch not in ".!?":
        return False

    nxt = text[idx + 1] if idx + 1 < len(text) else ""
    if nxt and not nxt.isspace():
        return False

    # If the next non-space character is lowercase, almost certainly
    # not a sentence boundary.
    j = idx + 1
    while j < len(text) and text[j].isspace():
        j += 1
    if j < len(text) and text[j].isalpha() and text[j].islower():
        return False

    # `!` and `?` are unambiguous — people don't abbreviate with them.
    if ch in "!?":
        return True

    # Walk back from the period, separating digit + alpha counts.
    k = idx - 1
    digit_count = 0
    alpha_chars: list[str] = []
    while k >= 0 and text[k].isalnum():
        if text[k].isdigit():
            digit_count += 1
        else:
            alpha_chars.append(text[k])
        k -= 1

    # All-digit token before the period (e.g. "15." in a date or
    # "$1,000."). Numbers don't get abbreviated → real sentence end.
    if digit_count > 0 and not alpha_chars:
        return True

    # 1–2 alpha chars (e.g., "U.", "Mr.", "St.") → abbreviation.
    if alpha_chars and len(alpha_chars) < 3:
        return False

    # Known multi-character abbreviations like "Mrs.", "Dr.", "Prof.".
    if alpha_chars:
        word = "".join(reversed(alpha_chars)).lower()
        if word in _KNOWN_ABBREVS:
            return False

    # Chained abbreviation chain ("U.S.S.R.") — char before alpha run
    # is itself a `.`.
    if k >= 0 and text[k] == ".":
        return False

    return True


def _first_sentence(text: str) -> str:
    """
    Return the first sentence of `text`, ignoring abbreviation periods
    like "U.S." or "Mr." inside the sentence.
    """
    text = text.strip()
    if not text:
        return ""
    for i in range(len(text)):
        if _is_real_sentence_end(text, i):
            return text[: i + 1].strip()
    return text


def split_summary_to_bullets(summary: Optional[str]) -> list[str]:
    """
    Convert the LLM-produced compliance_summary into a bullet array.

    The summary is typically 1–3 sentences of plain English. We split on
    sentence boundaries (`. `, `! `, `? `) so each bullet is a complete
    actionable thought. Existing bullet/numeric markers (`-`, `*`,
    `1.`) at the start of a line are stripped.

    Returns an empty list if `summary` is empty or None.
    """
    if not summary:
        return []

    raw = summary.strip()
    if not raw:
        return []

    # If the LLM gave us pre-formatted bullets / numbered items, honour them.
    pre_split: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _strip_bullet_marker(line)
        if line:
            pre_split.append(line)

    if len(pre_split) > 1:
        return pre_split

    # Otherwise treat the whole thing as one paragraph and split on
    # sentence boundaries — being careful with abbreviations.
    text = pre_split[0] if pre_split else raw
    bullets: list[str] = []
    start = 0
    for i in range(len(text)):
        if _is_real_sentence_end(text, i):
            sentence = text[start : i + 1].strip()
            if sentence:
                bullets.append(sentence)
            start = i + 1
    tail = text[start:].strip()
    if tail:
        bullets.append(tail)

    return bullets or [text]


def _strip_bullet_marker(line: str) -> str:
    """Remove a leading '- ', '* ', '• ', '1. ' or '1) ' if present."""
    for marker in ("- ", "* ", "• ", "•\t"):
        if line.startswith(marker):
            return line[len(marker):].strip()
    # "1. " / "12) " style
    i = 0
    while i < len(line) and line[i].isdigit():
        i += 1
    if (
        0 < i < len(line)
        and line[i] in (".", ")")
        and i + 1 < len(line)
        and line[i + 1] == " "
    ):
        return line[i + 2:].strip()
    return line


# ── Top-level builder ──────────────────────────────────────────────────

def _summary_bullets_for_detail(
    session: Session, event: ChangeEvent
) -> list[str]:
    """
    Pick the bullet list for the detail view.

    If the LLM has scored the event, use its compliance_summary. If not,
    return a single explanatory bullet so the detail page isn't empty.
    """
    if event.summary:
        return split_summary_to_bullets(event.summary)

    # Unscored event — show a placeholder so the page is still useful.
    src_title = fetch_source_title(session, event)
    if src_title:
        return [
            f"This regulation has been detected but not yet analyzed. "
            f"Source document: \"{src_title}\".",
        ]
    return [
        "This regulation has been detected but the AI analysis has not "
        "completed yet. Check back shortly for a compliance summary.",
    ]


def build_frontend_alert(
    session: Session,
    alert: Alert,
    event: ChangeEvent,
    *,
    include_summary_bullets: bool = False,
) -> dict:
    """
    Reshape (Alert, ChangeEvent) → the dict the frontend wants per Alert.

    Set include_summary_bullets=True for the detail endpoint, which adds
    a `summary` array of bullets used by AlertDetail.tsx.
    """
    payload: dict = {
        "id": str(alert.id),
        "title": derive_title(session, event),
        "country": pick_primary_country(event),
        "authority": derive_authority(event.source_url),
        "regulationType": topic_to_regulation_type(event.topic),
        # Full ISO datetime — frontend formats this as "May 5, 2026 14:08".
        # Field name kept as `publicationDate` for backward compat; the
        # value is now date+time (UTC) instead of date-only.
        "publicationDate": (
            event.detected_at.isoformat() if event.detected_at else ""
        ),
        "affectedProducts": fetch_hs_codes(session, event.id),
        "relevanceScore": score_to_pct(event.significance_score),
        "status": status_be_to_fe(alert.status),
        "userFeedback": alert.user_feedback,
        "pinned": bool(alert.pinned),
        "tradeLane": derive_trade_lane(event),
    }
    if include_summary_bullets:
        payload["summary"] = _summary_bullets_for_detail(session, event)
        payload["sourceUrl"] = event.source_url or ""
        # If the change event was detected on a PDF directly, expose that
        # URL so the frontend's "Download Official Document" link works.
        # Otherwise omit pdfUrl so the link is hidden.
        if (event.source_url or "").lower().endswith(".pdf"):
            payload["pdfUrl"] = event.source_url

        # Diff payload — what actually changed at the source. Populated
        # for "modified" events (where there's a previous version to
        # compare against). For "created" events the diff is the whole
        # document, which isn't useful to render so we omit it and let
        # the UI show only the summary.
        payload["diff"] = {
            "kind": event.diff_kind,             # "created" | "modified"
            "addedChars": int(event.added_chars or 0),
            "removedChars": int(event.removed_chars or 0),
            "changeType": event.change_type,     # typo_or_cosmetic, minor_wording, …
            # Cap the unified diff at a sane size so a 1MB-page diff
            # doesn't bloat the API response. The full thing is still
            # in the DB if a deeper view is needed later.
            "unifiedDiff": (
                (event.unified_diff or "")[:50_000]
                if event.diff_kind == "modified"
                else None
            ),
        }
    return payload
