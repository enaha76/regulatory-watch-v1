## Scripts

This folder contains **manual test/debug runners** for the ingestion layer.

- These are **not** automated tests (no pytest runner).
- Some scripts may depend on extra packages not in `requirements.txt` (noted inside the file).

## Benchmarking

See `scripts/benchmark/` for a repeatable runner that benchmarks multiple backends
(native ingestion vs Firecrawl vs Browserbase vs Crawl4AI) on the same URL list.

Run inside the worker container, for example:

```bash
docker exec -it regulation-prj-v1-worker-1 python scripts/test_rss.py
```

