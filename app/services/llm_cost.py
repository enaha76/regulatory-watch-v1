"""
LLM usage / cost reporting.

Reads the append-only JSONL ledger that the M4 scoring + obligations
pipelines write to (see ``LLM_USAGE_LEDGER_PATH`` in app.config).
Pure-python aggregation — no DB calls, no LLM calls, safe to run
anywhere.

Used by:
  - scripts/llm_cost_report.py  (CLI for ops)
  - app/routers/admin.py        (the /api/admin/cost-report endpoint)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


# ── Reading the ledger ────────────────────────────────────────────────


def iter_ledger_records(path: Path) -> Iterable[dict[str, Any]]:
    """Yield each JSON record from the ledger, tolerating partial lines."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                import json

                yield json.loads(line)
            except Exception:  # noqa: BLE001 — skip malformed lines
                continue


def parse_ts(rec: dict[str, Any]) -> Optional[datetime]:
    """Parse the record timestamp; tolerates missing / malformed values."""
    try:
        return datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None


def passes_filters(
    rec: dict[str, Any],
    *,
    since: Optional[datetime] = None,
    scope: Optional[str] = None,
) -> bool:
    if scope and rec.get("scope") != scope:
        return False
    if since is not None:
        ts = parse_ts(rec)
        if ts is None or ts < since:
            return False
    return True


# ── Aggregation ───────────────────────────────────────────────────────


def _empty_bucket() -> dict[str, Any]:
    return {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0}


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate a list of usage records into the report shape consumed by
    both the CLI and the admin frontend.

    Returns a dict with:
      - totals
      - by_scope, by_model, by_day  (each: {key: {calls,prompt,completion,cost}})
      - top_calls (the 5 most-expensive single calls, full record)
    """
    total_calls = len(records)
    tot_prompt = sum(r.get("prompt_tokens", 0) for r in records)
    tot_completion = sum(r.get("completion_tokens", 0) for r in records)
    tot_cost = sum(r.get("total_cost_usd", 0.0) for r in records)

    by_scope: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_model: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_day: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)

    for r in records:
        s = r.get("scope") or "unknown"
        m = r.get("model") or "unknown"
        ts = parse_ts(r)
        d = (
            ts.astimezone(timezone.utc).date().isoformat()
            if ts
            else "unknown"
        )

        for bucket in (by_scope[s], by_model[m], by_day[d]):
            bucket["calls"] += 1
            bucket["prompt"] += r.get("prompt_tokens", 0)
            bucket["completion"] += r.get("completion_tokens", 0)
            bucket["cost"] += r.get("total_cost_usd", 0.0)

    top = sorted(
        records, key=lambda r: r.get("total_cost_usd", 0.0), reverse=True
    )[:5]

    def _round(buckets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            k: {**v, "cost": round(v["cost"], 6)}
            for k, v in sorted(buckets.items())
        }

    return {
        "totals": {
            "calls": total_calls,
            "prompt_tokens": tot_prompt,
            "completion_tokens": tot_completion,
            "total_tokens": tot_prompt + tot_completion,
            "total_cost_usd": round(tot_cost, 6),
        },
        "by_scope": _round(by_scope),
        "by_model": _round(by_model),
        "by_day": _round(by_day),
        "top_calls": top,
    }


# ── Convenience: load + filter + aggregate in one call ───────────────


def load_report(
    ledger_path: Path,
    *,
    since: Optional[datetime] = None,
    scope: Optional[str] = None,
) -> dict[str, Any]:
    """End-to-end: read the ledger, apply filters, return the report."""
    records = [
        r
        for r in iter_ledger_records(ledger_path)
        if passes_filters(r, since=since, scope=scope)
    ]
    return build_report(records)
