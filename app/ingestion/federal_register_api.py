"""
Federal Register JSON API connector.

Replaces the BFS crawler for ``federalregister.gov`` with a direct
query against the government's public API. The API returns *only*
published regulatory documents (Rule / Proposed Rule / Notice /
Presidential Document) — zero careers pages, zero events, zero
about-us noise. This is Layer 1 of the "structured-feed-first"
ingestion strategy.

API reference: https://www.federalregister.gov/developers/api/v1
(Public, no authentication, no rate limit published but courtesy
1–2 rps applied here.)

What this connector does
------------------------
1. GET ``/api/v1/documents.json`` with filters:
     conditions[type][]=RULE
     conditions[type][]=PROPOSED_RULE
     conditions[publication_date][gte]=<days-back>
   → returns JSON index of matching documents (title, agencies,
     abstract, body_html_url, publication_date, effective_on).

2. For each result, fetch ``body_html_url`` to get the full
   rendered body HTML, strip it to plain text.

3. Build one ``RawDocument`` per document, with content_hash over
   the full text.

Cost profile
------------
1 index call + N body fetches, where N ≈ 100–300 daily US federal
rules. Compared to BFS crawling the same domain (~50 URLs per crawl,
mostly junk), this is strictly higher signal at roughly the same
HTTP budget.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

import httpx

from app.config import get_settings
from app.ingestion.base import IngestorBase
from app.models import RawDocument

logger = logging.getLogger(__name__)


# Document types the FR publishes. We ingest RULE + PROPOSED_RULE by
# default. NOTICE is non-regulatory (agency announcements,
# hearings) — skip unless the caller explicitly opts in.
# PRESIDENTIAL_DOCUMENT covers EOs / proclamations and is often
# operationally important, so include by default too.
_DEFAULT_DOC_TYPES: tuple[str, ...] = ("RULE", "PROPOSED_RULE", "PRESIDENTIAL_DOCUMENT")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _html_to_text(html: str) -> str:
    """Strip tags and normalize whitespace.

    The Federal Register's ``body_html_url`` returns clean semantic
    HTML (no ads, no navigation), so BeautifulSoup + ``.get_text``
    is sufficient. We do NOT reuse the heavier ``markdownify``
    pipeline from the web crawler because the FR markup is already
    clean and we want the raw text for M3/M4 without list-bullet
    prefixes.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # Drop script/style defensively.
    for tag in soup(("script", "style")):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines; preserve paragraph structure.
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln.strip():
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


class FederalRegisterAPIConnector(IngestorBase):
    """
    Pull new US Federal Register rules via the JSON API.

    Parameters
    ----------
    days_back
        How many days of publication history to fetch. Defaults to
        :attr:`Settings.FEDERAL_REGISTER_DAYS_BACK`.
    max_documents
        Upper bound per poll; capped by the API's per_page (1000).
    doc_types
        Which document types to fetch. Defaults to RULE + PROPOSED_RULE
        + PRESIDENTIAL_DOCUMENT.
    rate_limit_rps
        Politeness throttle for the body-fetch phase.
    """

    def __init__(
        self,
        *,
        days_back: Optional[int] = None,
        max_documents: Optional[int] = None,
        doc_types: Optional[tuple[str, ...]] = None,
        rate_limit_rps: Optional[float] = None,
    ) -> None:
        s = get_settings()
        self.days_back = days_back if days_back is not None else s.FEDERAL_REGISTER_DAYS_BACK
        self.max_documents = max_documents if max_documents is not None else s.FEDERAL_REGISTER_MAX_DOCS
        self.doc_types = doc_types or _DEFAULT_DOC_TYPES
        self.rate_limit_rps = rate_limit_rps if rate_limit_rps is not None else s.FEDERAL_REGISTER_RATE_LIMIT_RPS
        self.api_base = s.FEDERAL_REGISTER_API_BASE.rstrip("/")
        self.http_timeout = s.CRAWL_HTTP_TIMEOUT_SECONDS

    # ── Index phase ─────────────────────────────────────────────────

    async def _fetch_index(self, client: httpx.AsyncClient) -> list[dict]:
        """Return the metadata list from /documents.json."""
        gte = (date.today() - timedelta(days=self.days_back)).isoformat()
        params: list[tuple[str, str]] = [
            ("conditions[publication_date][gte]", gte),
            ("per_page", str(min(self.max_documents, 1000))),
            ("order", "newest"),
            # Explicit field list keeps the response small.
            ("fields[]", "document_number"),
            ("fields[]", "title"),
            ("fields[]", "abstract"),
            ("fields[]", "type"),
            ("fields[]", "agencies"),
            ("fields[]", "publication_date"),
            ("fields[]", "effective_on"),
            ("fields[]", "html_url"),
            ("fields[]", "body_html_url"),
        ]
        for dt in self.doc_types:
            params.append(("conditions[type][]", dt))

        url = f"{self.api_base}/documents.json"
        logger.info("FederalRegisterAPI: GET %s (types=%s, gte=%s)",
                    url, self.doc_types, gte)
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        body = resp.json()
        results = body.get("results") or []
        logger.info(
            "FederalRegisterAPI: index returned count=%s (results=%d, truncated=%s)",
            body.get("count"), len(results),
            body.get("count", 0) > len(results),
        )
        return results

    # ── Body phase ──────────────────────────────────────────────────

    async def _fetch_body(
        self,
        client: httpx.AsyncClient,
        body_html_url: str,
    ) -> Optional[str]:
        """Fetch + text-ify one document's body HTML. None on failure."""
        try:
            resp = await client.get(body_html_url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "FederalRegisterAPI body fetch failed: url=%s err=%s",
                body_html_url, exc,
            )
            return None
        try:
            return _html_to_text(resp.text)
        except Exception as exc:  # noqa: BLE001 — defensive: malformed HTML
            logger.warning(
                "FederalRegisterAPI body parse failed: url=%s err=%s",
                body_html_url, exc,
            )
            return None

    # ── Public API ──────────────────────────────────────────────────

    async def fetch(self) -> List[RawDocument]:
        documents: List[RawDocument] = []
        now = _utcnow()
        sleep_between = 1.0 / self.rate_limit_rps if self.rate_limit_rps > 0 else 0

        async with httpx.AsyncClient(timeout=self.http_timeout) as client:
            try:
                index = await self._fetch_index(client)
            except httpx.HTTPError as exc:
                logger.error("FederalRegisterAPI index fetch failed: %s", exc)
                return []

            for entry in index[: self.max_documents]:
                title = (entry.get("title") or "").strip()
                abstract = (entry.get("abstract") or "").strip()
                body_url = entry.get("body_html_url") or ""
                html_url = entry.get("html_url") or body_url
                pub_date = entry.get("publication_date") or ""
                doc_type = entry.get("type") or ""
                agencies = ", ".join(
                    a.get("raw_name", "") for a in (entry.get("agencies") or [])
                    if isinstance(a, dict)
                )
                effective = entry.get("effective_on") or ""

                # Fetch body text if we have a body URL; fall back to
                # abstract if the body fetch fails. A title-only doc
                # carries almost no downstream value, so we skip it.
                body_text = ""
                if body_url:
                    body_text = await self._fetch_body(client, body_url) or ""
                    if sleep_between:
                        await asyncio.sleep(sleep_between)

                # Assemble the RawDocument's raw_text with metadata
                # header — M3 benefits from seeing the title, type,
                # and effective date alongside the body.
                header_parts = [
                    f"Title: {title}" if title else "",
                    f"Type: {doc_type}" if doc_type else "",
                    f"Agencies: {agencies}" if agencies else "",
                    f"Published: {pub_date}" if pub_date else "",
                    f"Effective: {effective}" if effective else "",
                ]
                header = "\n".join(p for p in header_parts if p)
                abstract_block = f"\n\nAbstract:\n{abstract}" if abstract else ""
                body_block = f"\n\nBody:\n{body_text}" if body_text else ""
                raw_text = f"{header}{abstract_block}{body_block}".strip()

                if len(raw_text) < 80:
                    # Almost nothing to ingest — don't create an empty row.
                    logger.debug(
                        "FederalRegisterAPI: skipped near-empty doc %s",
                        entry.get("document_number"),
                    )
                    continue

                documents.append(
                    RawDocument(
                        id=uuid4(),
                        source_url=html_url,
                        source_type="web",  # HTML body, closest existing type
                        raw_text=raw_text,
                        title=title or entry.get("document_number"),
                        language="en",
                        content_hash=_sha256(raw_text),
                        fetched_at=now,
                        last_seen_at=now,
                    )
                )

        logger.info(
            "FederalRegisterAPI done: fetched_index=%d docs_built=%d",
            len(index), len(documents),
        )
        return documents
