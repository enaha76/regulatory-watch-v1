"""
Inspect recent change_events emitted by the ingestion layer.

Reads from PostgreSQL and prints a compact listing of detected
'created' / 'modified' transitions, optionally with an inline preview
of the unified diff.

Usage (inside the worker container — has DATABASE_URL configured):

    docker compose exec -T worker python scripts/show_changes.py
    docker compose exec -T worker python scripts/show_changes.py \
        --domain cbp.gov --since 24h --limit 20
    docker compose exec -T worker python scripts/show_changes.py \
        --kind modified --diff --diff-lines 30
    docker compose exec -T worker python scripts/show_changes.py \
        --url https://www.cbp.gov/trade --diff

Flags:
    --domain      Only show events whose source_url contains this substring
    --url         Only show events for this exact source_url
    --kind        'created' | 'modified' | 'all'  (default: all)
    --since       Time window: '1h', '24h', '7d' …  (default: all-time)
    --limit       Max rows to print (default: 25)
    --diff        Also print the (truncated) unified diff for each row
    --diff-lines  Cap diff preview to N lines (default: 40)
    --summary     Show LLM compliance_summary + affected_entities (M3)
    --min-score   Only show events with significance_score >= N (M3)
    --change-type Filter by change_type (M3): typo_or_cosmetic, minor_wording,
                  clarification, substantive, critical
    --topic       Filter by regulatory topic (M4): customs_trade, financial_services,
                  data_privacy, environmental, healthcare_pharma,
                  sanctions_export_control, labor_employment, tax_accounting,
                  consumer_protection, corporate_governance, other
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.database import engine
from app.models import ChangeEvent, SourceVersion


# ── Helpers ───────────────────────────────────────────────────────────────────

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if not m:
        raise SystemExit(f"--since: cannot parse '{value}' (try '24h', '7d', '15m')")
    n, unit = int(m.group(1)), m.group(2).lower()
    return datetime.now(timezone.utc) - timedelta(seconds=n * _UNIT_TO_SECONDS[unit])


def _truncate(s: str, n: int) -> str:
    if s is None:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _colorize_score(score: float) -> str:
    """Right-aligned 5-char score cell with an ANSI color by severity band."""
    if score >= 0.8:
        color = "\033[1;31m"   # bold red   — critical
    elif score >= 0.6:
        color = "\033[33m"     # yellow     — substantive
    elif score >= 0.4:
        color = "\033[36m"     # cyan       — clarification
    elif score >= 0.2:
        color = "\033[90m"     # grey       — minor wording
    else:
        color = "\033[90m"     # grey       — cosmetic
    return f"{color}{score:5.2f}\033[0m"


def _print_diff(diff_text: str, max_lines: int) -> None:
    if not diff_text:
        print("    (no diff stored)")
        return
    lines = diff_text.splitlines()
    shown = lines[:max_lines]
    for line in shown:
        if line.startswith("+++") or line.startswith("---"):
            print(f"    \033[1m{line}\033[0m")
        elif line.startswith("+"):
            print(f"    \033[32m{line}\033[0m")
        elif line.startswith("-"):
            print(f"    \033[31m{line}\033[0m")
        elif line.startswith("@@"):
            print(f"    \033[36m{line}\033[0m")
        else:
            print(f"    {line}")
    if len(lines) > max_lines:
        print(f"    … ({len(lines) - max_lines} more diff lines, use --diff-lines)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--domain", help="Substring filter on source_url")
    p.add_argument("--url", help="Exact source_url filter")
    p.add_argument("--kind", choices=["created", "modified", "all"], default="all")
    p.add_argument("--since", help="Time window like '24h', '7d', '15m'")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--diff", action="store_true", help="Print the unified diff")
    p.add_argument("--diff-lines", type=int, default=40)
    p.add_argument("--summary", action="store_true",
                   help="Show LLM compliance summary + affected entities")
    p.add_argument("--min-score", type=float, default=None,
                   help="Only events with significance_score >= N")
    p.add_argument("--change-type",
                   choices=["typo_or_cosmetic", "minor_wording", "clarification",
                            "substantive", "critical"],
                   help="Filter by LLM-assigned change_type")
    p.add_argument("--topic",
                   choices=["customs_trade", "financial_services", "data_privacy",
                            "environmental", "healthcare_pharma",
                            "sanctions_export_control", "labor_employment",
                            "tax_accounting", "consumer_protection",
                            "corporate_governance", "other"],
                   help="Filter by regulatory topic")
    args = p.parse_args()

    since_dt = _parse_since(args.since)

    with Session(engine) as session:
        stmt = select(ChangeEvent).order_by(ChangeEvent.detected_at.desc())
        if args.kind != "all":
            stmt = stmt.where(ChangeEvent.diff_kind == args.kind)
        if args.url:
            stmt = stmt.where(ChangeEvent.source_url == args.url)
        elif args.domain:
            stmt = stmt.where(ChangeEvent.source_url.contains(args.domain))
        if since_dt is not None:
            stmt = stmt.where(ChangeEvent.detected_at >= since_dt)
        if args.min_score is not None:
            stmt = stmt.where(ChangeEvent.significance_score >= args.min_score)
        if args.change_type:
            stmt = stmt.where(ChangeEvent.change_type == args.change_type)
        if args.topic:
            stmt = stmt.where(ChangeEvent.topic == args.topic)
        stmt = stmt.limit(args.limit)

        events = session.exec(stmt).all()

        if not events:
            print("No change events match the given filters.")
            print("\nQuick checks:")
            print("  - has the ingestion run since the migration was applied?")
            print("  - try a wider window:  --since 30d  (or omit --since)")
            print("  - to count rows:")
            print("      docker compose exec -T worker python -c \\")
            print('        "from sqlmodel import Session, select; '
                  'from app.database import engine; from app.models import ChangeEvent; '
                  's=Session(engine); print(len(s.exec(select(ChangeEvent)).all()))"')
            return 0

        # Header
        print(f"\nFound {len(events)} change event(s) "
              f"(kind={args.kind}, since={args.since or 'all-time'}):\n")
        print(f"{'when':<20}  {'kind':<8}  {'score':>5}  {'type':<17}  "
              f"{'topic':<25}  {'+chars':>7}  {'-chars':>7}  url")
        print("─" * 140)

        for ev in events:
            when = ev.detected_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            score_cell = (
                f"\033[90m  ?  \033[0m" if ev.significance_score is None
                else _colorize_score(ev.significance_score)
            )
            type_cell = ev.change_type or "\033[90munscored\033[0m"
            topic_cell = ev.topic or "\033[90m-\033[0m"
            print(
                f"{when:<20}  "
                f"{ev.diff_kind:<8}  "
                f"{score_cell}  "
                f"{type_cell:<17}  "
                f"{topic_cell:<25}  "
                f"{ev.added_chars:>7}  "
                f"{ev.removed_chars:>7}  "
                f"{_truncate(ev.source_url, 60)}"
            )

            if args.summary:
                if ev.summary:
                    print(f"    \033[1msummary:\033[0m  {ev.summary}")
                if ev.affected_entities:
                    ents = ", ".join(ev.affected_entities[:10])
                    print(f"    \033[1mentities:\033[0m {ents}")
                if ev.deadline_changes:
                    print(f"    \033[1mdeadlines:\033[0m")
                    for dc in ev.deadline_changes[:5]:
                        old = dc.get("old") if isinstance(dc, dict) else None
                        new = dc.get("new") if isinstance(dc, dict) else None
                        label = dc.get("deadline_text") if isinstance(dc, dict) else str(dc)
                        print(f"      - {label}: {old!r} → {new!r}")
                if ev.llm_error:
                    print(f"    \033[31mllm_error:\033[0m {_truncate(ev.llm_error, 180)}")
                if ev.summary or ev.affected_entities or ev.deadline_changes or ev.llm_error:
                    print()

            if args.diff:
                if ev.diff_kind == "created":
                    # Show first lines of the new version so the user gets a flavor
                    nv = session.get(SourceVersion, ev.new_version_id)
                    preview = (nv.raw_text or "").splitlines()[: args.diff_lines]
                    print("    \033[1m(initial version — preview)\033[0m")
                    for line in preview:
                        print(f"    {line}")
                else:
                    _print_diff(ev.unified_diff or "", args.diff_lines)
                print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
