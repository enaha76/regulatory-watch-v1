"""
Embedding service — wraps OpenAI text-embedding-3-small.

Two public helpers:
  embed(text)                   → list[float]  (call OpenAI, log cost)
  build_subscription_text(kws)  → str          (keywords → embed input)
  build_doc_text(event)         → str          (event fields → embed input)

Design notes
------------
* Swap the model by changing EMBEDDING_MODEL in config — the dim must
  match EMBEDDING_DIM (default 1536 for text-embedding-3-small).
* Failures raise; callers should catch and log — never block scoring or
  ingestion on an embedding error.
* Cost is tracked via llm_usage.record() with scope="embedding" so the
  existing cost ledger covers this too.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.services import llm_usage

if TYPE_CHECKING:
    from app.models import ChangeEvent

log = get_logger(__name__)


def embed(text: str) -> list[float]:
    """Call the OpenAI Embeddings API and return the vector.

    Retries on transient failures (timeouts, network errors, 429 rate
    limits, 5xx server errors) — without retry, ~half of substantive
    events were stranded in the DB scored-but-without-embedding,
    making them invisible to the matcher. Permanent failures (401,
    400) raise immediately so callers see real bugs.

    Raises httpx.HTTPError on terminal network / API errors after retries.
    Raises RuntimeError if OPENAI_API_KEY is not configured.
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured — cannot embed")

    text = text.strip()
    if not text:
        raise ValueError("embed() called with empty text")

    # Retry policy: 3 attempts with exponential backoff (1s, 2s, 4s).
    # The OpenAI embeddings endpoint is normally <1s; if it doesn't
    # respond within LLM_TIMEOUT, three retries cover virtually every
    # transient bump without compounding into long stalls.
    last_exc: Exception | None = None
    body: dict | None = None
    started = time.monotonic()
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.LLM_TIMEOUT) as client:
                resp = client.post(
                    "https://api.openai.com/v1/embeddings",
                    json={"model": settings.EMBEDDING_MODEL, "input": text},
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                # Permanent failures: don't retry (auth / malformed body).
                if resp.status_code in (400, 401, 403, 404, 422):
                    resp.raise_for_status()
                # Transient: 429 + 5xx — retry.
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    raise httpx.HTTPStatusError(
                        f"transient {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                body = resp.json()
                break
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
        ) as exc:
            last_exc = exc
            if attempt < 2:
                # 1s, 2s — keep total worst-case under ~10s.
                time.sleep(2 ** attempt)
                log.warning(
                    "embed_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            log.error(
                "embed_failed_after_retries",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise
    if body is None:
        # Defensive — the loop above either sets body or raises; this
        # branch only triggers if the retry budget is misconfigured.
        raise httpx.HTTPError(
            f"embed() exhausted retries: {last_exc}",
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    # OpenAI embeddings usage only has prompt_tokens (no completion).
    usage = body.get("usage", {})
    llm_usage.record(
        scope="embedding",
        model=settings.EMBEDDING_MODEL,
        usage=usage,
        latency_ms=latency_ms,
        request_hash="",
    )

    vector: list[float] = body["data"][0]["embedding"]
    log.debug("embedded", model=settings.EMBEDDING_MODEL,
              tokens=usage.get("prompt_tokens", 0),
              latency_ms=latency_ms, dim=len(vector))
    return vector


def build_subscription_text(keywords: list[str]) -> str:
    """Concatenate user keywords into a single embed input string."""
    return ", ".join(k.strip() for k in keywords if k.strip())


def build_doc_text(event: ChangeEvent) -> str:
    """Build the embed input for a ChangeEvent.

    Uses summary + entities + topic — compact, semantic-rich, and well
    within the ~8K token limit of text-embedding-3-small.
    """
    parts: list[str] = []
    if event.topic:
        parts.append(f"Topic: {event.topic}")
    if event.affected_entities:
        entities = [str(e) for e in event.affected_entities[:15]]
        parts.append("Entities: " + ", ".join(entities))
    if event.summary:
        parts.append(event.summary)
    return "\n".join(parts)
