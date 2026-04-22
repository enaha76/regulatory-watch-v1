# Demo Commands — Presentation Runbook

> Run these **in order** during the demo.
> All commands assume your working directory is the project root:
> `regulation-prj-v1/`

---

## Demo 0 — Prep (do BEFORE the audience arrives)

```bash
# Bring the full stack up
docker compose up -d

# Verify all 5 services are healthy
docker compose ps
```

> **What the audience sees**: `api`, `worker`, `postgres`, `redis`, and `scheduler` all `running / healthy`.

---

## Demo 1 — Stack is up

```bash
docker compose ps
```

> **Say**: "One command brings up the full production stack — API, worker, Postgres, Redis."

**Screenshot name**: `docs/slides/screenshots/01-docker.png`

---

## Demo 2 — Ingestion in action

Pick one source connector to show live (CBP is fast and visual):

```bash
docker compose exec -T worker python scripts/test_cbp.py
```

**Why it looked like “no output” before:** this script only printed **after** the Celery task finished (`r.get()` can block for many minutes). You should now see an immediate line with the **task id**; the final `Result:` still appears only when the crawl completes. For **live** progress, run in a second terminal:

```bash
docker compose logs -f worker
```

Alternatives if you want to showcase other lanes:

```bash
# EUR-Lex (European regulations)
docker compose exec -T worker python scripts/test_eurlex.py

# China (shows multilingual native handling)
docker compose exec -T worker python scripts/test_china.py

# PDF
docker compose exec -T worker python scripts/test_pdf.py

# RSS
docker compose exec -T worker python scripts/test_rss.py
```

> **Say**: "The connector fetches the page, detects the language, hashes the content, and stores the raw document."

**Screenshot name**: `docs/slides/screenshots/02-ingest.png`

---

## Demo 3 — Change detection + diffs

```bash
# Show the last 10 change events with diffs
docker compose exec -T worker python scripts/show_changes.py --limit 10
```

Useful variants:

```bash
# Only show MODIFIED events (not first-seen)
docker compose exec -T worker python scripts/show_changes.py --kind modified

# Show one specific event with full diff
docker compose exec -T worker python scripts/show_changes.py --event-id <id>
```

> **Say**: "Every change_event is the result of a hash miss followed by a unified diff. Unchanged pages never make it here."

**Screenshot name**: `docs/slides/screenshots/03-changes.png`

---

## Demo 4 — Significance score, topic, countries, summary

```bash
# Show scored events (significance_score + topic + summary)
docker compose exec -T worker python scripts/show_changes.py --scored --limit 5
```

SQL view for the same thing (fallback if the script is too verbose):

```bash
docker compose exec -T postgres psql -U postgres regwatch -c "
SELECT
  substring(source_url, 1, 50) AS url,
  significance_score,
  change_type,
  topic,
  origin_countries,
  destination_countries,
  trade_flow_direction,
  substring(summary, 1, 120) AS summary
FROM change_events
WHERE significance_score IS NOT NULL
ORDER BY scored_at DESC
LIMIT 5;"
```

> **Say**: "A single LLM call returns all of this — score, topic, entities, countries, and an English summary. That is what makes this cheap."

**Screenshot name**: `docs/slides/screenshots/04-significance.png`

---

## Demo 5 — Structured obligations

```bash
# Most recent obligations (actor / action / deadline / penalty)
docker compose exec -T worker python scripts/show_obligations.py --limit 10
```

Filter by a single event:

```bash
docker compose exec -T worker python scripts/show_obligations.py --event-id <id>
```

SQL fallback:

```bash
docker compose exec -T postgres psql -U postgres regwatch -c "
SELECT
  actor,
  substring(action, 1, 80) AS action,
  deadline,
  substring(penalty, 1, 60) AS penalty,
  obligation_type
FROM obligations
ORDER BY created_at DESC
LIMIT 10;"
```

> **Say**: "Unstructured regulatory prose, now machine-readable. Ready for dashboards and alerts."

**Screenshot name**: `docs/slides/screenshots/05-obligations.png`

---

## Demo 6 — Entities, HS codes, countries

```bash
# Show normalized entities linked to recent events
docker compose exec -T worker python scripts/show_entities.py --limit 20
```

**The "wow" query** — show every HS/HTS code we indexed:

```bash
docker compose exec -T postgres psql -U postgres regwatch -c "
SELECT
  canonical_key AS code,
  mention_count,
  first_seen_at::date
FROM entities
WHERE entity_type = 'code'
ORDER BY mention_count DESC
LIMIT 15;"
```

Filter change events by country (China-origin example):

```bash
docker compose exec -T postgres psql -U postgres regwatch -c "
SELECT
  substring(source_url, 1, 60) AS url,
  origin_countries,
  destination_countries,
  trade_flow_direction,
  substring(summary, 1, 80) AS summary
FROM change_events
WHERE origin_countries @> ARRAY['CN']
LIMIT 10;"
```

> **Say**: "Every event is queryable by country, agency, regulation, or tariff code."

**Screenshot name**: `docs/slides/screenshots/06-entities.png`

---

## Demo 7 — LLM cost & token report

```bash
docker compose exec -T worker python scripts/llm_cost_report.py
```

Optional breakdown by scope:

```bash
docker compose exec -T worker python scripts/llm_cost_report.py --by-scope
```

> **Say**: "Every LLM call is logged with tokens and US dollars. Full financial and audit transparency."

**Screenshot name**: `docs/slides/screenshots/07-cost.png`

---

## Demo 8 — Quality proof (optional but strong)

```bash
# Run the full unit test suite
docker compose exec -T worker pytest -q

# Or just show the count
docker compose exec -T worker pytest --collect-only -q | tail -5
```

> **Say**: "138 unit tests, all passing. Every new module has coverage."

**Screenshot name**: `docs/slides/screenshots/08-tests.png`

---

## Bonus — Show the backfill power (optional)

If someone asks "what about historical data?":

```bash
# Zero-LLM backfill: extract HS/HTS codes from every raw_document
docker compose exec -T worker python scripts/backfill_code_entities.py --dry-run
```

```bash
# Full LLM run on v1-only tariff PDFs (the analyze pipeline)
docker compose exec -T worker python scripts/analyze_tariff_docs.py --limit 3
```

> **Say**: "Historical documents that pre-date the pipeline can be backfilled in two passes — regex-only for free, or full LLM for structured obligations."

---

## Troubleshooting cheat sheet

| Problem | Fix |
|---|---|
| Worker not ready | `docker compose logs -f worker \| tail -50` |
| DB empty | Run a connector (Demo 2) first |
| OpenAI errors | Check `OPENAI_API_KEY` in `.env` |
| Costs unclear | `scripts/llm_cost_report.py` is the single source of truth |
| Want to reset | `docker compose down -v && docker compose up -d` (drops data) |

---

## Recommended demo order (10-minute version)

1. `docker compose ps` — stack up (10s)
2. `scripts/test_cbp.py` — live ingestion (60s, most visual)
3. `scripts/show_changes.py --scored --limit 5` — change events + scoring (90s)
4. SQL country filter query — "China-origin events" (60s)
5. `scripts/show_obligations.py` — structured obligations (90s)
6. `scripts/llm_cost_report.py` — cost transparency (30s)
7. `pytest -q` — 138 tests passing (30s)

**Total: ~7 minutes** of live commands, leaving 3 minutes for Q&A.
