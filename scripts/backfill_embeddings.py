"""One-shot backfill: embed every scored ChangeEvent and active
UserSubscription that's missing an embedding.

Why: ~258 substantive events were stranded scored-but-without-embedding
because the original `score_event` swallowed transient OpenAI failures
silently. Without an embedding, the matcher's pgvector cosine filter
rejects the event → it can never produce alerts. This script catches
them up. The accompanying retry fix in `embeddings.embed()` keeps
new events from landing in this state going forward.

Usage (inside the api or worker container):
    python -m scripts.backfill_embeddings [--limit N] [--dry-run] [--match]

`--match` re-runs the matcher for each newly-embedded event so any
matching subscriptions actually surface alerts. Skip the flag if you
just want to populate vectors and let the next normal match cycle
handle it.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.logging_setup import get_logger
from app.models import ChangeEvent, UserSubscription
from app.services.embeddings import (
    build_doc_text,
    build_subscription_text,
    embed,
)

log = get_logger(__name__)


def _events_needing_embedding(session: Session, limit: int) -> Iterable[ChangeEvent]:
    """Scored events missing an embedding. Order: highest-score first
    so the demo benefits from backfill even if interrupted."""
    stmt = (
        select(ChangeEvent)
        .where(ChangeEvent.scored_at.is_not(None))  # type: ignore[union-attr]
        .where(ChangeEvent.significance_score.is_not(None))  # type: ignore[union-attr]
        .where(ChangeEvent.embedding.is_(None))  # type: ignore[union-attr]
        .order_by(ChangeEvent.significance_score.desc())  # type: ignore[union-attr]
        .limit(limit)
    )
    return session.exec(stmt).all()


def _subscriptions_needing_embedding(session: Session) -> Iterable[UserSubscription]:
    """Active subscriptions with no embedding — those users currently
    receive zero alerts because the matcher SQL gates on
    us.embedding IS NOT NULL."""
    stmt = (
        select(UserSubscription)
        .where(UserSubscription.is_active.is_(True))  # type: ignore[union-attr]
        .where(UserSubscription.embedding.is_(None))  # type: ignore[union-attr]
    )
    return session.exec(stmt).all()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--match", action="store_true",
        help="After embedding each event, queue match_change_event so "
             "the resulting alerts surface in the inbox.",
    )
    args = parser.parse_args()

    s = get_settings()
    if not s.OPENAI_API_KEY:
        print("OPENAI_API_KEY missing — cannot embed", file=sys.stderr)
        return 1

    # Lazy import to avoid Celery import cycles when --match is unused.
    match_change_event = None
    if args.match:
        from app.celery_app import match_change_event as _match
        match_change_event = _match

    fixed_events = 0
    skipped_events = 0
    failed_events = 0

    with Session(engine) as session:
        events = list(_events_needing_embedding(session, args.limit))
        print(f"Found {len(events)} scored events without embeddings")
        for i, ev in enumerate(events, 1):
            doc_text = build_doc_text(ev)
            preview = (ev.headline or ev.summary or "")[:80].replace("\n", " ")
            print(f"  [{i}/{len(events)}] score={ev.significance_score} "
                  f"{str(ev.id)[:8]}  {preview}")
            if not doc_text.strip():
                print("      (skipped — empty doc text)")
                skipped_events += 1
                continue
            if args.dry_run:
                continue
            try:
                ev.embedding = embed(doc_text)
                session.add(ev)
                session.commit()
                fixed_events += 1
                if match_change_event is not None:
                    try:
                        match_change_event.delay(str(ev.id))
                    except Exception as match_exc:  # noqa: BLE001
                        log.warning(
                            "match_enqueue_failed",
                            event_id=str(ev.id),
                            error=str(match_exc),
                        )
            except Exception as exc:  # noqa: BLE001
                failed_events += 1
                log.error(
                    "backfill_event_failed",
                    event_id=str(ev.id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                # Don't bail — keep going so one bad row doesn't block
                # the rest. Tiny pause so a broader OpenAI hiccup
                # doesn't get rate-limited harder.
                time.sleep(0.5)

        # Subscriptions: small set, do it inline.
        subs = list(_subscriptions_needing_embedding(session))
        print(f"\nFound {len(subs)} active subscriptions without embeddings")
        fixed_subs = 0
        failed_subs = 0
        for sub in subs:
            kw_text = build_subscription_text(sub.keywords or [])
            print(f"  sub {str(sub.id)[:8]} email={sub.user_email} "
                  f"keywords={(sub.keywords or [])[:3]}")
            if not kw_text.strip():
                print("      (skipped — no keywords)")
                continue
            if args.dry_run:
                continue
            try:
                sub.embedding = embed(kw_text)
                session.add(sub)
                session.commit()
                fixed_subs += 1
            except Exception as exc:  # noqa: BLE001
                failed_subs += 1
                log.error(
                    "backfill_sub_failed",
                    sub_id=str(sub.id),
                    error=str(exc),
                )

    print()
    print(f"Events:  fixed={fixed_events} skipped={skipped_events} failed={failed_events}")
    print(f"Subs:    fixed={fixed_subs} failed={failed_subs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
