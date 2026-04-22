from app.celery_app import rss_ingest_task

# Test govinfo Federal Register RSS
r = rss_ingest_task.delay(feed_url="https://www.govinfo.gov/rss/fr.xml")
print("Federal Register (govinfo):", r.get(timeout=60))

# Test FCA RSS
r2 = rss_ingest_task.delay(feed_url="https://www.fca.org.uk/news/rss.xml")
print("FCA:", r2.get(timeout=60))

