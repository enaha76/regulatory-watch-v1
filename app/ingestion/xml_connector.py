"""
T2.5 — XMLConnector

Parses structured regulatory XML using lxml + XPath.
Supports two major regulatory XML standards:

  USLM  (United States Legislative Markup)
    — used by the US Code, Federal Register, GPO documents
    — namespace: http://schemas.gpo.gov/xml/uslm

  Akoma Ntoso (AKN)
    — used by UN, EU Parliament, many national legislatures
    — namespace: http://docs.oasis-open.org/legaldocml/ns/akn/3.0

Each top-level section / article becomes one RawDocument.
Extracted fields: section title, body text, effective dates, definitions.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

import httpx
from lxml import etree  # type: ignore

from app.ingestion.base import IngestorBase
from app.ingestion.http_utils import httpx_verify
from app.models import RawDocument

logger = logging.getLogger(__name__)

# ── XML namespace maps ────────────────────────────────────────────────────────

USLM_NS = {"uslm": "http://schemas.gpo.gov/xml/uslm"}
AKN_NS = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _detect_language(text: str) -> Optional[str]:
    """Shared CJK-aware language detection (see app.ingestion.lang)."""
    from app.ingestion.lang import detect as _shared_detect
    return _shared_detect(text)


def _element_text(el) -> str:
    """Recursively collect all text inside an lxml element."""
    return " ".join(el.itertext()).strip()


def _detect_format(root) -> str:
    """Return 'uslm', 'akn', or 'generic' based on the root element namespace."""
    ns = root.nsmap.get(None) or root.nsmap.get("uslm") or ""
    tag = root.tag.lower()
    if "gpo.gov" in ns or "uslm" in tag:
        return "uslm"
    if "oasis-open.org/legaldocml" in ns or "akomaNtoso" in root.tag:
        return "akn"
    return "generic"


# ── Format-specific extractors ────────────────────────────────────────────────

def _extract_uslm_sections(root) -> List[dict]:
    """
    Extract sections from a USLM document.
    Returns list of dicts with keys: title, text, effective_date.
    """
    sections = []

    # Try with namespace prefix first, then without
    for xpath in (
        "//uslm:section",
        "//section",
        "//*[local-name()='section']",
    ):
        try:
            ns = USLM_NS if "uslm:" in xpath else {}
            nodes = root.xpath(xpath, namespaces=ns)
            if nodes:
                break
        except Exception:
            nodes = []

    for node in nodes:
        # Section heading
        heading_nodes = node.xpath(
            ".//*[local-name()='heading'] | .//*[local-name()='num']"
        )
        title = " ".join(
            h.text.strip() for h in heading_nodes if h.text
        ).strip() or "Section"

        text = _element_text(node)
        if len(text) < 30:
            continue

        # Effective date (often in <effectiveDate> or date attributes)
        eff_date = (
            node.get("effectiveDate")
            or node.get("startDate")
            or ""
        )

        sections.append({"title": title, "text": text, "effective_date": eff_date})

    return sections


def _extract_akn_sections(root) -> List[dict]:
    """
    Extract articles/sections from an Akoma Ntoso document.
    Returns list of dicts with keys: title, text, effective_date.
    """
    sections = []

    for xpath in (
        "//akn:section | //akn:article | //akn:chapter",
        "//*[local-name()='section'] | //*[local-name()='article']",
    ):
        try:
            ns = AKN_NS if "akn:" in xpath else {}
            nodes = root.xpath(xpath, namespaces=ns)
            if nodes:
                break
        except Exception:
            nodes = []

    for node in nodes:
        num_nodes = node.xpath(".//*[local-name()='num']")
        heading_nodes = node.xpath(".//*[local-name()='heading']")
        num = num_nodes[0].text.strip() if num_nodes and num_nodes[0].text else ""
        heading = heading_nodes[0].text.strip() if heading_nodes and heading_nodes[0].text else ""
        title = f"{num} {heading}".strip() or "Article"

        text = _element_text(node)
        if len(text) < 30:
            continue

        # FRBRdate gives effective/expression date in AKN
        date_nodes = root.xpath(
            ".//*[local-name()='FRBRdate']/@date",
        )
        eff_date = date_nodes[0] if date_nodes else ""

        sections.append({"title": title, "text": text, "effective_date": eff_date})

    return sections


def _extract_generic_sections(root) -> List[dict]:
    """
    Fallback: extract top-level elements that look like sections.
    """
    sections = []
    # grab direct children of root that have substantial text
    for child in root:
        text = _element_text(child)
        if len(text) < 50:
            continue
        tag = etree.QName(child.tag).localname
        title = child.get("title") or child.get("id") or tag
        sections.append({"title": title, "text": text, "effective_date": ""})
    return sections


# ── XMLConnector ──────────────────────────────────────────────────────────────

class XMLConnector(IngestorBase):
    """
    Parses USLM or Akoma Ntoso regulatory XML and returns one
    RawDocument per section/article.

    Parameters
    ----------
    source : str
        HTTP/HTTPS URL or local file path to the XML document.
    title : str, optional
        Human-readable title for the document.
    """

    def __init__(self, source: str, title: Optional[str] = None) -> None:
        self.source = source
        self.title = title or source

    async def _get_xml_bytes(self) -> bytes:
        if self.source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                verify=httpx_verify(self.source),
                headers={"User-Agent": "RegulatoryWatch/1.0"},
            ) as client:
                resp = await client.get(self.source)
                resp.raise_for_status()
                return resp.content
        else:
            from pathlib import Path
            return Path(self.source).read_bytes()

    async def fetch(self) -> List[RawDocument]:
        logger.info("XMLConnector fetching: %s", self.source)

        try:
            xml_bytes = await self._get_xml_bytes()
        except Exception as exc:
            logger.error("Failed to fetch XML from %s: %s", self.source, exc)
            return []

        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            logger.error("XML parse error for %s: %s", self.source, exc)
            return []

        fmt = _detect_format(root)
        logger.info("XMLConnector detected format=%s for %s", fmt, self.source)

        if fmt == "uslm":
            sections = _extract_uslm_sections(root)
        elif fmt == "akn":
            sections = _extract_akn_sections(root)
        else:
            sections = _extract_generic_sections(root)

        documents: List[RawDocument] = []
        seen_hashes: set[str] = set()
        now = _utcnow()

        for sec in sections:
            text = sec["text"].strip()
            content_hash = _sha256(text)
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            eff = f" (effective: {sec['effective_date']})" if sec["effective_date"] else ""
            section_title = f"{self.title} — {sec['title']}{eff}"

            documents.append(
                RawDocument(
                    id=uuid4(),
                    source_url=self.source,
                    source_type="xml",
                    raw_text=text,
                    title=section_title,
                    language=_detect_language(text),
                    content_hash=content_hash,
                    fetched_at=now,
                    last_seen_at=now,
                )
            )

        logger.info(
            "XMLConnector done: source=%s format=%s sections=%d",
            self.source,
            fmt,
            len(documents),
        )
        return documents
