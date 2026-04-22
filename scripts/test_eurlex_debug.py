import asyncio

# NOTE: This script uses crawl4ai which is not listed in requirements.txt.
# Keep it here for experimentation only.
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


async def test():
    config = BrowserConfig(headless=True, verbose=False)
    async with AsyncWebCrawler(config=config) as crawler:
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=60000,
            delay_before_return_html=5.0,
        )
        result = await crawler.arun("https://eur-lex.europa.eu/latest-laws/", config=run_cfg)
        print("Success:", result.success)
        print("Status:", getattr(result, "status_code", "N/A"))
        md = result.markdown
        if hasattr(md, "raw_markdown"):
            md = md.raw_markdown
        print("Markdown length:", len(md or ""))
        print("Preview:", (md or "")[:500])
        print("Internal links:", len(result.links.get("internal", [])))
        print("HTML length:", len(result.html or ""))


asyncio.run(test())

