"""
Blocker / interstitial page detection — multilingual.

When a site serves us a CAPTCHA, a Cloudflare "Just a moment" challenge,
a 403/429 page, or a "please enable cookies" interstitial, the previous
implementation would happily extract its text and store it as a
legitimate regulatory document. That polluted ``raw_documents`` and,
worse, fired spurious change events as the challenge page rotated its
nonce.

This module is the single source of truth for that detection. It is:

* **Pure pattern matching** — no network calls, deterministic, easy to
  test.
* **Multilingual** — covers EN / FR / ES / DE / ZH at minimum so we
  don't silently ingest "Êtes-vous un robot?" as a French regulation.
* **Conservative** — a false positive (skipping a real page) is
  cheaper than a false negative (polluting the DB).

It also exposes a Redis-backed per-domain counter
(:func:`record_block`) so operators can detect when a previously-OK
source suddenly starts blocking us.
"""

from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlparse

import redis as _redis

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger(__name__)


# ── Patterns ────────────────────────────────────────────────────────────────
# Title fragments that unambiguously indicate a blocker interstitial.
# All lowercase, matched as substrings (case-insensitive). When adding a
# language, prefer 2–3 tokens that are SHORT and HIGH-PRECISION — long
# phrases break with translation variants.
_BLOCKER_TITLE_PATTERNS = (
    # English
    "access denied", "request access", "are you a robot", "are you human",
    "just a moment", "attention required", "cloudflare", "captcha",
    "please verify", "security check", "403 forbidden", "429 too many",
    "rate limit", "blocked",
    # French
    "accès refusé", "acces refuse", "vérification de sécurité",
    "verification de securite", "êtes-vous un robot", "etes-vous un robot",
    "veuillez patienter",
    # Spanish
    "acceso denegado", "verificación de seguridad", "verificacion de seguridad",
    "¿es usted un robot?", "es usted un robot",
    # German
    "zugriff verweigert", "zugriff abgelehnt", "sicherheitsüberprüfung",
    "sicherheitsuberprufung", "sind sie ein roboter",
    # Chinese (Simplified + Traditional common phrases)
    "访问被拒绝", "请稍候", "人机验证", "驗證您是真人",
)

# Body fragments that, in combination with a SHORT page, flag a blocker.
# Length-gated to avoid false-positives on legitimate articles that
# discuss CAPTCHAs / rate limiting in their content.
_BLOCKER_BODY_PATTERNS = (
    # English
    "enable javascript", "javascript is required", "enable cookies",
    "cookies are required", "verifying you are human",
    "checking your browser", "challenge-platform", "cf-chl-", "__cf_chl_",
    "ddos protection by cloudflare", "access to this resource is forbidden",
    "your ip has been blocked",
    # French
    "veuillez activer javascript", "activer les cookies",
    # Spanish
    "habilite javascript", "active las cookies",
    # German
    "javascript aktivieren", "cookies aktivieren",
    # Chinese
    "启用javascript", "请启用 javascript", "请启用cookies", "啟用 javascript",
)

_BLOCKER_MAX_SHORT_PAGE = 1500  # body-pattern + page < this many chars = blocker
_BLOCKER_EMPTY_THRESHOLD = 200   # any page below this is treated as empty


def is_blocker_page(raw_text: str, title: Optional[str] = None) -> Optional[str]:
    """
    Return a short reason string when the page looks like a blocker /
    interstitial, else None.

    Examples:
        >>> is_blocker_page("Access Denied", "Access Denied — Example")
        "title:'access denied'"
        >>> is_blocker_page("This is a regular regulatory text " * 200, "Customs Update")
        None
    """
    if not raw_text:
        return None

    title_lc = (title or "").lower()
    for pat in _BLOCKER_TITLE_PATTERNS:
        if pat in title_lc:
            return f"title:{pat!r}"

    body_lc = raw_text[:4000].lower()
    for pat in _BLOCKER_BODY_PATTERNS:
        if pat in body_lc and len(raw_text) < _BLOCKER_MAX_SHORT_PAGE:
            return f"body:{pat!r}+short({len(raw_text)}c)"

    if len(raw_text.strip()) < _BLOCKER_EMPTY_THRESHOLD:
        return f"empty_body({len(raw_text)}c)"

    return None


# ── Per-source counters ─────────────────────────────────────────────────────
# Operators want to know "did source X start blocking us today?". We
# maintain rolling per-domain block counters in Redis. Keys are bounded
# in size and TTL so this never grows unbounded.
_KEY_FAIL = "rw:blocker:fail:{domain}"  # ZSET timestamp → reason
_KEY_LAST_REASON = "rw:blocker:last_reason:{domain}"
_WINDOW_SECONDS = 24 * 3600  # rolling 24h


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower() or "unknown"
    except (ValueError, AttributeError):
        return "unknown"


def _client() -> _redis.Redis | None:
    try:
        return _redis.from_url(get_settings().REDIS_URL, socket_timeout=2)
    except _redis.RedisError:
        return None


def record_block(url: str, reason: str) -> None:
    """Record one blocked fetch for ``url``'s domain. Best-effort; never raises."""
    domain = _domain(url)
    log.warning("blocker_page_detected", url=url, domain=domain, reason=reason)
    cli = _client()
    if cli is None:
        return
    now = time.time()
    try:
        pipe = cli.pipeline()
        pipe.zadd(_KEY_FAIL.format(domain=domain), {f"{now}:{reason}": now})
        pipe.zremrangebyscore(_KEY_FAIL.format(domain=domain),
                              "-inf", now - _WINDOW_SECONDS)
        pipe.expire(_KEY_FAIL.format(domain=domain), _WINDOW_SECONDS * 2)
        pipe.setex(_KEY_LAST_REASON.format(domain=domain),
                   _WINDOW_SECONDS, reason)
        pipe.execute()
    except _redis.RedisError as exc:
        log.warning("blocker_counter_redis_error", domain=domain, error=str(exc))


def block_count(url_or_domain: str) -> int:
    """Return the number of blocks recorded for the domain in the last 24h."""
    domain = url_or_domain if "/" not in url_or_domain else _domain(url_or_domain)
    cli = _client()
    if cli is None:
        return 0
    now = time.time()
    try:
        cli.zremrangebyscore(_KEY_FAIL.format(domain=domain),
                             "-inf", now - _WINDOW_SECONDS)
        return int(cli.zcard(_KEY_FAIL.format(domain=domain)) or 0)
    except _redis.RedisError:
        return 0


def last_reason(url_or_domain: str) -> Optional[str]:
    """Return the most recent block reason recorded for the domain, if any."""
    domain = url_or_domain if "/" not in url_or_domain else _domain(url_or_domain)
    cli = _client()
    if cli is None:
        return None
    try:
        v = cli.get(_KEY_LAST_REASON.format(domain=domain))
        return v.decode("utf-8") if v else None
    except _redis.RedisError:
        return None
