# Regulatory Watch — v1

> **AI-powered regulatory monitoring platform** — continuously tracks global regulatory websites, official feeds, and legal documents, detects changes, and uses an LLM chain to extract compliant obligations, entities, and trade-flow impacts.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Services & Ports](#services--ports)
4. [Data Model](#data-model)
5. [Ingestion Layer](#ingestion-layer)
6. [Processing Pipeline (M3/M4)](#processing-pipeline)
7. [Background Jobs](#background-jobs)
8. [API Reference](#api-reference)
9. [Configuration Reference](#configuration-reference)
10. [Database Migrations](#database-migrations)
11. [Project Structure](#project-structure)
12. [Makefile Commands](#makefile-commands)
13. [Quick Start](#quick-start)

---

## Overview

Regulatory Watch solves a core compliance operations problem: regulatory rules change continuously across dozens of global sources (EUR-Lex, US Federal Register, UK FCA, CBP rulings, national gazettes, etc.), and tracking those changes manually is impossible at scale.

The platform:
- **Ingests** documents from web pages, PDFs, RSS/Atom feeds, XML legal corpora, and IMAP email
- **Versions** every document, computing SHA-256 content hashes for deduplication
- **Detects** exact diffs between versions and classifies them as `created` or `modified`
- **Scores** each change using an LLM rubric (0.0 typo → 1.0 critical new obligation)
- **Extracts** actionable, queryable obligations (`who must do what by when`) for high-significance changes
- **Indexes** regulatory entities (agencies, programs, HS codes) from LLM outputs for cross-event querying

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       INGESTION LAYER                            │
│   WebConnector (BFS+Crawl4AI)  ·  PDFConnector  ·  RSSConnector │
│   XMLConnector  ·  EmailConnector                                │
└─────────────────────────────┬────────────────────────────────────┘
                              │  RawDocument (SHA-256 hash)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    CHANGE DETECTION (Layer 1+2)                  │
│   Dedup  →  SourceVersion history  →  ChangeEvent (unified diff) │
└─────────────────────────────┬────────────────────────────────────┘
                              │  Celery task enqueued (best-effort)
                              ▼
┌────────────────────────────────────────────────────┐
│              LLM SIGNIFICANCE SCORER (M3)          │
│    GPT-4o-mini · score [0.0–1.0] · topic ·         │
│    change_type · affected_entities ·               │
│    deadline_changes · origin_countries             │
└────────────────┬───────────────────────────────────┘
                 │  if score ≥ 0.6 → auto-chain
                 ▼
┌────────────────────────────────────────────────────┐
│          LLM OBLIGATION EXTRACTOR (M4 Phase 3)     │
│    actor · action · condition · deadline · penalty │
│    obligation_type (reporting/prohibition/…)       │
└────────────────────────────────────────────────────┘
```

Key design principles:
- **Fail-soft at every layer.** An LLM outage or Redis crash does not block ingestion.
- **Idempotent by content hash.** Re-crawling the same URL produces 0 new rows if the content hasn't changed.
- **Cost-controlled LLM budget.** Diffs are truncated to ~6K chars; obligations gated at score ≥ 0.6; circuit breakers across Celery workers prevent hammering a failing API.

---

## Services & Ports

| Service     | Local Address           | Description                                      |
|-------------|-------------------------|--------------------------------------------------|
| **API**     | http://localhost:8001   | FastAPI REST API (maps to container port 8000)  |
| **Docs**    | http://localhost:8001/docs | Swagger UI (auto-generated from OpenAPI)      |
| **Flower**  | http://localhost:5555   | Celery task monitoring dashboard                 |
| **PostgreSQL** | localhost:5433       | Relational DB — `regwatch` database (mapped from 5432) |
| **Redis**   | localhost:6379          | Celery broker, result backend, circuit-breaker store |
| **Kafka**   | localhost:9092          | Message bus (Confluent 7.6)                      |
| **Zookeeper**| localhost:2181         | Kafka ensemble coordination                      |

---

## Data Model

### Core Entities

```
Domain  (1) ──────────── (N)  Url
  │                             │
  │                             └── (N)  FetchAttempt
  └── (N)  FetchRun  ──────────── (N)  FetchAttempt

RawDocument  →  SourceVersion  →  ChangeEvent
                                        │
                               ┌────────┼──────────────┐
                               │        │              │
                           Obligation  Entity   ChangeEventEntity
```

### Table Summary

| Table | Description |
|---|---|
| `domains` | Regulatory websites to monitor. Stores seed URLs, status (`active/paused/archived`), and rate limit (rps). |
| `urls` | Individual pages discovered per domain. Has full state machine: `discovered → queued → fetched → failed → ignored → blocked`. Tracks priority, relevance, hub/trap scores, ETags, error streaks, and cooldown timers. |
| `fetch_runs` | A batched crawl execution. Tracks metrics: planned, fetched, changed, and alert counts. |
| `fetch_attempts` | One row per URL per fetch. Stores HTTP status, content hash, and S3 URI pointers for raw HTML and extracted text. |
| `raw_documents` | The canonical extracted text of a fetched document. SHA-256 deduplicated. Stores page offsets for PDFs. |
| `source_versions` | Immutable history: one row per unique `(source_url, content_hash)`. Enables re-diff without re-fetching. |
| `change_events` | Detected transition between two `SourceVersion`s. Contains the unified diff, LLM-scored significance, topic, affected entities, deadline changes, compliance summary, trade-flow direction, and origin/destination countries. |
| `entities` | Normalized index of regulatory entities (agencies, regulations, HS codes, industries) extracted from LLM outputs. |
| `change_event_entities` | Many-to-many join: links `ChangeEvent` → `Entity` with the raw mention text preserved. |
| `obligations` | Structured compliance obligations extracted from high-significance events. Fields: `actor`, `action`, `condition`, `deadline_text`, `deadline_date`, `penalty`, `obligation_type`. |

### Significance Scoring Rubric

| `change_type` | Score Range | Description |
|---|---|---|
| `typo_or_cosmetic` | 0.00–0.19 | Whitespace, punctuation, broken links |
| `minor_wording` | 0.20–0.39 | Rephrasing with no legal effect |
| `clarification` | 0.40–0.59 | Explains existing rule more clearly |
| `substantive` | 0.60–0.79 | Rule, threshold, or scope altered |
| `critical` | 0.80–1.00 | New deadline, penalty, or obligation introduced |

### Regulatory Topic Taxonomy

`customs_trade` · `financial_services` · `data_privacy` · `environmental` · `healthcare_pharma` · `sanctions_export_control` · `labor_employment` · `tax_accounting` · `consumer_protection` · `corporate_governance` · `other`

---

## Ingestion Layer

All connectors live in `app/ingestion/` and return a list of `RawDocument` objects.

| Connector | File | Description |
|---|---|---|
| **WebConnector** | `web_connector.py` | BFS crawler (up to 50 pages/run). Primary engine: **Crawl4AI** headless Playwright with `PruningContentFilter` for clean main-content extraction. Falls back to `httpx`. Respects `robots.txt`, rate limits, path prefixes, and automatically detects blocker/CAPTCHA pages. Also auto-harvests linked PDFs and XML files. |
| **PDFConnector** | `pdf_connector.py` | Extracts text and tables from PDFs. Primary: `docling` (layout-aware, table detection). Falls back gracefully to `pdfplumber`. Stores character-level page offsets for per-page slicing without full re-fetch. |
| **RSSConnector** | `rss_connector.py` | Polls RSS 0.9–2.0, Atom, and RDF feeds via `feedparser`. |
| **XMLConnector** | `xml_connector.py` | Parses USLM and Akoma Ntoso structured legal XML (e.g. US Code USLM corpora from govinfo.gov). |
| **EmailConnector** | `email_connector.py` | Polls an IMAP mailbox for new regulatory notification emails (configurable via `IMAP_*` env vars). |

**Shared utilities:**
- `blocker_detect.py` — Multilingual CAPTCHA/rate-limit interstitial detector with Redis-backed per-domain block counters
- `lang.py` — CJK-aware ISO 639-1 language detection (local, no API key)
- `storage.py` — Upserts `RawDocument` rows and triggers `change_detection.record_change()`
- `artifact_store.py` — Optional AWS S3 upload for raw text archives
- `url_utils.py` — URL normalization, same-domain checks, and spider-trap detection
- `http_utils.py` — Per-host configurable TLS verification skip for problematic government sources

---

## Processing Pipeline

### Layer 1+2 — Change Detection (`app/services/change_detection.py`)

Deterministic, LLM-free, and called synchronously after every document upsert:

1. Computes SHA-256 of the extracted text
2. Checks `source_versions` for prior versions of this URL
3. If content hash is **unchanged** → just bumps `last_seen_at`
4. If it's **new or changed** → inserts a new `SourceVersion` row + a `ChangeEvent` (`created` or `modified`)
5. For `modified` events, stores a unified text diff (truncated to 100K chars)
6. Asynchronously enqueues the `score_change_event` Celery task (best-effort — a Redis failure here just logs a warning, it doesn't break ingestion)

### Layer 3 — Significance Scoring (`app/services/significance.py`)

Runs asynchronously per `ChangeEvent` via a Celery worker:

1. Builds a prompt including the unified diff (for `modified`) or full document content (for `created`)
2. Calls `gpt-4o-mini` (configurable via `OPENAI_MODEL`)
3. Parses a strict JSON response with Pydantic: `significance_score`, `change_type`, `topic`, `affected_entities`, `deadline_changes`, `compliance_summary`, `origin_countries`, `trade_flow_direction`
4. Writes all fields back to the `ChangeEvent` row
5. Resolves destination countries from the source URL via `app.services.geo`
6. Runs entity normalization + sync to `entities` table (`app.services.entity_index`)
7. If `score ≥ OBLIGATIONS_SCORE_GATE` (default 0.6) → auto-chains `extract_obligations_task`

### Layer 4 — Obligation Extraction (`app/services/obligations.py`)

Only runs for events with `significance_score ≥ 0.6`:

1. Uses the document content from the linked `SourceVersion`
2. Second LLM call with a compliance-analyst system prompt
3. Extracts zero or more structured `Obligation` rows per event
4. Parses deadlines from ISO-8601 strings and natural-language forms ("30 June 2026")
5. Obligation types: `reporting`, `prohibition`, `threshold`, `disclosure`, `registration`, `penalty`, `other`
6. Sets `change_events.obligations_extracted_at` for idempotency

---

## Background Jobs

Defined in `app/celery_app.py`, scheduled via **Celery Beat**:

| Task | Schedule | Description |
|---|---|---|
| `heartbeat` | every 5 min | Pings Redis and PostgreSQL; logs health status |
| `rss_ingest_task` (US Federal Register) | every 30 min | https://www.govinfo.gov/rss/fr.xml |
| `rss_ingest_task` (UK FCA) | every 30 min | https://www.fca.org.uk/news/rss.xml |
| `web_crawl_task` (EUR-Lex) | every 6 hours | https://eur-lex.europa.eu/latest-laws/ (50 pages, 0.5 rps) |
| `web_crawl_task` (UK FCA News) | every 6 hours | https://www.fca.org.uk/news (50 pages) |
| `web_crawl_task` (Federal Register) | every 6 hours | https://www.federalregister.gov/documents/current |
| `xml_ingest_task` (US Code Title 5) | daily | https://www.govinfo.gov/bulkdata/USLM/usc/xml/usc05.xml |
| `score_change_event` | on demand (auto-enqueued) | LLM significance scoring |
| `extract_obligations_task` | on demand (auto-chained) | LLM obligation extraction |

**Resilience features:**
- Exponential-backoff retries (up to 3 per task by default)
- Per-worker rate limits: 60/min for scoring, 30/min for obligations
- Redis-backed circuit breaker (`app/services/circuit_breaker.py`): trips after 10 consecutive HTTP errors in 60s, pauses new LLM calls for 5 min

---

## API Reference

Base URL: `http://localhost:8001`  
Interactive docs: `http://localhost:8001/docs`

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | App liveness — returns `{"status": "ok"}` |
| `GET` | `/health/db` | PostgreSQL connectivity |
| `GET` | `/health/redis` | Redis connectivity |

### Domains

| Method | Path | Description |
|---|---|---|
| `POST` | `/domains` | Register a domain. Body: `{"domain": "cbp.gov", "seed_urls": [...], "rate_limit_rps": 1.0}` |
| `GET` | `/domains` | List domains. Query params: `skip`, `limit` (max 100), `status` (active/paused/archived) |
| `GET` | `/domains/{id}` | Get a single domain by UUID |
| `PATCH` | `/domains/{id}` | Partial update (status, rate limit, seed URLs, etc.) |
| `DELETE` | `/domains/{id}` | Remove a domain |

---

## Configuration Reference

All settings loaded from environment variables or `.env`. Defaults are production-safe.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://regwatch:regwatch_secret@db:5432/regwatch` | PostgreSQL DSN |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:29092` | Kafka broker |
| `OPENAI_API_KEY` | _(empty)_ | **Required** for all LLM features. Without it, scoring/obligation tasks are skipped gracefully. |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model for scoring and obligation extraction |
| `LLM_TIMEOUT` | `30` | Seconds per LLM HTTP round-trip |
| `OBLIGATIONS_SCORE_GATE` | `0.6` | Min significance score to trigger obligation extraction |
| `LLM_MAX_DIFF_CHARS` | `6000` | Max diff chars sent to scoring LLM |
| `LLM_SCORING_MAX_TOKENS` | `600` | Max output tokens for significance scorer |
| `LLM_OBLIGATIONS_MAX_TOKENS` | `1200` | Max output tokens for obligation extractor |
| `CELERY_SCORING_RATE_LIMIT` | `60/m` | Per-worker scoring task rate cap |
| `CELERY_OBLIGATIONS_RATE_LIMIT` | `30/m` | Per-worker obligations task rate cap |
| `LLM_CIRCUIT_BREAKER_THRESHOLD` | `10` | HTTP errors before circuit trips |
| `LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `300` | Seconds circuit stays open |
| `CRAWL_DEFAULT_RATE_LIMIT_RPS` | `1.0` | Default crawler speed |
| `CRAWL_DEFAULT_MAX_PAGES` | `50` | Default max pages per crawl |
| `CRAWL_DEFAULT_MAX_DEPTH` | `3` | Default BFS max depth |
| `AWS_S3_BUCKET` | _(empty)_ | Optional — S3 bucket for extracted text archives |
| `IMAP_HOST` | _(empty)_ | Optional — IMAP server for `EmailConnector` |
| `LOG_FORMAT` | `json` | `json` (production) or `console` (dev) |
| `DEV_AUTOCREATE_TABLES` | `false` | If `true`, SQLModel creates tables on startup. **Dev only.** |

---

## Database Migrations

Schema is owned by **Alembic**. Never run `create_all()` in production.

| Migration | What it adds |
|---|---|
| `001_initial_schema` | `domains`, `urls`, `fetch_runs`, `fetch_attempts` |
| `002_add_raw_documents` | `raw_documents` table |
| `003_add_pdf_page_offsets` | `page_count`, `pages` JSON on `raw_documents` |
| `004_add_versioning_and_change_events` | `source_versions`, `change_events` |
| `005_add_artifact_uri` | `artifact_uri` S3 pointer on `raw_documents` + `source_versions` |
| `006_add_significance_score` | `significance_score`, `change_type`, `compliance_summary`, `llm_*` on `change_events` |
| `007_add_topic` | `topic` column + taxonomy constraint on `change_events` |
| `008_add_entities` | `entities` + `change_event_entities` tables |
| `009_add_obligations` | `obligations` table, `obligations_extracted_at` on `change_events` |
| `010_add_country_direction` | `origin_countries`, `destination_countries`, `trade_flow_direction` on `change_events` |

---

## Project Structure

```
regulation-prj-v1/
├── app/
│   ├── main.py               # FastAPI entrypoint. Lifespan, CORS, router registration.
│   ├── config.py             # All config via pydantic-settings (env vars / .env)
│   ├── database.py           # SQLAlchemy engine, session factory
│   ├── models.py             # All SQLModel table definitions (11 tables)
│   ├── schemas.py            # API request/response Pydantic models
│   ├── logging_setup.py      # structlog JSON/console logging
│   ├── celery_app.py         # Celery app + beat schedule + all task definitions
│   ├── routers/
│   │   ├── health.py         # /health, /health/db, /health/redis
│   │   └── domains.py        # CRUD /domains
│   ├── ingestion/
│   │   ├── base.py           # IngestorBase abstract class
│   │   ├── web_connector.py  # BFS crawler (Crawl4AI + httpx fallback)
│   │   ├── pdf_connector.py  # PDF extractor (docling + pdfplumber fallback)
│   │   ├── rss_connector.py  # RSS/Atom feed reader
│   │   ├── xml_connector.py  # USLM/Akoma Ntoso XML parser
│   │   ├── email_connector.py# IMAP mailbox reader
│   │   ├── web_extractor.py  # Content extraction strategies (BS4, LLM fallback)
│   │   ├── blocker_detect.py # CAPTCHA/rate-limit interstitial detection
│   │   ├── storage.py        # Document upsert + change detection trigger
│   │   ├── artifact_store.py # AWS S3 artifact upload
│   │   ├── lang.py           # Language detection (CJK-aware)
│   │   ├── url_utils.py      # URL normalization + spider-trap detection
│   │   └── http_utils.py     # Per-host TLS verification helpers
│   └── services/
│       ├── change_detection.py   # Diff engine → ChangeEvent (deterministic, LLM-free)
│       ├── significance.py       # LLM significance scorer (M3 Layer 3)
│       ├── obligations.py        # LLM obligation extractor (M4 Phase 3)
│       ├── entity_index.py       # Entity normalization + DB sync
│       ├── geo.py                # Country code resolution from source URLs
│       ├── circuit_breaker.py    # Redis-backed cross-worker circuit breaker
│       └── llm_usage.py          # LLM cost ledger (JSONL append-only log)
├── alembic/
│   └── versions/             # 10 incremental migrations
├── tests/                    # pytest suite (unit tests for all services)
├── scripts/                  # Operational + analysis utilities
│   └── benchmark/            # Crawler benchmark tooling
├── docs/                     # Architecture docs, reports, slides
├── docker-compose.yml        # 7 services: db, redis, kafka, zookeeper, api, worker, flower
├── Dockerfile
├── Makefile
├── requirements.txt
└── .env.example
```

---

## Makefile Commands

```bash
make up                 # Build and start all 7 services
make down               # Stop all services
make clean              # Stop + remove volumes (data reset)
make logs               # Tail all service logs (last 50 lines)
make logs-api           # Tail API logs only
make logs-worker        # Tail Celery worker logs only
make migrate            # Run Alembic migrations (alembic upgrade head)
make migrate-generate msg="my change"  # Auto-generate a new migration
make test               # Run smoke tests (health + domain CRUD via curl)
make shell              # Open a bash shell inside the API container
make status             # Show docker compose container status
```

---

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Set OPENAI_API_KEY in .env for LLM features (scoring, obligations)

# 2. Start all services (first build takes ~2 min)
make up

# 3. Run database migrations
make migrate

# 4. Verify everything is working
make test

# 5. Register a domain to start monitoring
curl -X POST http://localhost:8001/domains \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "cbp.gov",
    "seed_urls": ["https://www.cbp.gov/trade/rulings"],
    "rate_limit_rps": 0.5
  }'

# 6. Monitor Celery tasks
open http://localhost:5555   # Flower dashboard

# 7. View API docs
open http://localhost:8001/docs
```
