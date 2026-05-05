"""
Admin endpoints used by the mock-website admin UI to drive end-to-end tests.

POST /api/admin/trigger-crawl  — enqueue a web_crawl_task against the mock website
GET  /api/admin/task/{task_id} — check a Celery task's status
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings


router = APIRouter(prefix="/api/admin", tags=["Admin"])


class TriggerCrawlRequest(BaseModel):
    seed_urls: list[str] | None = None
    allowed_domain: str | None = None
    max_pages: int | None = None
    rate_limit_rps: float | None = None


@router.post("/trigger-crawl")
def trigger_crawl(payload: TriggerCrawlRequest | None = None):
    """Kick off a web crawl. Defaults to crawling the mock website."""
    s = get_settings()
    payload = payload or TriggerCrawlRequest()

    seed_urls = payload.seed_urls or [s.MOCK_WEBSITE_URL]
    allowed_domain = payload.allowed_domain or s.MOCK_WEBSITE_DOMAIN
    max_pages = payload.max_pages or 30
    rate_limit_rps = payload.rate_limit_rps or 5.0

    # Import here to avoid circular import at module load time
    from app.celery_app import web_crawl_task

    try:
        async_result = web_crawl_task.delay(
            seed_urls=seed_urls,
            allowed_domain=allowed_domain,
            max_pages=max_pages,
            rate_limit_rps=rate_limit_rps,
        )
    except Exception as exc:  # pragma: no cover — broker unreachable
        raise HTTPException(
            status_code=502,
            detail=f"Could not enqueue task: {exc.__class__.__name__}: {exc}",
        )

    return {
        "task_id": async_result.id,
        "seed_urls": seed_urls,
        "allowed_domain": allowed_domain,
        "max_pages": max_pages,
    }


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """Inspect a Celery task. Useful for the admin UI to poll completion.

    For a running web_crawl_task, ``state == "PROGRESS"`` and ``progress``
    is the latest meta the worker emitted via ``self.update_state`` —
    the frontend renders that as a live "thinking" log.
    """
    from app.celery_app import celery

    result = celery.AsyncResult(task_id)
    state = result.state
    ready = result.ready()
    payload: dict = {
        "task_id": task_id,
        "state": state,
        "ready": ready,
        "successful": result.successful() if ready else None,
        "result": result.result if ready and result.successful() else None,
        "error": str(result.result) if ready and not result.successful() else None,
        "progress": None,
    }
    # Custom states (PROGRESS) expose their meta dict via ``result.info``.
    # Only surface dicts — guard against tasks that overload other shapes.
    if state == "PROGRESS":
        info = getattr(result, "info", None)
        if isinstance(info, dict):
            payload["progress"] = info
    return payload
