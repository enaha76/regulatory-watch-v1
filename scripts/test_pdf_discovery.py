"""
Debug: how many PDF links are discovered on CBP /trade pages
before the max_pdfs cap kicks in?
"""

import asyncio
import logging
from urllib.parse import urljoin, urlparse

logging.basicConfig(level=logging.INFO)


async def count_pdf_links():
    from bs4 import BeautifulSoup
    from scrapling.fetchers import StealthyFetcher

    seed = "https://www.cbp.gov/trade"
    fetcher = StealthyFetcher()

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, fetcher.fetch, seed)

    raw = getattr(response, "body", b"") or b""
    html = raw.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")
    all_links = [urljoin(seed, a["href"]) for a in soup.find_all("a", href=True)]

    pdf_links = [l for l in all_links if urlparse(l).path.lower().endswith(".pdf")]
    html_links = [l for l in all_links if not urlparse(l).path.lower().endswith(".pdf")]

    print(f"\nTotal links on seed page: {len(all_links)}")
    print(f"PDF links found: {len(pdf_links)}")
    print(f"HTML links found: {len(html_links)}")

    if pdf_links:
        print("\nSample PDF links (first 10):")
        for l in pdf_links[:10]:
            print(f"  {l}")


asyncio.run(count_pdf_links())

