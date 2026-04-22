from app.celery_app import web_crawl_task

# Keep PDF/XML harvest small so the task finishes well under Celery/client
# timeouts; full-site harvest belongs in scheduled jobs with higher limits.
r = web_crawl_task.delay(
    seed_urls=["https://www.dof.gob.mx/"],
    allowed_domain="www.dof.gob.mx",
    max_pages=10,
    max_depth=2,
    rate_limit_rps=0.5,
    max_pdfs=5,
    max_xmls=3,
)
print("Result:", r.get(timeout=3600))

