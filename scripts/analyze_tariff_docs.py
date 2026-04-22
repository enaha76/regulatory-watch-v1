"""
scripts/analyze_tariff_docs.py

One-off backfill: run the full significance + obligations LLM pipeline
against v1-only tariff PDFs in the corpus.

Rationale
---------
The pipeline normally fires on diff events (v1 → v2). But 318 of our PDFs
contain HS codes and have never been revised — no diff, no event, no
LLM analysis. This script synthesises a `created` ChangeEvent for each
of those PDFs (if one does not already exist) and runs the inline
scorer + obligations extractor. It reuses the exact same prompts /
validators / entity index that the live pipeline uses, so the output
is interchangeable with a real change event.

Cost
----
gpt-4o-mini averages ≈ $0.0005 per scored event and $0.0004 per
obligation extraction. For the full 318-PDF run expect ≈ $0.30.

Usage
-----
    # See what WOULD happen, no LLM calls, no DB writes
    docker compose exec -T worker python scripts/analyze_tariff_docs.py --dry-run

    # Smoke test on 3 PDFs
    docker compose exec -T worker python scripts/analyze_tariff_docs.py --limit 3

    # Full run
    docker compose exec -T worker python scripts/analyze_tariff_docs.py

    # Only re-run on URLs not previously scored by THIS script
    docker compose exec -T worker python scripts/analyze_tariff_docs.py --skip-scored
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session, select  # noqa: E402

from app.database import engine  # noqa: E402
from app.models import (  # noqa: E402
    ChangeEvent,
    RawDocument,
    SourceVersion,
)


# Same conservative regex we trust from backfill_code_entities.py.
_HS_DOTTED_RE = re.compile(r"\b\d{4}\.\d{2}\.\d{2,4}\b")


def _find_tariff_urls(session: Session, limit: Optional[int]) -> list[str]:
    """Distinct source_urls for PDFs whose raw_text contains a dotted HS code."""
    q = select(RawDocument.source_url, RawDocument.raw_text).where(
        RawDocument.source_url.ilike("%.pdf")
    )
    urls: list[str] = []
    seen: set[str] = set()
    for url, text in session.exec(q).all():
        if not text:
            continue
        if url in seen:
            continue
        if _HS_DOTTED_RE.search(text):
            seen.add(url)
            urls.append(url)
            if limit is not None and len(urls) >= limit:
                break
    return urls


def _promote_raw_to_version(
    session: Session, url: str,
) -> Optional[SourceVersion]:
    """
    If no SourceVersion exists for this URL, promote the most recent
    RawDocument into one (mirroring what change_detection.process_document
    would have done had it been invoked at ingest time).

    This is the escape hatch for corpora ingested through the raw bulk
    path that bypassed the normal detection pipeline.
    """
    rd = session.exec(
        select(RawDocument)
        .where(RawDocument.source_url == url)
        .limit(1)
    ).one_or_none()
    if rd is None or not rd.raw_text:
        return None

    now = datetime.now(timezone.utc)
    sv = SourceVersion(
        source_url=rd.source_url,
        source_type=rd.source_type,
        content_hash=rd.content_hash,
        raw_text=rd.raw_text,
        title=rd.title,
        language=rd.language,
        page_count=rd.page_count,
        pages=rd.pages,
        artifact_uri=rd.artifact_uri,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(sv)
    try:
        session.commit()
        session.refresh(sv)
    except Exception:
        # Unique constraint (source_url, content_hash) may race — roll back
        # and re-read the existing row.
        session.rollback()
        sv = session.exec(
            select(SourceVersion)
            .where(SourceVersion.source_url == url)
            .order_by(SourceVersion.first_seen_at.desc())
            .limit(1)
        ).one_or_none()
    return sv


def _get_or_create_event(
    session: Session, url: str, force_new: bool,
) -> tuple[Optional[ChangeEvent], str]:
    """
    Returns (event, provenance):
      provenance ∈ {"existing", "created", "promoted+created", "missing_version"}.
    """
    sv = session.exec(
        select(SourceVersion)
        .where(SourceVersion.source_url == url)
        .order_by(SourceVersion.first_seen_at.desc())
        .limit(1)
    ).one_or_none()

    promoted = False
    if sv is None:
        sv = _promote_raw_to_version(session, url)
        if sv is None:
            return None, "missing_version"
        promoted = True

    if not force_new:
        existing = session.exec(
            select(ChangeEvent).where(ChangeEvent.new_version_id == sv.id).limit(1)
        ).one_or_none()
        if existing is not None:
            return existing, "existing"

    ev = ChangeEvent(
        source_url=url,
        new_version_id=sv.id,
        prev_version_id=None,
        diff_kind="created",
        added_chars=len(sv.raw_text or ""),
        removed_chars=0,
        unified_diff=None,
        detected_at=datetime.now(timezone.utc),
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev, "promoted+created" if promoted else "created"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="List target URLs; do not call the LLM, do not write.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of tariff URLs processed.")
    ap.add_argument("--skip-scored", action="store_true",
                    help="Skip URLs whose most-recent event is already scored.")
    ap.add_argument("--force-new-event", action="store_true",
                    help="Always create a fresh 'created' event, even if one exists.")
    args = ap.parse_args()

    # Stats
    t0 = time.monotonic()
    scored = 0
    skipped_already = 0
    missing_version = 0
    obligations_triggered = 0
    obligations_extracted_rows = 0
    errors: list[tuple[str, str]] = []
    total_start_cost: float | None = None
    topic_counts: dict[str, int] = {}
    origin_hits = 0
    dest_hits = 0
    flow_hits = 0

    with Session(engine) as session:
        urls = _find_tariff_urls(session, args.limit)

    print(f"Found {len(urls)} HS-code-bearing PDFs to process.")
    if args.dry_run:
        for u in urls[:20]:
            print("  ", u)
        if len(urls) > 20:
            print(f"  ... +{len(urls) - 20} more")
        return

    from app.services.significance import score_event
    from app.services.obligations import extract_obligations
    from app.config import get_settings
    settings = get_settings()

    # Establish a baseline cost from the LLM ledger so we can print
    # "this run cost $X" at the end.
    def _ledger_total_cost() -> float:
        path = Path(settings.LLM_USAGE_LEDGER_PATH)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        if not path.exists():
            return 0.0
        import json
        total = 0.0
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    total += float(rec.get("total_cost_usd", 0.0))
                except (ValueError, TypeError):
                    continue
        return total

    total_start_cost = _ledger_total_cost()

    for idx, url in enumerate(urls, start=1):
        with Session(engine) as session:
            ev, provenance = _get_or_create_event(
                session, url, force_new=args.force_new_event,
            )

        if provenance == "missing_version":
            missing_version += 1
            print(f"  [{idx:>3}/{len(urls)}] MISSING source_version: {url[:80]}")
            continue

        already_scored = (
            ev.significance_score is not None and not args.force_new_event
        )
        if args.skip_scored and already_scored:
            skipped_already += 1
            print(f"  [{idx:>3}/{len(urls)}] skip (scored)  {url[:70]}")
            continue

        try:
            result = score_event(ev.id, retry_errors=True)
        except Exception as exc:  # noqa: BLE001
            errors.append((url, f"score: {type(exc).__name__}: {exc}"))
            print(f"  [{idx:>3}/{len(urls)}] ERR  {type(exc).__name__}  {url[:60]}")
            continue

        status = result.get("status")
        score = result.get("score")
        change_type = result.get("change_type")

        if status not in ("scored", "already_scored"):
            errors.append((url, f"score-status={status}: {result.get('error')}"))
            print(f"  [{idx:>3}/{len(urls)}] ERR  {status}  {url[:60]}")
            continue

        scored += 1

        # Reload event for country/topic stats.
        with Session(engine) as session:
            ev2 = session.get(ChangeEvent, ev.id)
            if ev2 is not None:
                if ev2.topic:
                    topic_counts[ev2.topic] = topic_counts.get(ev2.topic, 0) + 1
                if ev2.origin_countries:
                    origin_hits += 1
                if ev2.destination_countries:
                    dest_hits += 1
                if ev2.trade_flow_direction:
                    flow_hits += 1

        oblig_note = ""
        if (
            isinstance(score, (int, float))
            and score >= settings.OBLIGATIONS_SCORE_GATE
        ):
            obligations_triggered += 1
            try:
                oblig_result = extract_obligations(ev.id, force=args.force_new_event)
                extracted_n = int(oblig_result.get("obligations", 0) or 0)
                obligations_extracted_rows += extracted_n
                oblig_note = f"  [+{extracted_n} obligations]"
            except Exception as exc:  # noqa: BLE001
                errors.append((url, f"obligations: {type(exc).__name__}: {exc}"))
                oblig_note = "  [obligations FAILED]"

        print(
            f"  [{idx:>3}/{len(urls)}] "
            f"{score if isinstance(score, float) else '---':<5} "
            f"{str(change_type)[:15]:<15} {provenance:<8} "
            f"{url[-60:]}{oblig_note}"
        )

    total_end_cost = _ledger_total_cost()
    run_cost = total_end_cost - (total_start_cost or 0.0)
    dt = time.monotonic() - t0

    print()
    print("── Run summary " + "─" * 45)
    print(f"  total PDFs targeted       : {len(urls):>5}")
    print(f"  scored this run           : {scored:>5}")
    print(f"  skipped (already scored)  : {skipped_already:>5}")
    print(f"  missing source_version    : {missing_version:>5}")
    print(f"  obligations calls made    : {obligations_triggered:>5}")
    print(f"  obligations rows inserted : {obligations_extracted_rows:>5}")
    print(f"  errors                    : {len(errors):>5}")
    print()
    print(f"  origin_countries set      : {origin_hits:>5}")
    print(f"  destination_countries set : {dest_hits:>5}")
    print(f"  trade_flow_direction set  : {flow_hits:>5}")
    print()
    if topic_counts:
        print("  topic distribution:")
        for t, c in sorted(topic_counts.items(), key=lambda kv: -kv[1]):
            print(f"    {t:<28} {c:>4}")
    print()
    print(f"  elapsed                   : {dt:>5.1f} s")
    print(f"  incremental LLM cost      : ${run_cost:.4f}")

    if errors:
        print()
        print("── First 10 errors ")
        for url, err in errors[:10]:
            print(f"  {err[:120]}")
            print(f"      {url[:120]}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
