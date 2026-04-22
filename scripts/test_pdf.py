from app.celery_app import pdf_ingest_task

r = pdf_ingest_task.delay(
    source="https://www.irs.gov/pub/irs-pdf/f1040.pdf",
    title="IRS Form 1040 Test",
)
print("PDF:", r.get(timeout=120))

