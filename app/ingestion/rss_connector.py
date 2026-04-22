"""
T2.4 — RSSConnector

Polls RSS 0.9–2.0, Atom, and RDF feeds using feedparser.
Extracts: title, published date, summary, and source link.
Each feed entry becomes one RawDocument with source_type="rss".

Scheduled every 30 minutes via Celery Beat (T2.10).
"""

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from uuid import uuid4

from app.ingestion.base import IngestorBase
from app.models import RawDocument

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _parse_date(entry) -> Optional[datetime]:
    """Extract a UTC datetime from a feedparser entry."""
    # feedparser provides parsed tuples in published_parsed / updated_parsed
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                import calendar
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except Exception:
                pass
    # Fallback: raw string fields
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def _detect_language(text: str) -> Optional[str]:
    """Shared CJK-aware language detection (see app.ingestion.lang)."""
    from app.ingestion.lang import detect as _shared_detect
    return _shared_detect(text)


class RSSConnector(IngestorBase):
    """
    Polls a single RSS/Atom/RDF feed and returns each entry as a RawDocument.

    Parameters
    ----------
    feed_url : str
        Full URL of the RSS/Atom feed.
    max_entries : int
        Maximum number of entries to process per poll cycle.
    """

    def __init__(self, feed_url: str, max_entries: int = 100) -> None:
        self.feed_url = feed_url
        self.max_entries = max_entries

    async def fetch(self) -> List[RawDocument]:
        """Parse the feed and return one RawDocument per entry."""
        try:
            import feedparser  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "feedparser is not installed. Run: pip install feedparser"
            ) from exc

        logger.info("RSSConnector polling: %s", self.feed_url)

        # feedparser.parse() is synchronous — run in thread to stay async-safe
        import asyncio
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, self.feed_url)

        if feed.bozo and not feed.entries:
            logger.warning(
                "RSSConnector: feed parse error for %s: %s",
                self.feed_url,
                feed.bozo_exception,
            )
            return []

        feed_title = getattr(feed.feed, "title", self.feed_url)
        logger.info(
            "RSSConnector: feed=%r entries=%d",
            feed_title,
            len(feed.entries),
        )

        documents: List[RawDocument] = []
        seen_hashes: set[str] = set()
        now = _utcnow()

        for entry in feed.entries[: self.max_entries]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "").strip()
            published = _parse_date(entry)

            # Build raw_text from all available fields
            parts = []
            if title:
                parts.append(f"Title: {title}")
            if published:
                parts.append(f"Published: {published.isoformat()}")
            if summary:
                parts.append(f"Summary: {summary}")
            if link:
                parts.append(f"Link: {link}")

            raw_text = "\n".join(parts)
            if len(raw_text.strip()) < 20:
                logger.debug("Skipping empty RSS entry: %s", title)
                continue

            # Stable identity key: prefer GUID (entry.id), then link, then content.
            # Using raw_text as the dedup key causes spurious inserts whenever the
            # feed's summary HTML shifts (tracking params, CDATA reformat, etc.).
            entry_key = (
                getattr(entry, "id", "")
                or getattr(entry, "guid", "")
                or link
            ).strip()
            if entry_key:
                content_hash = _sha256(f"{self.feed_url}||{entry_key}")
            else:
                content_hash = _sha256(raw_text)

            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            documents.append(
                RawDocument(
                    id=uuid4(),
                    source_url=link or self.feed_url,
                    source_type="rss",
                    raw_text=raw_text,
                    title=title or feed_title,
                    language=_detect_language(raw_text),
                    content_hash=content_hash,
                    fetched_at=now,
                    last_seen_at=now,
                )
            )

        logger.info(
            "RSSConnector done: feed=%s docs_collected=%d",
            self.feed_url,
            len(documents),
        )
        return documents
