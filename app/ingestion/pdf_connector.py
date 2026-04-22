"""
T2.3 — PDFConnector

Layout-aware PDF extraction using pdfplumber (primary).
Docling (IBM) is used when installed for richer table detection;
pdfplumber is the reliable fallback that handles most regulatory PDFs.

Features:
  - Downloads PDFs from a URL or reads from a local file path
  - Extracts plain text + tables per page
  - Tables are rendered as comma-delimited rows (each cell on its own line)
    so they pass TEST-2.2 (cells not merged into a single text run)
  - Emits ONE RawDocument per file — concatenated text plus per-page
    character offsets stored in `pages` (list of {n, start, end}) so a
    single document can still be sliced page-by-page downstream.
  - SHA-256 deduplication on the concatenated text.
"""

import hashlib
import io
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import httpx

from app.ingestion.base import IngestorBase
from app.ingestion.http_utils import httpx_verify
from app.models import RawDocument

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _detect_language(text: str) -> Optional[str]:
    """Shared CJK-aware language detection (see app.ingestion.lang)."""
    from app.ingestion.lang import detect as _shared_detect
    return _shared_detect(text)


# ── Table rendering ───────────────────────────────────────────────────────────

def _table_to_text(table: list) -> str:
    """
    Convert a pdfplumber table (list of rows, each row a list of cell strings)
    into readable text where every cell appears on its own line.

    Pass condition for TEST-2.2: cells are NOT merged into a single run of text.
    """
    lines = []
    for row in table:
        if row:
            # Filter None cells, strip whitespace
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(", ".join(cells))
    return "\n".join(lines)


# ── Docling (optional) ────────────────────────────────────────────────────────

def _extract_with_docling(pdf_bytes: bytes, source_url: str) -> Optional[List[str]]:
    """
    Try IBM Docling for layout-aware extraction.

    Returns a list of *per-page* markdown strings, or None if Docling is
    not installed or extraction fails. Per-page output matters so the
    outer connector can keep character offsets aligned to physical pages
    (same contract as pdfplumber).

    To enable: `pip install docling>=2.0` (adds ~1GB of Torch + models).
    Docling is an optional extra — the connector transparently falls
    back to pdfplumber when it isn't installed.
    """
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except ImportError:
        return None

    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        doc = result.document

        # Docling ≥ 2.x exposes `pages` on the DoclingDocument. Export each
        # page individually so we preserve page boundaries. Fallback to
        # a single-chunk markdown dump if the page API isn't available.
        per_page: List[str] = []
        pages = getattr(doc, "pages", None)
        if pages:
            # `pages` is a dict keyed by page_no (1-based) in Docling ≥ 2.x
            page_items = pages.items() if hasattr(pages, "items") else enumerate(pages, start=1)
            for page_no, _page in sorted(page_items, key=lambda x: x[0]):
                try:
                    text = doc.export_to_markdown(page_no=page_no)  # type: ignore[arg-type]
                except TypeError:
                    text = ""
                if text and text.strip():
                    per_page.append(text)
            if per_page:
                return per_page

        full_text = doc.export_to_markdown()
        return [full_text] if full_text and full_text.strip() else None

    except Exception as exc:
        logger.warning("Docling extraction failed for %s: %s", source_url, exc)
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── pdfplumber extraction ─────────────────────────────────────────────────────

def _extract_with_pdfplumber(pdf_bytes: bytes) -> List[str]:
    """
    Extract text + tables from each page using pdfplumber.
    Returns one string per page.
    """
    import pdfplumber  # type: ignore

    page_texts: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            parts: List[str] = []

            # Plain text (non-table regions)
            plain = page.extract_text(x_tolerance=3, y_tolerance=3)
            if plain:
                parts.append(plain.strip())

            # Tables — rendered as comma-delimited rows
            tables = page.extract_tables()
            for table in tables:
                table_text = _table_to_text(table)
                if table_text:
                    parts.append("--- TABLE ---")
                    parts.append(table_text)
                    parts.append("--- END TABLE ---")

            if parts:
                page_texts.append("\n".join(parts))

    return page_texts


# ── PDFConnector ──────────────────────────────────────────────────────────────

class PDFConnector(IngestorBase):
    """
    Extracts text and tables from a PDF document.

    Parameters
    ----------
    source : str
        HTTP/HTTPS URL or local file path to the PDF.
    title : str, optional
        Human-readable title for the document.  If omitted, the URL/filename is used.
    """

    def __init__(self, source: str, title: Optional[str] = None) -> None:
        self.source = source
        self.title = title or source

    async def _get_pdf_bytes(self) -> bytes:
        """Download PDF from URL or read from local path."""
        if self.source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(
                timeout=60,
                follow_redirects=True,
                verify=httpx_verify(self.source),
                headers={"User-Agent": "RegulatoryWatch/1.0"},
            ) as client:
                resp = await client.get(self.source)
                resp.raise_for_status()
                return resp.content
        else:
            return Path(self.source).read_bytes()

    # Marker inserted between pages in the concatenated raw_text.
    # Kept stable + machine-parseable so downstream diff tools can detect
    # per-page changes without needing the `pages` JSON.
    PAGE_SEPARATOR = "\n\n[[PAGE {n}]]\n\n"
    MIN_PAGE_CHARS = 50  # pages below this are dropped (blank/scan artefacts)

    async def fetch(self) -> List[RawDocument]:
        """
        Download and extract the PDF. Returns a single RawDocument whose
        `raw_text` is the concatenation of all usable pages separated by
        `[[PAGE n]]` markers, and whose `pages` JSON lists the character
        offsets of each page in the concatenated text.
        """
        logger.info("PDFConnector fetching: %s", self.source)

        try:
            pdf_bytes = await self._get_pdf_bytes()
        except Exception as exc:
            logger.error("Failed to fetch PDF from %s: %s", self.source, exc)
            return []

        # Try Docling first (richer layout understanding), fall back to pdfplumber
        page_texts = _extract_with_docling(pdf_bytes, self.source)
        extractor = "docling"
        if not page_texts:
            try:
                page_texts = _extract_with_pdfplumber(pdf_bytes)
                extractor = "pdfplumber"
            except Exception as exc:
                logger.error("pdfplumber extraction failed for %s: %s", self.source, exc)
                return []

        logger.info(
            "PDFConnector extracted %d pages from %s using %s",
            len(page_texts),
            self.source,
            extractor,
        )

        # ── Stitch pages into one document with offset tracking ───────────
        buf: List[str] = []
        pages_meta: List[dict] = []
        cursor = 0

        for page_num, text in enumerate(page_texts, start=1):
            text = (text or "").strip()
            if len(text) < self.MIN_PAGE_CHARS:
                logger.debug(
                    "Page %d too short (%d chars), skipping", page_num, len(text),
                )
                continue

            separator = self.PAGE_SEPARATOR.format(n=page_num)
            # Only prepend the separator between pages, not before the first.
            prefix = separator if buf else f"[[PAGE {page_num}]]\n\n"
            segment = prefix + text
            start = cursor + len(prefix)  # start of real page content
            end = cursor + len(segment)
            pages_meta.append({"n": page_num, "start": start, "end": end})

            buf.append(segment)
            cursor = end

        if not pages_meta:
            logger.info(
                "PDFConnector done: source=%s pages_kept=0 (all pages empty)",
                self.source,
            )
            return []

        raw_text = "".join(buf)
        content_hash = _sha256(raw_text)
        now = _utcnow()

        doc = RawDocument(
            id=uuid4(),
            source_url=self.source,
            source_type="pdf",
            raw_text=raw_text,
            title=self.title,
            language=_detect_language(raw_text),
            content_hash=content_hash,
            page_count=len(pages_meta),
            pages=pages_meta,
            fetched_at=now,
            last_seen_at=now,
        )

        logger.info(
            "PDFConnector done: source=%s pages_kept=%d total_chars=%d",
            self.source,
            len(pages_meta),
            len(raw_text),
        )
        return [doc]
