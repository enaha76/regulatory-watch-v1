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
    # User-managed sources: every 5 min, scan `domains` for ones whose last
    # crawl is older than their per-source `crawl_interval_seconds` (or the
    # platform default if NULL). See app/services/frequency.py and the
    # `crawl_due_domains` task below.
    "crawl-due-domains-every-5min": {
        "task": "app.celery_app.crawl_due_domains",
        "schedule": 300.0,
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


# ── User-managed source scheduler ─────────────────────────────────────────────
@celery.task(name="app.celery_app.crawl_due_domains")
def crawl_due_domains():
    """
    Find every active domain whose last fetch_run is older than its
    per-source crawl interval (or the platform default if NULL) and
    enqueue a `web_crawl_task` for it.

    This is the single beat task that powers the Add-Source UI's
    frequency picker. The hardcoded scheduled crawls (EUR-Lex, FCA, …)
    in this file run independently — this task only handles domains
    inserted via /api/v2/sources.
    """
    from datetime import datetime, timedelta, timezone

    from sqlmodel import Session, select

    from app.database import engine
    from app.models import Domain
    from app.services.frequency import effective_interval

    log = logger.bind(task="crawl_due_domains")
    enqueued = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        stmt = select(Domain).where(Domain.status == "active")

        for domain in session.exec(stmt).all():
            interval = effective_interval(domain.crawl_interval_seconds)
            last = domain.last_crawled_at
            due = last is None or (now - last) >= timedelta(seconds=interval)

            if not due:
                skipped += 1
                # Per-domain debug log — makes it easy to answer
                # "why didn't X crawl yet?" without poking at the DB.
                log.debug(
                    "crawl_due_skip",
                    domain=domain.domain,
                    last_crawled_at=last.isoformat() if last else None,
                    interval_seconds=interval,
                )
                continue

            seed_urls = list(domain.seed_urls or [])
            if not seed_urls:
                seed_urls = [f"https://{domain.domain}"]

            try:
                web_crawl_task.delay(
                    seed_urls=seed_urls,
                    allowed_domain=domain.domain,
                    rate_limit_rps=max(0.5, domain.rate_limit_rps),
                    # max_pages on the Domain row overrides the platform
                    # default. None → web_crawl_task falls back to the
                    # default itself.
                    max_pages=domain.max_pages,
                )
                enqueued += 1
                log.info(
                    "crawl_due_enqueued",
                    domain=domain.domain,
                    interval_seconds=interval,
                    max_pages=domain.max_pages,
                    last_crawled_at=last.isoformat() if last else "never",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "crawl_due_enqueue_failed",
                    domain=domain.domain,
                    error=str(exc),
                )

    log.info("crawl_due_domains_done", enqueued=enqueued, skipped=skipped)
    return {"enqueued": enqueued, "skipped": skipped}


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


# ── M5 Alerting Engine ───────────────────────────────────────────────────────
@celery.task(
    name="app.celery_app.match_change_event",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def match_change_event(self, event_id: str):
    """
    M5 — match a scored ChangeEvent against all active user subscriptions
    and insert alert rows for each match.

    Auto-enqueued by ``score_change_event`` after M4 scoring completes.
    Uses PostgreSQL full-text search (TSVector/TSQuery) — zero LLM cost.
    """
    from uuid import UUID

    from app.services.matching import match_event

    log = logger.bind(task="match_change_event", event_id=event_id)
    log.info("starting")

    try:
        result = match_event(UUID(event_id))
    except Exception as exc:  # noqa: BLE001
        log.error("crashed", error=str(exc), error_type=type(exc).__name__)
        raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

    log.info("done", alerts_created=result.get("alerts_created", 0))
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
    from datetime import datetime, timezone

    from sqlmodel import Session, select

    from app.database import engine
    from app.ingestion.storage import upsert_documents
    from app.ingestion.web_connector import WebConnector
    from app.models import Domain, FetchRun

    s = get_settings()
    log = logger.bind(task="web_crawl", domain=allowed_domain, seeds=seed_urls)
    log.info("starting")

    # ── Open a FetchRun row + stamp Domain.last_crawled_at ───────────
    # `last_crawled_at` is what `crawl_due_domains` reads to decide
    # whether to re-enqueue. The FetchRun row is the per-crawl history
    # entry the SourcesView reads ("last activity", "fetched count").
    #
    # Hardcoded beat entries may pass an `allowed_domain` that isn't
    # registered as a Domain row — in that case we simply don't write
    # a FetchRun and the crawl proceeds normally.
    fetch_run_id = None
    try:
        with Session(engine) as ssn:
            d = ssn.exec(
                select(Domain).where(Domain.domain == allowed_domain)
            ).first()
            if d is not None:
                d.last_crawled_at = datetime.now(timezone.utc)
                ssn.add(d)
                fr = FetchRun(
                    domain_id=d.id,
                    status="running",
                    started_at=datetime.now(timezone.utc),
                )
                ssn.add(fr)
                ssn.commit()
                ssn.refresh(fr)
                fetch_run_id = fr.id
    except Exception as exc:  # noqa: BLE001 — never let bookkeeping fail the crawl
        log.warning("fetch_run_open_failed",
                    error=str(exc), error_type=type(exc).__name__)

    def _close_fetch_run(status: str, fetched: int = 0, changed: int = 0) -> None:
        """Mark the FetchRun finished. No-op if the row was never created."""
        if fetch_run_id is None:
            return
        try:
            with Session(engine) as ssn:
                fr = ssn.get(FetchRun, fetch_run_id)
                if fr is None:
                    return
                fr.status = status
                fr.finished_at = datetime.now(timezone.utc)
                fr.fetched_count = fetched
                fr.changed_count = changed
                ssn.add(fr)
                ssn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch_run_close_failed",
                        status=status,
                        error=str(exc),
                        error_type=type(exc).__name__)

    # Live progress buffer surfaced via self.update_state. The frontend
    # polls /api/admin/task/{id}, sees state="PROGRESS" + meta.events, and
    # renders the events as a "thinking" log next to the spinner.
    import time as _time

    progress_events: list[dict] = []

    def _push_progress(meta: dict) -> None:
        # Each event already has {"event": str, ...}. Append a wall-clock
        # timestamp so the UI can render relative times if it wants.
        record = {"ts": _time.time(), **meta}
        progress_events.append(record)
        # Keep the buffer bounded so a 1000-page crawl doesn't blow up
        # Redis. The UI gets the most-recent slice.
        if len(progress_events) > 200:
            del progress_events[: len(progress_events) - 200]
        try:
            self.update_state(
                state="PROGRESS",
                meta={
                    "phase": meta.get("event", "running"),
                    "events": progress_events[-50:],
                },
            )
        except Exception as exc:  # noqa: BLE001
            # Never let result-backend hiccups derail the crawl.
            log.warning(
                "update_state_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

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
            on_progress=_push_progress,
        )

        # Crawl4AI's BestFirstCrawlingStrategy fetches many pages inside a
        # single black-box ``arun()`` call — our per-page progress hooks
        # only fire AFTER that call returns. To keep the UI alive during
        # those long silent stretches we run a parallel heartbeat task
        # that emits "still working" events every few seconds.
        async def _run_with_heartbeat():
            async def _heartbeat() -> None:
                elapsed = 0
                while True:
                    await asyncio.sleep(5)
                    elapsed += 5
                    _push_progress({
                        "event": "heartbeat",
                        "elapsed_sec": elapsed,
                    })

            fetch_task = asyncio.create_task(connector.fetch())
            hb_task = asyncio.create_task(_heartbeat())
            try:
                return await fetch_task
            finally:
                hb_task.cancel()
                # Swallow CancelledError — the heartbeat is meant to be
                # cancelled; anything else we just log and continue.
                try:
                    await hb_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "heartbeat_task_error",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )

        docs = asyncio.run(_run_with_heartbeat())
        # Surface the persistence step explicitly — for a big crawl this
        # can take a few seconds while the LLM scoring kicks off.
        _push_progress({"event": "persisting", "docs": len(docs)})
        stats = upsert_documents(docs)
        # `created` + `modified` from upsert_documents = docs that actually
        # produced a ChangeEvent (real "change" count). `inserted` is
        # raw_documents inserts which can include unchanged duplicates.
        changed = (stats.get("created", 0) or 0) + (stats.get("modified", 0) or 0)
        _close_fetch_run("completed", fetched=len(docs), changed=changed)
        log.info("done", fetched=len(docs), inserted=stats["inserted"], changed=changed)
        _push_progress({
            "event": "done",
            "fetched": len(docs),
            "created": stats.get("created", 0),
            "modified": stats.get("modified", 0),
            "unchanged": stats.get("unchanged", 0),
        })
        return {"domain": allowed_domain, "fetched": len(docs), **stats}
    except Exception as exc:  # noqa: BLE001
        log.error("failed", error=str(exc), error_type=type(exc).__name__)
        _close_fetch_run("failed")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
