"""
Content-extraction helpers for the web crawler.

This is the "what to keep, what to throw away" layer: turning raw HTML
or Crawl4AI markdown into the cleanest possible plain-text body that
still preserves the regulatory content.

Pulled out of ``web_connector.py`` so that:
  * The crawler module stays focused on BFS / fetching / orchestration.
  * Each cleaner is small, pure, and trivially unit-testable.
  * Future cleaners (a per-domain CSS profile, say) drop into one file.

Public surface
--------------
* :func:`clean_soup`     — strip boilerplate from a BeautifulSoup tree.
* :func:`clean_markdown` — post-process Crawl4AI markdown.
* :func:`normalize_for_hash` — stable text shape for content hashing
  and language detection.
* :func:`llm_extract`    — last-resort LLM extraction (only used when
  every deterministic strategy fails). Async.
* :data:`CONTENT_SELECTORS` / :data:`BOILERPLATE_CLASS_PATTERNS` — the
  shared selector lists used by both Crawl4AI excludes and the BS4
  fallback.
"""

from __future__ import annotations

import re
from typing import Optional

import httpx

from app.config import get_settings
from app.ingestion.http_utils import httpx_verify
from app.logging_setup import get_logger

log = get_logger(__name__)


# ── Selector lists ──────────────────────────────────────────────────────────
CONTENT_SELECTORS: tuple[str, ...] = (
    "main",
    "article",
    "#content",
    "#main-content",
    ".content",
    '[role="main"]',
    ".entry-content",
    ".post-content",
)

BOILERPLATE_CLASS_PATTERNS: tuple[str, ...] = (
    "nav", "menu", "breadcrumb", "sidebar", "footer", "header",
    "cookie", "banner", "toolbar", "share", "social", "widget",
    "modal", "popup", "overlay", "ad-", "ads-", "advertisement",
    "search-form", "login", "signup",
)


# ── BeautifulSoup cleaner ───────────────────────────────────────────────────
def clean_soup(soup):
    """
    Aggressively strip boilerplate from a BeautifulSoup tree.
    Removes scripts, styles, nav/header/footer, javascript-href anchors,
    image-only anchors, and any element whose class/id matches the
    boilerplate patterns.

    Returns the same soup (mutated in place).
    """
    for tag in soup.find_all([
        "script", "style", "nav", "header", "footer", "aside",
        "form", "noscript", "iframe", "svg",
    ]):
        tag.decompose()

    for el in soup.find_all(True):
        classes = " ".join(el.get("class", []))
        el_id = el.get("id", "")
        combined = f"{classes} {el_id}".lower()
        if any(pat in combined for pat in BOILERPLATE_CLASS_PATTERNS):
            el.decompose()

    for a in soup.find_all("a", href=True):
        if a["href"].strip().startswith("javascript:"):
            a.decompose()

    for a in soup.find_all("a"):
        children = list(a.children)
        if children and all(
            (getattr(c, "name", None) == "img")
            or (isinstance(c, str) and not c.strip())
            for c in children
        ):
            a.decompose()

    return soup


# ── Markdown cleaner ────────────────────────────────────────────────────────
_SKIP_LINE_MARKERS: tuple[str, ...] = (
    # Accessibility / a11y skip links
    "skip to main content", "skip to navigation", "skip to content",
    "jump to content", "jump to main content",
    "back to top", "return to top", "enter search term",
    # US government standard banner ("Here's how you know")
    "an official website of",
    "here's how you know",
    "here’s how you know",
    "a .gov website belongs",
    "a lock (",
    "a lock or https",
    "means you've safely connected",
    "means you’ve safely connected",
    "share sensitive information",
    "official websites use",
    "secure .gov websites use",
    # Cookie / consent banners
    "accept cookies", "cookie policy", "we use cookies", "this site uses cookies",
)

_EMPTY_ALT_IMAGE_RE = re.compile(r"!\[\s*\]\([^)]*\)")
_IMAGE_ONLY_LINE_RE = re.compile(
    r"^\s*\[?\s*!\[[^\]]*\]\([^)]+\)\s*\]?(?:\([^)]+\))?\s*$"
)
_MD_FORMATTING_RE = re.compile(r"\*{1,3}|_{1,3}|~{1,2}|`+")
_JS_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*(?:javascript:[^)]*|#)\s*\)")
_BREADCRUMB_RE = re.compile(
    r"^\d+\.\s+(?:\[[^\]]+\]\([^)]+\)|\S[^\n]{0,80})\s*$"
)
_RULER_RE = re.compile(r"[-*_]{3,}")


def _strip_md_inline_formatting(text: str) -> str:
    """Strip inline markdown formatting so chrome-marker matching isn't fooled
    by **bold**/_italic_/~~strike~~. Content between markers is preserved."""
    return _MD_FORMATTING_RE.sub("", text)


def _strip_leading_breadcrumb(lines: list[str]) -> list[str]:
    """
    Remove a breadcrumb trail from the top of a document. Conservative:
    only acts at the document head, so legitimate ordered lists inside
    body content are preserved.
    """
    i = 0
    numbered_items = 0
    last_match_idx = -1
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if _BREADCRUMB_RE.match(s):
            numbered_items += 1
            last_match_idx = i
            i += 1
        else:
            break

    if numbered_items == 0 or last_match_idx < 0:
        return lines

    next_is_heading = False
    j = last_match_idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j < len(lines) and lines[j].lstrip().startswith("#"):
        next_is_heading = True

    if numbered_items >= 2 or (numbered_items == 1 and next_is_heading):
        return lines[last_match_idx + 1:]
    return lines


def _is_nav_table_row(line: str) -> bool:
    """True for markdown table rows that are mostly nav links (`| [a](u) |`)."""
    s = line.strip()
    if not s.startswith("|") or not s.endswith("|"):
        return False
    if all(c in "|-: \t" for c in s):
        return True
    without_links = re.sub(r"\[[^\]]*\]\([^)]*\)", "", s)
    without_links = re.sub(r"[|×\-:]+", "", without_links).strip()
    return len(without_links) < 20


def clean_markdown(md: str) -> str:
    """
    Post-process Crawl4AI markdown.

    Drops accessibility/a11y skip-links, US-gov standard banners, cookie
    notices, decorative (empty-alt) images, rulers, image-only logo
    lines, javascript-void links, nav-like markdown table rows, and
    collapses repeated blanks. Never rewrites meaningful content.
    """
    out_lines: list[str] = []
    blank_run = 0
    for raw_line in md.splitlines():
        line = raw_line.rstrip()

        if _IMAGE_ONLY_LINE_RE.match(line):
            continue

        line = _EMPTY_ALT_IMAGE_RE.sub("", line)
        line = _JS_LINK_RE.sub(r"\1", line).strip()

        if _is_nav_table_row(line):
            continue

        stripped = line.strip()
        low = _strip_md_inline_formatting(stripped).lower()

        if not low:
            blank_run += 1
            if blank_run <= 1:
                out_lines.append("")
            continue
        blank_run = 0

        if _RULER_RE.fullmatch(low):
            continue
        if any(marker in low for marker in _SKIP_LINE_MARKERS):
            continue

        out_lines.append(stripped)

    out_lines = _strip_leading_breadcrumb(out_lines)
    return "\n".join(out_lines).strip()


# ── Hash-stable normalization ───────────────────────────────────────────────
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WS_RE = re.compile(r"\s+")


def normalize_for_hash(text: str) -> str:
    """
    Normalize extracted text for stable hashing and language detection.
    Strips markdown image/link syntax noise, drops table-noise lines,
    and collapses whitespace.
    """
    text = _MD_IMAGE_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not all(c in "|-*_ \t" for c in stripped):
            lines.append(stripped)
    text = "\n".join(lines)
    return _WS_RE.sub(" ", text).strip()


# ── LLM fallback (last resort) ──────────────────────────────────────────────
_LLM_APOLOGY_PHRASES = (
    "i'm sorry", "i cannot", "i can't", "unable to extract", "no regulatory",
)


async def llm_extract(raw_text: str, url: str) -> Optional[str]:
    """
    Last-resort LLM-based extraction.

    Only call when every deterministic strategy has failed; this costs
    tokens and is non-deterministic. Hard-capped input size and output
    tokens to keep the marginal bill bounded.
    """
    import hashlib
    import time
    from app.services import llm_usage

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return None

    content_preview = raw_text[:2000]
    prompt = (
        f"Extract the main regulatory content from this page. "
        f"Remove nav/footer/cookie banners. Plain text only.\n\n{content_preview}"
    )
    model = settings.OPENAI_MODEL
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    fp = hashlib.sha256((model + "\x1f" + prompt).encode("utf-8")).hexdigest()[:12]
    try:
        started = time.monotonic()
        async with httpx.AsyncClient(
            timeout=settings.LLM_TIMEOUT,
            verify=httpx_verify("https://api.openai.com/"),
        ) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload, headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
        latency_ms = int((time.monotonic() - started) * 1000)
        llm_usage.record(
            scope="web_extract",
            model=model,
            usage=body.get("usage"),
            latency_ms=latency_ms,
            request_hash=fp,
            url=url,
        )
        result = body["choices"][0]["message"]["content"].strip()
        if result and any(result.lower().startswith(p) for p in _LLM_APOLOGY_PHRASES):
            log.debug("llm_extract_apology_discarded", url=url)
            return None
        return result or None
    except httpx.HTTPError as exc:
        log.warning("llm_extract_http_error", url=url,
                    error_type=exc.__class__.__name__, error=str(exc)[:200])
        return None
    except (KeyError, ValueError) as exc:
        log.warning("llm_extract_parse_error", url=url,
                    error_type=exc.__class__.__name__, error=str(exc)[:200])
        return None
