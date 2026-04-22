import asyncio
import logging

from app.ingestion.web_connector import WebConnector

logging.basicConfig(level=logging.DEBUG)


async def main():
    connector = WebConnector(
        seed_urls=["https://eur-lex.europa.eu/latest-laws/"],
        allowed_domain="eur-lex.europa.eu",
        max_pages=3,
        rate_limit_rps=0.5,
    )
    docs = await connector.fetch()
    print(f"\nDocs collected: {len(docs)}")
    for d in docs:
        print(f"  - {d.title[:60]} | {len(d.raw_text)} chars")


asyncio.run(main())

