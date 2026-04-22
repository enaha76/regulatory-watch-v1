"""
Application configuration via environment variables.

Single source of truth for ALL tunable knobs (LLM budgets, crawl rate
limits, content size caps, gating thresholds, DB pool sizing).

Layered precedence (highest priority wins):

  1. Real environment variables (set by Docker, Kubernetes, systemd, …)
  2. ``.env`` file in the project root (dev only — DO NOT commit)
  3. The defaults declared in this file (production-safe baselines)

Secrets policy
--------------
Sensitive fields (`OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`,
`IMAP_PASSWORD`) MUST be supplied via env vars in production. The
``.env`` mechanism is a developer convenience only; production
deployments should mount secrets from Vault / AWS Secrets Manager /
Kubernetes Secrets so they never sit on disk in plaintext.

The settings file deliberately does NOT log or echo secret fields, and
``__repr__`` of a Settings instance redacts them via Pydantic's
``SecretStr`` where used.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is loaded from environment variables."""

    # ── Application ──────────────────────────────────────
    APP_NAME: str = "Regulatory Watch"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    # 'dev' | 'staging' | 'prod' — used for log routing + safety guards.
    APP_ENV: str = "dev"

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "postgresql://regwatch:regwatch_secret@db:5432/regwatch"
    # Pool sizing. Defaults sized for: 1 API + N Celery workers (~4)
    # + occasional CLI scripts. Total open connections ≤
    # (pool_size + max_overflow) * processes. Tune up for prod.
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60,
                                 description="Recycle connections every N seconds")
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1,
                                 description="Seconds to wait for a free connection before raising")
    # Set true ONLY in dev/test to allow SQLModel.create_all() at API
    # startup. In every real deployment Alembic is the only schema writer.
    DEV_AUTOCREATE_TABLES: bool = False

    # ── Redis ────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Kafka ────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:29092"

    # ── LLM (OpenAI) ─────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"  # cheap + fast
    # HTTP timeout for LLM round-trips (seconds).
    LLM_TIMEOUT: int = Field(default=30, ge=5)
    # Per-event prompt budgets (in chars, not tokens — cheaper to bound).
    # Total content < (HEAD + TAIL); diff <= MAX_DIFF_CHARS.
    LLM_MAX_DIFF_CHARS: int = Field(default=6000, ge=500)
    LLM_MAX_CONTENT_HEAD: int = Field(default=4500, ge=500)
    LLM_MAX_CONTENT_TAIL: int = Field(default=1500, ge=200)
    # Max output tokens per call — guards against runaway summaries.
    LLM_SCORING_MAX_TOKENS: int = Field(default=600, ge=100)
    LLM_OBLIGATIONS_MAX_TOKENS: int = Field(default=1200, ge=200)
    # Truncated-response logging on parse failure (keeps PII bounded).
    LLM_ERROR_LOG_RESPONSE_CHARS: int = Field(default=1000, ge=100, le=5000)

    # ── LLM cost & usage accounting ──────────────────────
    # USD per 1M tokens. Defaults = gpt-4o-mini public list price at
    # time of writing ($0.15 in / $0.60 out). Override via env per
    # model/account (negotiated rates, Azure, etc.).
    LLM_PRICE_INPUT_USD_PER_1M: float = Field(default=0.15, ge=0)
    LLM_PRICE_OUTPUT_USD_PER_1M: float = Field(default=0.60, ge=0)
    # Append-only JSONL ledger of every billable LLM call. Empty = disabled.
    # Path is relative to the project root unless absolute.
    LLM_USAGE_LEDGER_PATH: str = "artifacts/llm_usage/llm_usage.jsonl"

    # ── M3 / M4 gating ───────────────────────────────────
    # Min significance_score to trigger M4 obligation extraction.
    # 0.6 = "substantive" or higher per the L3 rubric.
    OBLIGATIONS_SCORE_GATE: float = Field(default=0.6, ge=0.0, le=1.0)
    # Max chars of doc content fed to the obligation extractor.
    LLM_OBLIGATIONS_MAX_CONTENT: int = Field(default=6000, ge=500)

    # ── Celery resilience ─────────────────────────────────
    # Hard caps on task-level retries — prevents a permanently-broken
    # event from hammering the LLM API forever.
    CELERY_SCORING_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    CELERY_OBLIGATIONS_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    # Per-second rate limits on LLM-bound tasks ("60/m" = 1/sec).
    # Celery enforces these per-worker. Empty string = no limit.
    CELERY_SCORING_RATE_LIMIT: str = "60/m"
    CELERY_OBLIGATIONS_RATE_LIMIT: str = "30/m"
    # Circuit breaker — if more than N consecutive HTTP errors occur
    # within WINDOW seconds, subsequent enqueues short-circuit for
    # COOLDOWN seconds. Implemented in app.services.circuit_breaker.
    LLM_CIRCUIT_BREAKER_THRESHOLD: int = Field(default=10, ge=1)
    LLM_CIRCUIT_BREAKER_WINDOW_SECONDS: int = Field(default=60, ge=1)
    LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = Field(default=300, ge=10)

    # ── Crawl / ingestion knobs ───────────────────────────
    CRAWL_DEFAULT_RATE_LIMIT_RPS: float = Field(default=1.0, gt=0)
    CRAWL_DEFAULT_MAX_PAGES: int = Field(default=50, ge=1)
    CRAWL_DEFAULT_MAX_DEPTH: int = Field(default=3, ge=0)
    CRAWL_DEFAULT_MAX_PDFS: int = Field(default=20, ge=0)
    CRAWL_DEFAULT_MAX_XMLS: int = Field(default=10, ge=0)
    CRAWL_HTTP_TIMEOUT_SECONDS: int = Field(default=30, ge=5)
    # Max chars of extracted text per page before truncation.
    CRAWL_MAX_TEXT_CHARS: int = Field(default=500_000, ge=1000)

    # ── AWS S3 (artifact storage — optional) ─────────────
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ── Email / IMAP (EmailConnector — optional) ──────────
    IMAP_HOST: str = ""
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_MAILBOX: str = "INBOX"

    # ── Ingestion HTTP (optional) ─────────────────────────
    # Comma-separated host suffixes for which PDF/XML/robots httpx calls skip
    # TLS verification (e.g. "dof.gob.mx" when the site sends a broken chain).
    INGEST_TLS_SKIP_VERIFY_HOST_SUFFIXES: str = ""

    # ── Logging ───────────────────────────────────────────
    # 'json' (production / log aggregation) | 'console' (human-readable dev)
    LOG_FORMAT: str = "json"
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
