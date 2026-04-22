from app.celery_app import web_crawl_task

r = web_crawl_task.delay(
    seed_urls=["https://eur-lex.europa.eu/latest-laws/"],
    allowed_domain="eur-lex.europa.eu",
    max_pages=10,
    rate_limit_rps=0.5,
)
print("Result:", r.get(timeout=300))

