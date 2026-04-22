"""
Inspect the M4 entity index and (optionally) backfill it from existing
scored change_events.

Two modes:

1. REPORT mode (default) — rank entities by mention count, with filters:

    docker compose exec -T worker python scripts/show_entities.py
    docker compose exec -T worker python scripts/show_entities.py \
        --since 30d --min-score 0.6 --limit 30
    docker compose exec -T worker python scripts/show_entities.py \
        --entity-type agency --since 7d

2. BACKFILL mode — materialise `change_event_entities` rows for every
   scored event that has `affected_entities` but no join rows yet
   (e.g. events scored before migration 008 was applied):

    docker compose exec -T worker python scripts/show_entities.py --backfill
    docker compose exec -T worker python scripts/show_entities.py --backfill --limit 500

Flags:
    --since         Time window for REPORT mode (e.g. '7d', '24h')
    --min-score     Only count mentions from events with score >= N
    --entity-type   Filter to agency|regulation|program|code|industry|other
    --limit         Top-N rows (report mode) / max events (backfill mode)
    --backfill      Switch to BACKFILL mode
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session

from app.database import engine
from app.services.entity_index import (
    iter_unindexed_events,
    sync_entities_for_event,
    top_entities,
)


_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if not m:
        raise SystemExit(f"--since: cannot parse '{value}' (try '24h', '7d')")
    n, unit = int(m.group(1)), m.group(2).lower()
    return datetime.now(timezone.utc) - timedelta(seconds=n * _UNIT_TO_SECONDS[unit])


# ── Modes ─────────────────────────────────────────────────────────────────────

def _run_report(args: argparse.Namespace) -> int:
    since_dt = _parse_since(args.since)
    with Session(engine) as session:
        rows = top_entities(
            session,
            since=since_dt,
            min_score=args.min_score,
            entity_type=args.entity_type,
            limit=args.limit,
        )
        if not rows:
            print("No indexed entities match the given filters.")
            print("Tip: run `--backfill` first to populate the index from existing events.")
            return 0

        print(f"\nTop {len(rows)} entities "
              f"(since={args.since or 'all-time'}, "
              f"min_score={args.min_score if args.min_score is not None else '-'}, "
              f"type={args.entity_type or 'any'}):\n")
        print(f"{'count':>6}  {'type':<11}  name")
        print("─" * 80)
        for name, etype, count in rows:
            print(f"{count:>6}  {etype:<11}  {name}")
    return 0


def _run_backfill(args: argparse.Namespace) -> int:
    with Session(engine) as session:
        ids = list(iter_unindexed_events(session, limit=args.limit))
    if not ids:
        print("Nothing to backfill — the entity index is up to date.")
        return 0

    print(f"Backfilling {len(ids)} event(s) into change_event_entities …")
    total_indexed = 0
    total_skipped = 0
    for i, eid in enumerate(ids, 1):
        result = sync_entities_for_event(eid)
        total_indexed += int(result.get("indexed", 0))
        total_skipped += int(result.get("skipped", 0))
        if i % 25 == 0 or i == len(ids):
            print(f"  [{i}/{len(ids)}] "
                  f"indexed={total_indexed} skipped={total_skipped}")
    print(f"\nDone. indexed={total_indexed} skipped={total_skipped}")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--since", help="Time window like '24h', '7d'")
    p.add_argument("--min-score", type=float, default=None,
                   help="Only count mentions from events with score >= N")
    p.add_argument("--entity-type",
                   choices=["agency", "regulation", "program", "code", "industry", "other"],
                   help="Filter to a specific entity type")
    p.add_argument("--limit", type=int, default=20,
                   help="Top-N rows (report) / max events (backfill)")
    p.add_argument("--backfill", action="store_true",
                   help="Populate change_event_entities for events missing it")
    args = p.parse_args()

    if args.backfill:
        return _run_backfill(args)
    return _run_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
