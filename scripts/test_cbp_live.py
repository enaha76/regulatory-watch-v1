"""
Live smoke test for WebConnector (Crawl4AI + httpx fallback).

Crawls a seed URL and prints a human-readable progress line for every page
that is fetched, then prints a final summary table.

Usage (inside the worker container — recommended, Playwright chromium is there):

    docker compose exec -T worker python scripts/test_cbp_live.py
    docker compose exec -T worker python scripts/test_cbp_live.py \
        --url https://www.cbp.gov/trade --max-pages 20 --path-prefix /trade

Flags:
    --url           Seed URL (default: https://www.cbp.gov/trade)
    --domain        Allowed domain (default: inferred from --url)
    --path-prefix   Restrict crawl to paths starting with this (default: inferred)
    --max-pages     Hard cap on HTML pages (default: 15)
    --max-depth     BFS depth (default: 2)
    --rps           Requests per second (default: 1.0)
    --no-pdf        Skip PDF harvesting
    --no-xml        Skip XML harvesting
    --quiet         Suppress DEBUG logs (default: INFO only already)
    --persist       Also write fetched documents through storage.upsert_documents
                    (which triggers source_versions + change_events). Without
                    this flag the script is a pure read-only smoke test and
                    NOTHING is written to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from app.ingestion.storage import upsert_documents  # noqa: E402
from app.ingestion.web_connector import WebConnector  # noqa: E402


# ── Pretty printing helpers ─────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _progress_bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + " " * width + "]"
    pct = min(done / total, 1.0)
    filled = int(pct * width)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct*100:5.1f}%"


def _short(url: str, n: int = 70) -> str:
    return url if len(url) <= n else url[: n - 1] + "…"


# ── Live progress wrapper around WebConnector._fetch_page ───────────────────

def _instrument(connector: WebConnector, max_pages: int) -> dict:
    """
    Monkey-patch the connector instance so every page fetch prints a progress
    line. Returns a stats dict we can read after fetch() finishes.
    """
    stats = {
        "started": 0,
        "finished": 0,
        "ok": 0,
        "fail": 0,
        "t0": time.monotonic(),
    }
    orig_fetch_page = connector._fetch_page

    async def wrapped(url: str):
        stats["started"] += 1
        idx = stats["started"]
        print(
            f"{DIM}→ [{idx:02d}] fetching{RESET} {_short(url)}",
            flush=True,
        )
        t = time.monotonic()
        try:
            response = await orig_fetch_page(url)
        except Exception as exc:
            stats["finished"] += 1
            stats["fail"] += 1
            dt = time.monotonic() - t
            bar = _progress_bar(stats["finished"], max_pages)
            print(
                f"{RED}✗ [{idx:02d}] error {dt:5.1f}s{RESET} {bar} "
                f"{DIM}{_short(url)} :: {exc}{RESET}",
                flush=True,
            )
            raise

        stats["finished"] += 1
        dt = time.monotonic() - t
        bar = _progress_bar(stats["finished"], max_pages)
        if response is None:
            stats["fail"] += 1
            print(
                f"{YELLOW}· [{idx:02d}] empty  {dt:5.1f}s{RESET} {bar} "
                f"{DIM}{_short(url)}{RESET}",
                flush=True,
            )
        else:
            stats["ok"] += 1
            body_len = len(getattr(response, "body", b"") or b"")
            status = getattr(response, "status_code", "?")
            print(
                f"{GREEN}✓ [{idx:02d}] ok     {dt:5.1f}s{RESET} {bar} "
                f"http={status} bytes={body_len:>7}  {_short(url)}",
                flush=True,
            )
        return response

    connector._fetch_page = wrapped  # type: ignore[assignment]
    return stats


# ── Main ────────────────────────────────────────────────────────────────────

def _setup_logging(quiet: bool) -> None:
    level = logging.WARNING if quiet else logging.INFO
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(name)s — %(message)s",
                          datefmt="%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(level)
    # Quiet noisy third-parties
    for noisy in ("httpx", "httpcore", "asyncio", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _run(args: argparse.Namespace) -> int:
    url = args.url
    parsed = urlparse(url)
    domain = args.domain or parsed.netloc.replace("www.", "")
    prefix = args.path_prefix
    if prefix is None:
        # Default: restrict to the seed path's first segment (e.g. /trade)
        segs = [s for s in parsed.path.split("/") if s]
        prefix = f"/{segs[0]}" if segs else None

    print(f"{BOLD}{CYAN}── WebConnector live test ──{RESET}")
    print(f"  seed        : {url}")
    print(f"  domain      : {domain}")
    print(f"  path prefix : {prefix or '(none)'}")
    print(f"  max_pages   : {args.max_pages}  max_depth: {args.max_depth}  rps: {args.rps}")
    print(f"  harvest     : pdf={not args.no_pdf}  xml={not args.no_xml}")
    print(f"  persist     : {args.persist}  "
          f"{'(writes to DB → triggers change detection)' if args.persist else '(read-only smoke test, NO DB writes)'}")
    print()

    connector = WebConnector(
        seed_urls=[url],
        allowed_domain=domain,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        rate_limit_rps=args.rps,
        allowed_path_prefix=prefix,
        harvest_pdfs=not args.no_pdf,
        harvest_xml=not args.no_xml,
        max_pdfs=args.max_pdfs,
        max_xmls=args.max_xmls,
    )
    stats = _instrument(connector, max_pages=args.max_pages)

    t0 = time.monotonic()
    try:
        docs = await connector.fetch()
    except Exception as exc:
        print(f"\n{RED}Fatal error:{RESET} {exc}")
        return 2
    elapsed = time.monotonic() - t0

    # ── Summary ─────────────────────────────────────────────────────────────
    by_type: dict[str, int] = {}
    total_chars = 0
    langs: dict[str, int] = {}
    pdf_pages_total = 0
    for d in docs:
        by_type[d.source_type] = by_type.get(d.source_type, 0) + 1
        total_chars += len(d.raw_text or "")
        if d.language:
            langs[d.language] = langs.get(d.language, 0) + 1
        if d.source_type == "pdf":
            pdf_pages_total += int(getattr(d, "page_count", 0) or 0)

    print()
    print(f"{BOLD}{CYAN}── Summary ──{RESET}")
    print(f"  elapsed           : {elapsed:6.1f}s")
    print(f"  pages fetched     : {stats['finished']} "
          f"(ok={stats['ok']}, empty/err={stats['fail']})")
    print(f"  documents stored  : {len(docs)}")
    for t, n in sorted(by_type.items()):
        extra = ""
        if t == "pdf" and pdf_pages_total:
            extra = f"  ({pdf_pages_total} pages across {n} file(s))"
        print(f"    - {t:<6}: {n}{extra}")
    if langs:
        print(f"  languages         : "
              + ", ".join(f"{k}={v}" for k, v in sorted(langs.items())))
    if docs:
        avg = total_chars // len(docs)
        print(f"  avg raw_text len  : {avg:,} chars")
        print(f"  total raw_text    : {total_chars:,} chars")

    # ── Optional persist (storage + change detection) ───────────────────────
    if args.persist and docs:
        print()
        print(f"{BOLD}{CYAN}── Persisting {len(docs)} doc(s) → storage + change detection ──{RESET}")
        try:
            result = upsert_documents(docs)
        except Exception as exc:
            print(f"{RED}upsert_documents failed:{RESET} {exc}")
        else:
            print(f"  raw_documents     : inserted={result.get('inserted', 0)} "
                  f"updated={result.get('updated', 0)}")
            print(f"  change_events     : created={result.get('created', 0)} "
                  f"modified={result.get('modified', 0)} "
                  f"unchanged={result.get('unchanged', 0)}")
            hint = (
                "    (next: docker compose exec -T worker "
                "python scripts/show_changes.py --since 5m)"
            )
            print(f"{DIM}{hint}{RESET}")

    if docs:
        print()
        print(f"{BOLD}Sample of first {min(5, len(docs))} docs:{RESET}")
        for i, d in enumerate(docs[:5], 1):
            title = (d.title or "").strip().replace("\n", " ")[:70] or "(no title)"
            preview = (d.raw_text or "").strip().replace("\n", " ")[:140]
            print(f"  {i}. [{d.source_type}] {title}")
            print(f"     {DIM}{_short(d.source_url, 90)}{RESET}")
            print(f"     {DIM}{preview}…{RESET}")

    return 0 if docs else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Live smoke test for WebConnector")
    p.add_argument("--url", default="https://www.cbp.gov/trade")
    p.add_argument("--domain", default=None)
    p.add_argument("--path-prefix", dest="path_prefix", default=None,
                   help="Set to empty string '' to disable prefix restriction")
    p.add_argument("--max-pages", type=int, default=15)
    p.add_argument("--max-depth", type=int, default=2)
    p.add_argument("--rps", type=float, default=1.0)
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--no-xml", action="store_true")
    p.add_argument("--max-pdfs", type=int, default=5)
    p.add_argument("--max-xmls", type=int, default=5)
    p.add_argument("--quiet", action="store_true")
    p.add_argument(
        "--persist", action="store_true",
        help="Write fetched docs to DB via upsert_documents "
             "(triggers source_versions + change_events).",
    )
    args = p.parse_args()

    # Treat explicit empty string as "no prefix"
    if args.path_prefix == "":
        args.path_prefix = None

    _setup_logging(args.quiet)
    code = asyncio.run(_run(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
