"""
Inspect extracted obligations (M4 phase 3) and/or backfill obligation
extraction across scored events.

Three modes:

1. REPORT (default) — list recent obligations with filters:

    docker compose exec -T worker python scripts/show_obligations.py
    docker compose exec -T worker python scripts/show_obligations.py \
        --since 30d --obligation-type reporting --limit 30
    docker compose exec -T worker python scripts/show_obligations.py \
        --upcoming --limit 20

2. BACKFILL — run extract_obligations over any scored event with
   score >= 0.6 that has not been through extraction yet:

    docker compose exec -T worker python scripts/show_obligations.py --backfill
    docker compose exec -T worker python scripts/show_obligations.py --backfill --limit 100

3. RE-EXTRACT — force re-extraction for a specific event (useful for
   prompt-engineering iteration):

    docker compose exec -T worker python scripts/show_obligations.py \
        --event-id <uuid> --force

Flags:
    --since           Time window for REPORT mode ('7d', '24h')
    --obligation-type reporting|prohibition|threshold|disclosure|registration|penalty|other
    --upcoming        Only obligations with a parsed deadline_date in the future
    --limit           Max rows (report) / max events (backfill)
    --backfill        Switch to BACKFILL mode
    --event-id        Run extraction on a single event (requires --force or the
                      event must not yet be extracted)
    --force           Wipe prior obligations + re-extract (with --event-id)
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.database import engine
from app.models import ChangeEvent, Obligation
from app.services.obligations import extract_obligations, iter_pending


_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if not m:
        raise SystemExit(f"--since: cannot parse '{value}'")
    n, unit = int(m.group(1)), m.group(2).lower()
    return datetime.now(timezone.utc) - timedelta(seconds=n * _UNIT_TO_SECONDS[unit])


def _truncate(s: Optional[str], n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Modes ─────────────────────────────────────────────────────────────────────

def _run_report(args: argparse.Namespace) -> int:
    since_dt = _parse_since(args.since)
    with Session(engine) as session:
        stmt = select(Obligation, ChangeEvent).join(
            ChangeEvent, ChangeEvent.id == Obligation.change_event_id,
        ).order_by(Obligation.extracted_at.desc())
        if since_dt is not None:
            stmt = stmt.where(Obligation.extracted_at >= since_dt)
        if args.obligation_type:
            stmt = stmt.where(Obligation.obligation_type == args.obligation_type)
        if args.upcoming:
            today = date.today()
            stmt = stmt.where(Obligation.deadline_date.is_not(None))
            stmt = stmt.where(Obligation.deadline_date >= today)
            stmt = stmt.order_by(Obligation.deadline_date.asc())
        stmt = stmt.limit(args.limit)

        rows = session.exec(stmt).all()
        if not rows:
            print("No obligations match the given filters.")
            print("Tip: run `--backfill` to extract obligations from existing scored events.")
            return 0

        print(f"\nFound {len(rows)} obligation(s):\n")
        for obl, ev in rows:
            deadline = (
                obl.deadline_date.isoformat() if obl.deadline_date
                else (obl.deadline_text or "-")
            )
            print(f"\033[1m[{obl.obligation_type}]\033[0m  deadline: {deadline}")
            print(f"  actor:   {obl.actor}")
            print(f"  action:  {_truncate(obl.action, 200)}")
            if obl.condition:
                print(f"  when:    {_truncate(obl.condition, 200)}")
            if obl.penalty:
                print(f"  penalty: {_truncate(obl.penalty, 200)}")
            print(f"  source:  {_truncate(ev.source_url, 90)}  "
                  f"(score {ev.significance_score or 0:.2f}, "
                  f"topic {ev.topic or '-'})")
            print()
    return 0


def _run_backfill(args: argparse.Namespace) -> int:
    with Session(engine) as session:
        ids = iter_pending(session, limit=args.limit)
    if not ids:
        print("Nothing to backfill — all high-score events have been through extraction.")
        return 0

    print(f"Backfilling obligations for {len(ids)} event(s) "
          f"(score >= 0.6, not yet extracted) …")
    total = 0
    for i, eid in enumerate(ids, 1):
        result = extract_obligations(eid)
        total += int(result.get("obligations", 0))
        if i % 10 == 0 or i == len(ids):
            print(f"  [{i}/{len(ids)}] total_obligations={total} "
                  f"last_status={result.get('status')}")
    print(f"\nDone. total_obligations={total}")
    return 0


def _run_single(args: argparse.Namespace) -> int:
    try:
        eid = UUID(args.event_id)
    except ValueError as exc:
        raise SystemExit(f"--event-id: invalid UUID: {exc}")
    result = extract_obligations(eid, force=args.force)
    print(result)
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--since", help="Time window like '24h', '7d'")
    p.add_argument("--obligation-type",
                   choices=["reporting", "prohibition", "threshold", "disclosure",
                            "registration", "penalty", "other"],
                   help="Filter by obligation type")
    p.add_argument("--upcoming", action="store_true",
                   help="Only obligations with deadline_date today or later")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--backfill", action="store_true",
                   help="Backfill extraction for scored events >= 0.6")
    p.add_argument("--event-id", help="Run extraction for a single event id")
    p.add_argument("--force", action="store_true",
                   help="With --event-id: wipe prior obligations and re-extract")
    args = p.parse_args()

    if args.event_id:
        return _run_single(args)
    if args.backfill:
        return _run_backfill(args)
    return _run_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
