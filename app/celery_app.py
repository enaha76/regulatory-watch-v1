"""
Celery application with Redis broker, periodic heartbeat, and ingestion tasks.

Resilience knobs (all in :mod:`app.config`):

* ``CELERY_SCORING_MAX_RETRIES`` / ``CELERY_OBLIGATIONS_MAX_RETRIES``
  bound the per-task retry budget so a single permanently-broken event
  cannot loop on the LLM forever.
* ``CELERY_SCORING_RATE_LIMIT`` / ``CELERY_OBLIGATIONS_RATE_LIMIT`` cap
  the per-worker LLM call rate (Celery enforces these natively).
* ``app.services.circuit_breaker`` provides a Redis-backed
  cross-worker circuit breaker; tasks consult it before calling the
  LLM and report success/failure back so a bad upstream stops being
  hammered by every worker simultaneously.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from app.config import get_settings
from app.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

settings = get_settings()


@worker_process_init.connect
def _init_worker_logging(**_kwargs) -> None:
    """Re-init structlog inside each forked worker process."""
    setup_logging()


celery = Celery(
    "regwatch",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# ── Periodic tasks (Celery Beat) ─────────────────────────────────────────────
celery.conf.beat_schedule = {
    "heartbeat-every-5minutes": {
        "task": "app.celery_app.heartbeat",
        "schedule": 300.0,
    },
    "rss-federal-register-every-30min": {
        "task": "app.celery_app.rss_ingest_task",
        "schedule": 1800.0,
        "kwargs": {"feed_url": "https://www.govinfo.gov/rss/fr.xml"},
    },
    "rss-fca-every-30min": {
        "task": "app.celery_app.rss_ingest_task",
        "schedule": 1800.0,
        "kwargs": {"feed_url": "https://www.fca.org.uk/news/rss.xml"},
    },
    "web-crawl-eur-lex-every-6h": {
        "task": "app.celery_app.web_crawl_task",
        "schedule": 21600.0,
        "kwargs": {
            "seed_urls": ["https://eur-lex.europa.eu/latest-laws/"],
            "allowed_domain": "eur-lex.europa.eu",
            "max_pages": 50,
            "rate_limit_rps": 0.5,
        },
    },
    "web-crawl-fca-every-6h": {
        "task": "app.celery_app.web_crawl_task",
        "schedule": 21600.0,
        "kwargs": {
            "seed_urls": ["https://www.fca.org.uk/news"],
            "allowed_domain": "www.fca.org.uk",
            "max_pages": 50,
            "rate_limit_rps": 0.5,
        },
    },
    "web-crawl-federal-register-every-6h": {
        "task": "app.celery_app.web_crawl_task",
        "schedule": 21600.0,
        "kwargs": {
            "seed_urls": ["https://www.federalregister.gov/documents/current"],
            "allowed_domain": "www.federalregister.gov",
            "max_pages": 50,
            "rate_limit_rps": 0.5,
        },
    },
    # T2.5 / T2.10 — XMLConnector daily schedule (representative source).
    "xml-uslm-usc-title5-daily": {
        "task": "app.celery_app.xml_ingest_task",
        "schedule": 86400.0,
        "kwargs": {
            "source": "https://www.govinfo.gov/bulkdata/USLM/usc/xml/usc05.xml",
            "title": "US Code, Title 5 — Government Organization and Employees",
        },
    },
}


# ── Heartbeat ────────────────────────────────────────────────────────────────
@celery.task(name="app.celery_app.heartbeat")
def heartbeat():
    """Heartbeat — verifies Redis + Postgres reachability."""
    import redis as redis_lib
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import text

    from app.database import engine

    status = {"redis": "unknown", "database": "unknown"}

    try:
        r = redis_lib.from_url(settings.REDIS_URL, socket_timeout=2)
        r.ping()
        status["redis"] = "healthy"
    except redis_lib.RedisError as exc:
        status["redis"] = f"unhealthy: {exc.__class__.__name__}"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "healthy"
    except SQLAlchemyError as exc:
        status["database"] = f"unhealthy: {exc.__class__.__name__}"

    logger.info("heartbeat", **status)
    return status


# ── Ingestion tasks ──────────────────────────────────────────────────────────
@celery.task(name="app.celery_app.rss_ingest_task", bind=True, max_retries=3)
def rss_ingest_task(self, feed_url: str, max_entries: int = 100):
    """T2.4 — Poll an RSS/Atom feed and store new entries."""
    import asyncio

    from app.ingestion.rss_connector import RSSConnector
    from app.ingestion.storage import upsert_documents

    log = logger.bind(task="rss_ingest", feed_url=feed_url)
    log.info("starting")
    try:
        connector = RSSConnector(feed_url=feed_url, max_entries=max_entries)
        docs = asyncio.run(connector.fetch())
        stats = upsert_documents(docs)
        log.info("done", fetched=len(docs), inserted=stats["inserted"])
        return {"feed_url": feed_url, "fetched": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001 — wrapped + re-raised via retry
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery.task(name="app.celery_app.pdf_ingest_task", bind=True, max_retries=3)
def pdf_ingest_task(self, source: str, title: str = ""):
    """T2.3 — Extract text and tables from a PDF URL or file path."""
    import asyncio

    from app.ingestion.pdf_connector import PDFConnector
    from app.ingestion.storage import upsert_documents

    log = logger.bind(task="pdf_ingest", source=source)
    log.info("starting")
    try:
        connector = PDFConnector(source=source, title=title or source)
        docs = asyncio.run(connector.fetch())
        stats = upsert_documents(docs)
        log.info("done", pages=len(docs), inserted=stats["inserted"])
        return {"source": source, "pages": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery.task(name="app.celery_app.xml_ingest_task", bind=True, max_retries=3)
def xml_ingest_task(self, source: str, title: str = ""):
    """T2.5 — Parse USLM or Akoma Ntoso XML."""
    import asyncio

    from app.ingestion.storage import upsert_documents
    from app.ingestion.xml_connector import XMLConnector

    log = logger.bind(task="xml_ingest", source=source)
    log.info("starting")
    try:
        connector = XMLConnector(source=source, title=title or source)
        docs = asyncio.run(connector.fetch())
        stats = upsert_documents(docs)
        log.info("done", sections=len(docs), inserted=stats["inserted"])
        return {"source": source, "sections": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery.task(name="app.celery_app.email_ingest_task", bind=True, max_retries=3)
def email_ingest_task(self):
    """T2.6 — Poll IMAP mailbox for new regulatory emails."""
    import asyncio

    from app.ingestion.email_connector import EmailConnector
    from app.ingestion.storage import upsert_documents

    s = get_settings()
    if not s.IMAP_HOST or not s.IMAP_USER:
        logger.info("email_ingest_skipped", reason="imap_not_configured")
        return {"skipped": True}

    log = logger.bind(task="email_ingest", host=s.IMAP_HOST, user=s.IMAP_USER)
    log.info("starting")
    try:
        connector = EmailConnector(
            host=s.IMAP_HOST,
            port=s.IMAP_PORT,
            user=s.IMAP_USER,
            password=s.IMAP_PASSWORD,
            mailbox=s.IMAP_MAILBOX,
        )
        docs = asyncio.run(connector.fetch())
        stats = upsert_documents(docs)
        log.info("done", fetched=len(docs), inserted=stats["inserted"])
        return {"fetched": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ── M3 / M4 LLM tasks ────────────────────────────────────────────────────────
@celery.task(
    name="app.celery_app.score_change_event",
    bind=True,
    max_retries=settings.CELERY_SCORING_MAX_RETRIES,
    rate_limit=settings.CELERY_SCORING_RATE_LIMIT or None,
    acks_late=True,
)
def score_change_event(self, event_id: str, retry_errors: bool = False):
    """
    M3 Layer-3 — run the LLM significance scorer for a single ChangeEvent.

    Idempotent and safe to re-queue. Bounded by:
    * ``CELERY_SCORING_MAX_RETRIES`` — hard retry cap.
    * ``CELERY_SCORING_RATE_LIMIT`` — per-worker QPS ceiling.
    * Circuit breaker on scope ``openai:scoring`` — short-circuits when
      consecutive HTTP errors cross ``LLM_CIRCUIT_BREAKER_THRESHOLD``.
    """
    from uuid import UUID

    from app.services import circuit_breaker
    from app.services.significance import score_event

    log = logger.bind(task="score_change_event", event_id=event_id)

    if circuit_breaker.is_open("openai:scoring"):
        log.warning("circuit_open_skipping")
        return {"status": "circuit_open", "scope": "openai:scoring"}

    try:
        result = score_event(UUID(event_id), retry_errors=retry_errors)
    except Exception as exc:  # noqa: BLE001 — wrapped + re-raised
        log.error("crashed", error=str(exc), error_type=type(exc).__name__)
        circuit_breaker.record_failure("openai:scoring")
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

    if result.get("status") == "error":
        err = (result.get("error") or "")
        if err.startswith("http_error"):
            circuit_breaker.record_failure("openai:scoring")
            raise self.retry(countdown=30 * (2 ** self.request.retries))
        # parse_error / validation_error → dead letter; do not retry.
        log.warning("dead_letter", error=err)
    elif result.get("status") == "scored":
        circuit_breaker.record_success("openai:scoring")
        score = result.get("score") or 0.0
        if score >= settings.OBLIGATIONS_SCORE_GATE:
            extract_obligations_task.delay(event_id)

    return result


@celery.task(
    name="app.celery_app.extract_obligations_task",
    bind=True,
    max_retries=settings.CELERY_OBLIGATIONS_MAX_RETRIES,
    rate_limit=settings.CELERY_OBLIGATIONS_RATE_LIMIT or None,
    acks_late=True,
)
def extract_obligations_task(self, event_id: str, force: bool = False):
    """
    M4 phase 3 — run obligation extraction for a high-significance ChangeEvent.

    Auto-enqueued by ``score_change_event`` when score crosses
    ``OBLIGATIONS_SCORE_GATE``. Idempotent via ``obligations_extracted_at``.
    """
    from uuid import UUID

    from app.services import circuit_breaker
    from app.services.obligations import extract_obligations

    log = logger.bind(task="extract_obligations", event_id=event_id)

    if circuit_breaker.is_open("openai:obligations"):
        log.warning("circuit_open_skipping")
        return {"status": "circuit_open", "scope": "openai:obligations"}

    try:
        result = extract_obligations(UUID(event_id), force=force)
    except Exception as exc:  # noqa: BLE001
        log.error("crashed", error=str(exc), error_type=type(exc).__name__)
        circuit_breaker.record_failure("openai:obligations")
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

    if result.get("status") == "http_error":
        circuit_breaker.record_failure("openai:obligations")
        raise self.retry(countdown=30 * (2 ** self.request.retries))

    if result.get("status") in {"extracted", "no_obligations"}:
        circuit_breaker.record_success("openai:obligations")

    return result


# ── Web crawl ────────────────────────────────────────────────────────────────
@celery.task(name="app.celery_app.web_crawl_task", bind=True, max_retries=3)
def web_crawl_task(
    self,
    seed_urls: list,
    allowed_domain: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    rate_limit_rps: float | None = None,
    allowed_path_prefix: str | None = None,
    max_pdfs: int | None = None,
    max_xmls: int | None = None,
):
    """T2.2 — Run WebConnector for a domain and persist results."""
    import asyncio

    from app.ingestion.storage import upsert_documents
    from app.ingestion.web_connector import WebConnector

    s = get_settings()
    log = logger.bind(task="web_crawl", domain=allowed_domain, seeds=seed_urls)
    log.info("starting")
    try:
        connector = WebConnector(
            seed_urls=seed_urls,
            allowed_domain=allowed_domain,
            max_pages=max_pages or s.CRAWL_DEFAULT_MAX_PAGES,
            max_depth=max_depth if max_depth is not None else s.CRAWL_DEFAULT_MAX_DEPTH,
            rate_limit_rps=rate_limit_rps or s.CRAWL_DEFAULT_RATE_LIMIT_RPS,
            allowed_path_prefix=allowed_path_prefix,
            max_pdfs=max_pdfs if max_pdfs is not None else s.CRAWL_DEFAULT_MAX_PDFS,
            max_xmls=max_xmls if max_xmls is not None else s.CRAWL_DEFAULT_MAX_XMLS,
        )
        docs = asyncio.run(connector.fetch())
        stats = upsert_documents(docs)
        log.info("done", fetched=len(docs), inserted=stats["inserted"])
        return {"domain": allowed_domain, "fetched": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
