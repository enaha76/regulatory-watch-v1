FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/app \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /opt/app

# System libraries required by Playwright/Chromium inside a slim container
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium runtime dependencies
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgtk-3-0 libx11-xcb1 libxcb-dri3-0 \
    # General utilities
    wget ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching — rebuilt only when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium for Crawl4AI (the primary web crawler engine).
# Scrapling's Camoufox browser is intentionally NOT installed — scrapling
# is imported by scripts only and its browser engine is unused in production.
RUN playwright install chromium --with-deps || true

# Copy application code
COPY . .

# Default: run the API server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
