"""
URL normalization, domain boundary checks, and spider-trap detection.

Used by WebConnector to ensure:
  - Canonical URL form (no tracking params, no fragments)
  - Crawl stays within the configured domain
  - Calendar loops, session IDs, and repeated path segments are skipped
"""

import re
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin
from urllib.robotparser import RobotFileParser
from typing import Optional

logger = logging.getLogger(__name__)

# ── Tracking query parameters to strip ───────────────────────────────────────
_TRACKING_PARAMS: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_referrer", "fbclid", "gclid", "msclkid", "ttclid",
    "_ga", "_gl", "ref", "referrer", "mc_cid", "mc_eid",
})

# ── Spider-trap patterns ──────────────────────────────────────────────────────
# Session IDs embedded in query string
_SESSION_RE = re.compile(
    r"[?&](session_?id|sid|jsessionid|phpsessid|aspsessionid)=",
    re.IGNORECASE,
)
# Calendar-style date paths that can generate infinite pages
_CALENDAR_RE = re.compile(
    r"/\d{4}/(?:0[1-9]|1[0-2])(?:/(?:0[1-9]|[12]\d|3[01]))?(?:/|$)"
)
# Repeated path segments (e.g. /a/b/a/b/a/)
_REPEATED_SEGMENT_RE = re.compile(r"(/[^/?#]{2,})\1{2,}")


# ── Public helpers ────────────────────────────────────────────────────────────

def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
    """
    Return a canonical form of *url*, or None if the URL is unusable.

    Steps:
      1. Resolve relative URLs against *base_url*.
      2. Accept only http / https schemes.
      3. Strip tracking query parameters; sort remaining params.
      4. Remove fragment identifiers.
      5. Normalise scheme and host to lower-case.
      6. Remove trailing slash from path (except root "/").
    """
    try:
        if base_url:
            url = urljoin(base_url, url)

        parsed = urlparse(url.strip())

        if parsed.scheme not in ("http", "https"):
            return None

        # Strip tracking params; keep the rest sorted for a stable canonical form
        clean_params = sorted(
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in _TRACKING_PARAMS
        )

        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",                         # params (;key=value) — strip
            urlencode(clean_params),
            "",                         # fragment — strip
        ))
    except Exception as exc:
        logger.debug("normalize_url failed for %r: %s", url, exc)
        return None


def extract_host(url: str) -> Optional[str]:
    """Return the lowercased host (netloc) of *url*, or None on error."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return None


def is_same_domain(url: str, allowed_domain: str) -> bool:
    """
    Return True if *url* belongs to *allowed_domain* or any of its subdomains.

    Examples
    --------
    is_same_domain("https://www.cbp.gov/trade/rules", "cbp.gov")  -> True
    is_same_domain("https://evil.com/cbp.gov",        "cbp.gov")  -> False
    """
    host = extract_host(url)
    if not host:
        return False
    # Strip leading www. from both sides for a stable comparison
    allowed = allowed_domain.lower().lstrip("www.")
    host_stripped = host.lstrip("www.")
    return host_stripped == allowed or host_stripped.endswith("." + allowed)


def is_spider_trap(url: str) -> bool:
    """
    Return True when the URL exhibits known spider-trap signatures:

    * URL longer than 512 characters
    * Session ID in query string  (generates infinite unique URLs)
    * Calendar-style date path    (can produce years worth of pages)
    * Repeated path segments      (/a/b/a/b/a/b/...)
    """
    if len(url) > 512:
        return True
    if _SESSION_RE.search(url):
        return True
    parsed = urlparse(url)
    if _CALENDAR_RE.search(parsed.path):
        return True
    if _REPEATED_SEGMENT_RE.search(parsed.path):
        return True
    return False
