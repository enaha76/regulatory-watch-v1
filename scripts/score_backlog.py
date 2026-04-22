"""
Backfill the LLM significance score for ChangeEvents that haven't been
scored yet. Useful after:

  * enabling OPENAI_API_KEY for the first time,
  * deploying the M3 migration onto a DB with pre-existing events, or
  * a Celery outage that dropped enqueued scoring jobs.

By default only events with `significance_score IS NULL AND
llm_error IS NULL` are picked (cheap, thanks to the partial index
`ix_change_events_unscored`). Pass `--retry-errors` to also rescore
events whose previous attempt failed.

Usage (inside the worker container):

    docker compose exec -T worker python scripts/score_backlog.py
    docker compose exec -T worker python scripts/score_backlog.py --limit 50
    docker compose exec -T worker python scripts/score_backlog.py --async
    docker compose exec -T worker python scripts/score_backlog.py \\
        --since 7d --retry-errors

Flags
-----
    --limit          Max events to process (default: 100)
    --since          Only events detected in the last window, e.g. '24h', '7d'
    --domain         Substring filter on source_url
    --kind           Filter by diff_kind: 'created' | 'modified'
    --retry-errors   Also rescore events where previous attempts set llm_error
    --force-rescore  Rescore ALL matching events (including already-scored).
                     Useful after a prompt/rubric change. Clears previous
                     score/change_type/summary before re-running.
    --async          Enqueue via Celery .delay() instead of scoring inline
                     (inline is useful for small backfills + visibility)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Allow running from the host without installing the project as a package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session, or_, select  # noqa: E402

from app.database import engine  # noqa: E402
from app.models import ChangeEvent  # noqa: E402


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


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--since", help="Only events in the last window (e.g. '24h', '7d')")
    p.add_argument("--domain", help="Substring filter on source_url")
    p.add_argument("--kind", choices=["created", "modified"],
                   help="Filter by diff_kind")
    p.add_argument("--retry-errors", action="store_true",
                   help="Also rescore events with llm_error set")
    p.add_argument("--force-rescore", action="store_true",
                   help="Rescore ALL matching events (even already-scored). "
                        "Clears previous score fields before re-running.")
    p.add_argument("--async", dest="async_mode", action="store_true",
                   help="Enqueue via Celery instead of scoring inline")
    args = p.parse_args()

    since_dt = _parse_since(args.since)

    with Session(engine) as session:
        base_cols = select(ChangeEvent.id, ChangeEvent.source_url)

        if args.force_rescore:
            stmt = base_cols  # match everything, filters applied below
        elif args.retry_errors:
            stmt = base_cols.where(
                or_(
                    ChangeEvent.significance_score.is_(None),
                    ChangeEvent.llm_error.is_not(None),
                )
            )
        else:
            stmt = base_cols.where(
                ChangeEvent.significance_score.is_(None),
                ChangeEvent.llm_error.is_(None),
            )

        if since_dt is not None:
            stmt = stmt.where(ChangeEvent.detected_at >= since_dt)
        if args.domain:
            stmt = stmt.where(ChangeEvent.source_url.contains(args.domain))
        if args.kind:
            stmt = stmt.where(ChangeEvent.diff_kind == args.kind)
        stmt = stmt.order_by(ChangeEvent.detected_at.desc()).limit(args.limit)

        rows = session.exec(stmt).all()

        # For --force-rescore, null-out the score fields in a single
        # UPDATE so `score_event`'s idempotency guard will re-run them.
        if args.force_rescore and rows:
            from sqlalchemy import update
            ids = [row[0] if isinstance(row, tuple) else row.id for row in rows]
            session.exec(
                update(ChangeEvent)
                .where(ChangeEvent.id.in_(ids))
                .values(
                    significance_score=None,
                    change_type=None,
                    topic=None,
                    affected_entities=None,
                    deadline_changes=None,
                    summary=None,
                    llm_error=None,
                    llm_model=None,
                    scored_at=None,
                )
            )
            session.commit()
            print(f"[force-rescore] cleared score fields on {len(ids)} event(s)\n")

    if not rows:
        print("No unscored change events match the given filters. Nothing to do.")
        return 0

    print(f"\nBackfilling {len(rows)} event(s) "
          f"(since={args.since or 'all-time'}, mode={'async' if args.async_mode else 'inline'}):\n")

    if args.async_mode:
        from app.celery_app import score_change_event
        for row in rows:
            ev_id = row[0] if isinstance(row, tuple) else row.id
            url = row[1] if isinstance(row, tuple) else row.source_url
            score_change_event.delay(str(ev_id), args.retry_errors)
            print(f"  enqueued  {ev_id}  {url[:80]}")
        print(f"\n{len(rows)} event(s) enqueued to Celery.")
        return 0

    # Inline mode — score serially with visible progress.
    from app.services.significance import score_event

    stats = {"scored": 0, "already_scored": 0, "error": 0, "skipped_no_api_key": 0, "other": 0}
    for row in rows:
        ev_id = row[0] if isinstance(row, tuple) else row.id
        url = row[1] if isinstance(row, tuple) else row.source_url
        result = score_event(ev_id, retry_errors=args.retry_errors)
        status = result.get("status", "other")
        stats[status] = stats.get(status, 0) + 1
        if status == "scored":
            print(f"  [ok]   {result['score']:.2f}  {result['change_type']:<17}  {url[:80]}")
        elif status == "already_scored":
            print(f"  [skip] already scored            {url[:80]}")
        elif status == "error":
            print(f"  [err]  {result.get('error','')[:60]:<40}  {url[:80]}")
        elif status == "skipped_no_api_key":
            print(f"  [skip] OPENAI_API_KEY not set    {url[:80]}")
            # Stop early — no point hammering the DB with the same error.
            break
        else:
            print(f"  [{status}] {url[:80]}")

    print("\n── Backfill summary ──")
    for k, v in stats.items():
        if v:
            print(f"  {k:<20} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
