# Pro-Max Release — Changes, Deployment, End-to-End Testing

This release takes the system from **"impressive pipeline"** to
**"product a compliance team can adopt."** Six arcs in sequence, each
closing a loop the product needed: correctness, scale, delivery,
evaluation, chunking, explainability, collaboration, and ingestion
filtering.

**Scope:** migrations **012–015**, new services in `app/services/`,
new connector in `app/ingestion/`, new eval harness under `app/services/eval/`
+ `eval/golden/`, new Celery task + beat entry, new API endpoints on the
alerts router.

---

## 1. What changed — complete inventory

### 1.1 Bug fixes

| Bug | Impact | Files |
|---|---|---|
| `to_tsquery` on raw user input could crash the entire matching query | One bad subscription query broke alerts for *every* user | `app/services/matching.py`, `app/routers/subscriptions.py` |
| Circuit breaker `record_success` wiped the sliding-failure window | Flapping upstream never tripped the breaker | `app/services/circuit_breaker.py`, `app/celery_app.py` |
| Cost ledger used a flat price regardless of model | Silent 10× cost drift on model change | `app/services/llm_usage.py` |
| Obligation content silently truncated at 6K chars | Obligations from the 2nd half of long regs dropped | `app/services/obligations.py` (superseded by chunking, §1.5) |
| Dead `settings = get_settings()` in `circuit_breaker.is_open` | Cosmetic but misleading | `app/services/circuit_breaker.py` |

### 1.2 Performance fixes

| Issue | Before → After | Files |
|---|---|---|
| `to_tsvector('english', :raw_text)` recomputed per subscription row | 500KB × 1000 subs = ~50s → ~50ms (CTE, tokenize once) | `app/services/matching.py` |
| N+1 sessions in change detection | ~100 round-trips per 50-doc batch → 4 (1 session, 2 prefetches, savepoints) | `app/services/change_detection.py` |
| No composite index for latest-by-URL lookup on `source_versions` | Heap-scan + sort → O(log n) index scan | migration **012** |

### 1.3 Delivery loop (M5b)

Alerts now leave Postgres. SMTP email notifier, per-subscription channel
routing, per-alert delivery tracking with exponential-backoff retry, and
a global kill switch for safe staging.

- **New files:** `app/services/notifiers/{__init__.py,base.py,email.py,registry.py}`, migration **013**
- **Changed:** `app/models.py` (Alert + UserSubscription columns), `app/config.py`, `app/celery_app.py` (`deliver_alert` task), `app/services/matching.py` (enqueues delivery after commit), `app/routers/subscriptions.py` (channel, channel_target fields)
- **Safety:** `ALERT_DELIVERY_ENABLED=false` default — matching still runs; delivery is a feature flag.

### 1.4 Eval harness (M3 trust loop)

Runs the production prompt + parser against a golden dataset. No DB
required. Writes JSON reports to `artifacts/eval/eval_<ISO>.json`;
exits non-zero on regression.

- **New:** `app/services/eval/{__init__.py,schema.py,metrics.py,runner.py}`, `eval/golden/significance.jsonl` (8 seeds), `scripts/run_eval.py`
- **Measures:** pass rate, score MAE, change-type accuracy, topic accuracy, obligations-gate accuracy

### 1.5 Obligation chunking (M4)

Replaces the silent 6K-char truncation with paragraph-aware chunking up
to `LLM_OBLIGATIONS_MAX_CHUNKS` (default 15). Per-chunk LLM call; dedup
on normalized `(actor, action, type)`. HTTP errors abort; per-chunk
parse errors skip that chunk only.

- **Changed:** `app/services/obligations.py` (chunker, dedup, per-chunk loop, telemetry), `app/config.py` (`LLM_OBLIGATIONS_CHUNK_OVERLAP`, `LLM_OBLIGATIONS_MAX_CHUNKS`)

### 1.6 Explainability (M5c)

Every alert carries the exact sentence that triggered it. Obligations
cite the source text. LLM quotes verbatim; `str.find` computes offsets;
NULL span when the LLM paraphrased (the email distinguishes verified
vs. unverified citations).

- **New:** `app/services/citations.py`, migration **014**
- **Changed:** `app/models.py` (ChangeEvent + Obligation span columns), `app/services/significance.py` (prompt, persist), `app/services/obligations.py` (per-obligation quote + span), `app/services/notifiers/email.py` (renders blockquote)

### 1.7 Collaboration / workflow (M5d)

State machine (`open → in_progress → done | waived`), assignment,
due dates, threaded comments, full audit log.

- **New:** `app/services/alert_workflow.py`, migration **015**
- **Changed:** `app/models.py` (7 new Alert columns + `AlertComment` + `AlertActivity`), `app/routers/alerts.py` (5 new endpoints, expanded filters on `GET /api/alerts`)
- **Endpoints:** `PATCH /api/alerts/{id}/workflow`, `PATCH /api/alerts/{id}/assignment`, `POST /api/alerts/{id}/comments`, `GET /api/alerts/{id}/comments`, `GET /api/alerts/{id}/activity`

### 1.8 Ingestion filtering (Layers 1 + 2)

Stops paying for "Join our team" pages. Universal multilingual content
filter drops junk before it becomes a `RawDocument`. Federal Register
now ingested via its public JSON API instead of BFS.

- **New:** `app/services/content_filter.py`, `app/ingestion/federal_register_api.py`
- **Changed:** `app/ingestion/storage.py` (content filter runs as Phase 0), `app/celery_app.py` (`federal_register_api_task` + beat entry; old BFS commented out), `app/config.py` (content filter + FR API knobs)

---

## 2. Database migrations

Apply in order. **All four are new in this release.**

| Rev | Description |
|---|---|
| **012** | Composite index `idx_source_versions_url_seen_desc` on `(source_url, last_seen_at DESC)` for latest-version lookup. |
| **013** | Delivery fields: `UserSubscription.channel`, `channel_target`; `Alert.delivered_at`, `delivery_error`, `delivery_attempts`; partial index `idx_alerts_pending_delivery`. |
| **014** | Citation fields: `ChangeEvent.trigger_quote/span_start/span_end`; `Obligation.source_quote/source_span_start/source_span_end`. CHECK constraints enforce that `(start, end)` is paired and ordered. |
| **015** | Workflow: `Alert.workflow_status`, `assigned_to`, `assigned_by`, `assigned_at`, `due_date`, `resolution_note`, `closed_at`; `alert_comments` and `alert_activity` tables; `idx_alerts_workflow`, `idx_alerts_due_date` (partial), `idx_alert_comments_alert_created`, `idx_alert_activity_alert_created`. |

### Apply them

```bash
# Bring the stack up if not already running
make up

# Apply everything up to HEAD (015)
make migrate

# Verify
docker compose exec api alembic current
# → expected: 015 (head)
```

---

## 3. Environment variables — new in this release

Add to `.env` (or set via your secret manager in prod). All have sensible
defaults; only `OPENAI_API_KEY` and the `SMTP_*` family must be set for
their respective features to actually work.

```bash
# ── Content filter (universal, multilingual — no per-domain config) ──
CONTENT_FILTER_ENABLED=true             # default true; drop non-regulatory docs
CONTENT_FILTER_MIN_WORDS=300
CONTENT_FILTER_MIN_KEYWORD_HITS=3
CONTENT_FILTER_MIN_DENSITY=0.003        # regulatory keywords per token

# ── Federal Register JSON API (public, no key) ──
FEDERAL_REGISTER_API_BASE=https://www.federalregister.gov/api/v1
FEDERAL_REGISTER_DAYS_BACK=2
FEDERAL_REGISTER_MAX_DOCS=200
FEDERAL_REGISTER_RATE_LIMIT_RPS=2.0

# ── Obligation chunking ──
LLM_OBLIGATIONS_MAX_CONTENT=6000        # per-chunk budget
LLM_OBLIGATIONS_CHUNK_OVERLAP=400       # sliding-window overlap (fallback only)
LLM_OBLIGATIONS_MAX_CHUNKS=15           # worst-case cost cap per event

# ── Alert delivery (M5b) ──
ALERT_DELIVERY_ENABLED=false            # flip true when ready to send
SMTP_HOST=smtp.postmarkapp.com          # any SMTP relay
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=alerts@yourdomain.com
SMTP_FROM_NAME=Regulatory Watch
SMTP_USE_TLS=true
SMTP_TIMEOUT_SECONDS=15
DELIVER_ALERT_MAX_RETRIES=5
PUBLIC_BASE_URL=https://regwatch.yourdomain.com
```

---

## 4. Running the stack

```bash
# 1. Start everything
make up
#    → API    http://localhost:8001
#    → Docs   http://localhost:8001/docs
#    → Flower http://localhost:5555

# 2. Apply migrations
make migrate

# 3. Verify health
curl -s http://localhost:8001/health    | python -m json.tool
curl -s http://localhost:8001/health/db | python -m json.tool
curl -s http://localhost:8001/health/redis | python -m json.tool

# 4. Tail logs
make logs              # everything
make logs-worker       # celery only
make logs-api          # API only

# 5. Shell into a container (for ad-hoc queries / scripts)
make shell             # lands in the API container
```

---

## 5. End-to-end test scenarios

Each scenario exercises a full vertical slice of the new capabilities.
Run them in order for best signal — they build on each other's state.

### 5.1 Ingestion filter drops junk (instant, no LLM cost)

**What this validates:** The universal content filter is dropping
non-regulatory pages before they become `RawDocument` rows, and logging
the reasons.

```bash
# Kick off the FCA web crawl manually (it also runs on schedule)
docker compose exec -T worker python -c "
from app.celery_app import web_crawl_task
result = web_crawl_task.delay(
    seed_urls=['https://www.fca.org.uk/news'],
    allowed_domain='www.fca.org.uk',
    max_pages=20,
    rate_limit_rps=0.5,
)
print('task_id:', result.id)
"

# Watch the content filter at work
make logs-worker | grep content_filter

# Expected lines in the worker log:
#   content_filter: kept=3 dropped=12 reasons={'too_short': 8, 'no_regulatory_keywords': 4}
```

Inspect the database to confirm only regulatory pages made it through:

```bash
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT COUNT(*) FILTER (WHERE source_url LIKE '%/careers/%')  AS careers,
         COUNT(*) FILTER (WHERE source_url LIKE '%/events/%')   AS events,
         COUNT(*) FILTER (WHERE source_url LIKE '%/about/%')    AS about,
         COUNT(*) FILTER (WHERE source_url LIKE '%/publications/%') AS publications,
         COUNT(*) AS total
    FROM raw_documents
    WHERE source_url LIKE 'https://www.fca.org.uk/%';
"
# Expected: careers=0, events=0, about=0, publications > 0
```

### 5.2 Federal Register API → scored + obligation-extracted

**What this validates:** Structured-feed ingestion (no BFS), chunked
obligation extraction, citations, full M1–M4 pipeline end to end.

```bash
# Trigger a single Federal Register API poll immediately
docker compose exec -T worker python -c "
from app.celery_app import federal_register_api_task
result = federal_register_api_task.delay(days_back=3, max_documents=5)
print('task_id:', result.id)
"

# Watch it flow end-to-end
make logs-worker | grep -E 'federal_register|change_event|scored|obligations'

# Expected sequence:
#   federal_register_api: starting ...
#   FederalRegisterAPI: GET .../documents.json ...
#   FederalRegisterAPI: index returned count=... (results=5)
#   federal_register_api: done fetched=5 inserted=5 filtered=0 ...
#   change_event: kind=created url=... +N -0
#   scored score=0.72 change_type=substantive topic=environmental trigger_span_located=True ...
#   (if score ≥ 0.6) done status=extracted obligations_created=3 chunks_processed=2 duplicates_removed=1 ...
```

Query the results:

```bash
# Most recent scored events with their trigger quotes
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT
    substring(source_url, 1, 50)       AS url,
    change_type,
    topic,
    significance_score                 AS score,
    substring(trigger_quote, 1, 80)    AS trigger_quote,
    trigger_span_start IS NOT NULL     AS quote_verified
  FROM change_events
  WHERE scored_at IS NOT NULL
  ORDER BY scored_at DESC
  LIMIT 5;
"

# Obligations with their source citations
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT
    substring(actor,  1, 40) AS actor,
    substring(action, 1, 60) AS action,
    deadline_date,
    obligation_type,
    substring(source_quote, 1, 60) AS quote,
    source_span_start IS NOT NULL  AS cited
  FROM obligations
  ORDER BY extracted_at DESC
  LIMIT 10;
"
```

### 5.3 Alert inbox → delivery → workflow loop

**What this validates:** Subscription creation with keyword validation,
matching, email delivery, and the full workflow state machine (assign
→ comment → close with resolution note).

**Step 1 — Create a subscription.** Note the bad-input test: a broken
tsquery must be rejected at POST time (not at match time).

```bash
# Happy path
curl -s -X POST http://localhost:8001/api/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "user_email": "sarah@acme.com",
    "label": "US Data Privacy Watch",
    "topics": ["data_privacy", "sanctions_export_control"],
    "origin_countries": ["US"],
    "min_significance": 0.6,
    "keyword_query": "breach & notification",
    "channel": "email"
  }' | python -m json.tool

# Record the "id" field from the response — use it as $SUB below.

# Broken tsquery — must 400 at create time
curl -sv -X POST http://localhost:8001/api/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "user_email": "sarah@acme.com",
    "label": "bad",
    "keyword_query": "lithium &"
  }'
# Expected: 400 {"detail":"Invalid keyword_query syntax"}
```

**Step 2 — Trigger matching on a recent event.**

```bash
# Pick the most recent scored event to match against
EVENT_ID=$(docker compose exec -T db psql -U regwatch regwatch -tAc "
  SELECT id FROM change_events
   WHERE scored_at IS NOT NULL AND significance_score >= 0.6
   ORDER BY scored_at DESC LIMIT 1;
")
echo "EVENT_ID=$EVENT_ID"

# Run the matcher
docker compose exec -T worker python -c "
from app.celery_app import match_change_event
r = match_change_event.delay('$EVENT_ID')
print('task_id:', r.id)
"
```

**Step 3 — Fetch the resulting alerts.**

```bash
curl -s 'http://localhost:8001/api/alerts?email=sarah@acme.com' | python -m json.tool

# Note the alert id ($ALERT below)
```

**Step 4 — Delivery (if SMTP + ALERT_DELIVERY_ENABLED are set).**

```bash
# Flip delivery on if you haven't yet
# (in .env:  ALERT_DELIVERY_ENABLED=true  then restart worker)
docker compose restart worker

# Manually re-enqueue delivery for the alert
docker compose exec -T worker python -c "
from app.celery_app import deliver_alert
deliver_alert.delay('$ALERT').get(timeout=30)
"

# Check delivery state
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT id, delivered_at, delivery_error, delivery_attempts
  FROM alerts WHERE id = '$ALERT';
"
# Expected after success: delivered_at is NOT NULL, delivery_error IS NULL
```

**Step 5 — Walk the workflow: assign → comment → close.**

```bash
# Assign to Sarah
curl -s -X PATCH "http://localhost:8001/api/alerts/$ALERT/assignment" \
  -H "Content-Type: application/json" \
  -d '{
    "assignee_email": "sarah@acme.com",
    "actor_email":    "lead@acme.com",
    "due_date":       "2026-05-15"
  }' | python -m json.tool

# Move it into progress
curl -s -X PATCH "http://localhost:8001/api/alerts/$ALERT/workflow" \
  -H "Content-Type: application/json" \
  -d '{"workflow_status":"in_progress", "actor_email":"sarah@acme.com"}' | python -m json.tool

# Leave a comment
curl -s -X POST "http://localhost:8001/api/alerts/$ALERT/comments" \
  -H "Content-Type: application/json" \
  -d '{
    "author_email": "sarah@acme.com",
    "body":         "Legal review complete — need policy update before we close."
  }' | python -m json.tool

# Close with resolution
curl -s -X PATCH "http://localhost:8001/api/alerts/$ALERT/workflow" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_status":  "done",
    "actor_email":      "sarah@acme.com",
    "resolution_note":  "Policy KB updated. No code changes required."
  }' | python -m json.tool
# Expected: closed_at is now populated, resolution_note persisted

# ── Negative case: invalid transition must return 409 ──
curl -sv -X PATCH "http://localhost:8001/api/alerts/$ALERT/workflow" \
  -H "Content-Type: application/json" \
  -d '{"workflow_status":"open", "actor_email":"sarah@acme.com"}'
# Expected: 409 {"detail":{"code":"invalid_transition", ...}}

# ── Negative case: close without resolution_note must return 400 ──
# (create + work another alert first, then:)
# curl ... PATCH /workflow with workflow_status=done, no resolution_note
# Expected: 400 {"detail":{"code":"missing_resolution_note", ...}}

# Audit trail
curl -s "http://localhost:8001/api/alerts/$ALERT/activity" | python -m json.tool
# Expected: 4 activity rows — assigned, status_changed (→ in_progress),
#           commented, status_changed (→ done)

# Dashboard query — everything assigned to Sarah
curl -s "http://localhost:8001/api/alerts?email=sarah@acme.com&assigned_to=sarah@acme.com&workflow_status=in_progress"
```

### 5.4 Run the M3 eval harness (quality regression check)

**What this validates:** The golden set passes on the current model.
Any pass-rate drop after a prompt or model change is a regression.

```bash
# Requires OPENAI_API_KEY to be set
docker compose exec -T worker python scripts/run_eval.py

# Typical output:
# ═══════════════════════════════════════════════════
#   Eval Run — 2026-04-24T...
#   Model: gpt-4o-mini
#   Entries         : 8
#   Passed          : 7 / 8    (87.5%)
#   Score MAE       : 0.073
#   Change-type acc.: 87.5%
#   Topic accuracy  : 100.0%
#   Obligation gate : 100.0%
#   Total latency   : 12483 ms
# ═══════════════════════════════════════════════════
#   ✗ clarification_hts_example:
#      - change_type='substantive' expected 'clarification'
#      actual: score=0.55 type='substantive' topic='customs_trade'
#
#   report → artifacts/eval/eval_2026-04-24T....json
#
# Exit code: 1 if any entry failed, 0 otherwise.

# Compare two models
docker compose exec -T worker python scripts/run_eval.py --model gpt-4.1-mini --output-dir artifacts/eval/41mini
docker compose exec -T worker python scripts/run_eval.py --model gpt-4o-mini  --output-dir artifacts/eval/4omini
diff <(jq '.pass_rate, .score_mae' artifacts/eval/41mini/eval_*.json | tail -1) \
     <(jq '.pass_rate, .score_mae' artifacts/eval/4omini/eval_*.json | tail -1)
```

### 5.5 Circuit breaker is actually breaking

**What this validates:** After enough consecutive HTTP errors, the
breaker trips and subsequent tasks short-circuit instead of hammering
the LLM.

```bash
# Temporarily point OPENAI_API_KEY at a bogus value in the worker env
# (or set a low threshold to make this easy to reproduce)
docker compose exec -T worker python -c "
from app.services import circuit_breaker
# Simulate 10 failures
for _ in range(10):
    circuit_breaker.record_failure('openai:scoring')
print('is_open:', circuit_breaker.is_open('openai:scoring'))
# Manual reset after testing
circuit_breaker.record_success('openai:scoring')
print('after reset is_open:', circuit_breaker.is_open('openai:scoring'))
"
# Expected: is_open: True   then   is_open: False
```

---

## 6. Evaluation commands

### 6.1 M3 quality

```bash
# Latest run summary (text)
docker compose exec -T worker python scripts/run_eval.py

# Time-series of quality over the last N runs (requires jq)
ls -t artifacts/eval/eval_*.json | head -10 | while read f; do
  jq -r --arg file "$(basename $f)" \
    '[.started_at, .pass_rate, .score_mae, .topic_accuracy] | @tsv' "$f"
done | column -t
```

### 6.2 Cost burn

```bash
# Total LLM spend by scope
docker compose exec -T worker python scripts/llm_cost_report.py

# Cheap jq one-liner against the raw ledger
docker compose exec -T worker sh -c "
  jq -r '[.scope, .total_cost_usd] | @tsv' artifacts/llm_usage/llm_usage.jsonl \
    | awk '{sum[\$1] += \$2} END {for (k in sum) printf \"%-20s \$%.4f\n\", k, sum[k]}'
"
```

### 6.3 Pipeline lag

```bash
# How long from change-detection to scoring to obligation-extraction?
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT
    percentile_cont(0.50) WITHIN GROUP (ORDER BY scored_at  - detected_at) AS p50_score_lag,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY scored_at  - detected_at) AS p95_score_lag,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY obligations_extracted_at - scored_at) AS p50_oblig_lag,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY obligations_extracted_at - scored_at) AS p95_oblig_lag,
    COUNT(*) FILTER (WHERE significance_score IS NULL) AS unscored_count,
    COUNT(*) FILTER (WHERE scored_at IS NOT NULL AND obligations_extracted_at IS NULL AND significance_score >= 0.6) AS pending_obligations
  FROM change_events
  WHERE detected_at > now() - interval '7 days';
"
```

### 6.4 Delivery success rate

```bash
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT
    COUNT(*)                                              AS total_alerts,
    COUNT(*) FILTER (WHERE delivered_at IS NOT NULL)      AS delivered,
    COUNT(*) FILTER (WHERE delivery_error IS NOT NULL
                     AND delivered_at IS NULL)            AS failed,
    COUNT(*) FILTER (WHERE delivery_attempts >= 5
                     AND delivered_at IS NULL)            AS dead_lettered,
    round(
      100.0 * COUNT(*) FILTER (WHERE delivered_at IS NOT NULL)
      / NULLIF(COUNT(*), 0), 1
    ) AS success_pct
  FROM alerts
  WHERE created_at > now() - interval '24 hours';
"
```

### 6.5 Content filter yield

```bash
docker compose exec -T worker sh -c "
  make logs-worker 2>&1 | grep 'content_filter:' | tail -20
"
```

### 6.6 Workflow throughput

```bash
docker compose exec -T db psql -U regwatch regwatch -c "
  SELECT
    workflow_status,
    COUNT(*)                                       AS alerts,
    COUNT(*) FILTER (WHERE assigned_to IS NOT NULL) AS assigned,
    COUNT(*) FILTER (WHERE due_date < current_date AND workflow_status IN ('open','in_progress')) AS overdue
  FROM alerts
  GROUP BY workflow_status
  ORDER BY 1;
"
```

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No alerts for any user | Broken `keyword_query` on one subscription | Validation should prevent this at POST. Check logs for `Invalid keyword_query syntax`; verify migration 013/015 applied. |
| Every event gets dropped by the content filter | Threshold too aggressive for your corpus | Lower `CONTENT_FILTER_MIN_WORDS` / `_MIN_KEYWORD_HITS` via env, or disable with `CONTENT_FILTER_ENABLED=false` while you inspect. |
| Federal Register task silent | `FEDERAL_REGISTER_DAYS_BACK=0` or no new rules today | Bump `days_back`; check Flower for task execution. |
| Obligation extractor produces 0 obligations | Source text not passing chunk filter | Check `chunks_processed` in the task log. If 0, `raw_text` was empty — verify the ingester populated it. |
| Emails silently not sent | `ALERT_DELIVERY_ENABLED=false` | Set it to `true`, restart worker. `deliver_alert` logs `delivery_disabled_skipping` when the kill switch is off. |
| `trigger_span_located=False` on most events | LLM paraphrasing instead of quoting | Expected rate 10–20%. If higher, tighten the prompt's "copy VERBATIM" language or move to a stronger model. Run the eval harness to measure. |
| Alerts pile up as `delivery_attempts = 5, delivered_at = NULL` | Exhausted retries (dead-lettered) | Query via the partial index `idx_alerts_pending_delivery`; after fixing the SMTP issue, re-enqueue with a small script loop. |
| Invalid workflow transition returned 200 instead of 409 | Client may be hitting a stale `PATCH /api/alerts/{id}` (status only) | The workflow transition endpoint is `PATCH /api/alerts/{id}/workflow`, not `/api/alerts/{id}`. |

---

## 8. Order-of-operations checklist for a fresh deploy

```bash
# 1. Pull the code (includes migrations 012-015 and all new services)
git pull

# 2. Set env vars (minimal)
cat >> .env <<'EOF'
OPENAI_API_KEY=sk-...
CONTENT_FILTER_ENABLED=true
ALERT_DELIVERY_ENABLED=false          # flip to true after verifying matches
FEDERAL_REGISTER_DAYS_BACK=2
EOF

# 3. Bring the stack up
make up

# 4. Apply migrations
make migrate

# 5. Health check
curl -s http://localhost:8001/health | python -m json.tool

# 6. Run the eval harness as a baseline
docker compose exec -T worker python scripts/run_eval.py

# 7. Trigger one Federal Register poll to prove the new lane works
docker compose exec -T worker python -c "
from app.celery_app import federal_register_api_task
print(federal_register_api_task.delay(days_back=2, max_documents=5).id)
"

# 8. Wait ~5 min for full M1→M4 to run; verify with the SQL in §5.2.

# 9. Create a pilot subscription (§5.3 step 1). Watch the matcher + delivery.

# 10. When you're confident, set ALERT_DELIVERY_ENABLED=true and restart worker.
```

---

## 9. What the pro-max arc does NOT cover

Kept honest on purpose — these are deliberate scope choices, not missing
code.

- **Authentication / multi-tenancy.** `user_email` is the only identity.
  Fine for a pilot; table-stakes before a real customer.
- **Slack / Teams / webhook notifiers.** The `Notifier` Protocol is
  there. Each adapter is ~50 LOC.
- **UI.** API + email only. Swagger on `/docs` is the admin view.
- **Layer 2 embedding gate** (`bge-small` ONNX) — needs a new runtime
  dependency; clean separate PR.
- **Layer 3 URL-pattern bandit.** Schema columns (`urls.priority`,
  `hub_score`, `trap_score`) exist but aren't wired to M3 outcomes yet.
- **More structured-feed adapters.** Federal Register shipped; EUR-Lex,
  SEC EDGAR, FCA RSS-by-category are one-at-a-time additions.

---

*Generated for the pro-max release. See `CLAUDE.md` for agent context
and `docs/architectural_problems.md` for the pre-existing flaws this
arc addressed.*
