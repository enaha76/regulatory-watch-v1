from app.celery_app import web_crawl_task

r = web_crawl_task.delay(
    seed_urls=["https://www.gov.cn/"],
    allowed_domain="www.gov.cn",
    max_pages=10,
    max_depth=2,
    rate_limit_rps=0.5,
)
print("Result:", r.get(timeout=600))

