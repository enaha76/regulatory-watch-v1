# Regulatory Watch — Architecture Speech (Presenter Script)

Use this while `docs/architecture_v2.html` (or your slide deck) is on screen. **Read in full sentences**; do not rush the pauses.

**How to use this file**

| Version | When | Where below |
|--------|------|----------------|
| **Elevator** | Someone asks “what does it do?” in one breath | § Elevator |
| **Standard** | Main architecture walk-through (~5–6 min) | § Standard — full script |
| **Deep dive** | Technical audience, Q&A after | § Deep dive add-ons |

**Delivery**

- **Pause** where you see `…` or a blank line — that is intentional breathing room.
- **Emphasis**: slightly lift your voice on the words in *italics* (not shout).
- **Gesture**: trace the diagram left-to-right once at the start (“data flows this way”).

---

## Elevator (~45 seconds)

Regulators publish in a *mess* of formats: HTML that only renders in a browser, PDF rulings, RSS, XML, sometimes email. Compliance teams cannot manually watch all of it, and they cannot afford to run an expensive language model on every page every hour.

**Regulatory Watch** is the middle layer that fixes that. We ingest everything into one pipeline, fingerprint every document with a cryptographic hash, and only when the content *actually* changes do we open a unified diff and send *that* to a small, fast model. The model returns a score, a topic, entities like tariff codes, origin and destination countries, and a plain-English summary. If the change matters, a second pass extracts structured *obligations*: who must do what, by when, with what penalty.

Everything is stored in Postgres, every model call is costed in a ledger, and workers share a circuit breaker so an outage does not become a billing disaster. That is the architecture in one sentence: **ingest, gate, enrich, prove.**

---

## Standard — full script (~5–6 minutes)

### Hook — why this exists

If you have ever owned a compliance monitoring workflow, you know the failure mode is not “we missed the internet.” The failure mode is *noise*: the navigation bar changed, a cookie banner moved, a timestamp updated — and your team spent half a day deciding whether anything legally material happened.

**Regulatory Watch** is built around the opposite idea: *the system should do the boring work deterministically, and the model should only speak when there is something real to say.*

Let me walk the diagram the same way the data walks it.

### Sources — the messy real world

At the top you see **sources**. In production, that is not a tidy API. It is government websites that need a real browser, it is fifty-page PDFs, it is XML and RSS feeds, and it can include email lists from agencies.

The architecture does not pretend every source is the same file format. It admits they are different, then **normalises them into one contract**: text, title, language, hash, and a pointer to the raw artifact if we need to reprocess.

### Ingestion — first mile, no magic

The first big band on the diagram is **ingestion**.

The web path is worth naming because it is where people stop believing slide decks: we use **Crawl4AI with Playwright** so JavaScript-heavy pages are real pages, not broken curl snapshots. PDFs go through **pdfplumber**. RSS and XML go through parsers you would expect. Email has its own connector.

Two things happen on every document before we get fancy. First, **language detection** — the corpus is multilingual; the model reads the source language natively and still emits **English** as the canonical analysis language. Second, a **SHA-256 hash** of the normalised body. That hash is not a checksum for fun; it is the **economic gate** for everything downstream.

We persist to **PostgreSQL** as `raw_documents`, and we can park the original bytes in **object storage** so “re-run the pipeline with a better extractor next year” is a configuration change, not a archaeology project.

### Change detection — where money and trust are won

The next band is **change detection**, and this is the sentence I want you to remember: **if the hash matches the last version, we stop.** No diff, no event, no tokens, no dollars.

When the hash differs, we create an immutable row in **`source_versions`** — a snapshot you can audit — and a **`change_events`** row that carries *what changed*: created versus modified, how many characters moved, and when we have two bodies, a **unified diff**.

Notice what is still *not* in that sentence: artificial intelligence. Hashing and diffing are deterministic. They are cheap at scale. They are also the reason you can tell your finance partner, with a straight face, that you are not “running GPT on the entire government internet.”

### Enrichment — intelligence only after the gate

Only now does the **significance** path run. One call to a small model — we use **`gpt-4o-mini` in JSON mode** — returns a tight bundle: *how* important the change is, *what kind* of change it is, *which topic bucket* it belongs to, *which entities* are touched — including tariff surface forms when they appear in the text — *which origin countries* the language model can justify from the document, and a **short compliance summary** written in second person so a human can scan it.

**Destination jurisdiction** is not guessed by the model. We derive it **deterministically from the URL** — for example a `cbp.gov` host maps to United States jurisdiction — because that should not drift with prompt temperature.

Entities are **normalised and indexed** so “FCA” and “Financial Conduct Authority” collapse to one queryable identity. That is how you get from paragraphs to filters.

Then comes the second model, **obligations extraction**, and here is the product discipline: it runs when the score crosses a threshold we set around **substantive impact**. Cosmetic churn does not earn a second bill. The output is rows a dashboard can render tomorrow: actor, action, condition, deadline, penalty, type.

### Cross-cutting — how you run this in production

Parallel to the happy path, two boxes matter for anyone who has operated software under load.

**LLM usage ledger**: every completion is appended with tokens, latency, scope, and estimated dollars. That is not vanity metrics; it is how you prove ROI and catch regressions when someone ships a prompt that suddenly doubles input size.

**Circuit breaker in Redis**: if the provider is failing, every worker sees the same red flag and backs off. That is the difference between “we had an incident” and “we accidentally minted a five-figure OpenAI invoice while retrying blindly.”

Structured logs tie the story together in your observability stack.

### Roadmap — honesty builds credibility

The dashed boxes at the bottom are deliberate. **Personalised alerts** and a **React dashboard** are the natural consumer of this signal; they are planned, not vaporware, but they are not what we are shipping as the core thesis today.

The thesis today is: **a clean, queryable regulatory event graph with defensible spend and defensible provenance.**

### Close — one line they repeat in the corridor

If you take nothing else away, take this: **we turned regulatory firehoses into a gated pipeline — deterministic first, model second, ledger always — so compliance can filter on facts instead of drowning in files.**

I am happy to zoom into connectors, scoring, obligations, or cost. What would you like to see first?

---

## Deep dive add-ons (optional, after questions)

Use these *only* if the room wants detail. Each block is roughly thirty to sixty seconds spoken.

### On “why not translate the whole web with a small MT model?”

We removed a classic “translate everything to English first” stage on purpose. Modern small chat models already read multiple scripts; translating twice would add latency, add error, and add weight without improving the outcome. English is still the **canonical analysis language** for search and matching; the original text stays in the database for audit.

### On “how do you prove the diff is real?”

Show one `show_changes` line with `+chars` / `-chars` and, if you have it, a **forty-line unified diff** for a single URL. The point is not the syntax; the point is *we can show the machine-readable delta that triggered the model.*

### On “HS codes and tariffs”

If you backfilled or indexed codes, one SQL or `show_entities` moment lands well: **from prose to a filterable code column** without hand-tagging.

### On “countries and trade flow”

One example row: `origin_countries` includes **CN**, `destination_countries` includes **US**, `trade_flow_direction` is **inbound**. That is a product sentence: “China-origin goods entering US jurisdiction,” queryable in SQL.

---

## If you lose the room — recovery lines

- **Too abstract**: “Concrete example: CBP trade crawl, fifteen HTML pages plus three PDFs, sixty seconds wall clock, every line item in the summary table is a row we can query.”
- **Too technical**: “Think of it as Git for regulations: commit hash, diff, then a reviewer — except the reviewer is a model with a price tag we measure.”
- **Cost sceptic**: “Pull `llm_cost_report.py`; the numbers are not estimates from a slide — they are summed from the ledger.”

---

## Timing cheat sheet

| Block | Approx. |
|--------|--------|
| Hook + sources | ~60 s |
| Ingestion | ~75 s |
| Change detection | ~75 s |
| Enrichment | ~90 s |
| Cross-cutting + roadmap + close | ~90 s |
| **Total** | **~8–9 min** if you use every optional beat; **~5–6 min** if you tighten pauses |

**One-minute cut**: Hook → “hash gate, no LLM” → “one scoring call, optional obligations” → ledger + breaker → closing line.

---

## Phrases worth memorising (three is enough)

1. *“Deterministic first, model second, ledger always.”*
2. *“We do not buy intelligence for boilerplate.”*
3. *“Same pipeline, every format — one contract into the database.”*

---

## After this slide — natural hand-off to demo

“Architecture is the promise; the terminal is the receipt. If we switch screens for ninety seconds, I will show you a live crawl summary, a filtered change list, one obligation extract, and the token ledger for the last run.”

That sentence bridges cleanly into `docs/demo_commands.md`.
