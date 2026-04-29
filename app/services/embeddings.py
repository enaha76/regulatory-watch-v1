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

    Raises httpx.HTTPError on network / API errors.
    Raises RuntimeError if OPENAI_API_KEY is not configured.
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured — cannot embed")

    text = text.strip()
    if not text:
        raise ValueError("embed() called with empty text")

    started = time.monotonic()
    with httpx.Client(timeout=settings.LLM_TIMEOUT) as client:
        resp = client.post(
            "https://api.openai.com/v1/embeddings",
            json={"model": settings.EMBEDDING_MODEL, "input": text},
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

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
