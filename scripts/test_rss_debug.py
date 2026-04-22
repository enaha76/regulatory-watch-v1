import feedparser
import urllib.request

# Follow redirects manually to see final URL
urls = [
    "https://www.federalregister.gov/documents/search.rss",
    "https://www.federalregister.gov/api/v1/documents.rss",
    "https://www.govinfo.gov/rss/fr.xml",
]

for url in urls:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final_url = resp.url
            print(f"\nURL: {url}")
            print(f"  final URL: {final_url}")
            print(f"  status: {resp.status}")
    except Exception as e:
        print(f"\nURL: {url}  ERROR: {e}")

# Test govinfo
feed = feedparser.parse("https://www.govinfo.gov/rss/fr.xml")
print(f"\ngovinfo FR RSS entries: {len(feed.entries)}, bozo: {feed.bozo}")
if feed.entries:
    print(f"  first: {feed.entries[0].get('title','')[:80]}")

