"""
Mock Regulatory Server — serves a full static website from /data/.

Serves any file under /data/ at the matching URL path:
  /index.html                        → /data/index.html
  /regulations/tariff-schedule.html  → /data/regulations/tariff-schedule.html
  /documents/tariff-schedule.pdf     → /data/documents/tariff-schedule.pdf

Also serves:
  /rss.xml  → /data/rss.xml  (static file, not auto-generated)

Internal Docker URL : http://mock-server:9000
Browser URL        : http://localhost:9000
"""

import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

DATA_DIR = Path("/data")
PORT = 9000

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript",
    ".pdf":  "application/pdf",
    ".xml":  "application/rss+xml; charset=utf-8",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}


class MockHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        raw_path = unquote(parsed.path)

        # Strip leading slash and resolve against DATA_DIR
        rel = raw_path.lstrip("/")

        # Default to index.html for directory paths
        if not rel or rel.endswith("/"):
            rel = rel + "index.html"

        filepath = DATA_DIR / rel

        # Security: prevent path traversal
        try:
            filepath.resolve().relative_to(DATA_DIR.resolve())
        except ValueError:
            self._respond(403, "text/plain", b"Forbidden")
            return

        if not filepath.exists():
            self._respond(404, "text/plain",
                          f"Not found: {raw_path}".encode())
            return

        if filepath.is_dir():
            filepath = filepath / "index.html"
            if not filepath.exists():
                self._respond(404, "text/plain", b"No index.html in directory")
                return

        suffix = filepath.suffix.lower()
        content_type = MIME_TYPES.get(suffix, "application/octet-stream")
        self._respond(200, content_type, filepath.read_bytes())

    def _respond(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[mock-server] {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"Mock Regulatory Server on port {PORT}", flush=True)
    print(f"  Home : http://localhost:{PORT}/", flush=True)
    print(f"  RSS  : http://localhost:{PORT}/rss.xml", flush=True)
    HTTPServer(("0.0.0.0", PORT), MockHandler).serve_forever()
