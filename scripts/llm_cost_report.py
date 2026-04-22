#!/usr/bin/env python
"""
LLM cost & token usage report.

Reads the append-only JSONL ledger at settings.LLM_USAGE_LEDGER_PATH
(or the path passed via --ledger) and prints:

* overall totals (calls, tokens, USD)
* per-scope breakdown  (scoring / obligations / web_extract)
* per-model breakdown
* a simple per-day timeline
* the top 5 most-expensive single calls

Does NOT touch the database. Safe to run anytime.

Usage
-----
    docker compose exec -T worker python scripts/llm_cost_report.py
    docker compose exec -T worker python scripts/llm_cost_report.py --since 2026-04-01
    docker compose exec -T worker python scripts/llm_cost_report.py --scope obligations
    docker compose exec -T worker python scripts/llm_cost_report.py --json   # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Make the project importable when run directly (outside pytest).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import get_settings  # noqa: E402


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # tolerate a corrupted trailing line (e.g. partial write)
                continue


def _parse_ts(rec: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def _filter(rec: dict[str, Any], *, since: datetime | None, scope: str | None) -> bool:
    if scope and rec.get("scope") != scope:
        return False
    if since is not None:
        ts = _parse_ts(rec)
        if ts is None or ts < since:
            return False
    return True


def _fmt_usd(x: float) -> str:
    if x >= 1:
        return f"${x:,.4f}"
    if x >= 0.01:
        return f"${x:.4f}"
    if x >= 0.0001:
        return f"${x:.6f}"
    return f"${x:.8f}"


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_calls = len(records)
    tot_prompt = sum(r.get("prompt_tokens", 0) for r in records)
    tot_completion = sum(r.get("completion_tokens", 0) for r in records)
    tot_cost = sum(r.get("total_cost_usd", 0.0) for r in records)

    by_scope: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0})
    by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0})
    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0})

    for r in records:
        s = r.get("scope") or "unknown"
        m = r.get("model") or "unknown"
        ts = _parse_ts(r)
        d = (ts.astimezone(timezone.utc).date().isoformat()) if ts else "unknown"

        for bucket in (by_scope[s], by_model[m], by_day[d]):
            bucket["calls"] += 1
            bucket["prompt"] += r.get("prompt_tokens", 0)
            bucket["completion"] += r.get("completion_tokens", 0)
            bucket["cost"] += r.get("total_cost_usd", 0.0)

    top = sorted(records, key=lambda r: r.get("total_cost_usd", 0.0), reverse=True)[:5]

    return {
        "totals": {
            "calls": total_calls,
            "prompt_tokens": tot_prompt,
            "completion_tokens": tot_completion,
            "total_tokens": tot_prompt + tot_completion,
            "total_cost_usd": round(tot_cost, 6),
        },
        "by_scope": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_scope.items())},
        "by_model": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_model.items())},
        "by_day": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_day.items())},
        "top_calls": top,
    }


def print_human(report: dict[str, Any]) -> None:
    t = report["totals"]
    print("── LLM usage ───────────────────────────────────────────")
    print(f"  calls            : {t['calls']:>10,}")
    print(f"  prompt tokens    : {t['prompt_tokens']:>10,}")
    print(f"  completion tokens: {t['completion_tokens']:>10,}")
    print(f"  total tokens     : {t['total_tokens']:>10,}")
    print(f"  total cost       : {_fmt_usd(t['total_cost_usd']):>10}")
    if t["calls"]:
        avg_cost = t["total_cost_usd"] / t["calls"]
        avg_tok = t["total_tokens"] / t["calls"]
        print(f"  avg / call       : {_fmt_usd(avg_cost)}  ({avg_tok:.0f} tok)")

    def _table(name: str, bucket: dict[str, Any]) -> None:
        if not bucket:
            return
        print(f"\n── {name} ────────────────────────────────────────────")
        print(f"  {'key':<24} {'calls':>6} {'prompt':>10} {'compl':>10} {'cost':>12}")
        for k, v in bucket.items():
            print(f"  {k:<24} {v['calls']:>6} {v['prompt']:>10,} {v['completion']:>10,} {_fmt_usd(v['cost']):>12}")

    _table("by scope", report["by_scope"])
    _table("by model", report["by_model"])
    _table("by day  ", report["by_day"])

    if report["top_calls"]:
        print("\n── top 5 single calls by cost ──────────────────────────")
        for r in report["top_calls"]:
            tag = r.get("event_id") or r.get("url") or "-"
            print(f"  {r.get('ts','?')}  {r.get('scope','?'):<12} "
                  f"{r.get('total_tokens',0):>6} tok  "
                  f"{_fmt_usd(r.get('total_cost_usd',0)):>12}  {tag}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", help="Override the ledger path (default: settings.LLM_USAGE_LEDGER_PATH)")
    ap.add_argument("--since", help="Only include records on/after this ISO date (YYYY-MM-DD)")
    ap.add_argument("--scope", choices=("scoring", "obligations", "web_extract"),
                    help="Filter by scope")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    settings = get_settings()
    path_str = args.ledger or settings.LLM_USAGE_LEDGER_PATH
    path = Path(path_str)
    if not path.is_absolute():
        path = Path("/opt/app") / path if Path("/opt/app").exists() else Path.cwd() / path

    since: datetime | None = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    records = [r for r in _iter_records(path) if _filter(r, since=since, scope=args.scope)]

    if not records:
        print(f"No LLM usage records in {path}", file=sys.stderr)
        sys.exit(0)

    report = build_report(records)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Ledger: {path}")
        print(f"Records: {len(records)}  (filters: since={args.since or 'none'}, scope={args.scope or 'all'})")
        print_human(report)


if __name__ == "__main__":
    main()
