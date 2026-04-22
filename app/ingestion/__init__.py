"""
Ingestion layer — connectors that pull regulatory content from external sources.

Each connector extends IngestorBase and implements:
    async def fetch(self) -> List[RawDocument]

Available connectors:
  - WebConnector  : Playwright-based async web crawler (Crawl4AI)
  - PDFConnector  : Layout-aware PDF extraction (Docling / pdfplumber)  [T2.3]
  - RSSConnector  : feedparser RSS/Atom polling                         [T2.4]
  - XMLConnector  : lxml XPath for USLM / Akoma Ntoso XML               [T2.5]
  - EmailConnector: IMAP + MIME parser                                   [T2.6]
"""
