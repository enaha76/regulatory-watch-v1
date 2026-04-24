"""
Structured obligation extraction (M4 phase 3).

For ChangeEvents the L3 scorer has flagged as substantive or critical
(`significance_score >= 0.6`), this service extracts discrete,
machine-readable obligations:

    (actor, action, condition, deadline, penalty, obligation_type)

Unlike the `compliance_summary` field on ChangeEvent — a human-readable
paragraph — these rows are queryable and composable. They power:

  * M5 alerts — "notify user X when a new obligation with
                actor='financial institutions' and deadline < 90 days
                is detected"
  * M6 dashboards — "upcoming compliance deadlines across all monitored
                     sources, sorted by due date"

Design
------
* **Gated on score ≥ 0.6.** typo/cosmetic/minor events produce zero
  obligations, so we don't pay the LLM cost. This is the single
  biggest knob on marginal cost.

* **Chunked extraction.** Long documents are split into paragraph-
  aware chunks (each ≤ ``LLM_OBLIGATIONS_MAX_CONTENT`` chars) and the
  LLM is called once per chunk. Results are deduplicated on normalized
  ``(actor, action, obligation_type)``. This replaces the previous
  "truncate to 6K chars" behaviour which silently dropped obligations
  from the second half of long regulations.

* **Chunk cap.** ``LLM_OBLIGATIONS_MAX_CHUNKS`` bounds the worst-case
  cost per event. Over-cap chunks are dropped with a warning log.

* **Idempotent.** ``change_events.obligations_extracted_at`` is set on
  every successful attempt (even when zero obligations are produced).
  Re-runs are a no-op unless the caller passes ``force=True``.

* **Fail modes.**
    - HTTP error on any chunk → bail the whole event, return
      ``http_error``; the Celery task retries. Partial obligations
      are never persisted.
    - Parse error on one chunk → log and skip *that chunk only*;
      continue with the others. Prevents a single malformed LLM
      response from losing the whole event's obligations.

* **Deadline parsing** is best-effort. We accept ISO-8601-ish dates
  ("2026-06-30") and a small set of obvious natural-language forms
  ("30 June 2026", "June 30, 2026"). Anything else →
  ``deadline_date = NULL``, ``deadline_text`` preserves the exact wording.

Public API
----------
extract_obligations(event_id: UUID, *, force: bool = False) -> dict
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.logging_setup import get_logger
from app.models import ChangeEvent, Obligation, SourceVersion
from app.services import llm_usage

logger = get_logger(__name__)


# ── Constants (keep in sync with alembic 009) ────────────────────────────────

OBLIGATION_TYPES = (
    "reporting",
    "prohibition",
    "threshold",
    "disclosure",
    "registration",
    "penalty",
    "other",
)


def _truncate_for_log(s: str, limit: int) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit] + f"… [+{len(s) - limit} chars]"


# ── Pydantic schema ──────────────────────────────────────────────────────────

class ObligationItem(BaseModel):
    actor: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=2000)
    condition: Optional[str] = Field(default=None, max_length=2000)
    deadline_text: Optional[str] = Field(default=None, max_length=255)
    penalty: Optional[str] = Field(default=None, max_length=2000)
    obligation_type: str = Field(default="other")
    # M5c — verbatim quote from the chunk that establishes this
    # obligation. Located in the full source_text downstream to
    # compute char offsets for in-document highlighting. None when
    # the LLM couldn't cite a specific sentence (in which case the
    # prompt asks it to drop the obligation entirely).
    source_quote: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("obligation_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        return v if v in OBLIGATION_TYPES else "other"


class ObligationOutput(BaseModel):
    obligations: list[ObligationItem] = Field(default_factory=list)


# ── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior compliance analyst. Given a regulatory document change,
extract the discrete ACTIONABLE OBLIGATIONS it imposes on regulated
parties.

Respond with a single JSON object:

{
  "obligations": [
    {
      "actor":           "who must act (e.g. 'importers', 'banks with >$10B assets',
                          'data controllers')",
      "action":          "what they must do or not do (1–2 sentences, imperative)",
      "condition":       "optional — when/if this applies (null if always)",
      "deadline_text":   "optional — human-readable deadline (null if none)",
      "penalty":         "optional — consequence of non-compliance (null if unspecified)",
      "obligation_type": one of:
        - "reporting"     — file / submit / report to an authority
        - "prohibition"   — must not / may not
        - "threshold"     — quantitative limits (capital ratios, HS quotas…)
        - "disclosure"    — publish / inform / disclose (public or counterparty)
        - "registration"  — register / license / notify an authority
        - "penalty"       — payment of fine / fee / sanction
        - "other",
      "source_quote":    verbatim text from THIS chunk that establishes
                         this obligation. Copy exactly — preserve
                         punctuation, capitalization, numbers, quotes.
                         Do NOT paraphrase. Do NOT merge sentences.
                         Typically 1–3 sentences, max ~500 chars.
                         If you cannot cite specific text for an
                         obligation, DO NOT extract it at all (better
                         to miss a real one than fabricate a citation).
    }
  ]
}

Rules:
- Extract each DISTINCT obligation as its own row. Do NOT concatenate
  multiple unrelated duties into a single row.
- Use literal wording from the source where possible.
- Do NOT invent deadlines, fines, or penalties not present in the text.
- If the text imposes no new obligations, return {"obligations": []}.
- Prefer specific actors ("SIFI banks", "US importers of steel")
  over vague ones ("businesses", "entities") when the text allows.
- Keep `action` in imperative form ("File a Form 8-K within 4 business days.").
- When you receive a chunk of a larger document, extract only what is
  clearly stated in THIS chunk. Do NOT speculate about content in
  other chunks or invent cross-references you cannot see.
- Every extracted obligation MUST have a verbatim source_quote from
  this chunk. No quote → drop the obligation.
"""


def _build_user_prompt(
    event: ChangeEvent,
    title: Optional[str],
    content: str,
    *,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> str:
    """Build the per-call user prompt.

    When ``total_chunks > 1`` the header tells the LLM it's seeing a
    chunk of a larger document so it doesn't invent cross-references
    or assume the chunk represents the whole regulation.
    """
    if total_chunks > 1:
        chunk_hint = (
            f"Document content — chunk {chunk_index + 1} of {total_chunks}. "
            "Extract only obligations clearly stated in THIS chunk."
        )
    else:
        chunk_hint = "Document content (what to extract obligations from):"

    parts = [
        f"Source URL: {event.source_url}",
        f"Title: {title or '-'}",
        f"Diff kind: {event.diff_kind}",
        f"Significance score: {event.significance_score:.2f}"
        if event.significance_score is not None else "Significance score: -",
        f"Change type: {event.change_type or '-'}",
        f"Topic: {event.topic or '-'}",
        f"LLM compliance summary: {event.summary or '-'}",
        "",
        chunk_hint,
        content,
    ]
    return "\n".join(parts)


# ── Chunking ─────────────────────────────────────────────────────────────────

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def _fixed_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Sliding-window fallback for text without paragraph breaks or for
    a single paragraph that exceeds the chunk budget."""
    if chunk_size <= 0:
        return [text] if text else []
    stride = chunk_size - overlap
    if stride <= 0:
        stride = chunk_size  # nonsensical overlap → behave as non-overlapping
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + chunk_size])
        i += stride
    return out


def _chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """
    Paragraph-aware chunker with sliding-window fallback.

    Algorithm:
      1. If the full text already fits, return ``[text]``.
      2. Split on blank lines. If there are no paragraph boundaries,
         fall through to fixed-size chunks.
      3. Pack paragraphs into chunks up to ``chunk_size``. When a chunk
         is full, emit it and start a new one.
      4. If a single paragraph exceeds ``chunk_size`` (rare; usually a
         PDF that lost its linebreaks), fall back to ``_fixed_chunks``
         for that paragraph only. Overlap is applied there so actor
         and verb introduced at the start carry into the next slice.

    Paragraph boundaries are natural cut points, so in the common case
    we do NOT add overlap between chunks — it would waste LLM budget
    re-processing text we already saw.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    if not paragraphs:
        return _fixed_chunks(text, chunk_size, overlap)

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for para in paragraphs:
        if len(para) > chunk_size:
            # Flush whatever we've accumulated, then slice this
            # oversized paragraph with overlap.
            if buf:
                chunks.append("\n\n".join(buf))
                buf, buf_len = [], 0
            chunks.extend(_fixed_chunks(para, chunk_size, overlap))
            continue

        # +2 accounts for the "\n\n" joiner when buf is non-empty.
        sep_cost = 2 if buf else 0
        if buf_len + sep_cost + len(para) > chunk_size:
            chunks.append("\n\n".join(buf))
            buf = [para]
            buf_len = len(para)
        else:
            buf.append(para)
            buf_len += sep_cost + len(para)

    if buf:
        chunks.append("\n\n".join(buf))

    return chunks


# ── Dedup ────────────────────────────────────────────────────────────────────

_DEDUP_WS_RE = re.compile(r"\s+")


def _normalize_for_dedup(s: Optional[str]) -> str:
    """Collapse whitespace + lowercase — good-enough fuzzy-equal key."""
    if not s:
        return ""
    return _DEDUP_WS_RE.sub(" ", s.strip().lower())


def _dedupe_obligations(items: list[ObligationItem]) -> list[ObligationItem]:
    """
    Remove duplicates by normalized ``(actor, action, obligation_type)``.

    When chunking, the same obligation can appear in two adjacent
    chunks if the LLM restated it, or if fixed-size slicing duplicated
    text within the overlap region. Keep the first occurrence; drop
    subsequent ones.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[ObligationItem] = []
    for item in items:
        key = (
            _normalize_for_dedup(item.actor),
            _normalize_for_dedup(item.action),
            item.obligation_type,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    api_key: str,
    event_id: Optional[str] = None,
) -> tuple[str, int, str]:
    """Call OpenAI; return (content, latency_ms, request_hash)."""
    settings = get_settings()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": settings.LLM_OBLIGATIONS_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    fp = hashlib.sha256(
        (model + "\x1f" + system_prompt + "\x1f" + user_prompt).encode("utf-8")
    ).hexdigest()[:12]

    started = time.monotonic()
    with httpx.Client(timeout=settings.LLM_TIMEOUT) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload, headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
    latency_ms = int((time.monotonic() - started) * 1000)
    llm_usage.record(
        scope="obligations",
        model=model,
        usage=body.get("usage"),
        latency_ms=latency_ms,
        request_hash=fp,
        event_id=event_id,
    )
    return body["choices"][0]["message"]["content"], latency_ms, fp


# ── Deadline parsing ─────────────────────────────────────────────────────────

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(\d{4})\b",
    re.IGNORECASE,
)
_MDY_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(\d{1,2}),\s*(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_TO_NUM = {
    m: i + 1
    for i, m in enumerate([
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ])
}


def _parse_deadline(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    t = text.strip()
    m = _ISO_DATE_RE.search(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DMY_RE.search(t)
    if m:
        try:
            return date(int(m.group(3)), _MONTH_TO_NUM[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            return None
    m = _MDY_RE.search(t)
    if m:
        try:
            return date(int(m.group(3)), _MONTH_TO_NUM[m.group(1).lower()], int(m.group(2)))
        except (ValueError, KeyError):
            return None
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def extract_obligations(event_id: UUID, *, force: bool = False) -> dict:
    """
    Extract structured obligations for a single ChangeEvent.

    Gating:
      - Skipped (``status=below_gate``) when ``significance_score <
        OBLIGATIONS_SCORE_GATE``.
      - Skipped (``status=already_extracted``) when already extracted
        and ``force=False``.

    Returns
    -------
    dict
        ``{"status": str, "event_id": str, "obligations": int, ...telemetry...}``
    """
    settings = get_settings()
    log = logger.bind(event_id=str(event_id), service="obligations")

    with Session(engine) as session:
        event = session.get(ChangeEvent, event_id)
        if event is None:
            log.warning("event_not_found")
            return {"status": "missing", "event_id": str(event_id)}

        if event.obligations_extracted_at is not None and not force:
            return {
                "status": "already_extracted",
                "event_id": str(event_id),
                "obligations": 0,
            }

        if (event.significance_score is None
                or event.significance_score < settings.OBLIGATIONS_SCORE_GATE):
            event.obligations_extracted_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            return {
                "status": "below_gate",
                "event_id": str(event_id),
                "score": event.significance_score,
            }

        if not settings.OPENAI_API_KEY:
            log.warning("missing_api_key")
            return {"status": "skipped_no_api_key", "event_id": str(event_id)}

        # ── Load full text (no truncation — chunking handles size) ──
        title: Optional[str] = None
        source_text = ""
        if event.new_version_id:
            sv = session.get(SourceVersion, event.new_version_id)
            if sv is not None:
                title = sv.title
                source_text = sv.raw_text or ""

        # Fallbacks when the version's raw_text is unavailable. Both
        # are small so chunking is a no-op for them.
        if not source_text and event.unified_diff:
            source_text = event.unified_diff
        if not source_text and event.summary:
            source_text = event.summary

        if not source_text:
            event.obligations_extracted_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            log.info("empty_content_skipped")
            return {"status": "empty_content", "event_id": str(event_id)}

        # ── Chunk ────────────────────────────────────────────────────
        chunks = _chunk_text(
            source_text,
            chunk_size=settings.LLM_OBLIGATIONS_MAX_CONTENT,
            overlap=settings.LLM_OBLIGATIONS_CHUNK_OVERLAP,
        )
        n_chunks_produced = len(chunks)
        if n_chunks_produced > settings.LLM_OBLIGATIONS_MAX_CHUNKS:
            log.warning(
                "obligations_chunk_cap_hit",
                produced=n_chunks_produced,
                cap=settings.LLM_OBLIGATIONS_MAX_CHUNKS,
                full_chars=len(source_text),
                source_url=event.source_url,
            )
            chunks = chunks[: settings.LLM_OBLIGATIONS_MAX_CHUNKS]

        # ── Extract per chunk ────────────────────────────────────────
        all_items: list[ObligationItem] = []
        total_latency = 0
        parse_errors = 0
        last_request_hash: Optional[str] = None

        for i, chunk in enumerate(chunks):
            user_prompt = _build_user_prompt(
                event, title, chunk,
                chunk_index=i, total_chunks=len(chunks),
            )
            try:
                raw, latency_ms, request_hash = _call_llm(
                    _SYSTEM_PROMPT,
                    user_prompt,
                    model=settings.OPENAI_MODEL,
                    api_key=settings.OPENAI_API_KEY,
                    event_id=str(event_id),
                )
                total_latency += latency_ms
                last_request_hash = request_hash
            except httpx.HTTPError as exc:
                # Abort the whole event on HTTP failure — partial
                # obligations would leave the caller thinking the
                # event is "done" when it isn't. Task-level retry will
                # re-enter here and redo all chunks.
                log.warning(
                    "llm_http_error",
                    error_type=exc.__class__.__name__,
                    error=str(exc)[:300],
                    model=settings.OPENAI_MODEL,
                    chunk_index=i,
                    total_chunks=len(chunks),
                    source_url=event.source_url,
                )
                return {
                    "status": "http_error",
                    "event_id": str(event_id),
                    "error": str(exc),
                    "chunk_index": i,
                }

            try:
                data = json.loads(raw)
                parsed = ObligationOutput(**data)
                all_items.extend(parsed.obligations)
            except (json.JSONDecodeError, ValidationError) as exc:
                # Skip this chunk; the others may still be usable.
                parse_errors += 1
                log.warning(
                    "llm_parse_error_in_chunk",
                    error_type=exc.__class__.__name__,
                    error=str(exc)[:300],
                    model=settings.OPENAI_MODEL,
                    request_hash=request_hash,
                    latency_ms=latency_ms,
                    chunk_index=i,
                    total_chunks=len(chunks),
                    raw_response=_truncate_for_log(
                        raw, settings.LLM_ERROR_LOG_RESPONSE_CHARS),
                    source_url=event.source_url,
                )
                continue

        # ── Dedup ────────────────────────────────────────────────────
        deduped = _dedupe_obligations(all_items)
        duplicates_removed = len(all_items) - len(deduped)

        # ── Persist ──────────────────────────────────────────────────
        # Locate each obligation's source_quote in the full source text
        # to compute char-offset spans for in-document highlighting.
        # Searching the full source (rather than per-chunk) is simpler
        # and still cheap: a few str.find calls over ~100KB text.
        from app.services.citations import locate_quote

        now = datetime.now(timezone.utc)
        if force:
            prior = session.exec(
                select(Obligation).where(Obligation.change_event_id == event_id)
            ).all()
            for row in prior:
                session.delete(row)
            session.flush()

        created = 0
        spans_located = 0
        for item in deduped:
            quote_clean = (item.source_quote or "").strip() or None
            span_start: Optional[int] = None
            span_end: Optional[int] = None
            if quote_clean and source_text:
                span = locate_quote(source_text, quote_clean)
                if span is not None:
                    span_start, span_end = span
                    spans_located += 1

            obl = Obligation(
                change_event_id=event_id,
                actor=item.actor[:255],
                action=item.action,
                condition=item.condition,
                deadline_text=(item.deadline_text or None),
                deadline_date=_parse_deadline(item.deadline_text),
                penalty=item.penalty,
                obligation_type=item.obligation_type,
                llm_model=settings.OPENAI_MODEL,
                extracted_at=now,
                source_quote=quote_clean,
                source_span_start=span_start,
                source_span_end=span_end,
            )
            session.add(obl)
            created += 1

        event.obligations_extracted_at = now
        session.add(event)
        score_snapshot = event.significance_score or 0.0
        source_url = event.source_url
        session.commit()

    status = "extracted" if created > 0 else "no_obligations"
    log.info(
        "done",
        status=status,
        obligations_created=created,
        chunks_processed=len(chunks),
        chunks_produced=n_chunks_produced,
        raw_obligations=len(all_items),
        duplicates_removed=duplicates_removed,
        parse_errors=parse_errors,
        spans_located=spans_located,
        total_latency_ms=total_latency,
        score=round(score_snapshot, 3),
        model=settings.OPENAI_MODEL,
        request_hash=last_request_hash,
        source_url=source_url,
    )
    return {
        "status": status,
        "event_id": str(event_id),
        "obligations": created,
        "chunks_processed": len(chunks),
        "chunks_produced": n_chunks_produced,
        "raw_obligations": len(all_items),
        "duplicates_removed": duplicates_removed,
        "parse_errors": parse_errors,
        "spans_located": spans_located,
    }


def iter_pending(session: Session, *, limit: Optional[int] = None) -> list[UUID]:
    """
    Return ids of scored events that are above the configured score gate
    and have NOT yet been through obligation extraction. Used by the
    Celery periodic sweeper + backfill script.
    """
    settings = get_settings()
    stmt = (
        select(ChangeEvent.id)
        .where(ChangeEvent.significance_score >= settings.OBLIGATIONS_SCORE_GATE)
        .where(ChangeEvent.obligations_extracted_at.is_(None))
        .where(ChangeEvent.scored_at.is_not(None))
        .order_by(ChangeEvent.detected_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())
