import React, { useEffect, useRef, useState } from "react";
import {
  CrawlProgress,
  CrawlProgressEvent,
  CrawlTaskResult,
  DataSource as ApiDataSource,
  createSource,
  getCrawlTaskStatus,
  listSources,
  triggerSourceCrawl,
  updateSource,
} from "@/api/sources";
import { useNotifications } from "@/app/notifications";
import { Button } from "@/app/components/ui/button";
import { Badge } from "@/app/components/ui/badge";
import { Input } from "@/app/components/ui/input";
import { Label } from "@/app/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/app/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/app/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/app/components/ui/select";
import {
  Search,
  Plus,
  Globe,
  Rss,
  Mail,
  Database,
  Clock,
  FileText,
  Ban,
  Check,
  Bell,
  BellOff,
  Globe2,
} from "lucide-react";
import { Switch } from "@/app/components/ui/switch";
import { IN, CN, EU, US, JP, SG, BR, AU } from "country-flag-icons/react/3x2";

// Use the API model. Local alias keeps the JSX below unchanged.
type DataSource = ApiDataSource;

// Dev-only fallback — used only when the API can't be reached.
const mockSources: DataSource[] = [
  { id: "SRC-001", name: "DGFT India Official Portal", url: "https://dgft.gov.in/CP/", type: "web", status: "active", lastActivity: "2026-04-15T09:30:00", activityCount: 156, activityMetric: "pages", addedDate: "2025-06-10", frequency: "Daily", userSubscribed: true, maxPages: 50, countryCode: "IN" },
  { id: "SRC-002", name: "European Commission Trade RSS", url: "https://ec.europa.eu/trade/rss", type: "rss", status: "active", lastActivity: "2026-04-15T08:15:00", activityCount: 892, activityMetric: "items", addedDate: "2025-06-12", frequency: "Hourly", userSubscribed: true, maxPages: 50, countryCode: "EU" },
  { id: "SRC-003", name: "US Federal Register - Trade", url: "trade-alerts@federalregister.gov", type: "email", status: "active", lastActivity: "2026-04-14T16:45:00", activityCount: 234, activityMetric: "messages", addedDate: "2025-06-15", frequency: "Daily", userSubscribed: true, maxPages: 50, countryCode: "US" },
  { id: "SRC-004", name: "China MOFCOM API", url: "https://api.mofcom.gov.cn/regulations", type: "api", status: "active", lastActivity: "2026-04-15T10:00:00", activityCount: 1423, activityMetric: "records", addedDate: "2025-07-01", frequency: "Real-time", userSubscribed: true, maxPages: 50, countryCode: "CN" },
  { id: "SRC-005", name: "WTO Notifications Database", url: "https://www.wto.org/notifications", type: "database", status: "active", lastActivity: "2026-04-15T07:20:00", activityCount: 567, activityMetric: "entries", addedDate: "2025-07-15", frequency: "Daily", userSubscribed: true, maxPages: 50 },
  { id: "SRC-006", name: "Japan METI Updates", url: "https://www.meti.go.jp/english/rss", type: "rss", status: "active", lastActivity: "2026-04-15T06:30:00", activityCount: 345, activityMetric: "items", addedDate: "2025-08-01", frequency: "Daily", userSubscribed: false, maxPages: 50, countryCode: "JP" },
  { id: "SRC-007", name: "Singapore Customs Portal", url: "https://www.customs.gov.sg/", type: "web", status: "inactive", lastActivity: "2026-03-28T14:20:00", activityCount: 89, activityMetric: "pages", addedDate: "2025-08-15", frequency: "Weekly", userSubscribed: false, maxPages: 50, countryCode: "SG" },
  { id: "SRC-008", name: "ASEAN Trade Updates", url: "asean-trade@asean.org", type: "email", status: "active", lastActivity: "2026-04-13T11:30:00", activityCount: 167, activityMetric: "messages", addedDate: "2025-09-01", frequency: "Weekly", userSubscribed: true, maxPages: 50 },
  { id: "SRC-009", name: "Brazil MDIC Regulations", url: "https://www.gov.br/mdic/pt-br", type: "web", status: "active", lastActivity: "2026-04-15T05:45:00", activityCount: 203, activityMetric: "pages", addedDate: "2025-09-20", frequency: "Daily", userSubscribed: false, maxPages: 50, countryCode: "BR" },
  { id: "SRC-010", name: "Australia Border Force Newsletter", url: "alerts@abf.gov.au", type: "email", status: "inactive", lastActivity: "2026-04-01T09:15:00", activityCount: 78, activityMetric: "messages", addedDate: "2025-10-05", frequency: "Monthly", userSubscribed: false, maxPages: 50, countryCode: "AU" },
];

// Preset choices for the Max Pages dropdown. Backend accepts any
// integer in [1, 10000]; these are the buckets we expose in the UI to
// keep the dialog tidy and prevent typo-driven runaway crawls.
const MAX_PAGES_OPTIONS: { value: number; label: string }[] = [
  { value: 25, label: "25 pages" },
  { value: 50, label: "50 pages" },
  { value: 100, label: "100 pages" },
  { value: 500, label: "500 pages" },
  { value: 1000, label: "1,000 pages" },
  { value: 10000, label: "Max (10,000 pages)" },
];

const DEFAULT_MAX_PAGES = 50;

/**
 * Snap an arbitrary stored value to the nearest preset so the Select
 * always has a matching option (handles legacy rows or values set via
 * direct API).
 */
function snapToPreset(value: number | undefined | null): number {
  if (!Number.isFinite(value as number)) return DEFAULT_MAX_PAGES;
  const v = Math.round(value as number);
  if (v <= 0) return MAX_PAGES_OPTIONS[0].value;
  let best = MAX_PAGES_OPTIONS[0];
  let bestDiff = Math.abs(best.value - v);
  for (const opt of MAX_PAGES_OPTIONS) {
    const d = Math.abs(opt.value - v);
    if (d < bestDiff) {
      best = opt;
      bestDiff = d;
    }
  }
  return best.value;
}

// ─────────────────────────────────────────────────────────────────────
// Crawl progress helpers (module-level so the inline log row component
// below can reuse them without re-creating closures).
// ─────────────────────────────────────────────────────────────────────

/** Format one progress event as a single human-readable line. */
function renderEventLine(e: CrawlProgressEvent): string {
  switch (e.event) {
    case "crawl_started": {
      const max = (e.max_pages as number | undefined) ?? "?";
      return `Started — up to ${max} pages`;
    }
    case "heartbeat": {
      const sec = (e.elapsed_sec as number | undefined) ?? 0;
      return `Still crawling… ${sec}s elapsed`;
    }
    case "bestfirst_done": {
      const n = (e.pages_returned as number | undefined) ?? 0;
      return `Crawler returned ${n} candidate page${n === 1 ? "" : "s"}`;
    }
    case "page_indexed": {
      const cur = (e.current as number | undefined) ?? 0;
      const max = (e.max as number | undefined) ?? 0;
      const url = (e.url as string | undefined) ?? "";
      const short = url.length > 70 ? url.slice(0, 67) + "…" : url;
      return `Indexed ${cur}/${max} · ${short}`;
    }
    case "pdf_phase": {
      const c = (e.count as number | undefined) ?? 0;
      return `Harvesting ${c} PDF${c === 1 ? "" : "s"}…`;
    }
    case "xml_phase": {
      const c = (e.count as number | undefined) ?? 0;
      return `Harvesting ${c} XML file${c === 1 ? "" : "s"}…`;
    }
    case "connector_done": {
      const total = (e.total as number | undefined) ?? 0;
      return `Crawler done — ${total} document${total === 1 ? "" : "s"}`;
    }
    case "persisting": {
      const d = (e.docs as number | undefined) ?? 0;
      return `Persisting ${d} document${d === 1 ? "" : "s"} & detecting changes…`;
    }
    case "done": {
      const f = (e.fetched as number | undefined) ?? 0;
      return `Done — ${f} fetched`;
    }
    default:
      return e.event;
  }
}

/** Most-recent counter (e.g. "12 / 50") + freshest headline. */
function summarizeProgress(
  progress: CrawlProgress,
): { headline: string; counter: string | null } {
  const events = progress.events;
  if (events.length === 0) {
    return { headline: "Starting…", counter: null };
  }
  let lastPage: CrawlProgressEvent | undefined;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event === "page_indexed") {
      lastPage = events[i];
      break;
    }
  }
  const last = events[events.length - 1];
  return {
    headline: renderEventLine(last),
    counter: lastPage
      ? `${lastPage.current as number} / ${lastPage.max as number}`
      : null,
  };
}

/** Format an elapsed duration in seconds as "0:25" / "1:42" / "12:03". */
function formatElapsed(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Local crawl-row props re-declare CrawlEntry inline because it's
// scoped to the SourcesView component below. Marked partial so we
// don't pull the full type into module scope.
interface CrawlLogRowProps {
  entry: {
    sourceId: string;
    sourceName: string;
    taskId: string;
    phase: "starting" | "running" | "done" | "failed";
    progress?: CrawlProgress;
    result?: CrawlTaskResult;
    error?: string;
    expanded: boolean;
    startedAt: number;
  };
  colSpan: number;
  onDismiss: () => void;
  onToggle: () => void;
}

/**
 * One inline log row rendered directly under the source it belongs to.
 *
 * Behaviour:
 *   - while running: header strip with counter + elapsed clock + collapse
 *     toggle, plus an animated event log
 *   - on success: collapses to a one-line summary (auto-dismisses upstream
 *     after a few seconds)
 *   - on failure: red banner with the error, sticks until the user
 *     dismisses
 */
const CrawlLogRow = React.memo(function CrawlLogRow({
  entry,
  colSpan,
  onDismiss,
  onToggle,
}: CrawlLogRowProps) {
  const [now, setNow] = React.useState(() => Date.now());
  const logRef = React.useRef<HTMLDivElement | null>(null);

  // Tick every 500ms while the crawl is running so the elapsed clock
  // stays current. Stops as soon as we transition to done/failed.
  React.useEffect(() => {
    if (entry.phase !== "running" && entry.phase !== "starting") return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [entry.phase]);

  const events = entry.progress?.events ?? [];
  const eventCount = events.length;

  // Auto-scroll to the latest event whenever a new one arrives, but only
  // if the user is already near the bottom — otherwise let them keep
  // their scroll position while reading older lines.
  React.useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (nearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [eventCount]);

  const isRunning = entry.phase === "running" || entry.phase === "starting";
  const summary = entry.progress ? summarizeProgress(entry.progress) : null;
  const elapsedMs = now - entry.startedAt;

  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={colSpan} className="p-0">
        <div
          className={`mx-2 my-1 rounded-md border ${
            entry.phase === "failed"
              ? "border-destructive/30 bg-destructive/5"
              : entry.phase === "done"
                ? "border-accent/30 bg-accent/5"
                : "border-border bg-muted/30"
          }`}
        >
          {/* Header strip ─────────────────────────────────────── */}
          <div className="flex items-center gap-3 px-4 py-2.5">
            {isRunning && (
              <div
                className="size-3 rounded-full border-2 border-primary border-t-transparent animate-spin shrink-0"
                aria-hidden="true"
              />
            )}
            {entry.phase === "done" && (
              <Check className="size-4 text-accent shrink-0" />
            )}
            {entry.phase === "failed" && (
              <Ban className="size-4 text-destructive shrink-0" />
            )}

            <div className="flex-1 min-w-0">
              {isRunning && (
                <p
                  className="text-muted-foreground truncate"
                  style={{ fontSize: "var(--text-xs)" }}
                >
                  {summary?.headline ?? "Enqueuing task…"}
                </p>
              )}
              {entry.phase === "done" && entry.result && (
                <p
                  className="truncate"
                  style={{ fontSize: "var(--text-sm)" }}
                >
                  Crawled {entry.result.fetched} page
                  {entry.result.fetched === 1 ? "" : "s"} ·{" "}
                  <span className="text-muted-foreground">
                    {entry.result.created} new · {entry.result.modified}{" "}
                    changed · {entry.result.unchanged} unchanged
                  </span>
                </p>
              )}
              {entry.phase === "failed" && (
                <p
                  className="text-destructive"
                  style={{ fontSize: "var(--text-sm)" }}
                >
                  {entry.error || "Crawl failed"}
                </p>
              )}
            </div>

            <div className="flex items-center gap-3 shrink-0">
              {isRunning && summary?.counter && (
                <Badge variant="outline" className="tabular-nums">
                  {summary.counter}
                </Badge>
              )}
              {isRunning && (
                <span
                  className="text-muted-foreground tabular-nums"
                  style={{ fontSize: "var(--text-xs)" }}
                >
                  {formatElapsed(elapsedMs)}
                </span>
              )}
              {isRunning && eventCount > 0 && (
                <button
                  type="button"
                  onClick={onToggle}
                  className="text-muted-foreground hover:text-foreground"
                  style={{ fontSize: "var(--text-xs)" }}
                  aria-expanded={entry.expanded}
                  title={entry.expanded ? "Hide log" : "Show log"}
                >
                  {entry.expanded ? "▾ Hide" : "▸ Show"} log
                </button>
              )}
              <button
                type="button"
                onClick={onDismiss}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Dismiss"
                title="Dismiss"
              >
                ×
              </button>
            </div>
          </div>

          {/* Event log ─────────────────────────────────────────── */}
          {isRunning && entry.expanded && eventCount > 0 && (
            <div
              ref={logRef}
              className="border-t bg-background/60 max-h-48 overflow-y-auto px-4 py-2 font-mono"
              style={{ fontSize: "var(--text-xs)" }}
            >
              {events.map((e, idx) => (
                <div
                  key={`${entry.taskId}-${idx}`}
                  className="flex gap-2 py-0.5 text-muted-foreground animate-in fade-in-0 slide-in-from-bottom-1 duration-300"
                >
                  <span className="text-muted-foreground/60 shrink-0 tabular-nums">
                    {new Date(e.ts * 1000).toLocaleTimeString([], {
                      hour12: false,
                    })}
                  </span>
                  <span className="break-all">{renderEventLine(e)}</span>
                </div>
              ))}
              {/* Blinking cursor at the tail to give the LLM-thinking feel. */}
              <div
                className="text-primary animate-pulse"
                style={{ fontSize: "var(--text-xs)" }}
                aria-hidden="true"
              >
                ▍
              </div>
            </div>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
});

/**
 * Compact stat tile for the Sources page header strip.
 *
 * Visually leaner than the previous "Bootstrap card" layout — a thin
 * left accent rule, an icon chip, then a big number. Reads as a status
 * banner instead of a 2010s admin dashboard.
 */
function StatTile({
  icon,
  label,
  value,
  tone,
  dim = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  tone: "primary" | "accent" | "muted";
  dim?: boolean;
}) {
  const accent =
    tone === "primary"
      ? "before:bg-primary [&_.icon]:bg-primary/10 [&_.icon]:text-primary"
      : tone === "accent"
        ? "before:bg-accent [&_.icon]:bg-accent/10 [&_.icon]:text-accent"
        : "before:bg-muted-foreground/30 [&_.icon]:bg-muted [&_.icon]:text-muted-foreground";

  return (
    <div
      className={`relative rounded-md border bg-card pl-4 pr-4 py-3 overflow-hidden
        before:content-[''] before:absolute before:left-0 before:top-2 before:bottom-2 before:w-[3px] before:rounded-r-sm
        ${accent} ${dim ? "opacity-60" : ""}`}
    >
      <div className="flex items-center gap-3">
        <div className="icon size-7 rounded-md flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <p
            className="text-muted-foreground uppercase tracking-wider truncate"
            style={{
              fontSize: "var(--text-xs)",
              fontWeight: "var(--font-weight-medium)",
            }}
          >
            {label}
          </p>
          <p
            className="tabular-nums leading-tight"
            style={{
              fontSize: "var(--text-xl)",
              fontWeight: "var(--font-weight-medium)",
            }}
          >
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}

export function SourcesView() {
  const { notify, refreshUnread, unreadCount, unreadAlerts } =
    useNotifications();
  const [sources, setSources] = useState<DataSource[]>([]);
  // Mirror unreadCount + unreadAlerts in refs so the polling closure
  // (set up only when the first crawl starts) can still capture the
  // freshest values without re-binding the interval.
  const unreadCountRef = useRef<number>(unreadCount);
  useEffect(() => {
    unreadCountRef.current = unreadCount;
  }, [unreadCount]);
  const unreadAlertsRef = useRef(unreadAlerts);
  useEffect(() => {
    unreadAlertsRef.current = unreadAlerts;
  }, [unreadAlerts]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [newSource, setNewSource] = useState({
    name: "",
    url: "",
    frequency: "Daily" as DataSource["frequency"],
    maxPages: 50,
  });

  // Edit dialog — pre-filled from a row when "Edit" is clicked. Null
  // means the dialog is closed.
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [editForm, setEditForm] = useState<{
    name: string;
    frequency: DataSource["frequency"];
    maxPages: number;
  }>({ name: "", frequency: "Daily", maxPages: 50 });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ── Crawl state ────────────────────────────────────────────────────
  // Multiple crawls can run in parallel — keyed by sourceId. Each row
  // that's actively crawling renders an inline log row directly below
  // it. One master poller polls every active task each tick.
  type CrawlEntry = {
    sourceId: string;
    sourceName: string;
    taskId: string;
    phase: "starting" | "running" | "done" | "failed";
    progress?: CrawlProgress;
    result?: CrawlTaskResult;
    error?: string;
    /** Whether the row is in user-collapsed state. Defaults to true. */
    expanded: boolean;
    /** ms since epoch — used for elapsed clock + safety timeout. */
    startedAt: number;
    /**
     * Inbox unread count captured at click time. Used to compute the
     * real "new alerts from this crawl" delta in the success toast —
     * upsert_documents.{created,modified} count *page changes*, not
     * alerts (a low-significance change-event may be filtered out by
     * the user's min_significance and never produce an alert).
     */
    unreadBefore: number;
    /**
     * Inbox alert IDs at click time. After the crawl we re-fetch the
     * unread list and surface any IDs not in this set as the *new*
     * alerts — that's how we get real titles to show in the toast.
     */
    unreadIdsBefore: Set<string>;
  };
  const [crawls, setCrawls] = useState<Record<string, CrawlEntry>>({});
  // Mirror of `crawls` kept in a ref so the polling loop can read the
  // *current* state without rebinding the interval every render. Without
  // this the closure inside setInterval freezes the value of `crawls`
  // from when polling started — a row stuck on phase="starting" never
  // sees its taskId update to "running".
  const crawlsRef = useRef<Record<string, CrawlEntry>>({});
  useEffect(() => {
    crawlsRef.current = crawls;
  }, [crawls]);
  const masterPollRef = useRef<number | null>(null);
  // Per-sourceId timers for auto-dismissing successful entries.
  const dismissTimersRef = useRef<Record<string, number>>({});

  // Stop any in-flight timers when the view unmounts.
  useEffect(() => {
    return () => {
      if (masterPollRef.current) window.clearInterval(masterPollRef.current);
      Object.values(dismissTimersRef.current).forEach((id) =>
        window.clearTimeout(id),
      );
    };
  }, []);

  // Load sources from /api/v2/sources on mount; fall back to the mock
  // dataset if the API isn't reachable so the UI still renders during
  // offline dev.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listSources()
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        console.warn("Sources API unreachable, using mock data:", err.message);
        setSources(mockSources);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleUserSubscription = (sourceId: string) => {
    let nextSubscribed = false;
    setSources((prev) =>
      prev.map((source) => {
        if (source.id !== sourceId) return source;
        nextSubscribed = !source.userSubscribed;
        return { ...source, userSubscribed: nextSubscribed };
      }),
    );
    // Backend stores it as a stub for now — call anyway so we get an error
    // surface if the endpoint regresses.
    updateSource(sourceId, { userSubscribed: nextSubscribed }).catch((err) =>
      console.warn("subscribe PATCH failed:", err),
    );
  };

  const toggleSourceStatus = (sourceId: string) => {
    let nextStatus: "active" | "inactive" = "active";
    setSources((prev) =>
      prev.map((source) => {
        if (source.id !== sourceId) return source;
        nextStatus = source.status === "active" ? "inactive" : "active";
        return { ...source, status: nextStatus };
      }),
    );
    updateSource(sourceId, { status: nextStatus }).catch((err) =>
      console.warn("status PATCH failed:", err),
    );
  };

  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const handleAddSource = async () => {
    setAddError(null);
    if (!newSource.url.trim()) {
      setAddError("URL is required");
      return;
    }
    setAdding(true);
    try {
      const created = await createSource({
        name: newSource.name || undefined,
        url: newSource.url.trim(),
        frequency: newSource.frequency as
          | "Hourly"
          | "Daily"
          | "Weekly"
          | "Monthly",
        maxPages: snapToPreset(newSource.maxPages),
      });
      setSources((prev) => [created, ...prev]);
      setIsAddDialogOpen(false);
      setNewSource({ name: "", url: "", frequency: "Daily", maxPages: 50 });
    } catch (err: any) {
      setAddError(err?.message || "Failed to add source");
    } finally {
      setAdding(false);
    }
  };

  // ── Edit dialog handlers ────────────────────────────────────────────
  const openEdit = (source: DataSource) => {
    setEditError(null);
    setEditing(source);
    setEditForm({
      name: source.name === source.url ? "" : source.name,
      frequency: source.frequency,
      maxPages: snapToPreset(source.maxPages),
    });
  };

  const handleEditSave = async () => {
    if (!editing) return;
    setEditError(null);
    setEditSaving(true);
    try {
      const updated = await updateSource(editing.id, {
        name: editForm.name,
        frequency: editForm.frequency as
          | "Hourly"
          | "Daily"
          | "Weekly"
          | "Monthly",
        maxPages: snapToPreset(editForm.maxPages),
      });
      setSources((prev) =>
        prev.map((s) => (s.id === updated.id ? updated : s)),
      );
      setEditing(null);
    } catch (err: any) {
      setEditError(err?.message || "Failed to save");
    } finally {
      setEditSaving(false);
    }
  };

  // ── Crawl Now ──────────────────────────────────────────────────────
  // One master poller iterates every active crawl on each tick. Per-task
  // intervals would scale O(N) — this is O(1) timers regardless of how
  // many crawls run in parallel.
  const POLL_INTERVAL_MS = 1500;
  // Real sources crawl 50 pages and routinely take 1–3 minutes; PDFs in
  // particular can stretch to 5+. Cap at 10 minutes so we still catch
  // genuinely stuck tasks instead of polling forever.
  const POLL_TIMEOUT_MS = 600_000;

  /**
   * One tick of the master poller — fetches the latest status for every
   * crawl in flight and merges results back into state.
   */
  const pollAllActive = async () => {
    // Read from the ref, NOT from the captured `crawls` — see the
    // comment on `crawlsRef` for why.
    const inFlight = Object.values(crawlsRef.current).filter(
      // taskId is "" for ~few hundred ms while triggerSourceCrawl is in
      // flight; skip those — there's nothing to poll yet.
      (c) =>
        (c.phase === "running" || c.phase === "starting") &&
        !!c.taskId,
    );
    if (inFlight.length === 0) return;

    const results = await Promise.all(
      inFlight.map(async (c) => {
        try {
          const status = await getCrawlTaskStatus(c.taskId);
          return { crawl: c, status, error: null as Error | null };
        } catch (err: any) {
          return { crawl: c, status: null, error: err as Error };
        }
      }),
    );

    let didFinish = false;

    setCrawls((prev) => {
      const next = { ...prev };
      for (const { crawl, status, error } of results) {
        const cur = next[crawl.sourceId];
        if (!cur || cur.taskId !== crawl.taskId) continue;

        // Hard timeout — mark the entry failed but leave the backend task
        // running. The user can dismiss and click again to re-poll.
        if (Date.now() - cur.startedAt > POLL_TIMEOUT_MS) {
          next[crawl.sourceId] = {
            ...cur,
            phase: "failed",
            error:
              "Crawl is still running on the server but the UI stopped polling. Click × to dismiss.",
          };
          continue;
        }

        if (error) {
          next[crawl.sourceId] = {
            ...cur,
            phase: "failed",
            error: error.message || "Could not poll task status",
          };
          continue;
        }
        if (!status) continue;

        if (!status.ready) {
          // Live progress update — preserve everything except the new
          // events buffer.
          if (status.progress) {
            next[crawl.sourceId] = { ...cur, progress: status.progress };
          }
          continue;
        }

        // Task finished.
        didFinish = true;
        if (status.successful && status.result) {
          next[crawl.sourceId] = {
            ...cur,
            phase: "done",
            result: status.result,
          };
          // Auto-dismiss the success row after a few seconds — gives the
          // user time to read the result without making the table
          // permanently larger.
          if (dismissTimersRef.current[crawl.sourceId] !== undefined) {
            window.clearTimeout(dismissTimersRef.current[crawl.sourceId]);
          }
          dismissTimersRef.current[crawl.sourceId] = window.setTimeout(() => {
            dismissCrawlEntry(crawl.sourceId);
          }, 8000);

          // Fire a global toast based on the REAL inbox delta — not
          // upsert_documents.{created,modified}, which count page-level
          // changes (a cosmetic banner shift produces a "modified"
          // page even though no alert is generated because the LLM
          // scores it 0 and the user's min_significance filter drops
          // it).
          //
          // We re-fetch the unread list AFTER the worker has had a
          // moment to run scoring + matching, then diff against the IDs
          // captured at click time to surface the *actual* new alerts
          // — with their real titles — in the toast.
          const pageChanges =
            (status.result.created ?? 0) + (status.result.modified ?? 0);
          const fetched = status.result.fetched;
          const sourceName = cur.sourceName;
          const idsBefore = cur.unreadIdsBefore;
          // Defer the unread re-fetch slightly so M5 matching has a
          // chance to insert any alert rows. This is best-effort —
          // the badge keeps refreshing on its own cadence anyway.
          window.setTimeout(async () => {
            const after = await refreshUnread();
            const newOnes =
              after?.filter((a) => !idsBefore.has(a.id)) ?? [];

            if (newOnes.length === 1) {
              // One new alert — link straight to the detail page and
              // show the actual title so the user knows what changed.
              const a = newOnes[0];
              notify(`New alert from ${sourceName}`, {
                description: a.title,
                variant: "success",
                href: `/alerts/${a.id}`,
              });
            } else if (newOnes.length > 1) {
              // Multiple — show the highest-relevance one's title and
              // a "+N more" hint.
              const sorted = [...newOnes].sort(
                (x, y) => y.relevanceScore - x.relevanceScore,
              );
              const top = sorted[0];
              const extra = newOnes.length - 1;
              notify(
                `${newOnes.length} new alerts from ${sourceName}`,
                {
                  description: `${top.title} · +${extra} more`,
                  variant: "success",
                  href: "/alerts",
                },
              );
            } else if (pageChanges > 0) {
              // Pages changed but nothing made it past the relevance
              // filter — typical for cosmetic banner shifts. Tell the
              // user clearly so they don't go hunting in the inbox.
              notify(`Crawled ${sourceName} — no new alerts`, {
                description: `${pageChanges} page${pageChanges === 1 ? "" : "s"} changed but score was below your relevance threshold (cosmetic / minor edits)`,
                variant: "info",
                durationMs: 6000,
              });
            } else {
              // Nothing changed at all.
              notify(`Crawled ${sourceName} — no changes`, {
                description: `${fetched} page${fetched === 1 ? "" : "s"} fetched, all unchanged`,
                variant: "info",
                durationMs: 4000,
              });
            }
          }, 1500);
        } else {
          next[crawl.sourceId] = {
            ...cur,
            phase: "failed",
            error: status.error || `Task ended with state ${status.state}`,
          };
          notify(`Crawl failed for ${cur.sourceName}`, {
            description: status.error || `Task ended with state ${status.state}`,
            variant: "error",
            durationMs: 0,
          });
        }
      }
      return next;
    });

    // Refresh the underlying sources list so lastActivity / activityCount
    // reflect the new crawl state. Fire-and-forget — non-fatal.
    if (didFinish) {
      listSources()
        .then((rows) => setSources(rows))
        .catch(() => {});
      // Recount inbox so the sidebar badge updates immediately.
      void refreshUnread();
    }
  };

  // Master poller — runs while any crawl is active. The empty deps array
  // keeps it stable across renders; pollAllActive reads `crawls` via its
  // closure each tick (refreshed via state update on the previous tick).
  useEffect(() => {
    const anyActive = Object.values(crawls).some(
      (c) => c.phase === "running" || c.phase === "starting",
    );
    if (anyActive && masterPollRef.current === null) {
      masterPollRef.current = window.setInterval(() => {
        void pollAllActive();
      }, POLL_INTERVAL_MS);
    } else if (!anyActive && masterPollRef.current !== null) {
      window.clearInterval(masterPollRef.current);
      masterPollRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crawls]);

  const handleCrawlNow = async (source: DataSource) => {
    // Replacing an existing entry restarts the crawl. Clear any pending
    // auto-dismiss for this source first.
    if (dismissTimersRef.current[source.id] !== undefined) {
      window.clearTimeout(dismissTimersRef.current[source.id]);
      delete dismissTimersRef.current[source.id];
    }

    setCrawls((prev) => ({
      ...prev,
      [source.id]: {
        sourceId: source.id,
        sourceName: source.name,
        taskId: "",
        phase: "starting",
        expanded: true,
        startedAt: Date.now(),
        unreadBefore: unreadCountRef.current,
        unreadIdsBefore: new Set(unreadAlertsRef.current.map((a) => a.id)),
      },
    }));

    let taskId: string;
    try {
      const r = await triggerSourceCrawl(source.id);
      if (!r.task_id) {
        throw new Error("Backend did not return a task_id");
      }
      taskId = r.task_id;
    } catch (err: any) {
      setCrawls((prev) => ({
        ...prev,
        [source.id]: {
          ...(prev[source.id] ?? {
            sourceId: source.id,
            sourceName: source.name,
            taskId: "",
            phase: "failed" as const,
            expanded: true,
            startedAt: Date.now(),
            unreadBefore: unreadCountRef.current,
            unreadIdsBefore: new Set(
              unreadAlertsRef.current.map((a) => a.id),
            ),
          }),
          phase: "failed",
          error: err?.message || "Failed to enqueue crawl",
        },
      }));
      return;
    }

    setCrawls((prev) => {
      const cur = prev[source.id];
      if (!cur) return prev;
      return {
        ...prev,
        [source.id]: { ...cur, taskId, phase: "running" },
      };
    });
  };

  const dismissCrawlEntry = (sourceId: string) => {
    if (dismissTimersRef.current[sourceId] !== undefined) {
      window.clearTimeout(dismissTimersRef.current[sourceId]);
      delete dismissTimersRef.current[sourceId];
    }
    setCrawls((prev) => {
      if (!(sourceId in prev)) return prev;
      const next = { ...prev };
      delete next[sourceId];
      return next;
    });
  };

  const toggleExpand = (sourceId: string) => {
    setCrawls((prev) => {
      const cur = prev[sourceId];
      if (!cur) return prev;
      return { ...prev, [sourceId]: { ...cur, expanded: !cur.expanded } };
    });
  };


  const getSourceTypeIcon = (type: DataSource["type"]) => {
    const iconMap = {
      web: <Globe className="size-4" />,
      rss: <Rss className="size-4" />,
      email: <Mail className="size-4" />,
      api: <Database className="size-4" />,
      database: <FileText className="size-4" />,
    };
    return iconMap[type];
  };

  const getCountryFlag = (countryCode?: string | null) => {
    if (!countryCode) {
      return (
        <span className="inline-flex">
          <Globe2 className="size-5 text-muted-foreground" />
        </span>
      );
    }

    const flagMap: { [key: string]: React.ReactNode } = {
      IN: <span className="inline-flex"><IN className="size-5" /></span>,
      CN: <span className="inline-flex"><CN className="size-5" /></span>,
      EU: <span className="inline-flex"><EU className="size-5" /></span>,
      US: <span className="inline-flex"><US className="size-5" /></span>,
      JP: <span className="inline-flex"><JP className="size-5" /></span>,
      SG: <span className="inline-flex"><SG className="size-5" /></span>,
      BR: <span className="inline-flex"><BR className="size-5" /></span>,
      AU: <span className="inline-flex"><AU className="size-5" /></span>,
    };

    return (
      flagMap[countryCode] || (
        <span className="inline-flex">
          <Globe2 className="size-5 text-muted-foreground" />
        </span>
      )
    );
  };

  const formatLastActivity = (dateString: string | null | undefined) => {
    if (!dateString) return "—";
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return "—";
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) {
      return `${diffMins} min ago`;
    } else if (diffHours < 24) {
      return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
    } else if (diffDays < 7) {
      return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
    } else {
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }
  };

  const filteredSources = sources.filter((source) => {
    const query = searchQuery.toLowerCase();
    return (
      source.name.toLowerCase().includes(query) ||
      source.url.toLowerCase().includes(query) ||
      source.type.toLowerCase().includes(query) ||
      source.id.toLowerCase().includes(query)
    );
  });

  const activeSourcesCount = sources.filter((s) => s.status === "active").length;
  const subscribedSourcesCount = sources.filter(
    (s) => s.userSubscribed && s.status === "active",
  ).length;
  const totalActivityCount = sources
    .filter((s) => s.status === "active")
    .reduce((sum, s) => sum + s.activityCount, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-muted-foreground">
            Manage and monitor regulatory data sources
          </p>
        </div>
        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 size-4" />
              Add Source
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Data Source</DialogTitle>
              <DialogDescription>
                Enter the URL of a regulatory site, RSS feed, or email
                address. Type and country are inferred automatically from
                the URL.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="source-url">URL / Address</Label>
                <Input
                  id="source-url"
                  placeholder="e.g. https://www.fca.org.uk/news"
                  value={newSource.url}
                  onChange={(e) =>
                    setNewSource({ ...newSource, url: e.target.value })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Web pages, RSS feeds (URL ends in .rss or /feed), or email
                  addresses (alerts@example.gov) all work.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-name">
                  Source Name{" "}
                  <span className="text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  id="source-name"
                  placeholder="Leave blank to auto-derive from the URL"
                  value={newSource.name}
                  onChange={(e) =>
                    setNewSource({ ...newSource, name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-frequency">Crawl Frequency</Label>
                <Select
                  value={newSource.frequency}
                  onValueChange={(v) =>
                    setNewSource({
                      ...newSource,
                      frequency: v as DataSource["frequency"],
                    })
                  }
                >
                  <SelectTrigger id="source-frequency">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Hourly">Hourly</SelectItem>
                    <SelectItem value="Daily">Daily</SelectItem>
                    <SelectItem value="Weekly">Weekly</SelectItem>
                    <SelectItem value="Monthly">Monthly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-max-pages">Max Pages per Run</Label>
                <Select
                  value={String(newSource.maxPages)}
                  onValueChange={(v) =>
                    setNewSource({
                      ...newSource,
                      maxPages: parseInt(v, 10) || DEFAULT_MAX_PAGES,
                    })
                  }
                >
                  <SelectTrigger id="source-max-pages">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MAX_PAGES_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={String(opt.value)}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  How many pages to fetch per crawl. Higher = deeper coverage
                  but more LLM cost.
                </p>
              </div>
              <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                <p className="font-semibold mb-1">Other defaults</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  <li>Rate limit: 1 request/sec</li>
                </ul>
              </div>
            </div>
            {addError && (
              <p className="text-sm text-red-600 mt-2">{addError}</p>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setAddError(null);
                  setIsAddDialogOpen(false);
                }}
                disabled={adding}
              >
                Cancel
              </Button>
              <Button
                onClick={handleAddSource}
                disabled={!newSource.url || adding}
              >
                {adding ? "Adding…" : "Add Source"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Stat strip — single row of large-number tiles, each with a
          subtle accent. Reads like a status banner instead of four
          identical Bootstrap cards. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatTile
          icon={<Globe className="size-4" />}
          label="Active sources"
          value={activeSourcesCount}
          tone="primary"
        />
        <StatTile
          icon={<Bell className="size-4" />}
          label="Receiving alerts"
          value={subscribedSourcesCount}
          tone="accent"
        />
        <StatTile
          icon={<FileText className="size-4" />}
          label="Items monitored"
          value={totalActivityCount.toLocaleString()}
          tone="muted"
        />
        <StatTile
          icon={<Clock className="size-4" />}
          label="Inactive"
          value={sources.length - activeSourcesCount}
          tone="muted"
          dim={sources.length - activeSourcesCount === 0}
        />
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search sources by name, URL, or type..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        {searchQuery && (
          <Button variant="ghost" onClick={() => setSearchQuery("")}>
            Clear
          </Button>
        )}
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ width: "100px" }}>ID</TableHead>
              <TableHead>Source Name</TableHead>
              <TableHead style={{ width: "100px" }}>Country</TableHead>
              <TableHead style={{ width: "120px" }}>Type</TableHead>
              <TableHead style={{ width: "150px" }}>Last Activity</TableHead>
              <TableHead style={{ width: "120px" }}>Activity</TableHead>
              <TableHead style={{ width: "120px" }}>Frequency</TableHead>
              <TableHead style={{ width: "120px" }}>Added</TableHead>
              <TableHead style={{ width: "100px" }}>Status</TableHead>
              <TableHead style={{ width: "140px" }}>Receive Alerts</TableHead>
              <TableHead style={{ width: "200px" }}>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredSources.length === 0 ? (
              <TableRow>
                <TableCell colSpan={11} className="h-24 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <Search className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">
                      {searchQuery
                        ? `No sources found matching "${searchQuery}"`
                        : "No sources configured"}
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              filteredSources.map((source) => {
                const crawl = crawls[source.id];
                const isCrawling =
                  !!crawl &&
                  (crawl.phase === "starting" || crawl.phase === "running");
                return (
                  <React.Fragment key={source.id}>
                <TableRow
                  className={source.status === "inactive" ? "opacity-60" : ""}
                >
                  <TableCell>
                    <span className="text-muted-foreground">{source.id}</span>
                  </TableCell>
                  <TableCell>
                    <div>
                      <p style={{ fontWeight: "var(--font-weight-medium)" }}>
                        {source.name}
                      </p>
                      <p
                        className="text-muted-foreground truncate"
                        style={{ fontSize: "var(--text-xs)", maxWidth: "300px" }}
                        title={source.url}
                      >
                        {source.url}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getCountryFlag(source.countryCode)}
                      {source.countryCode && (
                        <span
                          className="text-muted-foreground"
                          style={{ fontSize: "var(--text-xs)" }}
                        >
                          {source.countryCode}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getSourceTypeIcon(source.type)}
                      <span style={{ textTransform: "capitalize" }}>
                        {source.type}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Clock className="size-3" />
                      {formatLastActivity(source.lastActivity)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <span style={{ fontWeight: "var(--font-weight-medium)" }}>
                        {source.activityCount}
                      </span>
                      <span
                        className="text-muted-foreground"
                        style={{ fontSize: "var(--text-xs)" }}
                      >
                        {source.activityMetric}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{source.frequency}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(source.addedDate).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </TableCell>
                  <TableCell>
                    {source.status === "active" ? (
                      <Badge className="bg-accent text-accent-foreground">
                        <Check className="mr-1 size-3" />
                        Active
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="border-destructive text-destructive"
                      >
                        <Ban className="mr-1 size-3" />
                        Inactive
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <Switch
                        checked={source.userSubscribed}
                        onCheckedChange={() => toggleUserSubscription(source.id)}
                        disabled={source.status === "inactive"}
                        className="data-[state=unchecked]:bg-muted"
                      />
                      <div className="flex items-center gap-1">
                        {source.userSubscribed ? (
                          <>
                            <Bell className="size-4 text-accent" />
                            <span style={{ fontSize: "var(--text-xs)" }}>On</span>
                          </>
                        ) : (
                          <>
                            <BellOff className="size-4 text-muted-foreground" />
                            <span
                              className="text-muted-foreground"
                              style={{ fontSize: "var(--text-xs)" }}
                            >
                              Off
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openEdit(source)}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => handleCrawlNow(source)}
                        disabled={
                          isCrawling || source.status === "inactive"
                        }
                      >
                        {isCrawling ? "Crawling…" : "Crawl Now"}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
                {crawl && (
                  <CrawlLogRow
                    entry={crawl}
                    colSpan={11}
                    onDismiss={() => dismissCrawlEntry(source.id)}
                    onToggle={() => toggleExpand(source.id)}
                  />
                )}
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>


      {/* ── Edit dialog ─────────────────────────────────────────── */}
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Source</DialogTitle>
            <DialogDescription>
              Update the display name or how often this source is crawled.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">Source Name</Label>
              <Input
                id="edit-name"
                placeholder="Leave blank to auto-derive from the URL"
                value={editForm.name}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-frequency">Crawl Frequency</Label>
              <Select
                value={editForm.frequency}
                onValueChange={(v) =>
                  setEditForm({
                    ...editForm,
                    frequency: v as DataSource["frequency"],
                  })
                }
              >
                <SelectTrigger id="edit-frequency">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Hourly">Hourly</SelectItem>
                  <SelectItem value="Daily">Daily</SelectItem>
                  <SelectItem value="Weekly">Weekly</SelectItem>
                  <SelectItem value="Monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-max-pages">Max Pages per Run</Label>
              <Select
                value={String(editForm.maxPages)}
                onValueChange={(v) =>
                  setEditForm({
                    ...editForm,
                    maxPages: parseInt(v, 10) || DEFAULT_MAX_PAGES,
                  })
                }
              >
                <SelectTrigger id="edit-max-pages">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MAX_PAGES_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={String(opt.value)}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {editing && (
              <p className="text-xs text-muted-foreground">
                URL:{" "}
                <span className="font-mono">{editing.url}</span> (read-only)
              </p>
            )}
          </div>
          {editError && (
            <p className="text-sm text-red-600 mt-2">{editError}</p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditing(null)}
              disabled={editSaving}
            >
              Cancel
            </Button>
            <Button onClick={handleEditSave} disabled={editSaving}>
              {editSaving ? "Saving…" : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
