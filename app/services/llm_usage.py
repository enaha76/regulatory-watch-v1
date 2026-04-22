"""
LLM usage & cost ledger.

Every billable LLM round-trip should funnel through :func:`record` so we
have a single source of truth for:

* structured log event  ("llm_call_recorded")
* append-only JSONL ledger at settings.LLM_USAGE_LEDGER_PATH
* USD cost computation (settings.LLM_PRICE_INPUT/OUTPUT_USD_PER_1M)

The ledger is intentionally file-based (not a DB table) so it works
without a migration, survives worker restarts, and can be shipped to
S3 / Loki / CloudWatch by any log forwarder. One line per call:

    {"ts": "2026-04-16T14:05:21.812Z",
     "scope": "scoring",
     "model": "gpt-4o-mini",
     "event_id": "7f9c…",
     "url": null,
     "prompt_tokens": 512,
     "completion_tokens": 183,
     "total_tokens": 695,
     "input_cost_usd": 0.0000768,
     "output_cost_usd": 0.0001098,
     "total_cost_usd": 0.0001866,
     "latency_ms": 842,
     "request_hash": "5aa1e8d0b913"}

Failures to write the ledger are *never* fatal — LLM work proceeds,
we just emit a warning.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger(__name__)

_WRITE_LOCK = Lock()


def _ledger_path() -> Optional[Path]:
    raw = (get_settings().LLM_USAGE_LEDGER_PATH or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        # Resolve relative paths against /opt/app (container) or cwd.
        base = Path(os.environ.get("APP_ROOT", "/opt/app"))
        if base.exists():
            p = base / p
        else:
            p = Path.cwd() / p
    return p


def compute_cost_usd(prompt_tokens: int, completion_tokens: int) -> tuple[float, float, float]:
    """Return (input_cost, output_cost, total_cost) in USD."""
    s = get_settings()
    in_cost = (prompt_tokens / 1_000_000.0) * s.LLM_PRICE_INPUT_USD_PER_1M
    out_cost = (completion_tokens / 1_000_000.0) * s.LLM_PRICE_OUTPUT_USD_PER_1M
    return in_cost, out_cost, in_cost + out_cost


def record(
    *,
    scope: str,
    model: str,
    usage: dict[str, Any] | None,
    latency_ms: int,
    request_hash: str,
    event_id: Optional[str] = None,
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Record one LLM call.

    ``usage`` is the raw OpenAI ``usage`` object (``prompt_tokens`` /
    ``completion_tokens`` / ``total_tokens``). Missing or malformed
    usage blobs are tolerated — we record zeros and log a warning so
    the call still shows up in the ledger.

    Returns the record dict (useful for tests + callers that want to
    echo the cost in their own logs).
    """
    usage = usage or {}
    try:
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    except (TypeError, ValueError):
        log.warning("llm_usage_malformed", scope=scope, request_hash=request_hash, usage=str(usage)[:200])
        prompt_tokens = completion_tokens = total_tokens = 0

    in_cost, out_cost, total_cost = compute_cost_usd(prompt_tokens, completion_tokens)

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "model": model,
        "event_id": event_id,
        "url": url,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "input_cost_usd": round(in_cost, 8),
        "output_cost_usd": round(out_cost, 8),
        "total_cost_usd": round(total_cost, 8),
        "latency_ms": latency_ms,
        "request_hash": request_hash,
    }

    # Always emit a structured log line (captured by any log aggregator).
    log.info("llm_call_recorded", **rec)

    # Best-effort append to the JSONL ledger.
    path = _ledger_path()
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            with _WRITE_LOCK:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except OSError as exc:
            log.warning("llm_usage_ledger_write_failed",
                        path=str(path), error=str(exc), error_type=type(exc).__name__)

    return rec
