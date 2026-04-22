## Benchmark harness (Firecrawl vs Browserbase vs Crawl4AI vs native)

This folder contains a **repeatable benchmark runner** that tests multiple web-ingestion backends against the **same URL list** and writes a **CSV/JSONL** report.

### What it measures

- **success**: did we extract usable text?
- **latency**: wall-clock time per URL
- **text_len**: extracted text length (after normalization)
- **content_hash**: SHA-256 of normalized text (used for change detection)

### Backends

- **native**: uses your project connectors (`WebConnector`, `PDFConnector`, `XMLConnector`, `RSSConnector`)
- **firecrawl**: calls Firecrawl `/v2/scrape` (markdown)
- **browserbase_fetch**: calls Browserbase `/v1/fetch` (raw HTTP; **no JS**)
- **crawl4ai**: runs Crawl4AI locally (Playwright-based) and returns markdown

### Setup

Install deps (local dev) or run inside your Docker container:

```bash
pip install -r requirements.txt
```

Environment variables (only needed for those backends):

- `FIRECRAWL_API_KEY`
- `BROWSERBASE_API_KEY` (used as `X-BB-API-Key` header)

### URL list format

Provide a CSV with at least a `url` column:

```csv
url,kind
https://eur-lex.europa.eu/latest-laws/,web
https://www.govinfo.gov/rss/fr.xml,rss
https://example.com/file.pdf,pdf
```

`kind` is optional; if omitted, the runner infers it from the URL (`.pdf`, `.xml`, RSS-like, else `web`).

### Run

From repo root:

```bash
python scripts/benchmark/run_benchmark.py --urls scripts/benchmark/urls.sample.csv --out artifacts/bench --backends native,crawl4ai
```

Include API backends (requires keys):

```bash
python scripts/benchmark/run_benchmark.py --urls scripts/benchmark/urls.sample.csv --out artifacts/bench --backends native,firecrawl,browserbase_fetch,crawl4ai
```

### “False change” check

Run twice with the same inputs and compare `content_hash` between runs. If a backend produces different hashes without a real page change, it’s noisy for monitoring.
