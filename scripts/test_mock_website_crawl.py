"""
Live crawl test against the mock-website (ATCA) — runs the full pipeline:

  WebConnector → upsert_documents → change_detection → score → match → alerts

Run inside the api container:
    docker compose exec api python scripts/test_mock_website_crawl.py

You will see every step as it happens in this terminal.
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import timezone

from sqlmodel import Session, select, text

from app.database import engine
from app.ingestion.storage import upsert_documents
from app.ingestion.web_connector import WebConnector
from app.models import Alert, ChangeEvent, RawDocument, SourceVersion

SEED     = "http://mock-website.local/"
DOMAIN   = "mock-website.local"
MAX_PAGES = 50
MAX_DEPTH = 4
RPS       = 5.0
MAX_PDFS  = 10

SEP  = "=" * 64
SEP2 = "-" * 64


def _count(session, model):
    return session.exec(select(model)).all().__len__()


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def step(label: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {label}")
    print(SEP2)


async def run_crawl() -> list:
    section("STEP 1 — WEB CRAWL  (WebConnector → RawDocument)")
    print(f"  Seed  : {SEED}")
    print(f"  Domain: {DOMAIN}")
    print(f"  Pages : up to {MAX_PAGES}  |  Depth: {MAX_DEPTH}  |  PDFs: {MAX_PDFS}")
    print()
    print("  Starting Playwright browser (takes ~15s the first time)…")
    t0 = time.time()

    connector = WebConnector(
        seed_urls=[SEED],
        allowed_domain=DOMAIN,
        max_pages=MAX_PAGES,
        max_depth=MAX_DEPTH,
        rate_limit_rps=RPS,
        max_pdfs=MAX_PDFS,
    )
    docs = await connector.fetch()

    elapsed = time.time() - t0
    print(f"\n  Crawl finished in {elapsed:.1f}s")
    print(f"  Documents fetched: {len(docs)}")

    if not docs:
        print("\n  [!] No documents returned — check mock-website is running:")
        print("      docker compose ps mock-website")
        return []

    html_docs = [d for d in docs if not d.source_url.endswith(".pdf")]
    pdf_docs  = [d for d in docs if d.source_url.endswith(".pdf")]

    print(f"\n  HTML pages : {len(html_docs)}")
    print(f"  PDF files  : {len(pdf_docs)}")

    print("\n  ── HTML pages fetched ──────────────────────────────────")
    for d in html_docs:
        chars = len(d.raw_text or "")
        title = (d.title or d.source_url)[:60]
        print(f"    [{chars:>6} chars]  {title}")
        print(f"               {d.source_url}")

    if pdf_docs:
        print("\n  ── PDFs fetched ────────────────────────────────────────")
        for d in pdf_docs:
            chars = len(d.raw_text or "")
            print(f"    [{chars:>6} chars]  {d.source_url}")

    return docs


def run_upsert(docs: list) -> tuple[list, list]:
    section("STEP 2 — UPSERT  (RawDocument → SourceVersion + ChangeEvent)")
    print(f"  Upserting {len(docs)} document(s)…")

    source_urls = [d.source_url for d in docs]

    with Session(engine) as session:
        before_ce = len(session.exec(select(ChangeEvent)).all())

    stats = upsert_documents(docs)

    with Session(engine) as session:
        after_ce = len(session.exec(select(ChangeEvent)).all())

        # Fetch the actual ChangeEvent rows for our URLs (most recent per URL)
        events = session.exec(
            select(ChangeEvent)
            .where(ChangeEvent.source_url.in_(source_urls))
            .order_by(ChangeEvent.detected_at.desc())
        ).all()

    new_ce = after_ce - before_ce

    print(f"\n  Stats   : {stats}")
    print(f"  ChangeEvents in DB (before → after): {before_ce} → {after_ce}  (+{new_ce} new)")
    print(f"  Events fetched for our URLs: {len(events)}")

    created  = [e for e in events if e.diff_kind == "created"]
    modified = [e for e in events if e.diff_kind == "modified"]
    print(f"\n  created  (baseline) : {len(created)}")
    print(f"  modified (real diff): {len(modified)}")

    if modified:
        print("\n  ── Modified events (will be scored) ────────────────────")
        for e in modified:
            print(f"    {e.source_url}")

    return events, modified


def run_scoring(modified_events: list) -> None:
    section("STEP 3 — SCORING  (Celery score_change_event task)")

    if not modified_events:
        print("  No modified events — nothing to score.")
        print("  (This is expected on the FIRST crawl; run again after editing a page.)")
        return

    from app.celery_app import score_change_event

    print(f"  Queuing {len(modified_events)} scoring task(s)…")
    results = []
    for e in modified_events:
        r = score_change_event.delay(str(e.id))
        results.append((e, r))
        print(f"    Queued  task_id={r.id}  event={e.id}")

    print("\n  Waiting for scores (timeout 120s each)…")
    for e, r in results:
        try:
            out = r.get(timeout=120)
            print(f"\n  Event  : {e.source_url}")
            print(f"  Result : {out}")
        except Exception as exc:
            print(f"\n  [!] Score failed for {e.source_url}: {exc}")


def show_db_results() -> None:
    section("STEP 4 — DATABASE RESULTS")

    with Session(engine) as session:
        events = session.exec(
            select(ChangeEvent)
            .where(ChangeEvent.source_url.like("%mock-website%"))
            .order_by(ChangeEvent.detected_at.desc())
        ).all()

    print(f"  Total change_events for mock-website: {len(events)}\n")
    if not events:
        print("  (none yet)")
        return

    print(f"  {'KIND':<10} {'SCORE':<7} {'TYPE':<22} {'ORIGIN':<8} {'DEST':<8}  URL / TITLE")
    print(f"  {'-'*9} {'-'*6} {'-'*21} {'-'*7} {'-'*7}  {'-'*40}")
    for e in events:
        kind  = (e.diff_kind or "")[:9]
        score = f"{e.significance_score:.2f}" if e.significance_score is not None else "  –  "
        ctype = (e.change_type or "–")[:21]
        orig  = ",".join(e.origin_countries or [])[:7] or "–"
        dest  = ",".join(e.destination_countries or [])[:7] or "–"
        label = (e.source_url or "")[:50]
        print(f"  {kind:<10} {score:<7} {ctype:<22} {orig:<8} {dest:<8}  {label}")

    scored = [e for e in events if e.significance_score is not None]
    if scored:
        print(f"\n  ── Scored events ───────────────────────────────────────")
        for e in scored:
            print(f"\n  URL    : {e.source_url}")
            print(f"  Score  : {e.significance_score:.2f}  ({e.change_type})")
            print(f"  Topic  : {e.topic}")
            print(f"  Flow   : {e.trade_flow_direction}")
            print(f"  Origin : {e.origin_countries}  →  Dest: {e.destination_countries}")
            print(f"  Summary: {(e.summary or '')[:200]}")


def show_alerts() -> None:
    section("STEP 5 — ALERTS")

    with Session(engine) as session:
        alerts = session.exec(
            select(Alert)
            .order_by(Alert.created_at.desc())
            .limit(20)
        ).all()

    if not alerts:
        print("  No alerts yet.")
        print("  (Alerts are created only for modified+scored events that match a subscription.)")
        print("  Tip: curl http://localhost:8001/api/alerts?email=sarah@acme.com")
        return

    print(f"  Alerts found: {len(alerts)}\n")
    for a in alerts:
        print(f"  Alert   : {a.id}")
        print(f"  Event   : {a.change_event_id}")
        print(f"  Keywords: {a.matched_keywords}")
        print(f"  Status  : {a.status}")
        print()


if __name__ == "__main__":
    section("MOCK WEBSITE FULL PIPELINE TEST")
    print(f"  Target : {SEED}")
    print("  Stages : crawl → upsert → score (modified only) → show results")

    # Step 1: crawl
    docs = asyncio.run(run_crawl())
    if not docs:
        sys.exit(1)

    # Step 2: upsert → change events
    all_events, modified_events = run_upsert(docs)

    # Step 3: score modified events via Celery
    run_scoring(modified_events)

    # Step 4: show DB results
    show_db_results()

    # Step 5: show alerts
    show_alerts()

    section("TEST COMPLETE")
    print("  To trigger another run after editing a page:")
    print("    docker compose exec api python scripts/test_mock_website_crawl.py")
    print()
    print("  To check alerts via API:")
    print("    curl http://localhost:8001/api/alerts?email=sarah@acme.com")
    print()
