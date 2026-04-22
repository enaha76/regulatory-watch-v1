"""
Smoke-test CBP crawl via Celery. Enqueues `web_crawl_task` and waits for the result.

Note: There is no progress until the worker finishes — crawls can run many minutes.
You will see a line immediately with the task id; use `docker compose logs -f worker`
in another terminal for live worker logs.
"""
from __future__ import annotations

from app.celery_app import web_crawl_task

if __name__ == "__main__":
    r = web_crawl_task.delay(
        seed_urls=["https://www.cbp.gov/trade"],
        allowed_domain="cbp.gov",
        max_pages=50,
        rate_limit_rps=0.5,
        allowed_path_prefix="/trade",
        max_pdfs=100,
    )
    print(f"Queued Celery task id={r.id} — waiting for result (timeout 1200s)…", flush=True)
    print("Tip: in another terminal run: docker compose logs -f worker", flush=True)
    out = r.get(timeout=1200)
    print("Result:", out, flush=True)

