import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def normalize_text(text: str) -> str:
    """
    Normalize text for stable hashing and fair comparisons.
    - collapse whitespace
    - drop empty lines
    """
    import re

    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    collapsed = " ".join(lines)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    return collapsed


def infer_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith(".xml"):
        # Many RSS feeds are .xml; keep a heuristic.
        if "rss" in path or "feed" in path or "atom" in path:
            return "rss"
        return "xml"
    if "rss" in url.lower() or "atom" in url.lower() or "feed" in url.lower():
        return "rss"
    return "web"


@dataclass
class BenchResult:
    run_id: str
    backend: str
    url: str
    kind: str
    ok: bool
    status: str
    elapsed_ms: int
    text_len: int
    content_hash: str
    title: str = ""
    error: str = ""
    meta: dict[str, Any] = None


async def run_native(url: str, kind: str) -> tuple[str, str, str, dict[str, Any]]:
    """
    Use in-repo connectors. Returns (title, extracted_text, status, meta).
    """
    if kind == "pdf":
        from app.ingestion.pdf_connector import PDFConnector

        docs = await PDFConnector(source=url, title=url).fetch()
        text = "\n\n".join([d.raw_text or "" for d in docs])
        title = docs[0].title if docs else url
        return title or url, text, "ok", {"chunks": len(docs), "source_type": "pdf"}

    if kind == "xml":
        from app.ingestion.xml_connector import XMLConnector

        docs = await XMLConnector(source=url, title=url).fetch()
        text = "\n\n".join([d.raw_text or "" for d in docs])
        title = docs[0].title if docs else url
        return title or url, text, "ok", {"chunks": len(docs), "source_type": "xml"}

    if kind == "rss":
        from app.ingestion.rss_connector import RSSConnector

        docs = await RSSConnector(feed_url=url, max_entries=100).fetch()
        text = "\n\n".join([d.raw_text or "" for d in docs])
        title = docs[0].title if docs else url
        return title or url, text, "ok", {"entries": len(docs), "source_type": "rss"}

    # web: constrain to a single page, no discovery
    # Prefer the project's WebConnector. If optional deps (scrapling/playwright)
    # are missing in the current environment, fall back to a lightweight httpx
    # fetch + BeautifulSoup extraction so the benchmark can still run.
    try:
        from app.ingestion.web_connector import WebConnector

        parsed = urlparse(url)
        allowed_domain = parsed.netloc
        connector = WebConnector(
            seed_urls=[url],
            allowed_domain=allowed_domain,
            max_pages=1,
            max_depth=0,
            rate_limit_rps=1.0,
            harvest_pdfs=False,
            harvest_xml=False,
            max_pdfs=0,
            max_xmls=0,
        )
        docs = await connector.fetch()
        if not docs:
            raise RuntimeError("web_connector returned 0 documents")
        text = "\n\n".join([d.raw_text or "" for d in docs])
        title = docs[0].title if docs else url
        return title or url, text, "ok", {"pages": len(docs), "source_type": "web", "mode": "web_connector"}
    except (ModuleNotFoundError, RuntimeError) as exc:
        # Likely missing scrapling or other optional crawler deps.
        missing = str(exc)
        try:
            import httpx
            from bs4 import BeautifulSoup  # type: ignore

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "RegulatoryWatch/benchmark"})
                resp.raise_for_status()
                html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            return url, text, "ok", {"source_type": "web", "mode": "httpx_bs4_fallback", "missing": missing}
        except Exception:
            raise RuntimeError(f"native web failed (and fallback failed): {missing}")


async def run_firecrawl(url: str) -> tuple[str, str, str, dict[str, Any]]:
    """
    Firecrawl: /v2/scrape markdown.
    """
    import httpx

    api_key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing FIRECRAWL_API_KEY")

    payload = {
        "url": url,
        "formats": ["markdown"],
        # Avoid cached content for monitoring-style benchmarking.
        "maxAge": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post("https://api.firecrawl.dev/v2/scrape", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"firecrawl unsuccessful: {data}")
        md = (data.get("data") or {}).get("markdown") or ""
        title = (data.get("data") or {}).get("metadata", {}).get("title") or ""
        return title, md, "ok", {"provider": "firecrawl", "credits_hint": 1}


async def run_browserbase_fetch(url: str) -> tuple[str, str, str, dict[str, Any]]:
    """
    Browserbase Fetch: raw HTTP response (no JS). We strip HTML tags crudely
    to keep the benchmark lightweight and deterministic.
    """
    import httpx

    api_key = os.getenv("BROWSERBASE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing BROWSERBASE_API_KEY")

    headers = {"X-BB-API-Key": api_key, "Content-Type": "application/json"}
    payload = {"url": url, "allowRedirects": True}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://api.browserbase.com/v1/fetch", json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        content = body.get("content") or ""
        content_type = body.get("contentType") or ""

    # If it's HTML, parse text; otherwise keep as-is.
    text = content
    if "text/html" in (content_type or "").lower():
        try:
            from bs4 import BeautifulSoup  # type: ignore

            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
        except Exception:
            pass

    return "", text, "ok", {"provider": "browserbase_fetch", "content_type": content_type}


async def run_crawl4ai(url: str) -> tuple[str, str, str, dict[str, Any]]:
    """
    Crawl4AI: local markdown extraction (Playwright-based).
    """
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Crawl4AI not installed. Install requirements.txt (includes crawl4ai)."
        ) from exc

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)
        if not result or not getattr(result, "success", False):
            raise RuntimeError(getattr(result, "error_message", "crawl4ai failed"))
        md = getattr(result, "markdown", "") or ""
        title = getattr(result, "title", "") or ""
        return title, md, "ok", {"provider": "crawl4ai"}


BACKENDS: dict[str, Any] = {
    "native": run_native,
    "firecrawl": run_firecrawl,
    "browserbase_fetch": run_browserbase_fetch,
    "crawl4ai": run_crawl4ai,
}


def read_urls_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url or url.startswith("#"):
                continue
            kind = (row.get("kind") or "").strip().lower()
            rows.append({"url": url, "kind": kind})
        return rows


async def run_one(run_id: str, backend: str, url: str, kind: str, min_text_len: int) -> BenchResult:
    t0 = time.perf_counter()
    title = ""
    extracted = ""
    status = "error"
    meta: dict[str, Any] = {}
    err = ""
    ok = False

    try:
        fn = BACKENDS[backend]
        if backend == "native":
            title, extracted, status, meta = await fn(url, kind)
        else:
            title, extracted, status, meta = await fn(url)
        norm = normalize_text(extracted)
        ok = len(norm) >= min_text_len
        h = sha256_hex(norm) if norm else ""
    except Exception as exc:
        norm = ""
        h = ""
        err = str(exc)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return BenchResult(
        run_id=run_id,
        backend=backend,
        url=url,
        kind=kind,
        ok=ok,
        status=status if err == "" else "error",
        elapsed_ms=elapsed_ms,
        text_len=len(norm),
        content_hash=h,
        title=title or "",
        error=err,
        meta=meta or {},
    )


async def run_all(
    urls: list[dict[str, str]],
    backends: list[str],
    out_dir: Path,
    concurrency: int,
    min_text_len: int,
) -> tuple[str, list[BenchResult]]:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(backend: str, url: str, kind: str):
        async with sem:
            return await run_one(run_id, backend, url, kind, min_text_len=min_text_len)

    tasks = []
    for row in urls:
        url = row["url"]
        kind = row["kind"] or infer_kind(url)
        for backend in backends:
            tasks.append(guarded(backend, url, kind))

    results = await asyncio.gather(*tasks)
    return run_id, list(results)


def write_outputs(out_dir: Path, run_id: str, results: list[BenchResult]) -> tuple[Path, Path]:
    csv_path = out_dir / f"benchmark_{run_id}.csv"
    jsonl_path = out_dir / f"benchmark_{run_id}.jsonl"

    # CSV
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "run_id",
            "backend",
            "url",
            "kind",
            "ok",
            "status",
            "elapsed_ms",
            "text_len",
            "content_hash",
            "title",
            "error",
            "meta",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            d = asdict(r)
            d["meta"] = json.dumps(d.get("meta") or {}, ensure_ascii=False)
            w.writerow(d)

    # JSONL
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    return csv_path, jsonl_path


def print_summary(results: list[BenchResult]) -> None:
    by_backend: dict[str, list[BenchResult]] = {}
    for r in results:
        by_backend.setdefault(r.backend, []).append(r)

    lines = []
    for backend, rows in sorted(by_backend.items()):
        n = len(rows)
        ok = sum(1 for r in rows if r.ok)
        err = sum(1 for r in rows if r.status == "error")
        p50 = percentile([r.elapsed_ms for r in rows], 50)
        p95 = percentile([r.elapsed_ms for r in rows], 95)
        avg_len = int(sum(r.text_len for r in rows) / max(1, n))
        lines.append(
            {
                "backend": backend,
                "total": n,
                "ok": ok,
                "ok_rate": round(ok / max(1, n), 3),
                "errors": err,
                "lat_p50_ms": p50,
                "lat_p95_ms": p95,
                "avg_text_len": avg_len,
            }
        )
    print(json.dumps({"summary": lines}, indent=2))


def percentile(values: list[int], p: int) -> int:
    if not values:
        return 0
    vs = sorted(values)
    k = int(round((p / 100) * (len(vs) - 1)))
    k = max(0, min(k, len(vs) - 1))
    return int(vs[k])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True, help="CSV with at least a 'url' column")
    ap.add_argument("--out", default="artifacts/bench", help="Output directory")
    ap.add_argument(
        "--backends",
        default="native",
        help="Comma-separated: native,firecrawl,browserbase_fetch,crawl4ai",
    )
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--min-text-len", type=int, default=300)
    args = ap.parse_args()

    urls_path = Path(args.urls)
    out_dir = Path(args.out)
    backends = [b.strip() for b in (args.backends or "").split(",") if b.strip()]

    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        raise SystemExit(f"Unknown backends: {unknown}. Allowed: {list(BACKENDS.keys())}")

    urls = read_urls_csv(urls_path)
    if not urls:
        raise SystemExit("No URLs found in input CSV.")

    # Run
    run_id, results = asyncio.run(
        run_all(
            urls=urls,
            backends=backends,
            out_dir=out_dir,
            concurrency=args.concurrency,
            min_text_len=args.min_text_len,
        )
    )

    csv_path, jsonl_path = write_outputs(out_dir, run_id, results)
    print_summary(results)
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {jsonl_path}")


if __name__ == "__main__":
    main()

