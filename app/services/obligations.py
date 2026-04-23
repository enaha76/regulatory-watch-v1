"""
Structured obligation extraction (M4 phase 3).

For ChangeEvents the L3 scorer has flagged as substantive or critical
(`significance_score >= 0.6`), this service makes a second, cheaper LLM
call to pull out discrete, machine-readable obligations:

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
* **Idempotent.** `change_events.obligations_extracted_at` is set on
  every attempt (even when zero obligations are produced), so a re-run
  is a no-op unless the caller passes `force=True`.
* **Fail-soft.** HTTP / parse errors are logged and the `extracted_at`
  marker is NOT set, so the next scheduler pass will retry.
* **Deadline parsing** is best-effort. We accept ISO-8601-ish dates
  ("2026-06-30") and a small set of obvious natural-language forms
  ("30 June 2026", "June 30, 2026"). Anything else → `deadline_date
  = NULL`, `deadline_text` preserves the exact wording.

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
        - "other"
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
"""


def _build_user_prompt(event: ChangeEvent, title: Optional[str], content: str) -> str:
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
        "Document content (what to extract obligations from):",
        content,
    ]
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
      - Skipped (`status=below_gate`) when significance_score < OBLIGATIONS_SCORE_GATE.
      - Skipped (`status=already_extracted`) when already extracted and
        `force=False`.

    Return shape: {"status": str, "event_id": str, "obligations": int}.
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

        title: Optional[str] = None
        content: str = ""
        max_content = settings.LLM_OBLIGATIONS_MAX_CONTENT
        if event.new_version_id:
            sv = session.get(SourceVersion, event.new_version_id)
            if sv is not None:
                title = sv.title
                content = (sv.raw_text or "")[:max_content]
        # For modified events, if we got the full text above, use it.
        # Only fall back to diff if no full text is available at all.
        # (Fix 3 — Contextless Diff: the diff alone lacks actor/section
        # context needed for obligation extraction.)
        if not content and event.unified_diff:
            content = event.unified_diff[:max_content]
        if not content and event.summary:
            content = event.summary
        if not content:
            event.obligations_extracted_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
            log.info("empty_content_skipped")
            return {"status": "empty_content", "event_id": str(event_id)}

        user_prompt = _build_user_prompt(event, title, content)

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
            log.warning("llm_http_error",
                        error_type=exc.__class__.__name__,
                        error=str(exc)[:300],
                        model=settings.OPENAI_MODEL,
                        source_url=event.source_url)
            return {"status": "http_error", "event_id": str(event_id),
                    "error": str(exc)}

        try:
            data = json.loads(raw)
            parsed = ObligationOutput(**data)
        except (json.JSONDecodeError, ValidationError) as exc:
            event.obligations_extracted_at = datetime.now(timezone.utc)
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
            return {"status": "parse_error", "event_id": str(event_id),
                    "error": str(exc)}

        now = datetime.now(timezone.utc)
        if force:
            prior = session.exec(
                select(Obligation).where(Obligation.change_event_id == event_id)
            ).all()
            for row in prior:
                session.delete(row)
            session.flush()

        created = 0
        for item in parsed.obligations:
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
            )
            session.add(obl)
            created += 1

        event.obligations_extracted_at = now
        session.add(event)
        # Capture values before commit closes the session to avoid
        # DetachedInstanceError on access post-commit.
        score_snapshot = event.significance_score or 0.0
        source_url = event.source_url
        session.commit()

    status = "extracted" if created > 0 else "no_obligations"
    log.info("done",
             status=status,
             obligations_created=created,
             score=round(score_snapshot, 3),
             model=settings.OPENAI_MODEL,
             latency_ms=latency_ms,
             request_hash=request_hash,
             source_url=source_url)
    return {
        "status": status,
        "event_id": str(event_id),
        "obligations": created,
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
