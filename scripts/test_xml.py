from app.celery_app import xml_ingest_task

# Test with a public Akoma Ntoso / generic XML regulatory document
r = xml_ingest_task.delay(
    source="https://www.govinfo.gov/content/pkg/BILLS-119hr1enr/xml/BILLS-119hr1enr.xml",
    title="US House Bill 119 HR1",
)
print("XML:", r.get(timeout=60))

