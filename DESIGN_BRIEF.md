# RegWatch — Frontend Design Brief

> Self-contained design brief for redesigning the entire RegWatch frontend.
> Paste this into Figma Make / v0.dev / Lovable / Bolt / a human designer.
> The backend, API contracts, and data shapes are fixed; only the **frontend
> visual & interaction layer** is open for redesign.

---

## 1. What this app is, in one paragraph

**RegWatch** is an enterprise regulatory-monitoring product. It crawls
government sites (US Federal Register, US Customs & Border Protection,
India's DGFT, EU Commission, etc.), runs LLM analysis on every change it
detects, and surfaces only the *material* changes to the user as alerts —
each with a one-line headline, a plain-English summary, structured
compliance obligations (who must do what, by when), a diff of what
changed at the source, and a relevance score. The user is a compliance
officer, customs broker, or trade lawyer at a mid-market or Fortune 500
company. They open this app first thing in the morning to see what
regulators changed overnight that they need to act on.

**The job-to-be-done:** *"Tell me which of yesterday's regulatory
changes I personally need to act on, and what specifically I need to do."*

---

## 2. Comparable products (for visual reference)

The redesign should feel like a peer of these:

| Product | What to borrow |
|---|---|
| **Linear** | Calm, dense issue lists. Hover-reveal actions. Strong keyboard nav. Subtle borders, soft shadows. Status icons not status badges. |
| **Superhuman** | Email-inbox-style row density. Sender + subject + 1-line snippet + time. Bold for unread, normal for read. |
| **Bloomberg Terminal** | Information density. Tabular numbers. Color-coded severity. Tickers and small headlines. |
| **Stripe Dashboard** | Beautiful empty states. Generous whitespace around primary actions. Clean stat tiles. |
| **Vercel Dashboard** | Sticky save bars. Subtle accent colors. Mono fonts for IDs. Dark mode that doesn't feel like a hack. |
| **Notion** | Type hierarchy that breathes. Iconography that's calm, not decorative. |

Avoid: 2014 admin dashboards, Material Design heavy shadows, cartoon
illustrations, gradients-for-the-sake-of-gradients, oversized buttons.

---

## 3. Target user

**Persona: Sarah, Senior Compliance Manager at a $2B importer.**
- Reviews 30–80 regulatory alerts a day across multiple jurisdictions.
- Power user — wants keyboard shortcuts, dense displays, fast triage.
- Reads on a 27" external monitor (1920–2560px wide) most of the time;
  occasionally on a laptop (1440px) and rarely on tablet/mobile.
- Will judge the tool's professionalism in the first 10 seconds. If it
  looks like a startup MVP, she'll forward to her assistant; if it
  looks like Linear, she'll use it herself.

The bar is **"this looks like something a Big4 partner would be
comfortable opening in front of a client."**

---

## 4. Tech stack the redesign must work with

These are non-negotiable — the redesign must produce code that drops
into the existing project:

- **Framework:** Vite 6 + React 18 + TypeScript
- **Routing:** `react-router` v7 with HashRouter (URLs use `#/path`)
- **Styling:** Tailwind CSS v4 with CSS variables for theming
- **Component library:** shadcn/ui (Radix primitives + Tailwind). All
  primitives already imported and customised via `@/app/components/ui/*`.
- **Icons:** lucide-react
- **Charts:** Recharts
- **Auth:** Keycloak (the UI never renders the login screen — Keycloak
  hosts it; the app sees a logged-in user via `useAuth()`)

CSS variables that already exist (light + dark):
`--background --foreground --card --primary --secondary --muted --accent
--destructive --border --sidebar --sidebar-foreground --ring
--font-sans --text-xs --text-sm --text-base --text-lg --text-xl
--font-weight-normal --font-weight-medium --font-weight-bold`

Default font: **Inter** (Google Fonts). Use `tabular-nums` for all
numeric columns.

---

## 5. Brand & visual direction

### Current palette (light mode)
- **Primary** — navy `#1B2A6B` (used for buttons, links, sidebar bg)
- **Accent** — amber `#F5A623` (used for badges, highlights, "Beyond Borders" tagline)
- **Destructive** — red `#E42308` (errors, critical alerts ≥ 80% relevance)
- **Background** — near-white `#FAFAFA`
- **Foreground / text** — near-black `#0F1424`
- **Muted** — slate `#7E869F`

### Typography scale (already in CSS variables)
- `--text-xs` 13px (meta, chips, hints)
- `--text-sm` 14px (body in tight contexts)
- `--text-base` 16px (default body)
- `--text-lg` 18px (section titles)
- `--text-xl` 22px (page titles)
- Weights: 400 / 500 / 700

You can evolve the palette but **keep it sober and enterprise-feeling**.
No purple, no neon, no playful palettes. The accent amber is what gives
it personality — keep something with that role.

### Logo
A round navy badge with a white tower silhouette + an amber arc.
Wordmark: **MyTower** in bold + tagline **"Beyond Borders"** in amber.
Do not redesign the logo.

### Dark mode
Required. The CSS variables flip automatically when `class="dark"` is
on `<html>`. Sidebar stays navy in both modes (it's our brand anchor).
Body goes from near-white to near-black.

---

## 6. App shell — what's always on screen

```
┌─────────────────────────────────────────────────────────────────┐
│ [SIDEBAR  240px]  │  [HEADER 56px tall]                         │
│                   │  Toggle / Page title         [Health dot]   │
│ MyTower           ├─────────────────────────────────────────────┤
│ Beyond Borders    │                                             │
│ Global Trade …    │                                             │
│                   │              [PAGE CONTENT]                 │
│ □ Inbox      [9]  │                                             │
│ □ Archive         │                                             │
│ □ Reg Search      │                                             │
│ □ Areas of Int    │                                             │
│ □ Sources         │                                             │
│ □ LLM Costs       │                                             │
│                   │                                             │
│ ──────────        │                                             │
│ Ahmed ENAHA       │                                             │
│ ahmed@example     │                                             │
│ ☾ Dark mode       │                                             │
│ ➜ Sign out        │                                             │
└─────────────────────────────────────────────────────────────────┘
```

- Sidebar collapsible to icon-only via the toggle button.
- Inbox nav item shows a small amber count badge for unread alerts.
- The "Health" dot in the header is green when all sources & workers are
  healthy, amber if any source is degraded, red if any is blocked.
- User identity + dark-mode toggle + sign out cluster at the bottom of
  the sidebar.

---

## 7. Pages — what each one shows

### 7.1 Inbox (primary view)

The most important page. Sarah opens this 50× a day.

**Goal:** Let her triage 30–80 alerts in 5 minutes — read the headline,
decide relevance, take an action, move on.

**Toolbar (top of page):**
- Tagline: "Review pending alerts on global trade regulatory changes"
- Right-aligned controls:
  - `Include read` toggle
  - `Filter` button (opens popover: country checkboxes + regulation-type checkboxes)
  - `Sort` dropdown (Newest / Oldest / Relevance high / Relevance low)
  - vertical divider
  - `Export CSV` button
  - small keyboard hint: `[j] [k] to navigate`
- Optional review-progress bar (only shown after the user has reviewed ≥1 alert today)

**Search bar:** "Search alerts by title, country, authority, type, or product…"

**The list itself:** This is the design centerpiece. Each row should
have just enough information to triage without opening the detail page.

Per-row data available (this is the EXACT API contract):
```ts
{
  id: string;                         // UUID
  title: string;                       // already a real headline like
                                       // "ATF: Remove Outdated Proscribed
                                       //  Countries List for Defense Imports"
  country: string;                     // "United States" / "India" / "European Union"
  authority: string;                   // "US Customs and Border Protection"
  regulationType: string;              // "Tariff & Duties" / "Sanctions & Export Control" / …
  publicationDate: string;             // ISO 8601 datetime
  affectedProducts: string[];          // ["8541.40.60", "8517.62.00"]
  relevanceScore: number;              // 0–100
  status: "new" | "read" | "archived";
  userFeedback?: "relevant" | "not_relevant" | "partially_relevant" | null;
  pinned?: boolean;
  tradeLane: string;                   // "*->US" / "CN->EU" — origin->destination
}
```

Per-row actions (with current keyboard shortcuts):
- Pin/Unpin (`p`)
- Mark seen / Mark new (`r`)
- Archive (`e`)
- Mark relevant / partially relevant / not relevant (thumbs up / clock / thumbs down)
- Open detail page (`Enter` or click title)

**Required visual states:**
- **Unread:** stronger weight on title; small primary-blue dot or left-edge stripe
- **Pinned:** small pin icon next to title
- **Reviewed:** faded row + the chosen feedback shown as a chip (with an undo button on hover)
- **Keyboard-focused:** clear ring/outline around the row (j/k navigation)
- **Hover:** action icons fade in (idle row should be calm, hovered row gets controls)

**Empty state:** "Inbox zero — nice work." With a check icon and an
encouraging line. Show some next-step affordance ("Browse archive" /
"Adjust your areas of interest").

**Loading state:** Skeleton rows (4–6), not a centered spinner.

**Important:** rows should NOT have empty horizontal space when actions
are hidden. The right side should naturally collapse to date + score
when there's nothing else to show.

### 7.2 Alert detail

Opened when the user clicks a row or presses Enter.

**Layout:**

```
[← Back to Alerts]                              [75% Relevance] (badge)
┌─────────────────────────────────────────────────────────────────┐
│ 🇺🇸  ATF: Remove Outdated Proscribed Countries List…            │  ← page title (h1)
│      [📄 Authority] · [📍 Country] · [📅 Date]                  │  ← meta row
│      [Sanctions & Export Control]                                │  ← topic chip
│                                                                  │
│  Summary                                                         │  ← section
│  ┌─ │ The Bureau of Alcohol, Tobacco, Firearms, and Explos.. │  ← left-stripe card
│  │  │ The new rule will reference a Department of State list… │
│  │  │ You need to ensure compliance with these updated rules. │
│  └─                                                              │
│                                                                  │
│  Compliance Obligations                                  [2]     │  ← section + count
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ [ACTION]  importers of defense articles and services      │ │
│  │ Ensure compliance with the updated regulations…           │ │
│  │                                            Deadline: —    │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │ [PROHIBITION]  importers of firearms and ammunition       │ │
│  │ Do not import from any country other than Russia.         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  What changed   [Substantive change]  +620 · -188 chars  [Show raw diff]
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ BEFORE  (red strip)                                        │ │
│  │ The Bureau of Alcohol, Tobacco… (struck through)          │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │ AFTER  (green strip)                                       │ │
│  │ The Bureau of Alcohol, Tobacco… (new content)             │ │
│  └────────────────────────────────────────────────────────────┘ │
│  [Show 8 formatting changes]                                    │ ← cosmetic-fold toggle
│                                                                  │
│  Documents & Source                                              │
│  📥 Download Official Document (PDF)                             │
│  ↗  View Original Source                                         │
└─────────────────────────────────────────────────────────────────┘
```

Floating "Ask AI about this alert" pill at bottom-right (currently disabled / "soon").

**Obligation card data shape:**
```ts
{
  id: string;
  type: "reporting" | "prohibition" | "threshold" | "disclosure"
      | "registration" | "penalty" | "other";
  actor: string;       // "importers of defense articles and services"
  action: string;      // imperative verb phrase
  condition: string | null;
  deadlineText: string | null;  // free text as written
  deadlineDate: string | null;  // resolved ISO date
  penalty: string | null;
}
```

Color-tier the obligation type badge: prohibition → red; reporting/disclosure → primary navy; threshold → amber; registration → emerald; penalty → red; other → muted.

If a deadline is < 7 days away, render the deadline pill in red with an "overdue" or "due in N days" label.

### 7.3 Archive

Same row layout as Inbox, but for `status: "archived"` alerts.
Each row has a "Restore" button that returns it to the inbox.
Empty state: "Nothing archived yet."

### 7.4 Regulatory Search

Full-corpus semantic search over every alert (new + read + archived).

**Layout:**
- A single fat search input at the top (placeholder: "Search by title,
  country, authority, regulation type, HS code, or trade lane…").
- **When empty:** show 3–5 example query chips ("All US sanctions changes",
  "China tariff updates", "Critical changes this week", "Anti-dumping
  reviews") that populate the search on click. Plus a small stat:
  "*N alerts indexed.*"
- **When typed:** results render as a list using the same row design as
  the inbox.
- Results are de-duplicated by underlying change-event (same as inbox).

### 7.5 Areas of Interest

User-editable preferences that drive what alerts the user receives.

Three tabs: **Products (HS Code)** · **Geography** · **Keywords**

**Products (HS Code) tab:**
- Two-column layout.
- Left: tree-style HS code picker with check-boxes. Top-level chapters
  (84 — Nuclear reactors, 85 — Electrical machinery, 72 — Iron and steel)
  expand to sub-headings (8541 — Semiconductor devices) which expand to
  full 6/8/10-digit codes (8541.40.60 — Photosensitive semiconductor
  devices). Search box at the top of the left column.
- Right: a "Selected Products" panel listing every checked code as a
  card (code + description + ✕ remove button). A "Clear all" link at the top.

**Geography tab:**
- World map (subtle, monochrome background) with countries highlighted
  as user toggles them. OR a simpler regions+countries multi-select if
  the map is too heavy. Show selected countries as flag chips below.

**Keywords tab:**
- A tag-input field where the user types and presses Enter to add a
  keyword. Each keyword renders as a chip with an ✕. Below: tiny
  preview "Matches will fire when these terms appear in a regulation
  change you're watching."

**Header:** "Define what regulatory updates you care about" + a
right-aligned coverage summary: `13 products · 4 countries · 4 keywords`.

**Sticky save bar at bottom:** `Cancel | Save Areas of Interest`. The
Save button is disabled until there are unsaved changes; an inline
"You have unsaved changes" hint appears on the left of the bar when
appropriate. A subtle elevation shadow lifts the bar so it reads as a
floating action surface.

### 7.6 Sources

The catalog of regulator sites the user has connected.

**Header:** Title + right-aligned `+ Add Source` button.

**Stat tiles (grid of 4):** Active sources / Receiving alerts / Items monitored / Inactive. Each tile has a left-edge color accent and a small icon.

**Search bar** for the table.

**Source rows:**
```ts
{
  id: string;
  name: string;             // "US Federal Register"
  url: string;              // seed URL
  type: "web" | "rss" | "email" | "api" | "database";
  status: "active" | "inactive";
  lastActivity: string | null;
  activityCount: number;
  activityMetric: string;   // "pages" / "items"
  addedDate: string;
  frequency: string;        // "Daily" / "Hourly" / "Weekly" / "Monthly"
  maxPages: number;
  countryCode?: string | null;
  health: "ok" | "degraded" | "blocked";
  lastBlockReason?: string | null;
  blockCount24h?: number;
}
```

Columns: **Source Name** (with health dot when not "ok") · Country (flag + ISO code) · Type (icon + word) · Last Activity · Activity (count + metric) · Frequency · Added · Status (active/inactive badge) · Receive Alerts (toggle switch) · Actions (Edit / Crawl Now).

Health-dot rules:
- `ok` → no dot
- `degraded` → small amber dot, tooltip with reason + count
- `blocked` → small red dot, tooltip with reason + count

**Add Source dialog:**
- Single field "URL or email address" (auto-detects connector type from URL pattern).
- Optional: `Name` override, `Frequency`, `Max pages per crawl`.
- On submit, the system probes the URL; on failure, show the actual error.

**Crawl Now button:**
- Triggers an immediate crawl. Replaces the row's row-state with a live
  progress strip while running. Show phases as they happen
  ("Crawling 7 / 15 pages…", "Indexing 4 / 20 PDFs…", "Persisting…",
  "Done — 5 documents updated, 2 changes detected").
- On completion show a toast:
  - With new alerts: "2 new alerts from US Federal Register"
  - First crawl with no modifications: "Baseline captured — 15 documents
    now being watched."
  - Cosmetic-only: "Crawled — no new alerts (cosmetic edits only)."

### 7.7 LLM Costs (admin)

Token usage and dollar spend across every LLM call.

**Top-right controls:** Time range dropdown ("All time / Last 24h / Last 7 days / Last 30 days") · Scope dropdown · Refresh button.

**Stat tiles (4):** Total Spend (USD) / LLM Calls / Total Tokens / Avg per Call. Each tile with a left-color-bar accent.

**Two side-by-side cards:**
- **By scope** — horizontal bar chart of $-spend per scope (scoring,
  obligations, web_extract, headline_backfill, embedding). Each row
  shows `<scope>: <calls> calls · <tokens> tok    $X.XXX  XX%`
- **By model** — same shape, per model.

**Daily spend** — 30-bar histogram (last 30 days). Show max-day annotation.

**Most expensive single calls** (Top 5 list):
- Each row: `#1 $0.000904  5,442 tok  [scoring badge]  gpt-4o-mini  6084ms     event a1b2c3d4`     timestamp on the right.

Footer: tiny muted text noting the data source path (e.g. `Source: /opt/app/artifacts/llm_usage/llm_usage.jsonl`).

---

## 8. Universal patterns the redesign should establish

### 8.1 Empty states
Every list / table needs a **first-class** empty state with: an icon
(64×64, monochrome), a one-line headline, a one-paragraph hint, and a
single primary CTA. No bare "No data" text.

### 8.2 Loading states
- For tables: 4–6 skeleton rows.
- For detail pages: skeleton card with skeleton lines.
- Never show a centered spinner unless the load is < 500ms.

### 8.3 Error states
A clear card with an icon (warning triangle), the error sentence, and
a `Retry` button. Never a full-page redirect.

### 8.4 Toasts / notifications
Top-right corner, stack down. Three variants: `success` (emerald),
`info` (primary navy), `error` (destructive red). Auto-dismiss after
4–8s based on importance. Click to dismiss.

### 8.5 Keyboard
A complete shortcut sheet for the inbox:
- `j` / `↓` next alert
- `k` / `↑` previous alert
- `Enter` / `o` open the selected alert
- `e` archive
- `r` mark read / unread
- `p` pin / unpin
- `1` thumbs up (relevant)
- `2` clock (partially relevant)
- `3` thumbs down (not relevant)
- `/` focus search
- `?` open shortcut cheat sheet
- `Esc` clear selection

A `?` overlay shows the cheat sheet — a clean two-column list, no popup chrome.

### 8.6 Density
Default density is "comfortable" (the values in the typography section).
Optionally support a "compact" toggle that reduces row padding by ~30%
for power users. Persist to localStorage.

### 8.7 Responsive
- 1280px+ (desktop): full layout
- 768–1279px (tablet): sidebar collapses to icon-only by default; tables remain horizontal-scroll if needed
- < 768px (mobile): sidebar becomes a hamburger drawer; tables become stacked cards (one alert = one card with all fields stacked vertically). Mobile is **best-effort** — Sarah uses desktop 95% of the time — but it shouldn't be visibly broken.

### 8.8 Accessibility
- All interactive elements reachable by keyboard.
- All icons that act as buttons have `aria-label`.
- Color contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text.
- Focus rings visible on every interactive element (use `--ring` token).
- Don't rely on color alone for state (the unread dot is fine because it's also bold weight).
- Respect `prefers-reduced-motion` — disable the action-icon fade-in animation when set.

---

## 9. Microcopy / tone of voice

- Direct and factual. "Submit comments by June 5, 2026." Not "Please be advised that you may wish to consider submitting…"
- Numerical changes always quote both sides: "194.09% → 82.12%".
- Address the reader as **you** in summaries and obligations.
- Headlines lead with the actor: "ATF: …", "CBP: …", "EU Commission: …".
- Empty states are warm but not cute: "Inbox zero — nice work" yes, "Yay you did it! 🎉" no.
- Error messages name what failed and what the user can do.

---

## 10. What's NOT in scope (do not redesign)

- Login screen — Keycloak hosts it, we just see a logged-in user.
- The mock website used for development testing.
- Backend admin tooling.
- Email digest formatting (separate channel).

---

## 11. Acceptance criteria

The redesign is "done" when, on a fresh user's first visit:

1. Within **5 seconds** the user understands what the app is for.
2. The inbox shows enough information per row to triage **without
   opening the detail page** for ~70% of alerts (i.e. headline + meta
   chips are enough for most decisions).
3. A power user can clear a 30-alert inbox in **under 2 minutes** using
   only the keyboard.
4. Switching to dark mode flips every page cleanly with no contrast
   regressions.
5. The product would not look out of place on a procurement screenshot
   alongside Linear, Vercel, or Stripe.

---

## 12. Concrete content samples (use these in mock-ups)

Use these REAL example alerts so the design renders against realistic
content (not "Lorem ipsum"):

### Alert example 1 (high relevance, US sanctions)
- **Title:** ATF: Remove Outdated Proscribed Countries List for Defense Imports
- **Authority:** US Government Publishing Office
- **Country:** United States
- **Trade lane:** *->US
- **Type:** Sanctions & Export Control
- **Date:** 2026-05-06 13:10
- **Score:** 75
- **Summary:** The Bureau of Alcohol, Tobacco, Firearms, and Explosives
  (ATF) is proposing to amend regulations by removing the outdated list
  of proscribed countries for importing defense articles and services.
  The new rule will reference a Department of State list instead and
  will only maintain the Russian Federation as the proscribed country
  for importing most firearms and ammunition.
- **Obligation 1:** [ACTION] importers of defense articles and services
  → Ensure compliance with the updated regulations regarding imports
  from the Russian Federation.
- **Obligation 2:** [PROHIBITION] importers of firearms and ammunition
  → Do not import firearms and ammunition from any country other than
  the Russian Federation.

### Alert example 2 (substantive, US tariff)
- **Title:** Court Reduces PRC Anti-Dumping Duty Rate: 194.09% → 82.12%
- **Authority:** US Customs and Border Protection
- **Country:** United States
- **Type:** Tariff & Duties
- **Score:** 60
- **Summary:** The court has reduced the PRC-wide rate of anti-dumping
  duty from 194.09% to 82.12%. Additionally, the court awarded the
  government $299,441.10 in prejudgment interest under 19 U.S.C. § 580
  but denied equitable prejudgment interest.

### Alert example 3 (with a deadline, India)
- **Title:** India DGFT: Extend Minimum Import Price Condition Until April 30, 2026
- **Authority:** Directorate General of Foreign Trade (DGFT)
- **Country:** India
- **Type:** Tariff & Duties
- **Score:** 60
- **Obligation:** [ACTION] importers of items under Chapter 48 of ITC HS
  → Comply with the extended Minimum Import Price (MIP) Condition.
  **Deadline: 2026-04-30**

### Alert example 4 (low relevance, comment period)
- **Title:** CBP: Open Comment Period for Form 6059B Until June 5, 2026
- **Type:** Tariff & Duties
- **Score:** 60
- **Obligation:** [REPORTING] interested parties → Submit comments
  regarding the Customs Declaration. **Deadline: 2026-06-05**

---

## 13. Deliverables

If you're a designer, deliver:
1. Figma file with: Design tokens (colors, type, spacing, radii) ·
   Component library (button, badge, input, table row, tabs, dialog,
   toast, sidebar) · Every page in light AND dark mode · Mobile
   variants for inbox + detail · Keyboard cheat sheet overlay.
2. Optional: a Loom walkthrough explaining notable choices.

If you're an AI design tool (Figma Make / v0.dev / Lovable / Bolt),
output:
1. A new Vite + React + Tailwind v4 project that drops into
   `frontend/src/` with the same component paths
   (`@/app/components/...`).
2. Pages routed via `react-router` HashRouter at the same paths used
   today: `/alerts`, `/alerts/:id`, `/archive`, `/regulatory-search`,
   `/areas-of-interest`, `/sources`, `/costs`.
3. Working dark mode toggle (already wired in `useTheme`).
4. **Do not change the API client files** in `frontend/src/api/`.
   Just consume them.

---

## 14. Closing note

The brief above is the *what* and the *why*. The *how* — exact pixel
values, animation timings, illustration style — is yours to choose.
Treat this as a pitch for a serious B2B compliance product, not a
consumer app. The bar: **a Senior Compliance Manager at a Fortune 500
should look at this for ten seconds and trust it.**
