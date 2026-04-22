"""
T2.6 — EmailConnector

Connects to an IMAP mailbox, reads unread emails, extracts:
  - Plain text / HTML body  → RawDocument (source_type="email")
  - PDF attachments         → handed off to PDFConnector

Configuration via environment variables (see app/config.py):
  IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD, IMAP_MAILBOX
"""

import email
import hashlib
import imaplib
import logging
from datetime import datetime, timezone
from email.header import decode_header
from typing import List, Optional
from uuid import uuid4

from app.ingestion.base import IngestorBase
from app.models import RawDocument

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _detect_language(text: str) -> Optional[str]:
    try:
        from langdetect import detect  # type: ignore
        return detect(text[:2000])
    except Exception:
        return None


def _decode_header_value(value: str) -> str:
    """Decode RFC 2047 encoded email header values."""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded).strip()


def _extract_body(msg: email.message.Message) -> str:
    """Extract the best available text body from a MIME message."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/html" and not body_parts:
                # Use HTML only if no plain text found
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    # Strip HTML tags with a simple regex
                    import re
                    body_parts.append(re.sub(r"<[^>]+>", " ", html))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body_parts.append(payload.decode(charset, errors="replace"))

    return "\n".join(body_parts).strip()


def _get_pdf_attachments(msg: email.message.Message) -> List[tuple[str, bytes]]:
    """Return list of (filename, bytes) for all PDF attachments."""
    pdfs = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            filename = part.get_filename() or ""
            if (
                "attachment" in disposition or content_type == "application/pdf"
            ) and filename.lower().endswith(".pdf"):
                payload = part.get_payload(decode=True)
                if payload:
                    pdfs.append((filename, payload))
    return pdfs


class EmailConnector(IngestorBase):
    """
    Reads unread emails from an IMAP mailbox.

    Parameters
    ----------
    host : str        IMAP server hostname
    port : int        IMAP port (993 for SSL, 143 for STARTTLS)
    user : str        Login username / email address
    password : str    Login password or app-specific password
    mailbox : str     Mailbox folder to read (default: INBOX)
    use_ssl : bool    Use IMAPS (SSL) connection (default: True)
    max_emails : int  Maximum number of unread emails to process
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str = "INBOX",
        use_ssl: bool = True,
        max_emails: int = 50,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.mailbox = mailbox
        self.use_ssl = use_ssl
        self.max_emails = max_emails

    def _connect(self) -> imaplib.IMAP4:
        if self.use_ssl:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
        else:
            conn = imaplib.IMAP4(self.host, self.port)
            conn.starttls()
        conn.login(self.user, self.password)
        return conn

    async def fetch(self) -> List[RawDocument]:
        """
        Fetch unread emails, extract bodies and PDF attachments.
        PDF attachments are processed via PDFConnector.
        """
        logger.info(
            "EmailConnector connecting: %s@%s/%s", self.user, self.host, self.mailbox
        )

        import asyncio

        # IMAP is synchronous — run in thread executor
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync)

    def _fetch_sync(self) -> List[RawDocument]:
        documents: List[RawDocument] = []
        seen_hashes: set[str] = set()
        now = _utcnow()

        try:
            conn = self._connect()
        except Exception as exc:
            logger.error("IMAP connection failed (%s@%s): %s", self.user, self.host, exc)
            return []

        try:
            conn.select(self.mailbox)
            # Search for UNSEEN (unread) messages
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                logger.warning("IMAP SEARCH failed: %s", status)
                return []

            msg_ids = data[0].split()
            logger.info(
                "EmailConnector: %d unread messages in %s", len(msg_ids), self.mailbox
            )

            for msg_id in msg_ids[: self.max_emails]:
                try:
                    status, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not msg_data:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                    sender = _decode_header_value(msg.get("From", ""))
                    date_str = msg.get("Date", "")
                    source_url = f"email://{self.host}/{self.mailbox}/{msg_id.decode()}"

                    # ── Email body ────────────────────────────────────────
                    body = _extract_body(msg)
                    if body and len(body) >= 50:
                        raw_text = (
                            f"Subject: {subject}\n"
                            f"From: {sender}\n"
                            f"Date: {date_str}\n\n"
                            f"{body}"
                        )
                        content_hash = _sha256(raw_text)
                        if content_hash not in seen_hashes:
                            seen_hashes.add(content_hash)
                            documents.append(
                                RawDocument(
                                    id=uuid4(),
                                    source_url=source_url,
                                    source_type="email",
                                    raw_text=raw_text,
                                    title=subject,
                                    language=_detect_language(body),
                                    content_hash=content_hash,
                                    fetched_at=now,
                                    last_seen_at=now,
                                )
                            )

                    # ── PDF attachments → PDFConnector ────────────────────
                    pdf_attachments = _get_pdf_attachments(msg)
                    for filename, pdf_bytes in pdf_attachments:
                        logger.info(
                            "EmailConnector: processing PDF attachment %s from %s",
                            filename,
                            subject,
                        )
                        documents.extend(
                            self._process_pdf_attachment(
                                pdf_bytes, filename, source_url, now, seen_hashes
                            )
                        )

                except Exception as exc:
                    logger.warning("Error processing email %s: %s", msg_id, exc)
                    continue

        finally:
            try:
                conn.logout()
            except Exception:
                pass

        logger.info(
            "EmailConnector done: host=%s docs_collected=%d",
            self.host,
            len(documents),
        )
        return documents

    @staticmethod
    def _process_pdf_attachment(
        pdf_bytes: bytes,
        filename: str,
        email_source_url: str,
        now: datetime,
        seen_hashes: set,
    ) -> List[RawDocument]:
        """Process a PDF attachment using pdfplumber and return RawDocuments."""
        from app.ingestion.pdf_connector import _extract_with_pdfplumber, _extract_with_docling

        page_texts = _extract_with_docling(pdf_bytes, filename) or _extract_with_pdfplumber(pdf_bytes)
        docs = []
        for page_num, text in enumerate(page_texts, start=1):
            text = text.strip()
            if len(text) < 50:
                continue
            content_hash = _sha256(text)
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            docs.append(
                RawDocument(
                    id=uuid4(),
                    source_url=f"{email_source_url}/attachment/{filename}",
                    source_type="pdf",
                    raw_text=text,
                    title=f"{filename} — page {page_num}",
                    language=_detect_language(text),
                    content_hash=content_hash,
                    fetched_at=now,
                    last_seen_at=now,
                )
            )
        return docs
