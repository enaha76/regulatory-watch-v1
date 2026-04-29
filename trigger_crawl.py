from app.celery_app import web_crawl_task

result = web_crawl_task.delay(
    seed_urls=["http://mock-website:3001/"],
    allowed_domain="mock-website",
    max_pages=50,
    max_depth=4,
    rate_limit_rps=5.0,
    max_pdfs=10,
)

print(f"Task queued: {result.id}")
