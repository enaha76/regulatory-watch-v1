"""
Change-event significance scorer (M3 Layer 3).

Given an already-emitted `ChangeEvent`, this module asks an LLM the
compliance-officer question: *"does this change actually matter, and if
so, why?"* The answer — a score, a category, affected entities, deadline
changes, and a plain-English summary — is persisted back onto the event.

Design notes
------------
* Deliberately *decoupled from ingestion*. The ingestion pipeline emits
  change events via `record_change()` (Layer-1+2, deterministic, fast).
  Scoring happens asynchronously via a Celery task. A failure here
  **must not** block ingestion or alerting.

* **Cache-by-construction**: each ChangeEvent.id is scored at most once.
  Re-running scoring on an already-scored row is a no-op.

* **Fail-soft**: if the LLM is unavailable, rate-limited, or returns
  malformed JSON, we record `llm_error` and move on. The alerting
  layer can still fall back to a character-count heuristic.

* **Cost control**:
    - diff truncated to ~6k chars before sending
    - `response_format=json_object` → no retries for JSON parsing
    - `temperature=0` for deterministic scoring
    - uses the project's default cheap model (`gpt-4o-mini`)

Public API
----------
score_event(event_id: UUID) -> dict
    Score a single event. Returns a summary dict (also logged). Safe to
    call from a Celery worker or a backfill script.

needs_scoring(event: ChangeEvent) -> bool
    True iff the event hasn't been successfully scored yet.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session

from app.config import get_settings
from app.database import engine
from app.logging_setup import get_logger
from app.models import ChangeEvent, SourceVersion
from app.services import llm_usage

logger = get_logger(__name__)


# ── Rubric (keep in sync with alembic 006 + prompt) ──────────────────────────
CHANGE_TYPES = (
    "typo_or_cosmetic",   # 0.00–0.19  punctuation, whitespace, broken links
    "minor_wording",      # 0.20–0.39  rephrasing with no legal effect
    "clarification",      # 0.40–0.59  explains existing rule more clearly
    "substantive",        # 0.60–0.79  rule, threshold, or scope is altered
    "critical",           # 0.80–1.00  new deadline / penalty / obligation
)

# ── Topic taxonomy (keep in sync with alembic 007) ───────────────────────────
TOPICS = (
    "customs_trade",
    "financial_services",
    "data_privacy",
    "environmental",
    "healthcare_pharma",
    "sanctions_export_control",
    "labor_employment",
    "tax_accounting",
    "consumer_protection",
    "corporate_governance",
    "other",
)


def _truncate_for_log(s: str, limit: int) -> str:
    """Bounded preview for log fields. Avoids leaking full document text."""
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit] + f"… [+{len(s) - limit} chars]"


# ── Pydantic output schema ───────────────────────────────────────────────────

class DeadlineChange(BaseModel):
    """A single deadline delta extracted from the diff."""
    old: Optional[str] = Field(default=None, description="Previous deadline text; null if newly introduced.")
    new: Optional[str] = Field(default=None, description="New deadline text; null if removed.")
    deadline_text: str = Field(description="Short human label, e.g. 'ISF filing window'.")


_TRADE_FLOW_VALUES = ("inbound", "outbound", "bilateral", "global")


class SignificanceOutput(BaseModel):
    """LLM output schema. Validated strictly."""
    significance_score: float = Field(ge=0.0, le=1.0)
    change_type: str
    topic: str = Field(default="other")
    affected_entities: list[str] = Field(default_factory=list)
    deadline_changes: list[DeadlineChange] = Field(default_factory=list)
    compliance_summary: str = Field(min_length=1, max_length=2000)
    # ── M5 prelude: trade-flow / country filters ─────────────────────
    # LLM-produced. `origin_countries` is normalised downstream through
    # `app.services.geo.normalize_country_codes`; here we accept any
    # list of strings so a single typo doesn't fail the whole call.
    origin_countries: list[str] = Field(default_factory=list)
    trade_flow_direction: Optional[str] = Field(default=None)

    @field_validator("change_type")
    @classmethod
    def _known_change_type(cls, v: str) -> str:
        if v not in CHANGE_TYPES:
            raise ValueError(f"change_type must be one of {CHANGE_TYPES}, got {v!r}")
        return v

    @field_validator("topic")
    @classmethod
    def _known_topic(cls, v: str) -> str:
        # Be permissive: unknown topics collapse to "other" rather than
        # failing the whole scoring call. The taxonomy may evolve faster
        # than the LLM learns it.
        return v if v in TOPICS else "other"

    @field_validator("trade_flow_direction")
    @classmethod
    def _known_trade_flow(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v2 = v.strip().lower()
        if not v2:
            return None
        return v2 if v2 in _TRADE_FLOW_VALUES else None

    @field_validator("affected_entities")
    @classmethod
    def _trim_entities(cls, v: list[str]) -> list[str]:
        # Deduplicate, strip, drop empties, cap at 20 — keeps JSON sane.
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            s = (item or "").strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            out.append(s)
            if len(out) >= 20:
                break
        return out


# ── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior compliance analyst reviewing a diff between two versions of
a regulatory document. Your job is to decide whether the change is noise
(cosmetic/editorial) or signal (substantive/critical) for a compliance team.

You MUST respond with a single JSON object matching this schema:

{
  "significance_score": float in [0.0, 1.0],
  "change_type": one of:
    - "typo_or_cosmetic"  (0.00–0.19)  punctuation, whitespace, broken links, asset paths
    - "minor_wording"     (0.20–0.39)  rephrasing with no legal effect
    - "clarification"     (0.40–0.59)  explains an existing rule more clearly, no new obligation
    - "substantive"       (0.60–0.79)  a rule / threshold / scope / definition is altered
    - "critical"          (0.80–1.00)  a new deadline, penalty, or obligation is introduced or removed
  "topic": one of (pick the SINGLE best-fitting regulatory domain):
    - "customs_trade"             — import/export, tariffs, customs, HS codes, trade sanctions on goods
    - "financial_services"        — banking, payments, securities, insurance, crypto, AML/KYC, consumer credit
    - "data_privacy"              — GDPR, CCPA, data protection, cybersecurity, breach notification
    - "environmental"             — emissions, waste, chemicals (REACH), climate disclosure
    - "healthcare_pharma"         — FDA/EMA, medical devices, drug approvals, clinical trials, HIPAA
    - "sanctions_export_control"  — OFAC, export controls, dual-use goods, embargo lists
    - "labor_employment"          — workplace safety, wages, discrimination, unions, immigration
    - "tax_accounting"            — tax rules, reporting, transfer pricing, audit standards
    - "consumer_protection"       — product safety, advertising, consumer rights, recalls
    - "corporate_governance"      — securities disclosure, M&A, board duties, ESG reporting
    - "other"                     — use only if NONE of the above clearly fits
  "affected_entities": list of strings (regulations cited, HS/HTS/CN/TARIC
                       codes, industries, agency names, program names).
                       - If a tariff / customs code appears ANYWHERE in the diff
                         or the NEW body (e.g. "HTS 9401.61", "0304.29.00",
                         "Schedule B 0405.20.3000", "Heading 39.09", "Chapter 69"),
                         you MUST list it verbatim as its own entry — one
                         entity per distinct code.
                       - Keep the code's exact punctuation and spacing
                         ("0304.29.00", not "030429 00").
                       Empty list if none.
  "deadline_changes":  list of objects {old, new, deadline_text}. Empty list if none.
  "compliance_summary": 1–3 sentences, plain English, actionable.
                        Address the reader as "you" and say what they need to do
                        (or not do) as a result of this change.
  "origin_countries":  list of ISO-3166 alpha-2 codes identifying the country of
                       ORIGIN of goods / transactions / entities the rule applies
                       to. Use "EU" for European Union, "GB" for the United Kingdom.
                       - For a CBP ruling on Chinese-origin goods → ["CN"].
                       - For an EU directive affecting imports from several
                         countries → list all of them, e.g. ["CN","RU","IR"].
                       - HTSUS Chapter 99 subheadings 9903.01.* / 9903.88.* are
                         Section 301 China tariffs → include "CN".
                       - 9903.80.* are Japan-related, 9903.81.* Korea-related,
                         9903.85.* Vietnam-related (use the appropriate ISO-2).
                       - If the rule is genuinely global / multilateral with no
                         country focus, return [].
                       Empty list when unknown — do NOT guess.
  "trade_flow_direction": one of "inbound" | "outbound" | "bilateral" | "global"
                       relative to the REGULATOR's jurisdiction.
                       - "inbound"   : goods / services entering the regulator's
                                       jurisdiction (e.g. US tariff on imports).
                       - "outbound"  : restrictions on what the jurisdiction can
                                       export (e.g. OFAC export controls).
                       - "bilateral" : applies both ways (FTA, MRA, sanctions
                                       covering both export AND import).
                       - "global"    : multilateral / jurisdiction-agnostic.
                       null when the document has no trade-flow aspect
                       (e.g. a pure domestic labour-safety rule).

Rules for MODIFIED events (unified diff provided):
- If the diff is only added/removed whitespace, punctuation, nav links, image
  paths, or boilerplate headers/footers → "typo_or_cosmetic", score ≤ 0.1.
- If there's no substantive text change at all → score 0.0, summary = "No material change."
- Do not invent deadlines that are not explicitly in the diff.

Rules for CREATED events (no prior version — judge the DOCUMENT CONTENT itself):
- A newly-crawled document is NOT automatically critical. Score based on what
  the content actually contains:
    * Boilerplate pages (landing pages, navigation hubs, index pages with no
      real content) → "typo_or_cosmetic", score ≤ 0.1, summary = "No material change."
    * News/announcement articles with no new obligations → "minor_wording"
      or "clarification" (0.2–0.5) with a 1–2 sentence factual summary.
    * Actual regulatory documents introducing obligations, deadlines,
      penalties, or thresholds → "substantive" or "critical" (0.6–1.0)
      with a specific actionable summary naming the obligation.
- The presence of Chinese / non-English text is irrelevant to significance.
  Read it in the original language and summarize in ENGLISH.
- Do NOT say "you should review this document" as a catch-all.
  If there's nothing to act on, say so explicitly.

Universal rules:
- Do not invent deadlines, amounts, or entities not explicitly in the input.
- Output valid JSON only. No prose, no markdown fences.
"""


def _trim_content(text: str) -> str:
    """Keep head + tail of long content to stay within prompt budget."""
    if not text:
        return ""
    text = text.strip()
    settings = get_settings()
    head_n = settings.LLM_MAX_CONTENT_HEAD
    tail_n = settings.LLM_MAX_CONTENT_TAIL
    max_len = head_n + tail_n
    if len(text) <= max_len:
        return text
    head = text[:head_n]
    tail = text[-tail_n:]
    return f"{head}\n… [content truncated for scoring — {len(text)} chars total] …\n{tail}"


def _build_user_prompt(
    *,
    source_url: str,
    title: Optional[str],
    diff_kind: str,
    added_chars: int,
    removed_chars: int,
    unified_diff: Optional[str],
    new_content: Optional[str] = None,
    context_snippet: Optional[str] = None,
) -> str:
    """
    Build the user prompt. For `modified` events we send the unified diff
    plus a surrounding context window so the LLM knows the section/actor;
    for `created` events we send a snippet of the actual document content
    so the LLM can score based on substance rather than mere existence.
    """
    parts = [
        f"Source URL : {source_url}",
        f"Title      : {title or '(unknown)'}",
        f"Change kind: {diff_kind}",
        f"Added chars: {added_chars}",
        f"Removed chars: {removed_chars}",
        "",
    ]

    if diff_kind == "created":
        content_snippet = _trim_content(new_content or "")
        if not content_snippet:
            content_snippet = "(no content available)"
        parts.extend([
            "Document content (this is a newly-discovered document; no prior version).",
            "Judge significance based on WHAT IS IN THIS DOCUMENT, not the mere fact that it is new:",
            "```",
            content_snippet,
            "```",
        ])
    else:
        diff_snippet = (unified_diff or "").strip()
        max_diff = get_settings().LLM_MAX_DIFF_CHARS
        if len(diff_snippet) > max_diff:
            head = diff_snippet[: max_diff // 2]
            tail = diff_snippet[-max_diff // 2 :]
            diff_snippet = f"{head}\n… [diff truncated for scoring] …\n{tail}"
        elif not diff_snippet:
            diff_snippet = "(no diff available for this modification)"
        parts.extend([
            "Unified diff:",
            "```diff",
            diff_snippet,
            "```",
        ])
        # Fix 3 — Contextless Diff: include surrounding document context
        # so the LLM knows which section/actor the diff applies to.
        if context_snippet:
            parts.extend([
                "",
                "Surrounding document context (for understanding who/what the diff applies to):",
                "```",
                context_snippet,
                "```",
            ])

    return "\n".join(parts)


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    api_key: str,
    event_id: Optional[str] = None,
) -> tuple[str, int, str]:
    """POST to OpenAI Chat Completions.

    Returns ``(content, latency_ms, request_hash)`` where ``request_hash`` is
    a short fingerprint of the prompts (NOT the API key) so logs can correlate
    a parse-failed response back to the exact prompts that produced it
    without dumping the full prompt text into log storage.
    """
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": settings.LLM_SCORING_MAX_TOKENS,
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
        scope="scoring",
        model=model,
        usage=body.get("usage"),
        latency_ms=latency_ms,
        request_hash=fp,
        event_id=event_id,
    )
    return body["choices"][0]["message"]["content"], latency_ms, fp


# ── Public API ───────────────────────────────────────────────────────────────

def needs_scoring(event: ChangeEvent) -> bool:
    """
    True iff `event` has never been successfully scored.

    An event with `llm_error` set is still eligible for a re-score
    (the backfill script picks those up when called with --retry-errors).
    """
    return event.significance_score is None and event.llm_error is None


def score_event(event_id: UUID, *, retry_errors: bool = False) -> dict:
    """
    Score a single ChangeEvent by id.

    Parameters
    ----------
    event_id : UUID
    retry_errors : bool
        If True, also rescore events whose previous attempt set `llm_error`.

    Returns
    -------
    dict summary (also logged). Keys:
      status : "scored" | "already_scored" | "skipped_no_api_key" |
               "skipped_missing_event" | "error"
      event_id : str
      score : float | None
      change_type : str | None
      error : str | None
    """
    settings = get_settings()

    log = logger.bind(event_id=str(event_id), service="significance")

    with Session(engine) as session:
        event = session.get(ChangeEvent, event_id)
        if event is None:
            log.warning("event_not_found")
            return {"status": "skipped_missing_event", "event_id": str(event_id)}

        # Idempotency guard
        if event.significance_score is not None:
            return {
                "status": "already_scored",
                "event_id": str(event_id),
                "score": event.significance_score,
                "change_type": event.change_type,
            }
        if event.llm_error is not None and not retry_errors:
            return {
                "status": "already_scored",
                "event_id": str(event_id),
                "score": None,
                "change_type": None,
                "error": event.llm_error,
            }

        if not settings.OPENAI_API_KEY:
            event.llm_error = "missing_api_key"
            event.scored_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            log.warning("missing_api_key", source_url=event.source_url)
            return {"status": "skipped_no_api_key", "event_id": str(event_id)}

        # Pull the new version's title + (for `created` events) its raw text
        # so the LLM can score on substance, not just existence.
        # For `modified` events, also grab a trimmed context window
        # (Fix 3 — Contextless Diff) so the LLM knows which
        # section/actor the diff applies to.
        title: Optional[str] = None
        new_content: Optional[str] = None
        context_snippet: Optional[str] = None
        if event.new_version_id:
            sv = session.get(SourceVersion, event.new_version_id)
            if sv is not None:
                title = sv.title
                if event.diff_kind == "created":
                    new_content = sv.raw_text
                elif event.diff_kind == "modified":
                    # Provide surrounding context so the LLM knows
                    # which section/actor the diff applies to.
                    context_snippet = _trim_content(sv.raw_text or "")

        user_prompt = _build_user_prompt(
            source_url=event.source_url,
            title=title,
            diff_kind=event.diff_kind,
            added_chars=event.added_chars or 0,
            removed_chars=event.removed_chars or 0,
            unified_diff=event.unified_diff,
            new_content=new_content,
            context_snippet=context_snippet,
        )

        raw = ""
        latency_ms = 0
        request_hash = ""
        try:
            raw, latency_ms, request_hash = _call_llm(
                _SYSTEM_PROMPT,
                user_prompt,
                model=settings.OPENAI_MODEL,
                api_key=settings.OPENAI_API_KEY,
                event_id=str(event_id),
            )
        except httpx.HTTPError as exc:
            err = f"http_error: {exc.__class__.__name__}: {exc}"
            event.llm_error = err[:1000]
            event.llm_model = settings.OPENAI_MODEL
            event.scored_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            log.warning("llm_http_error",
                        error_type=exc.__class__.__name__,
                        error=str(exc)[:300],
                        model=settings.OPENAI_MODEL,
                        source_url=event.source_url)
            return {"status": "error", "event_id": str(event_id), "error": err}

        try:
            data = json.loads(raw)
            parsed = SignificanceOutput(**data)
        except (json.JSONDecodeError, ValidationError) as exc:
            err = f"parse_error: {exc.__class__.__name__}: {exc}"
            event.llm_error = err[:1000]
            event.llm_model = settings.OPENAI_MODEL
            event.scored_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            log.warning("llm_parse_error",
                        error_type=exc.__class__.__name__,
                        error=str(exc)[:300],
                        model=settings.OPENAI_MODEL,
                        request_hash=request_hash,
                        latency_ms=latency_ms,
                        raw_response=_truncate_for_log(
                            raw, settings.LLM_ERROR_LOG_RESPONSE_CHARS),
                        source_url=event.source_url)
            return {"status": "error", "event_id": str(event_id), "error": err}

        # ── Persist ───────────────────────────────────────────────────
        from app.services.geo import (
            assign_trade_countries,
            normalize_country_codes,
            resolve_jurisdiction,
        )

        event.significance_score = parsed.significance_score
        event.change_type = parsed.change_type
        event.topic = parsed.topic
        event.affected_entities = parsed.affected_entities or None
        event.deadline_changes = (
            [dc.model_dump() for dc in parsed.deadline_changes]
            if parsed.deadline_changes
            else None
        )
        # M5 translation note: when the source document's language matches
        # the user's preferred_lang, bypass the English summary entirely.
        # The LLM should summarize directly in the source language to avoid
        # the lossy round-trip (source_lang → EN → source_lang).
        # See docs/architectural_problems.md §2 for rationale.
        event.summary = parsed.compliance_summary
        # Fix 1 — Hardcoded Trade Flow: use assign_trade_countries()
        # which respects trade_flow_direction instead of blindly mapping
        # the URL jurisdiction to destination_countries.
        jurisdiction = resolve_jurisdiction(event.source_url)
        llm_origins = normalize_country_codes(parsed.origin_countries)
        origin_iso, dest_iso = assign_trade_countries(
            jurisdiction=jurisdiction,
            llm_origin_countries=llm_origins,
            trade_flow_direction=parsed.trade_flow_direction,
        )
        event.origin_countries = origin_iso or None
        event.destination_countries = dest_iso or None
        event.trade_flow_direction = parsed.trade_flow_direction
        event.llm_model = settings.OPENAI_MODEL
        event.llm_error = None  # clear any prior failure
        event.scored_at = datetime.now(timezone.utc)

        # ── M5 semantic embedding ─────────────────────────────────────
        # Embed summary + entities + topic so the matching engine can do
        # cosine similarity against subscription embeddings. Best-effort:
        # a failure here never blocks scoring from persisting.
        try:
            from app.services.embeddings import build_doc_text, embed
            doc_text = build_doc_text(event)
            if doc_text:
                event.embedding = embed(doc_text)
        except Exception as _emb_exc:  # noqa: BLE001
            log.warning("doc_embedding_failed",
                        error=str(_emb_exc),
                        error_type=type(_emb_exc).__name__,
                        event_id=str(event_id))

        session.add(event)
        session.commit()

        log.info("scored",
                 score=round(parsed.significance_score, 3),
                 change_type=parsed.change_type,
                 topic=parsed.topic,
                 model=settings.OPENAI_MODEL,
                 latency_ms=latency_ms,
                 request_hash=request_hash,
                 entity_count=len(parsed.affected_entities),
                 origin_countries=origin_iso,
                 destination_countries=dest_iso,
                 trade_flow_direction=parsed.trade_flow_direction,
                 jurisdiction=jurisdiction,
                 source_url=event.source_url)

    # Post-scoring enrichment (M4) — best-effort; runs OUTSIDE the
    # scoring transaction so a failure here never corrupts the row.
    try:
        from app.services.entity_index import sync_entities_for_event
        sync_entities_for_event(event_id)
    except (ValueError, RuntimeError, KeyError) as exc:
        log.warning("entity_index_sync_failed",
                    error=str(exc), error_type=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        log.exception("entity_index_sync_unexpected_error",
                      error=str(exc), error_type=type(exc).__name__)

    # M5 — dispatch matching against user subscriptions (best-effort).
    # Fire-and-forget: a failure here never blocks M4 scoring.
    try:
        from app.celery_app import match_change_event
        match_change_event.delay(str(event_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("m5_match_dispatch_failed",
                    error=str(exc), error_type=type(exc).__name__)

    return {
        "status": "scored",
        "event_id": str(event_id),
        "score": parsed.significance_score,
        "change_type": parsed.change_type,
        "topic": parsed.topic,
    }
