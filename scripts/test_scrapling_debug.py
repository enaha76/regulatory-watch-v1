from scrapling.fetchers import StealthyFetcher

fetcher = StealthyFetcher()
response = fetcher.fetch("https://www.cbp.gov/trade")

print("Type:", type(response))
print("Dir:", [a for a in dir(response) if not a.startswith("_")])
print()

# Check common attribute names for HTML content
for attr in ["text", "html", "content", "body", "source", "page_source", "raw", "data"]:
    val = getattr(response, attr, "NOT_FOUND")
    if val != "NOT_FOUND":
        if callable(val):
            print(f"  {attr}(): callable")
        elif isinstance(val, str):
            print(f"  {attr}: str, len={len(val)}, preview={val[:100]}")
        elif isinstance(val, bytes):
            print(f"  {attr}: bytes, len={len(val)}")
        else:
            print(f"  {attr}: {type(val).__name__}")

print()
print("Status:", getattr(response, "status", getattr(response, "status_code", "NOT_FOUND")))

