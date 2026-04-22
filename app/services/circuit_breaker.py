"""
Tiny Redis-backed circuit breaker for outbound LLM calls.

Why
---
Without this, a transient OpenAI outage can have N Celery workers each
retrying ``CELERY_*_MAX_RETRIES`` times with exponential backoff while
new events keep landing in the queue — amplifying the problem and
running up the bill. The breaker collapses that into a fast fail and a
single coordinated cooldown across all workers.

Algorithm
---------
* Every failed LLM call calls :func:`record_failure(scope)`.
  We append the current timestamp to a Redis list keyed by ``scope``
  (e.g. ``"openai:scoring"``) and trim entries older than ``WINDOW``.
* :func:`is_open(scope)` returns True when the count of recent
  failures within the window crosses ``THRESHOLD``. We also set an
  explicit ``open_until`` key so the breaker stays open for the full
  ``COOLDOWN`` even if old failures age out.
* :func:`record_success(scope)` clears state.

Failure modes
-------------
If Redis itself is down we fail OPEN-ish: the breaker is bypassed and
the underlying retry policy still applies. Reason: blocking all LLM
work because the breaker's bookkeeping store is unreachable would be
worse than the problem the breaker is trying to solve.
"""

from __future__ import annotations

import time
from typing import Final

import redis as _redis

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger(__name__)

_KEY_FAILURES: Final = "rw:cb:failures:{scope}"
_KEY_OPEN_UNTIL: Final = "rw:cb:open_until:{scope}"


def _client() -> _redis.Redis | None:
    settings = get_settings()
    try:
        return _redis.from_url(settings.REDIS_URL, socket_timeout=2)
    except _redis.RedisError as exc:
        log.warning("circuit_breaker_redis_unreachable", error=str(exc))
        return None


def is_open(scope: str) -> bool:
    """Return True if the breaker for ``scope`` is currently open."""
    settings = get_settings()
    cli = _client()
    if cli is None:
        return False  # fail-open: don't block real work on bookkeeping outage
    try:
        until_raw = cli.get(_KEY_OPEN_UNTIL.format(scope=scope))
        if until_raw is None:
            return False
        until = float(until_raw)
        if time.time() < until:
            return True
        cli.delete(_KEY_OPEN_UNTIL.format(scope=scope))
        return False
    except _redis.RedisError as exc:
        log.warning("circuit_breaker_check_failed", scope=scope, error=str(exc))
        return False


def record_failure(scope: str) -> bool:
    """Record one failure. Returns True iff the breaker just tripped open."""
    settings = get_settings()
    cli = _client()
    if cli is None:
        return False

    now = time.time()
    window_start = now - settings.LLM_CIRCUIT_BREAKER_WINDOW_SECONDS
    key = _KEY_FAILURES.format(scope=scope)
    open_key = _KEY_OPEN_UNTIL.format(scope=scope)

    try:
        pipe = cli.pipeline()
        pipe.zadd(key, {f"{now}": now})
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        pipe.expire(key, settings.LLM_CIRCUIT_BREAKER_WINDOW_SECONDS * 2)
        _, _, count, _ = pipe.execute()

        if count >= settings.LLM_CIRCUIT_BREAKER_THRESHOLD:
            until = now + settings.LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS
            cli.setex(open_key,
                      settings.LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
                      str(until))
            log.warning("circuit_breaker_tripped", scope=scope,
                        failures_in_window=int(count),
                        cooldown_seconds=settings.LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS)
            return True
        return False
    except _redis.RedisError as exc:
        log.warning("circuit_breaker_record_failed", scope=scope, error=str(exc))
        return False


def record_success(scope: str) -> None:
    """Clear all breaker bookkeeping for ``scope`` (call on a successful LLM round-trip)."""
    cli = _client()
    if cli is None:
        return
    try:
        cli.delete(_KEY_FAILURES.format(scope=scope),
                   _KEY_OPEN_UNTIL.format(scope=scope))
    except _redis.RedisError:
        pass


class CircuitOpen(RuntimeError):
    """Raised by callers that want to short-circuit when the breaker is open."""
