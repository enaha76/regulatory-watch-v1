# Mock Website Admin Guide

A web UI to manage the regulations served by the mock ATCA website. Use it to
add, edit, and delete regulations so you can drive end-to-end tests of the
regulatory-watch crawler and change-detection pipeline.

---

## What this is for

The crawler in this project ingests regulations from external sites
(EUR-Lex, FCA, Federal Register…). Those external sites change on their own
schedule, which makes them useless for repeatable testing. The mock-website
solves that: it's a fake regulatory site **you control**, so you can publish
a regulation, run the crawler, edit the regulation, run the crawler again,
and watch the change-detection pipeline pick up the diff.

The admin UI lets you do this without editing JSON files by hand.

---

## URLs

| URL | What you'll see |
|-----|-----------------|
| `http://mock-website.local/admin` | Admin dashboard (the UI) |
| `http://mock-website.local/` | Public mock website (what the crawler sees) |
| `http://mock-website.local/regulations/<slug>.html` | A specific regulation page |
| `http://mock-website.local/documents/<filename>.pdf` | A generated PDF |
| `http://mock-website.local/rss.xml` | RSS feed of all regulations |

`mock-website.local` resolves to `127.0.0.1` via `/etc/hosts`. nginx on port
80 forwards everything to the Express server on `:3001`.

---

## How to start it

From `mock-website/` directory:

```bash
# 1. Build the admin SPA (only required after editing src/*)
npm run build:admin

# 2. Start the server (serves both the public site and the admin)
npx tsx server.ts
```

Server boot output should show:

```
Mock website running on http://0.0.0.0:3001
  Static dir : .../mock-website/mock_server/data
  Data dir   : .../mock-website/data
  Admin dist : .../mock-website/dist/admin (built)
```

If it says `(NOT built)`, run `npm run build:admin` first.

---

## What you can do in the admin

### List view (`/admin`)

Shows every regulation in a table:

| Column | Meaning |
|--------|---------|
| Title | The regulation's display title (slug shown below in monospace) |
| Category | `regulations`, `notices`, or `guidance` (color-coded badge) |
| Effective | The effective date (if set) |
| Updated | Relative time since last edit |
| PDF | 📄 if a PDF is generated for this entry |
| Actions | Edit, View, Delete |

Three buttons next to each row:

- **Edit** — opens the editor for this regulation
- **View** — opens the public regulation page in a new tab
- **Delete** — opens a red confirm dialog; on confirm, removes JSON + HTML + PDF

Plus a **+ New Regulation** button at the top right.

### Create view (`/admin/new`)

Blank form. Required fields:

- **Slug** — unique identifier in the URL. Must match `[a-z0-9][a-z0-9-]{1,80}`.
  Example: `tariff-schedule-2026`. Cannot be changed after creation.
- **Category** — one of `regulations | notices | guidance`. Determines which
  folder the page lives in. Cannot be changed after creation.
- **Title** — display title shown on the public page.

Optional fields:

- **Subtitle** — small text above the title (e.g. "CFR Title 19, Chapter IV")
- **Effective Date** — date picker
- **Reference Number** — e.g. "ATCA/TS/2026/001"
- **Summary** — paragraph shown below the title; also used in the RSS feed
- **Generate PDF** — checkbox. If on, a PDF is built from the same content

Then a **Sections** area to add content (see below).

### Edit view (`/admin/edit/<slug>`)

Same form as Create, pre-filled with the existing JSON. Slug and category
are locked (delete + re-create if you really need to change them).

---

## The Sections editor

A regulation's body is a list of typed sections. Each section type renders
differently in HTML and PDF.

| Section type | Use it for |
|--------------|------------|
| **heading** | A section heading. Levels: H1, H2, H3 |
| **paragraph** | A block of plain text |
| **list** | Bullet or numbered list (toggle with checkbox) |
| **table** | Data table with column headers and rows |
| **note** | A boxed callout — info (blue), warning (amber), critical (red) |

Each section card has:

- **↑ / ↓** buttons — reorder
- **Remove** button — delete this section

Add new sections via the buttons at the bottom: `+ heading`, `+ paragraph`,
`+ list`, `+ table`, `+ note`.

For tables: click `+ col` to add columns, `+ row` to add rows. Each cell is
free text. The `✕` button on a row removes that row.

---

## What happens when you save

1. Form sends `POST /api/regulations` (create) or `PUT /api/regulations/:slug` (edit)
2. Server writes the JSON file to `data/<category>/<slug>.json`
3. Server runs `scripts/generate_html.ts --all` — rebuilds every HTML page
   plus category indexes, the home page, and `rss.xml`
4. Server runs `scripts/generate_pdf.py --all` — rebuilds every PDF that has
   `pdf.enabled: true`
5. UI redirects you to the list view

Nothing is queued — it's synchronous. By the time you're back on the list,
the public site is already live with the change.

---

## What happens when you delete

1. UI shows a red confirm dialog with the regulation's title
2. On confirm: `DELETE /api/regulations/:slug`
3. Server removes:
   - The JSON file (`data/<category>/<slug>.json`)
   - The generated HTML (`mock_server/data/<category>/<slug>.html`)
   - The generated PDF (if any)
4. Server rebuilds the rest of the site so links to the deleted page no
   longer appear in the index pages or RSS

---

## Typical test scenarios

### Test 1 — Detect a numeric change

1. **Edit** `tariff-schedule-2026`. In the table section, change the Lithium
   batteries duty rate from `3.4%` to `7.5%`.
2. **Save**.
3. Trigger your crawler against `http://mock-website.local/`.
4. Check `change_events` — you should see a `modified` event with the diff
   showing `3.4%` → `7.5%`.
5. Check the LLM significance score; substantial threshold change should
   score above 0.6 and trigger obligation extraction.

### Test 2 — Detect a new deadline

1. **Edit** any notice. Add a new `note` section with style "critical":
   *"All importers must file Form ATC-2 by 2026-08-15."*
2. **Save**.
3. Crawl. Check that the LLM picks up the new deadline and that an
   `obligation` row is created with `deadline = 2026-08-15`.

### Test 3 — Cosmetic change should NOT trigger an alert

1. **Edit** any regulation. Change "shall result in" to "will result in" in
   a paragraph.
2. **Save**.
3. Crawl. Verify the LLM scores this below 0.6 (typo / minor wording) and
   does not create alerts.

### Test 4 — New regulation appears

1. Click **+ New Regulation**. Slug `test-2027-tariff`, title
   "Test Tariff 2027", a few sections.
2. **Save**.
3. Crawl. The crawler should pick up the new URL, ingest it, and produce a
   `created` change event.

### Test 5 — PDF content change

1. **Edit** `tariff-schedule-2026` (which has PDF enabled). Change values
   inside the table or summary.
2. **Save**. The PDF is regenerated.
3. Crawl. The PDF connector should detect a hash change and produce a
   modified change event for the PDF document.

---

## Where things live

```
mock-website/
├── data/                          ← source-of-truth JSON (what you edit)
│   ├── regulations/*.json
│   ├── notices/*.json
│   └── guidance/*.json
├── mock_server/data/              ← generated output (what crawler reads)
│   ├── index.html
│   ├── regulations/*.html
│   ├── notices/*.html
│   ├── documents/*.pdf            ← generated PDFs
│   └── rss.xml
├── scripts/
│   ├── generate_html.ts           ← reads JSON, writes HTML + indexes + RSS
│   └── generate_pdf.py            ← reads JSON, writes PDFs
├── src/                           ← React admin UI source
│   ├── App.tsx                    ← Router (BrowserRouter, basename "/admin")
│   ├── api.ts                     ← typed fetch wrappers + types
│   ├── components/
│   │   ├── Layout.tsx             ← page shell with nav
│   │   ├── ConfirmDialog.tsx      ← delete confirm modal
│   │   └── SectionEditor.tsx      ← 5-type section editor
│   └── pages/
│       ├── AdminHome.tsx          ← list view + delete
│       └── Editor.tsx             ← create + edit form
├── dist/admin/                    ← built admin SPA (served at /admin)
└── server.ts                      ← Express server (API + SPA + static site)
```

## API endpoints (also callable directly with curl)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/regulations` | — | `{items: [...]}` list of all regulations |
| GET | `/api/regulations/:slug` | — | Full regulation JSON |
| POST | `/api/regulations` | `{slug, category, title, ...}` | `{ok, slug, category}` |
| PUT | `/api/regulations/:slug` | Full regulation JSON | `{ok, slug}` |
| DELETE | `/api/regulations/:slug` | — | `{ok, deleted}` |
| POST | `/api/regenerate` | — | Forces full rebuild of all HTML + PDFs |

Slug constraint: `^[a-z0-9][a-z0-9-]{1,80}$` (lowercase, digits, hyphens).
Category must be `regulations | notices | guidance`.

Example:

```bash
curl http://mock-website.local/api/regulations | jq

curl -X POST http://mock-website.local/api/regulations \
  -H 'content-type: application/json' \
  -d @new-rule.json
```

---

## Development workflow

When editing the admin UI source code:

```bash
# Option A: rebuild after changes
npm run build:admin
# refresh browser

# Option B: hot reload via vite dev server
npm run dev:admin
# opens http://localhost:5173 with /api proxied to :3001 automatically
# (server.ts must still be running on :3001 for the API to work)
```

When editing a generator (`scripts/generate_*.ts` or `.py`):

```bash
npm run build:site
# regenerates all HTML + PDFs from current JSON
```

When editing JSON directly (no UI):

```bash
# After editing a JSON file by hand:
npm run build:site
# Or call /api/regenerate via the server
curl -X POST http://mock-website.local/api/regenerate
```

---

## Troubleshooting

**Admin page shows "Admin UI not built"**
Run `npm run build:admin` and refresh.

**Save fails with "regeneration failed"**
Check the server log. Most likely the Python PDF generator is missing a
dependency (`pip install reportlab`) or the slug already exists.

**Browser shows old content after save**
Hard refresh (Ctrl+Shift+R). The HTML is rebuilt synchronously, but your
browser may have cached the old page.

**Slug rejected with "must match [a-z0-9-]"**
Slugs must start with a letter or digit, contain only lowercase letters,
digits, and hyphens, and be 2–81 characters total.

**Delete button does nothing**
Open browser DevTools network tab. The DELETE request should return 200.
If it returns 404, the regulation file may have been removed by something
else; refresh the page.

**Public page still shows after delete**
nginx may be caching. Hard-refresh the browser. The file in
`mock_server/data/<category>/<slug>.html` should be gone.
