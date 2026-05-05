"""
T2.2 — WebConnector (Crawl4AI primary, httpx fallback)

Async BFS web crawler. Fetches pages with Crawl4AI (Playwright-based, JS
rendering, produces clean HTML/markdown) and falls back to a lightweight
httpx GET when Crawl4AI is not available or fails.

Extraction:
  1. Targeted CSS selectors (main, article, #content) → markdownify
  2. Full-page markdownify with boilerplate tag stripping
  3. LLM fallback via OpenAI (optional, last resort)

Features:
  - Crawl4AI AsyncWebCrawler: a single browser instance reused across URLs
  - httpx fallback for environments without a browser / when JS isn't needed
  - Concurrent fetching: up to MAX_CONCURRENT pages in parallel
  - PDF/XML harvesting: auto-detects and extracts PDF/XML links
  - robots.txt compliance, rate limiting, domain boundary, spider trap detection
  - Path prefix filtering: restrict crawl to specific site sections
"""

import asyncio
import hashlib
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Callable, List, Optional, Set
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.ingestion.base import IngestorBase
from app.ingestion.http_utils import httpx_verify
from app.ingestion.url_utils import (
    normalize_url,
    is_same_domain,
    is_spider_trap,
)
from app.models import RawDocument

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _detect_language(text: str) -> Optional[str]:
    """Shared CJK-aware language detection (see app.ingestion.lang)."""
    from app.ingestion.lang import detect as _shared_detect
    return _shared_detect(text)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Blocker-page detection lives in app.ingestion.blocker_detect — multilingual
# patterns + per-domain Redis counter for "is this source starting to block us"
# observability. We re-export the functional names here so callers inside this
# module keep their existing call sites.
from app.ingestion.blocker_detect import (  # noqa: E402
    is_blocker_page as _is_blocker_page,
    record_block as _record_block,
)


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _is_xml_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    skip = ("sitemap", "robots", "feed", "rss", "atom")
    return path.endswith(".xml") and not any(s in path for s in skip)


# Binary/download file extensions that should be skipped entirely
_SKIP_EXTENSIONS = (
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".gz", ".tar", ".7z",
    ".exe", ".dmg", ".pkg",
    ".mp4", ".mp3", ".avi", ".mov",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
)

# URL path/query fragments that indicate a non-regulatory useless page.
# Checked against the lowercased full URL (path + query).
# Ordered from most common to least for early exit.
_SKIP_URL_FRAGMENTS = (
    # ── Auth & account ────────────────────────────────────────────
    "/login", "/logout", "/signin", "/sign-in", "/sign-up",
    "/signup", "/register", "/forgot-password", "/reset-password",
    "/change-password", "/my-account", "/my-profile", "/user-profile",
    "/account/", "/session/",

    # ── Contact & corporate ───────────────────────────────────────
    "/contact", "/contact-us", "/about-us", "/about/team",
    "/our-team", "/meet-the-team", "/careers", "/jobs",
    "/vacancies", "/press", "/media-center", "/newsroom",
    "/investors", "/advertise", "/partners", "/sponsors",

    # ── Legal boilerplate ─────────────────────────────────────────
    "/privacy", "/privacy-policy", "/terms", "/terms-of-service",
    "/terms-and-conditions", "/cookie", "/cookies", "/cookie-policy",
    "/accessibility", "/accessibility-statement", "/disclaimer",
    "/copyright", "/legal-notice", "/legal-information",

    # ── Navigation & utility ──────────────────────────────────────
    "/sitemap", "/site-map", "/help", "/faq", "/support",
    "/feedback", "/newsletter", "/subscribe", "/unsubscribe",
    "/404", "/error", "/page-not-found", "/not-found",

    # ── Social / share ────────────────────────────────────────────
    "/share", "/social-media", "/follow-us",

    # ── Print / export / download ─────────────────────────────────
    "/print", "/print-version", "/printable", "/export",
    "/download", "/attachment/", "nota_to_doc", "nota_to_imagen",

    # ── Search result pages (not documents) ───────────────────────
    "?q=", "?query=", "?keyword=", "?search=", "?s=",

    # ── Language / pagination params ──────────────────────────────
    "?lang=", "?language=", "?locale=",
)


def _is_skippable_url(url: str) -> bool:
    """Return True for URLs that have no regulatory content value."""
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    full_lower = (parsed.path + ("?" + parsed.query if parsed.query else "")).lower()

    if any(path_lower.endswith(ext) for ext in _SKIP_EXTENSIONS):
        return True
    if any(frag in full_lower for frag in _SKIP_URL_FRAGMENTS):
        return True
    return False


# ── Regulatory keyword list for BestFirstCrawlingStrategy scorer ─────────────
# Used by KeywordRelevanceScorer to rank discovered URLs by regulatory relevance
# so the most important pages are visited first within the max_pages budget.
REGULATORY_KEYWORDS = [
    # Core regulatory language
    "regulation", "regulatory", "rule", "rulemaking", "ruling",
    "law", "legislation", "statute", "act", "directive", "decision",
    "order", "notice", "guidance", "policy", "framework", "procedure",
    "compliance", "noncompliance", "enforcement", "penalty", "sanction",
    "fine", "violation", "infringement", "obligation", "requirement",
    "mandate", "mandatory", "prohibition", "prohibited", "restriction",
    "deadline", "effective date", "implementation", "coming into force",
    "amendment", "revision", "repeal", "update",
    "official gazette", "federal register", "official journal",
    # Trade & customs
    "tariff", "customs", "duty", "duties", "excise", "levy",
    "import", "export", "trade", "cross-border", "commerce",
    "HS code", "HTS", "TARIC", "harmonized system",
    "quota", "embargo", "anti-dumping", "countervailing", "safeguard",
    "free trade", "FTA", "preferential tariff",
    "customs clearance", "port of entry", "border control",
    "CBP", "HMRC", "rules of origin", "certificate of origin",
    "Section 301", "Section 232", "Section 201",
    # Export controls & sanctions
    "export control", "dual-use", "ECCN", "EAR",
    "OFAC", "sanctions", "embargoed", "entity list", "denied party",
    "BIS", "Commerce Control List",
    # Financial services
    "AML", "anti-money laundering", "KYC", "MiFID", "Basel",
    "capital requirement", "reporting obligation", "disclosure",
    "financial regulation", "banking regulation", "securities",
    "fintech", "crypto", "digital asset", "FATF", "FinCEN",
    # Data privacy & cybersecurity
    "GDPR", "CCPA", "data protection", "personal data",
    "data breach", "cybersecurity", "adequacy decision",
    # Environmental
    "emissions", "carbon", "greenhouse gas", "CBAM",
    "carbon border adjustment", "waste regulation", "hazardous substance",
    "REACH", "RoHS", "PFAS", "environmental impact",
    "sustainability reporting", "deforestation regulation",
    # Health & pharma
    "pharmaceutical", "drug approval", "medical device",
    "FDA", "EMA", "marketing authorization", "pharmacovigilance", "recall",
    # Labor & employment
    "minimum wage", "workplace safety", "labor law",
    "immigration", "work permit", "posted workers",
    # Tax
    "VAT", "GST", "withholding tax", "transfer pricing",
    "BEPS", "FATCA", "CRS", "country-by-country reporting",
    # Corporate governance
    "ESG reporting", "sustainability disclosure",
    "antitrust", "merger control", "corporate governance",
]

# Content extraction (cleaning, markdown post-processing, LLM fallback) lives
# in app.ingestion.web_extractor. We re-export the underscore-prefixed names
# the rest of this module uses.
from app.ingestion.web_extractor import (  # noqa: E402
    CONTENT_SELECTORS,
    BOILERPLATE_CLASS_PATTERNS,
    clean_soup as _clean_soup,
    clean_markdown as _clean_markdown,
    normalize_for_hash as _normalize_for_hash,
    llm_extract as _llm_extract,
)


# ── WebConnector ──────────────────────────────────────────────────────────────

class WebConnector(IngestorBase):
    """
    BFS web crawler with Crawl4AI fetching, concurrent page loading,
    and automatic PDF/XML harvesting.
    """

    USER_AGENT = (
        "RegulatoryWatch/1.0 (compliance monitoring bot; "
        "+https://github.com/your-org/regulatory-watch)"
    )
    MIN_TEXT_LEN = 200
    MAX_CONCURRENT = 5  # parallel page fetches per batch

    def __init__(
        self,
        seed_urls: List[str],
        allowed_domain: str,
        max_pages: int = 50,
        max_depth: int = 3,
        rate_limit_rps: float = 1.0,
        allowed_path_prefix: Optional[str] = None,
        harvest_pdfs: bool = True,
        harvest_xml: bool = True,
        max_pdfs: int = 20,
        max_xmls: int = 10,
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.seed_urls = seed_urls
        self.allowed_domain = allowed_domain
        self.max_pages = max_pages
        self.max_depth = max_depth
        self._delay = 1.0 / max(rate_limit_rps, 0.1)
        self.allowed_path_prefix = allowed_path_prefix
        self.harvest_pdfs = harvest_pdfs
        self.harvest_xml = harvest_xml
        self.max_pdfs = max_pdfs
        self.max_xmls = max_xmls
        self._robots_cache: dict = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        # Lazy-initialised Crawl4AI browser (one per connector run)
        self._crawler = None
        self._crawler_cfg = None
        self._crawl_run_cfg = None
        # Optional progress callback. Invoked synchronously from inside the
        # asyncio loop; the celery task wires it to self.update_state so the
        # UI can render a live "thinking" log. Failures here MUST NOT abort
        # the crawl, hence the broad except in _emit_progress.
        self.on_progress = on_progress

    def _emit_progress(self, event: str, **kwargs) -> None:
        """Send a progress event to the optional callback. Never raises."""
        if self.on_progress is None:
            return
        try:
            self.on_progress({"event": event, **kwargs})
        except Exception:  # noqa: BLE001
            # Bookkeeping failure must not derail the crawl.
            pass

    # ── robots.txt ───────────────────────────────────────────────────────────

    async def _get_robots(self, url: str):
        from urllib.robotparser import RobotFileParser
        parsed_url = httpx.URL(url)
        robots_url = f"{parsed_url.scheme}://{parsed_url.host}/robots.txt"
        if robots_url in self._robots_cache:
            return self._robots_cache[robots_url]

        rp = RobotFileParser(robots_url)
        try:
            async with httpx.AsyncClient(
                timeout=10,
                verify=httpx_verify(robots_url),
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=True,
            ) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    logger.debug(
                        "robots.txt returned %d for %s — assuming allow all",
                        resp.status_code, robots_url,
                    )
                    rp.parse(["User-agent: *", "Allow: /"])
        except Exception as exc:
            logger.debug("robots.txt unavailable at %s: %s", robots_url, exc)
            rp.parse(["User-agent: *", "Allow: /"])

        self._robots_cache[robots_url] = rp
        return rp

    async def _is_allowed(self, url: str) -> bool:
        rp = await self._get_robots(url)
        allowed = rp.can_fetch("*", url) or rp.can_fetch(self.USER_AGENT, url)
        if not allowed:
            logger.warning("robots.txt disallows: %s", url)
        return allowed

    # ── Page fetching (Crawl4AI primary, httpx fallback) ─────────────────────

    PAGE_TIMEOUT = 60  # max seconds per page (includes JS render wait)

    class _HttpxResponse:
        """
        Uniform response shape consumed by _extract_text / _extract_links.

        `markdown` is populated only by the Crawl4AI path (it contains
        pre-extracted, main-content-only markdown). httpx responses leave it
        empty and fall through to BS4 extraction.
        """
        def __init__(
            self,
            body: bytes,
            status_code: int,
            headers: dict,
            markdown: str = "",
        ):
            self.body = body
            self.status_code = status_code
            self.headers = headers
            self.markdown = markdown

    async def _httpx_fetch(self, url: str):
        """Lightweight fallback fetcher (no JS rendering)."""
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            verify=httpx_verify(url),
            headers={"User-Agent": self.USER_AGENT},
        ) as client:
            resp = await client.get(url)
            return self._HttpxResponse(
                body=resp.content or b"",
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )

    async def _init_crawler(self) -> None:
        """Start a single Crawl4AI browser to be reused across all pages."""
        if self._crawler is not None:
            return
        try:
            from crawl4ai import (  # type: ignore
                AsyncWebCrawler,
                BrowserConfig,
                CrawlerRunConfig,
                CacheMode,
            )

            # Pruning content filter: keeps only likely main-content blocks
            # based on text-density / link-density heuristics. This is what
            # makes result.markdown clean enough to skip BS4+LLM entirely.
            markdown_generator = None
            try:
                from crawl4ai.content_filter_strategy import PruningContentFilter  # type: ignore
                from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator  # type: ignore
                markdown_generator = DefaultMarkdownGenerator(
                    content_filter=PruningContentFilter(
                        threshold=0.50,
                        threshold_type="fixed",
                        min_word_threshold=20,
                    ),
                )
            except Exception as exc:
                logger.debug(
                    "Crawl4AI pruning filter unavailable (%s) — using default markdown",
                    exc,
                )

            self._crawler_cfg = BrowserConfig(
                headless=True,
                verbose=False,
                user_agent=self.USER_AGENT,
            )
            # Strip global chrome tags at the HTML level BEFORE markdown is
            # generated. PruningContentFilter cannot reliably detect site
            # navigation on its own when nav is rendered as a table with
            # dense links (e.g. cbp.gov's top menu).
            excluded_tags = ["nav", "header", "footer", "aside", "form", "noscript"]
            excluded_selector = ", ".join([
                # Common semantic / ARIA landmarks
                '[role="navigation"]',
                '[role="banner"]',
                '[role="contentinfo"]',
                '[role="search"]',
                '[aria-label*="breadcrumb"]',
                '[aria-label*="Breadcrumb"]',
                # Common class / id name patterns used by CMSes for chrome
                ".navigation", ".main-navigation", ".site-header", ".site-footer",
                ".page-header", ".page-footer", ".global-nav", ".primary-nav",
                ".breadcrumb", ".breadcrumbs", "#breadcrumb", "#breadcrumbs",
                ".crumb", ".crumbs", ".crumb-trail", ".page-breadcrumb",
                ".skip-link", ".skip-links",
                ".search-form", ".search-box", ".menu-toggle",
                ".cookie-banner", ".cookie-notice", ".usa-banner",
            ])
            run_kwargs = dict(
                cache_mode=CacheMode.BYPASS,
                page_timeout=30_000,
                wait_until="networkidle",
                excluded_tags=excluded_tags,
                excluded_selector=excluded_selector,
                word_count_threshold=10,
                exclude_external_images=True,
            )
            if markdown_generator is not None:
                run_kwargs["markdown_generator"] = markdown_generator
            self._crawl_run_cfg = CrawlerRunConfig(**run_kwargs)

            crawler = AsyncWebCrawler(config=self._crawler_cfg)
            await crawler.__aenter__()
            self._crawler = crawler
            logger.info(
                "Crawl4AI browser started for %s (pruning_filter=%s)",
                self.allowed_domain,
                markdown_generator is not None,
            )
        except ImportError:
            logger.warning(
                "crawl4ai not installed — WebConnector will use httpx only "
                "(no JS rendering). Install with: pip install crawl4ai"
            )
            self._crawler = None
        except Exception as exc:
            logger.warning(
                "Crawl4AI failed to start (%s) — falling back to httpx only", exc,
            )
            self._crawler = None

    @staticmethod
    def _crawl4ai_markdown(result) -> str:
        """
        Extract markdown from a Crawl4AI result across API versions.
        Prefers fit_markdown (post content-filter) when available,
        else raw_markdown, else the plain .markdown string.
        """
        md_obj = getattr(result, "markdown", None)
        if md_obj is None:
            return ""
        if isinstance(md_obj, str):
            return md_obj
        return (
            getattr(md_obj, "fit_markdown", "")
            or getattr(md_obj, "raw_markdown", "")
            or str(md_obj)
        )

    async def _close_crawler(self) -> None:
        if self._crawler is None:
            return
        try:
            await self._crawler.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug("Crawl4AI teardown error: %s", exc)
        finally:
            self._crawler = None

    async def _fetch_page(self, url: str):
        """
        Fetch a single page. Crawl4AI first (real browser, JS), httpx second.
        Hard PAGE_TIMEOUT prevents one slow page from stalling the crawl.
        """
        try:
            return await asyncio.wait_for(
                self._fetch_page_inner(url), timeout=self.PAGE_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Page timeout (%ds) for %s — skipping", self.PAGE_TIMEOUT, url)
            return None

    async def _fetch_page_inner(self, url: str):
        async with self._semaphore:
            await asyncio.sleep(self._delay)

            # 1. Primary: Crawl4AI (reused browser instance)
            if self._crawler is not None:
                try:
                    result = await self._crawler.arun(url=url, config=self._crawl_run_cfg)
                    if result is not None and getattr(result, "success", False):
                        html = (
                            getattr(result, "html", None)
                            or getattr(result, "cleaned_html", None)
                            or ""
                        )
                        markdown = self._crawl4ai_markdown(result)
                        if html or markdown:
                            status = int(getattr(result, "status_code", 200) or 200)
                            return self._HttpxResponse(
                                body=html.encode("utf-8", errors="replace") if html else b"",
                                status_code=status,
                                headers={},
                                markdown=markdown,
                            )
                    err = getattr(result, "error_message", None) if result else None
                    logger.debug("Crawl4AI returned no content for %s (%s)", url, err)
                except Exception as exc:
                    logger.debug("Crawl4AI failed for %s: %s", url, exc)

            # 2. Fallback: plain httpx GET
            try:
                return await self._httpx_fetch(url)
            except Exception as exc:
                logger.warning("All fetchers failed for %s: %s", url, exc)
                return None

    # ── Content extraction ───────────────────────────────────────────────────

    async def _extract_text(self, response, url: str) -> Optional[str]:
        """
        Extract main body content as markdown.

        Strategy order (cheapest + most deterministic first):
          1. Crawl4AI pre-extracted markdown (response.markdown) — free & stable
          2. BeautifulSoup + markdownify on <main>/<article>/etc. (httpx path)
          3. Plain get_text() on cleaned soup
          4. LLM fallback (costs tokens, non-deterministic — last resort)
        """
        import markdownify  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore

        # ── Strategy 1: Crawl4AI already did main-content extraction ──────
        md = getattr(response, "markdown", "") or ""
        if md:
            cleaned = _clean_markdown(md)
            if len(cleaned) >= self.MIN_TEXT_LEN:
                logger.debug(
                    "Crawl4AI markdown used for %s (%d chars)", url, len(cleaned)
                )
                return cleaned

        # ── Prepare HTML for BS4 fallbacks ────────────────────────────────
        raw = getattr(response, "body", b"") or b""
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if not html:
            html = getattr(response, "html_content", "") or getattr(response, "text", "") or ""
        if not html or len(html) < 100:
            logger.debug("Empty HTML for %s", url)
            return None

        # ── Strategy 2: BeautifulSoup + markdownify on main container ─────
        try:
            soup = BeautifulSoup(html, "html.parser")
            soup = _clean_soup(soup)

            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find(id="content")
                or soup.find(id="main-content")
                or soup.find(attrs={"role": "main"})
                or soup.find(class_="content")
                or soup.find(class_="main-content")
                or soup.find(class_="article-content")
                or soup.find(class_="entry-content")
                or soup.find(class_="post-content")
            )
            target_html = str(main) if main else str(soup.body or soup)
            text = markdownify.markdownify(target_html)

            if text and len(text.strip()) >= self.MIN_TEXT_LEN:
                return text.strip()
        except Exception as exc:
            logger.debug("BeautifulSoup extraction failed for %s: %s", url, exc)

        # ── Strategy 3: plain text from cleaned soup ──────────────────────
        try:
            soup = BeautifulSoup(html, "html.parser")
            soup = _clean_soup(soup)
            text = soup.get_text(separator="\n", strip=True)
            if len(text.strip()) >= self.MIN_TEXT_LEN:
                return text.strip()
        except Exception:
            pass

        # ── Strategy 4: LLM fallback (last resort, costs tokens) ──────────
        logger.debug("All deterministic extraction failed for %s — trying LLM", url)
        llm_text = await _llm_extract(html[:2000], url)
        if llm_text and len(llm_text.strip()) >= self.MIN_TEXT_LEN:
            return llm_text.strip()

        return None

    # ── Link extraction ──────────────────────────────────────────────────────

    def _extract_links(self, response, base_url: str) -> List[str]:
        """Extract all href links from the page using BeautifulSoup."""
        from bs4 import BeautifulSoup  # type: ignore
        hrefs = []
        try:
            raw = getattr(response, "body", b"") or b""
            html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if not html:
                html = getattr(response, "html_content", "") or getattr(response, "text", "") or ""
            soup = BeautifulSoup(html, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if href and not href.startswith(("javascript:", "mailto:", "#")):
                    hrefs.append(urljoin(base_url, href))
        except Exception as exc:
            logger.debug("Link extraction error for %s: %s", base_url, exc)
        return hrefs

    # ── PDF harvesting ────────────────────────────────────────────────────────

    async def _harvest_pdf_docs(self, pdf_urls: Set[str]) -> List[RawDocument]:
        from app.ingestion.pdf_connector import PDFConnector
        docs: List[RawDocument] = []
        for url in list(pdf_urls)[: self.max_pdfs]:
            logger.info("Harvesting PDF: %s", url)
            try:
                connector = PDFConnector(source=url)
                pdf_docs = await connector.fetch()
                docs.extend(pdf_docs)
                logger.info("PDF harvested: %s — %d pages", url, len(pdf_docs))
            except Exception as exc:
                logger.warning("PDF harvest failed for %s: %s", url, exc)
            await asyncio.sleep(self._delay)
        return docs

    # ── XML harvesting ────────────────────────────────────────────────────────

    async def _harvest_xml_docs(self, xml_urls: Set[str]) -> List[RawDocument]:
        from app.ingestion.xml_connector import XMLConnector
        docs: List[RawDocument] = []
        for url in list(xml_urls)[: self.max_xmls]:
            logger.info("Harvesting XML: %s", url)
            try:
                connector = XMLConnector(source=url)
                xml_docs = await connector.fetch()
                docs.extend(xml_docs)
                logger.info("XML harvested: %s — %d sections", url, len(xml_docs))
            except Exception as exc:
                logger.warning("XML harvest failed for %s: %s", url, exc)
            await asyncio.sleep(self._delay)
        return docs

    # ── Main fetch loop ──────────────────────────────────────────────────────

    async def fetch(self) -> List[RawDocument]:
        """
        BFS crawl from seed_urls with concurrent fetching.
        Automatically harvests PDF and XML links found during crawl.
        Manages the lifecycle of the Crawl4AI browser.
        """
        await self._init_crawler()
        try:
            return await self._fetch_impl()
        finally:
            await self._close_crawler()

    async def _fetch_impl(self) -> List[RawDocument]:
        html_documents: List[RawDocument] = []
        seen_hashes: Set[str] = set()
        pdf_urls: Set[str] = set()
        xml_urls: Set[str] = set()

        logger.info(
            "WebConnector starting: domain=%s seeds=%d max_pages=%d",
            self.allowed_domain, len(self.seed_urls), self.max_pages,
        )
        self._emit_progress(
            "crawl_started",
            domain=self.allowed_domain,
            seeds=list(self.seed_urls),
            max_pages=self.max_pages,
        )

        # ── Try Crawl4AI BestFirstCrawlingStrategy ────────────────────────────
        # Ranks discovered URLs by regulatory keyword relevance so the most
        # important pages are visited first within the max_pages budget.
        # Falls back to manual BFS if Crawl4AI deep-crawl API is unavailable.
        crawl4ai_results = []
        try:
            from crawl4ai.deep_crawling import BestFirstCrawlingStrategy  # type: ignore
            from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer  # type: ignore
            from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter  # type: ignore

            scorer = KeywordRelevanceScorer(
                keywords=REGULATORY_KEYWORDS,
                weight=0.7,
            )
            # Include only URLs that look like actual content pages.
            # This is an inclusion filter — complements _is_skippable_url
            # exclusions that run at link-discovery time.
            url_filter = URLPatternFilter(patterns=[
                "*regulation*", "*rule*", "*ruling*", "*guidance*",
                "*notice*", "*directive*", "*compliance*", "*enforcement*",
                "*tariff*", "*customs*", "*import*", "*export*",
                "*trade*", "*sanction*", "*penalty*", "*obligation*",
                "*amendment*", "*document*", "*publication*",
                "*bulletin*", "*gazette*", "*register*",
                # generic patterns that catch most gov doc URLs
                "*/?id=*", "*/id/*", "*/doc/*", "*/docs/*",
                "*/page/*", "*/pages/*", "*/content/*",
                "*/news/*", "*/updates/*", "*/announcement*",
                "*/legal/*", "*/law/*", "*/legislation/*",
            ])
            filter_chain = FilterChain([url_filter])

            strategy = BestFirstCrawlingStrategy(
                max_depth=self.max_depth,
                max_pages=self.max_pages,
                include_external=False,
                url_scorer=scorer,
                filter_chain=filter_chain,
            )

            await self._init_crawler()
            if self._crawler is not None:
                from crawl4ai import CrawlerRunConfig, CacheMode  # type: ignore

                excluded_tags = ["nav", "header", "footer", "aside", "form", "noscript"]
                excluded_selector = ", ".join([
                    '[role="navigation"]', '[role="banner"]',
                    '[role="contentinfo"]', '[role="search"]',
                    ".navigation", ".site-header", ".site-footer",
                    ".breadcrumb", ".breadcrumbs", ".cookie-banner",
                    ".usa-banner", ".skip-link",
                ])

                run_cfg = CrawlerRunConfig(
                    deep_crawl_strategy=strategy,
                    cache_mode=CacheMode.BYPASS,
                    page_timeout=30_000,
                    wait_until="networkidle",
                    excluded_tags=excluded_tags,
                    excluded_selector=excluded_selector,
                    word_count_threshold=10,
                    exclude_external_images=True,
                )

                results = await self._crawler.arun(
                    url=self.seed_urls[0],
                    config=run_cfg,
                )
                crawl4ai_results = results if isinstance(results, list) else [results]
                logger.info(
                    "BestFirst crawl done: domain=%s pages=%d",
                    self.allowed_domain, len(crawl4ai_results),
                )
                self._emit_progress(
                    "bestfirst_done",
                    pages_returned=len(crawl4ai_results),
                )

        except (ImportError, AttributeError) as exc:
            logger.warning(
                "BestFirstCrawlingStrategy unavailable (%s) — falling back to BFS",
                exc,
            )
            crawl4ai_results = []

        # ── Process BestFirst results ─────────────────────────────────────────
        if crawl4ai_results:
            for result in crawl4ai_results:
                if not getattr(result, "success", False):
                    continue

                url = getattr(result, "url", "") or ""
                if not url or _is_skippable_url(url):
                    continue
                if not is_same_domain(url, self.allowed_domain):
                    continue
                if self.allowed_path_prefix:
                    if not urlparse(url).path.startswith(self.allowed_path_prefix):
                        continue

                markdown = self._crawl4ai_markdown(result)
                raw_text = _clean_markdown(markdown) if markdown else None
                if not raw_text or len(raw_text) < self.MIN_TEXT_LEN:
                    continue

                # Extract title
                title = url
                try:
                    from bs4 import BeautifulSoup  # type: ignore
                    html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
                    if html:
                        soup = BeautifulSoup(html, "html.parser")
                        t = soup.find("title")
                        if t and t.string:
                            title = t.string.strip()
                except Exception:
                    pass

                # Blocker detection
                blocker_reason = _is_blocker_page(raw_text, title)
                if blocker_reason:
                    logger.warning(
                        "blocker page skipped: reason=%s title=%r url=%s",
                        blocker_reason, title[:80], url,
                    )
                    _record_block(url, blocker_reason)
                    continue

                # Harvest PDF/XML links from the page
                html_body = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
                if html_body:
                    fake_response = self._HttpxResponse(
                        body=html_body.encode("utf-8", errors="replace"),
                        status_code=200,
                        headers={},
                    )
                    for href in self._extract_links(fake_response, url):
                        norm_href = normalize_url(href, base_url=url)
                        if not norm_href:
                            continue
                        if self.harvest_pdfs and _is_pdf_url(norm_href):
                            pdf_urls.add(norm_href)
                        elif self.harvest_xml and _is_xml_url(norm_href):
                            xml_urls.add(norm_href)

                normalized = _normalize_for_hash(raw_text)
                content_hash = _sha256(normalized)
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
                now = _utcnow()
                html_documents.append(
                    RawDocument(
                        id=uuid4(),
                        source_url=url,
                        source_type="web",
                        raw_text=raw_text,
                        title=title,
                        language=_detect_language(normalized),
                        content_hash=content_hash,
                        fetched_at=now,
                        last_seen_at=now,
                    )
                )
                self._emit_progress(
                    "page_indexed",
                    url=url,
                    title=title[:120] if title else None,
                    current=len(html_documents),
                    max=self.max_pages,
                )

        # ── Fallback: manual BFS (when BestFirst unavailable) ─────────────────
        else:
            visited_urls: Set[str] = set()
            queue: deque[tuple[str, int]] = deque()
            for raw_url in self.seed_urls:
                norm = normalize_url(raw_url)
                if norm and norm not in visited_urls:
                    queue.append((norm, 0))
                    visited_urls.add(norm)

            while queue and len(html_documents) < self.max_pages:
                batch: List[tuple[str, int]] = []
                while (
                    queue
                    and len(batch) < self.MAX_CONCURRENT
                    and len(html_documents) + len(batch) < self.max_pages
                ):
                    url, depth = queue.popleft()
                    if not await self._is_allowed(url):
                        continue
                    batch.append((url, depth))

                if not batch:
                    break

                fetch_tasks = [self._fetch_page(url) for url, _ in batch]
                responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                for (url, depth), response in zip(batch, responses):
                    if isinstance(response, Exception) or response is None:
                        continue
                    status = getattr(response, "status_code", 0) or 0
                    if status >= 400:
                        continue

                    raw_text = await self._extract_text(response, url)
                    if not raw_text:
                        continue

                    title = url
                    try:
                        from bs4 import BeautifulSoup  # type: ignore
                        raw = getattr(response, "body", b"") or b""
                        page_html = raw.decode("utf-8", errors="replace")
                        soup = BeautifulSoup(page_html, "html.parser")
                        t = soup.find("title")
                        if t and t.string:
                            title = t.string.strip()
                    except Exception:
                        pass

                    blocker_reason = _is_blocker_page(raw_text, title)
                    if blocker_reason:
                        logger.warning(
                            "blocker page skipped: reason=%s title=%r url=%s",
                            blocker_reason, title[:80], url,
                        )
                        _record_block(url, blocker_reason)
                    else:
                        normalized = _normalize_for_hash(raw_text)
                        content_hash = _sha256(normalized)
                        if content_hash not in seen_hashes:
                            seen_hashes.add(content_hash)
                            now = _utcnow()
                            html_documents.append(
                                RawDocument(
                                    id=uuid4(),
                                    source_url=url,
                                    source_type="web",
                                    raw_text=raw_text,
                                    title=title,
                                    language=_detect_language(normalized),
                                    content_hash=content_hash,
                                    fetched_at=now,
                                    last_seen_at=now,
                                )
                            )
                            self._emit_progress(
                                "page_indexed",
                                url=url,
                                title=title[:120] if title else None,
                                current=len(html_documents),
                                max=self.max_pages,
                            )

                    if depth < self.max_depth:
                        for href in self._extract_links(response, url):
                            norm_href = normalize_url(href, base_url=url)
                            if not norm_href or _is_skippable_url(norm_href):
                                continue
                            if self.harvest_pdfs and _is_pdf_url(norm_href):
                                pdf_urls.add(norm_href)
                                continue
                            if self.harvest_xml and _is_xml_url(norm_href):
                                xml_urls.add(norm_href)
                                continue
                            if norm_href in visited_urls:
                                continue
                            if not is_same_domain(norm_href, self.allowed_domain):
                                continue
                            if self.allowed_path_prefix:
                                if not urlparse(norm_href).path.startswith(
                                    self.allowed_path_prefix
                                ):
                                    continue
                            if is_spider_trap(norm_href):
                                continue
                            visited_urls.add(norm_href)
                            queue.append((norm_href, depth + 1))

        logger.info(
            "WebConnector crawl done: domain=%s html=%d pdf_links=%d xml_links=%d",
            self.allowed_domain, len(html_documents),
            len(pdf_urls), len(xml_urls),
        )

        # ── Harvest PDFs ──────────────────────────────────────────────
        pdf_documents: List[RawDocument] = []
        if self.harvest_pdfs and pdf_urls:
            logger.info(
                "Harvesting %d PDF files (max %d)...",
                len(pdf_urls), self.max_pdfs,
            )
            self._emit_progress(
                "pdf_phase",
                count=len(pdf_urls),
                max=self.max_pdfs,
            )
            pdf_documents = await self._harvest_pdf_docs(pdf_urls)

        # ── Harvest XMLs ──────────────────────────────────────────────
        xml_documents: List[RawDocument] = []
        if self.harvest_xml and xml_urls:
            logger.info(
                "Harvesting %d XML files (max %d)...",
                len(xml_urls), self.max_xmls,
            )
            self._emit_progress(
                "xml_phase",
                count=len(xml_urls),
                max=self.max_xmls,
            )
            xml_documents = await self._harvest_xml_docs(xml_urls)

        all_docs = html_documents + pdf_documents + xml_documents
        logger.info(
            "WebConnector finished: domain=%s html=%d pdf=%d xml=%d total=%d",
            self.allowed_domain, len(html_documents),
            len(pdf_documents), len(xml_documents), len(all_docs),
        )
        self._emit_progress(
            "connector_done",
            html=len(html_documents),
            pdf=len(pdf_documents),
            xml=len(xml_documents),
            total=len(all_docs),
        )
        return all_docs
