"""
Structured logging — single setup function used by API, Celery and CLI scripts.

We use ``structlog`` so every log line is machine-parseable and every
field (event_id, source_url, model, latency_ms, …) is a discrete key
rather than buried in a printf message. This is the difference between
``grep -F "score=0.7"`` and ``jq '.score >= 0.7'`` on a log aggregator.

Two output modes (controlled by ``LOG_FORMAT``):

  * ``json``    — newline-delimited JSON, suitable for Loki / Datadog /
                  CloudWatch / Promtail. Default in production.
  * ``console`` — coloured, human-readable. For local dev.

Stdlib loggers (``logging.getLogger(...)``) are also routed through
structlog's processor chain so libraries (SQLAlchemy, httpx, celery)
emit the same JSON shape.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import get_settings


def setup_logging() -> None:
    """Configure stdlib + structlog. Idempotent."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.LOG_FORMAT == "console":
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Quiet down noisy libraries.
    for noisy in ("urllib3", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog-bound logger.

    Usage::

        log = get_logger(__name__)
        log.info("scored_event", event_id=str(event_id), score=0.7,
                 latency_ms=412, model="gpt-4o-mini")
    """
    return structlog.get_logger(name)
