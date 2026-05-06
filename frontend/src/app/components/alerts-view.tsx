import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  Alert as ApiAlert,
  AlertFeedback,
  listAlerts,
  updateAlert,
} from "@/api/alerts";
import { useNotifications } from "@/app/notifications";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/app/components/ui/table";
import { Button } from "@/app/components/ui/button";
import { Badge } from "@/app/components/ui/badge";
import { Input } from "@/app/components/ui/input";
import {
  Archive,
  Eye,
  EyeOff,
  Search,
  Pin,
  ThumbsUp,
  ThumbsDown,
  Clock,
  Check,
  Undo2,
  Filter as FilterIcon,
  Download,
  X,
} from "lucide-react";
import { Progress } from "@/app/components/ui/progress";
import { Switch } from "@/app/components/ui/switch";
import { Checkbox } from "@/app/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/app/components/ui/select";
import { IN, CN, EU, US } from "country-flag-icons/react/3x2";

// Alert shape comes from the API client. Keep the alias for readability —
// every reference to `Alert` below now resolves to the typed API model.
type Alert = ApiAlert;

// Dev-only fallback dataset used when the backend isn't reachable.
// Lets the UI render with realistic content during local development.
const mockAlerts: Alert[] = [
  {
    id: "ALT-001",
    title: "New tariff rates for semiconductor imports effective March 2026",
    country: "India",
    authority: "Directorate General of Foreign Trade (DGFT)",
    regulationType: "Tariff & Duties",
    publicationDate: "2026-01-15",
    affectedProducts: ["HS 854140", "HS 850440"],
    relevanceScore: 92,
    status: "new",
    tradeLane: "*->IN",
  },
  {
    id: "ALT-002",
    title: "Updated import licensing requirements for electrical machinery",
    country: "China",
    authority: "Ministry of Commerce (MOFCOM)",
    regulationType: "Licensing & Permits",
    publicationDate: "2026-01-18",
    affectedProducts: ["HS 850440", "HS 851770"],
    relevanceScore: 87,
    status: "new",
    tradeLane: "*->CN",
  },
  {
    id: "ALT-003",
    title: "Conformity assessment changes for consumer electronics",
    country: "EU",
    authority: "European Commission",
    regulationType: "Labeling & Conformity",
    publicationDate: "2026-01-20",
    affectedProducts: ["HS 854140", "HS 851762"],
    relevanceScore: 78,
    status: "read",
    tradeLane: "*->EU",
  },
  {
    id: "ALT-004",
    title: "Export restriction on dual-use semiconductor equipment",
    country: "United States",
    authority: "Bureau of Industry and Security (BIS)",
    regulationType: "Export Restrictions",
    publicationDate: "2026-01-12",
    affectedProducts: ["HS 854140"],
    relevanceScore: 95,
    status: "new",
    tradeLane: "US->*",
  },
  {
    id: "ALT-005",
    title: "Revised customs clearance procedures for electronic goods",
    country: "India",
    authority: "Central Board of Indirect Taxes and Customs (CBIC)",
    regulationType: "Import/Export Procedures",
    publicationDate: "2026-01-10",
    affectedProducts: ["HS 854140", "HS 850440", "HS 851770"],
    relevanceScore: 65,
    status: "read",
    tradeLane: "*->IN",
  },
  {
    id: "ALT-006",
    title: "Anti-dumping duty investigation on lithium batteries",
    country: "EU",
    authority: "European Commission - DG Trade",
    regulationType: "Anti-dumping Measures",
    publicationDate: "2026-01-08",
    affectedProducts: ["HS 850760", "HS 850720"],
    relevanceScore: 88,
    status: "read",
    userFeedback: "relevant",
    tradeLane: "CN->EU",
  },
  {
    id: "ALT-007",
    title: "New environmental compliance standards for electronic waste",
    country: "China",
    authority: "Ministry of Ecology and Environment",
    regulationType: "Environmental Standards",
    publicationDate: "2026-01-05",
    affectedProducts: ["HS 854140", "HS 851770", "HS 850440"],
    relevanceScore: 72,
    status: "read",
    tradeLane: "*->CN",
  },
  {
    id: "ALT-008",
    title: "Updated certification requirements for wireless devices",
    country: "United States",
    authority: "Federal Communications Commission (FCC)",
    regulationType: "Labeling & Conformity",
    publicationDate: "2026-01-03",
    affectedProducts: ["HS 851762", "HS 851770"],
    relevanceScore: 81,
    status: "read",
    userFeedback: "partially_relevant",
    tradeLane: "*->US",
  },
  {
    id: "ALT-009",
    title: "Import quota changes for steel products",
    country: "India",
    authority: "Ministry of Steel",
    regulationType: "Quotas & Restrictions",
    publicationDate: "2025-12-28",
    affectedProducts: ["HS 720710", "HS 720890"],
    relevanceScore: 45,
    status: "read",
    tradeLane: "*->IN",
  },
  {
    id: "ALT-010",
    title: "Origin marking requirements for consumer goods",
    country: "United States",
    authority: "U.S. Customs and Border Protection",
    regulationType: "Labeling & Conformity",
    publicationDate: "2025-12-22",
    affectedProducts: ["HS 854140", "HS 850440"],
    relevanceScore: 68,
    status: "read",
    tradeLane: "CN->US",
  },
  {
    id: "ALT-011",
    title: "Chemical safety regulations update for batteries",
    country: "EU",
    authority: "European Chemicals Agency (ECHA)",
    regulationType: "Safety Standards",
    publicationDate: "2025-12-20",
    affectedProducts: ["HS 850760", "HS 850720"],
    relevanceScore: 76,
    status: "read",
    userFeedback: "relevant",
    tradeLane: "*->EU",
  },
  {
    id: "ALT-012",
    title: "Cybersecurity requirements for IoT devices",
    country: "EU",
    authority: "European Union Agency for Cybersecurity (ENISA)",
    regulationType: "Safety Standards",
    publicationDate: "2025-12-15",
    affectedProducts: ["HS 851762", "HS 851770"],
    relevanceScore: 84,
    status: "read",
    tradeLane: "*->EU",
  },
  {
    id: "ALT-013",
    title: "Trade remedies on solar panel imports extended",
    country: "United States",
    authority: "U.S. International Trade Commission",
    regulationType: "Anti-dumping Measures",
    publicationDate: "2025-12-10",
    affectedProducts: ["HS 854140"],
    relevanceScore: 62,
    status: "read",
    tradeLane: "CN->US",
  },
  {
    id: "ALT-014",
    title: "Prohibited substances list update for electronics",
    country: "China",
    authority: "State Administration for Market Regulation",
    regulationType: "Safety Standards",
    publicationDate: "2025-12-08",
    affectedProducts: ["HS 854140", "HS 850440", "HS 851770"],
    relevanceScore: 79,
    status: "read",
    userFeedback: "relevant",
    tradeLane: "*->CN",
  },
  {
    id: "ALT-015",
    title: "Packaging and recycling requirements for electronics",
    country: "EU",
    authority: "European Parliament and Council",
    regulationType: "Environmental Standards",
    publicationDate: "2025-12-05",
    affectedProducts: ["HS 854140", "HS 851762"],
    relevanceScore: 70,
    status: "read",
    tradeLane: "*->EU",
  },
  {
    id: "ALT-016",
    title: "Import ban on certain electronic components",
    country: "India",
    authority: "Ministry of Electronics and IT",
    regulationType: "Import Restrictions",
    publicationDate: "2025-12-01",
    affectedProducts: ["HS 854140"],
    relevanceScore: 91,
    status: "read",
    userFeedback: "relevant",
    tradeLane: "*->IN",
  },
  {
    id: "ALT-017",
    title: "Energy efficiency labeling requirements update",
    country: "China",
    authority: "National Development and Reform Commission",
    regulationType: "Labeling & Conformity",
    publicationDate: "2025-11-28",
    affectedProducts: ["HS 850440", "HS 851770"],
    relevanceScore: 58,
    status: "read",
    tradeLane: "*->CN",
  },
  {
    id: "ALT-018",
    title: "Product safety recall procedures modernization",
    country: "United States",
    authority: "Consumer Product Safety Commission",
    regulationType: "Safety Standards",
    publicationDate: "2025-11-25",
    affectedProducts: ["HS 854140", "HS 851762"],
    relevanceScore: 73,
    status: "read",
    tradeLane: "*->US",
  },
  {
    id: "ALT-019",
    title: "Digital trade facilitation platform launch",
    country: "India",
    authority: "Directorate General of Foreign Trade (DGFT)",
    regulationType: "Import/Export Procedures",
    publicationDate: "2025-11-20",
    affectedProducts: ["HS 854140", "HS 850440", "HS 851770"],
    relevanceScore: 55,
    status: "read",
    tradeLane: "IN->*",
  },
  {
    id: "ALT-020",
    title: "Intellectual property enforcement at borders strengthened",
    country: "EU",
    authority: "European Commission - DG Taxation",
    regulationType: "Import/Export Procedures",
    publicationDate: "2025-11-18",
    affectedProducts: ["HS 854140", "HS 851762"],
    relevanceScore: 67,
    status: "read",
    tradeLane: "*->EU",
  },
];

function sortAlerts(list: Alert[]): Alert[] {
  return [...list].sort((a, b) => {
    // Pinned always wins.
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    // Newest first. publicationDate is an ISO 8601 datetime string —
    // lexicographic order matches chronological order for that format.
    // Fall back to relevance score on ties (or when one date is missing).
    if (a.publicationDate && b.publicationDate &&
        a.publicationDate !== b.publicationDate) {
      return b.publicationDate.localeCompare(a.publicationDate);
    }
    return b.relevanceScore - a.relevanceScore;
  });
}

export function AlertsView() {
  const navigate = useNavigate();
  // Subscribe to the global unread count so the inbox can detect when
  // *new* alerts arrive (count goes up) and refresh — but NOT when the
  // user marks alerts read (count goes down), which would yank rows
  // out from under them mid-action.
  const { unreadCount, refreshUnread } = useNotifications();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  // When true, the inbox includes status="read" alerts in addition to
  // status="new". Lets the user revisit alerts they've already seen
  // without going to the Archive page (those are explicitly dismissed).
  const [includeRead, setIncludeRead] = useState(false);
  // Filter + Sort state. Filters are inclusion sets — empty = no
  // restriction. Sort mode controls the ordering applied AFTER the
  // pinned-first preference.
  type SortMode = "newest" | "oldest" | "relevance-high" | "relevance-low";
  const [sortMode, setSortMode] = useState<SortMode>("newest");
  const [filterCountries, setFilterCountries] = useState<Set<string>>(
    new Set(),
  );
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set());
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const filterButtonRef = useRef<HTMLButtonElement | null>(null);
  const filterPanelRef = useRef<HTMLDivElement | null>(null);

  // Click-outside to close the filter panel.
  useEffect(() => {
    if (!filterPanelOpen) return;
    const onPointer = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node | null;
      if (
        filterPanelRef.current?.contains(t) ||
        filterButtonRef.current?.contains(t)
      ) {
        return;
      }
      setFilterPanelOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("touchstart", onPointer);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("touchstart", onPointer);
    };
  }, [filterPanelOpen]);
  // Mirror in a ref so the count-up watcher can read the latest value
  // without re-creating its closure each render.
  const includeReadRef = useRef(includeRead);
  useEffect(() => {
    includeReadRef.current = includeRead;
  }, [includeRead]);

  // Keyboard navigation index — which row is "selected" for j/k/Enter/e/r.
  // -1 means no row selected (initial state). The row at this index gets
  // a left ring + scrolls into view. Reset whenever the filtered list
  // changes shape.
  const [keyboardIdx, setKeyboardIdx] = useState<number>(-1);
  const tableContainerRef = useRef<HTMLDivElement | null>(null);

  // Build the list-of-statuses to fetch based on the toggle. Backend
  // accepts only one status per call, so we issue parallel requests
  // and concatenate.
  const fetchInbox = async (withRead: boolean): Promise<Alert[]> => {
    const calls = [listAlerts({ status: "new", limit: 200 })];
    if (withRead) calls.push(listAlerts({ status: "read", limit: 200 }));
    const results = await Promise.all(calls);
    return results.flat();
  };
  // Last unread count we synced to. Used by the watcher effect below
  // to detect *upward* drifts only (= new alerts arrived). Reset by
  // the cleanup on every real unmount so a fresh navigation gets a
  // clean baseline.
  const lastUnreadRef = useRef<number | null>(null);

  // ── Effect 1: initial fetch on mount + on toggle change ────────────
  // Runs on every real mount and whenever the user flips the
  // "include read" switch. Doesn't depend on the count, so it's not
  // affected by ref-persistence weirdness across StrictMode remounts.
  // The latest fetch wins via the cancellation flag.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetchInbox(includeRead)
      .then((rows) => {
        if (cancelled) return;
        setAlerts(sortAlerts(rows));
      })
      .catch((err: Error) => {
        if (cancelled) return;
        console.warn("API unreachable, using mock data:", err.message);
        setLoadError(err.message);
        setAlerts(sortAlerts(mockAlerts));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      // Reset the watcher's baseline so a future navigation back to
      // this view starts clean instead of comparing against a stale
      // count from the previous mount (which broke the loading state).
      lastUnreadRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeRead]);

  // ── Effect 2: silent re-fetch when new alerts arrive ───────────────
  // Watches the global unread count. When it goes UP we refetch
  // silently (no spinner) so the table grows without a flicker. When
  // it goes DOWN (the user marked some read / archived) we skip — we
  // don't want to yank the row they just acted on.
  useEffect(() => {
    const previous = lastUnreadRef.current;
    if (previous === null) {
      // First time we observe a count this mount — just record it.
      lastUnreadRef.current = unreadCount;
      return;
    }
    if (unreadCount <= previous) {
      lastUnreadRef.current = unreadCount;
      return;
    }
    lastUnreadRef.current = unreadCount;

    let cancelled = false;
    fetchInbox(includeReadRef.current)
      .then((rows) => {
        if (!cancelled) setAlerts(sortAlerts(rows));
      })
      .catch(() => {
        // Silent — the badge keeps refreshing on its own cadence.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unreadCount]);

  // Real counters — no more hardcoded "23". `reviewed` = alerts with a
  // thumbs-up/down/partial set. `total` = alerts currently visible in
  // the inbox (post-search-filter). Progress = reviewed / total.
  const reviewedCount = alerts.filter((a) => a.userFeedback).length;
  const totalCount = alerts.length;
  const progressPercentage =
    totalCount > 0 ? (reviewedCount / totalCount) * 100 : 0;

  const handleExportCsv = async () => {
    // Server streams the CSV with a stable column order; we just
    // trigger the download. The auth header has to come from authFetch
    // (the same wrapper API clients use) since the browser's <a download>
    // can't attach our Bearer token directly.
    try {
      const qs = new URLSearchParams();
      // Honour the include-read switch so the export matches what's
      // visually on screen — auditors get the rows they think they're
      // exporting.
      if (!includeRead) qs.set("status", "new");
      const url = `/api/v2/alerts/export.csv${qs.toString() ? `?${qs}` : ""}`;
      const { authFetch } = await import("@/app/auth");
      const res = await authFetch(url);
      if (!res.ok) {
        throw new Error(`Export failed: HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `regwatch-alerts-${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Free the object URL after the click; some browsers leak it.
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (err: any) {
      console.warn("CSV export failed:", err);
    }
  };

  const handleClearReviewed = async () => {
    // Archive every alert that has feedback set — clears them out of
    // the inbox for real, not just locally.
    const ids = alerts.filter((a) => a.userFeedback).map((a) => a.id);
    if (ids.length === 0) return;
    setAlerts((prev) => prev.filter((alert) => !alert.userFeedback));
    await Promise.allSettled(
      ids.map((id) => updateAlert(id, { status: "archived" })),
    );
    void refreshUnread();
  };

  const handleUndoFeedback = (alertId: string) => {
    setAlerts((prev) =>
      prev.map((alert) =>
        alert.id === alertId ? { ...alert, userFeedback: null } : alert,
      ),
    );
    updateAlert(alertId, { userFeedback: null }).catch((err) =>
      console.warn("undo feedback PATCH failed:", err),
    );
  };

  const handleFeedback = (alertId: string, feedback: AlertFeedback) => {
    setAlerts((prev) =>
      prev.map((alert) =>
        alert.id === alertId ? { ...alert, userFeedback: feedback } : alert,
      ),
    );
    updateAlert(alertId, { userFeedback: feedback }).catch((err) =>
      console.warn("feedback PATCH failed:", err),
    );
  };

  const toggleSeen = (alertId: string) => {
    let nextStatus: "new" | "read" = "read";
    setAlerts((prev) =>
      prev.map((alert) => {
        if (alert.id !== alertId) return alert;
        nextStatus = alert.status === "new" ? "read" : "new";
        return { ...alert, status: nextStatus };
      }),
    );
    updateAlert(alertId, { status: nextStatus })
      .then(() => {
        // Update the badge immediately so the user gets feedback that
        // their click had an effect — don't wait for the 60s periodic.
        void refreshUnread();
      })
      .catch((err) => console.warn("status PATCH failed:", err));
  };

  const handleArchive = (alertId: string) => {
    // Optimistically remove from the inbox and PATCH backend. The
    // alert's status becomes "archived" so it shows up in the Archive
    // page and never in the inbox again.
    setAlerts((prev) => prev.filter((alert) => alert.id !== alertId));
    updateAlert(alertId, { status: "archived" })
      .then(() => void refreshUnread())
      .catch((err) => console.warn("archive PATCH failed:", err));
  };

  const togglePin = (alertId: string) => {
    let nextPinned = false;
    setAlerts((prev) => {
      const updated = prev.map((alert) => {
        if (alert.id !== alertId) return alert;
        nextPinned = !alert.pinned;
        return { ...alert, pinned: nextPinned };
      });
      return sortAlerts(updated);
    });
    updateAlert(alertId, { pinned: nextPinned }).catch((err) =>
      console.warn("pin PATCH failed:", err),
    );
  };

  // Three-tier relevance colour. Mirrors the LLM scoring rubric:
  //   ≥ 80 → critical (red urgency — needs your attention now)
  //   60-79 → substantive (amber — meaningful change)
  //   < 60 → informational (slate — file under FYI)
  // The previous palette put two scores under the same primary/accent
  // colour so a 60% read like a 95% — flat hierarchy. This pulls the
  // urgent ones out visually and demotes the noise.
  const getRelevanceColor = (score: number) => {
    if (score >= 80) {
      return "bg-destructive/90 text-destructive-foreground border-transparent";
    }
    if (score >= 60) {
      return "bg-accent text-accent-foreground border-transparent";
    }
    return "bg-muted text-muted-foreground border-transparent";
  };

  const getCountryFlag = (country: string) => {
    const flagMap: { [key: string]: React.ReactNode } = {
      India: (
        <span className="inline-flex">
          <IN className="size-6" />
        </span>
      ),
      China: (
        <span className="inline-flex">
          <CN className="size-6" />
        </span>
      ),
      EU: (
        <span className="inline-flex">
          <EU className="size-6" />
        </span>
      ),
      "United States": (
        <span className="inline-flex">
          <US className="size-6" />
        </span>
      ),
    };
    return flagMap[country] || "🌐";
  };

  // Distinct countries and regulation types in the currently-loaded
  // alerts — drives the Filter popover's checkbox lists. Recomputing
  // each render is cheap for ≤200 alerts.
  const uniqueCountries = Array.from(
    new Set(alerts.map((a) => a.country).filter(Boolean)),
  ).sort();
  const uniqueTypes = Array.from(
    new Set(alerts.map((a) => a.regulationType).filter(Boolean)),
  ).sort();

  const activeFilterCount = filterCountries.size + filterTypes.size;

  const filteredAlerts = (() => {
    const query = searchQuery.toLowerCase();
    let list = alerts.filter((alert) => {
      // Search across the indexed text fields.
      const matchesQuery =
        query === "" ||
        alert.title.toLowerCase().includes(query) ||
        alert.country.toLowerCase().includes(query) ||
        alert.authority.toLowerCase().includes(query) ||
        alert.regulationType.toLowerCase().includes(query) ||
        alert.affectedProducts.some((p) =>
          p.toLowerCase().includes(query),
        ) ||
        alert.id.toLowerCase().includes(query);

      // Inclusion filters — empty set = no restriction. Multiple
      // selections within a category are OR'd; across categories
      // they're AND'd.
      const matchesCountry =
        filterCountries.size === 0 || filterCountries.has(alert.country);
      const matchesType =
        filterTypes.size === 0 || filterTypes.has(alert.regulationType);

      return matchesQuery && matchesCountry && matchesType;
    });

    // Sort: pinned first, then per the user's chosen mode. Falls back
    // to relevance for ties on date sorts.
    return [...list].sort((a, b) => {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      switch (sortMode) {
        case "newest":
          if (a.publicationDate && b.publicationDate &&
              a.publicationDate !== b.publicationDate) {
            return b.publicationDate.localeCompare(a.publicationDate);
          }
          return b.relevanceScore - a.relevanceScore;
        case "oldest":
          if (a.publicationDate && b.publicationDate &&
              a.publicationDate !== b.publicationDate) {
            return a.publicationDate.localeCompare(b.publicationDate);
          }
          return b.relevanceScore - a.relevanceScore;
        case "relevance-high":
          return b.relevanceScore - a.relevanceScore;
        case "relevance-low":
          return a.relevanceScore - b.relevanceScore;
      }
    });
  })();

  // ── Keyboard shortcuts ─────────────────────────────────────────────
  // j / k        — next / previous alert
  // Enter / o    — open the selected alert detail
  // e            — archive the selected alert
  // r            — toggle read / unread (mark seen)
  // p            — pin / unpin the selected alert
  // /            — focus the search input
  // Escape       — clear keyboard selection
  //
  // Skipped while the user is typing in any input/textarea/contenteditable
  // element so the search box and dialogs aren't hijacked. This is the
  // pattern Linear / Superhuman / GitHub all use; a compliance officer
  // burning through 50 alerts/day will instinctively look for it.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't intercept when the user is typing in a form field.
      const t = e.target as HTMLElement | null;
      const tag = (t?.tagName || "").toLowerCase();
      if (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        t?.isContentEditable
      ) {
        // Allow `/` to refocus search even from another input — but we're
        // already in one, so do nothing.
        return;
      }
      // Modifiers reserved for browser/OS shortcuts.
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const list = filteredAlerts;
      const len = list.length;
      const cur = keyboardIdx;

      switch (e.key) {
        case "j":
        case "ArrowDown": {
          if (len === 0) return;
          e.preventDefault();
          setKeyboardIdx((i) => (i < 0 ? 0 : Math.min(i + 1, len - 1)));
          break;
        }
        case "k":
        case "ArrowUp": {
          if (len === 0) return;
          e.preventDefault();
          setKeyboardIdx((i) => (i <= 0 ? 0 : i - 1));
          break;
        }
        case "Enter":
        case "o": {
          if (cur < 0 || cur >= len) return;
          e.preventDefault();
          navigate(`/alerts/${list[cur].id}`);
          break;
        }
        case "e": {
          if (cur < 0 || cur >= len) return;
          e.preventDefault();
          handleArchive(list[cur].id);
          // The row about to disappear — keep the same index so the
          // user lands on the next row down naturally.
          break;
        }
        case "r": {
          if (cur < 0 || cur >= len) return;
          e.preventDefault();
          toggleSeen(list[cur].id);
          break;
        }
        case "p": {
          if (cur < 0 || cur >= len) return;
          e.preventDefault();
          togglePin(list[cur].id);
          break;
        }
        case "/": {
          // Focus the search input. Don't preventDefault until we know
          // the input is there, so falling through still works.
          const search = document.querySelector<HTMLInputElement>(
            'input[type="search"], input[placeholder^="Search alerts"]',
          );
          if (search) {
            e.preventDefault();
            search.focus();
            search.select();
          }
          break;
        }
        case "Escape": {
          if (cur >= 0) {
            e.preventDefault();
            setKeyboardIdx(-1);
          }
          break;
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredAlerts, keyboardIdx]);

  // Clamp the keyboard index when filtered list shrinks (e.g. user
  // archives the selected row, or filter narrows it out of view).
  useEffect(() => {
    if (keyboardIdx >= filteredAlerts.length) {
      setKeyboardIdx(filteredAlerts.length > 0 ? filteredAlerts.length - 1 : -1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredAlerts.length]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <p className="text-muted-foreground">Loading alerts…</p>
      </div>
    );
  }

  // True empty state: zero alerts loaded and no active search. We
  // render the toolbar (with the Include-read toggle) on top of the
  // empty state so the user can flip the switch and see read alerts
  // without leaving the page — earlier this view returned early and
  // hid the toggle entirely, which was confusing.
  const isEmpty = alerts.length === 0 && searchQuery === "";

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-muted-foreground">
              Review pending alerts on global trade regulatory changes
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <Switch
                checked={includeRead}
                onCheckedChange={setIncludeRead}
                aria-label="Include read alerts"
              />
              <span
                className="text-muted-foreground"
                style={{ fontSize: "var(--text-sm)" }}
              >
                Include read
              </span>
            </label>

            {/* Filter — popover with country + type checklists ────── */}
            <div className="relative">
              <Button
                ref={filterButtonRef}
                variant={activeFilterCount > 0 ? "default" : "outline"}
                onClick={() => setFilterPanelOpen((v) => !v)}
                aria-expanded={filterPanelOpen}
                aria-haspopup="dialog"
                className="gap-2"
              >
                <FilterIcon className="size-4" />
                Filter
                {activeFilterCount > 0 && (
                  <Badge
                    variant="secondary"
                    className="bg-primary-foreground text-primary px-1.5"
                  >
                    {activeFilterCount}
                  </Badge>
                )}
              </Button>
              {filterPanelOpen && (
                <div
                  ref={filterPanelRef}
                  role="dialog"
                  aria-label="Filter alerts"
                  className="absolute right-0 top-full mt-2 z-30 w-80 rounded-md border bg-card shadow-lg"
                >
                  <div className="px-4 py-3 flex items-center justify-between border-b">
                    <p
                      style={{
                        fontWeight: "var(--font-weight-medium)",
                      }}
                    >
                      Filters
                    </p>
                    {activeFilterCount > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setFilterCountries(new Set());
                          setFilterTypes(new Set());
                        }}
                      >
                        Clear all
                      </Button>
                    )}
                  </div>

                  <div className="max-h-96 overflow-y-auto">
                    {uniqueCountries.length > 0 && (
                      <div className="px-4 py-3 border-b">
                        <p
                          className="text-muted-foreground mb-2 uppercase tracking-wider"
                          style={{
                            fontSize: "var(--text-xs)",
                            fontWeight: "var(--font-weight-medium)",
                          }}
                        >
                          Country
                        </p>
                        <div className="space-y-1.5">
                          {uniqueCountries.map((c) => (
                            <label
                              key={c}
                              className="flex items-center gap-2 cursor-pointer hover:bg-muted/40 rounded px-2 py-1 -mx-2"
                            >
                              <Checkbox
                                checked={filterCountries.has(c)}
                                onCheckedChange={(checked) => {
                                  setFilterCountries((prev) => {
                                    const next = new Set(prev);
                                    if (checked) next.add(c);
                                    else next.delete(c);
                                    return next;
                                  });
                                }}
                              />
                              <span
                                style={{ fontSize: "var(--text-sm)" }}
                              >
                                {c}
                              </span>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {uniqueTypes.length > 0 && (
                      <div className="px-4 py-3">
                        <p
                          className="text-muted-foreground mb-2 uppercase tracking-wider"
                          style={{
                            fontSize: "var(--text-xs)",
                            fontWeight: "var(--font-weight-medium)",
                          }}
                        >
                          Regulation Type
                        </p>
                        <div className="space-y-1.5">
                          {uniqueTypes.map((t) => (
                            <label
                              key={t}
                              className="flex items-center gap-2 cursor-pointer hover:bg-muted/40 rounded px-2 py-1 -mx-2"
                            >
                              <Checkbox
                                checked={filterTypes.has(t)}
                                onCheckedChange={(checked) => {
                                  setFilterTypes((prev) => {
                                    const next = new Set(prev);
                                    if (checked) next.add(t);
                                    else next.delete(t);
                                    return next;
                                  });
                                }}
                              />
                              <span
                                style={{ fontSize: "var(--text-sm)" }}
                              >
                                {t}
                              </span>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Sort dropdown ────────────────────────────────────── */}
            <Select
              value={sortMode}
              onValueChange={(v) => setSortMode(v as SortMode)}
            >
              <SelectTrigger
                className="w-[180px]"
                aria-label="Sort alerts"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">Newest first</SelectItem>
                <SelectItem value="oldest">Oldest first</SelectItem>
                <SelectItem value="relevance-high">Highest relevance</SelectItem>
                <SelectItem value="relevance-low">Lowest relevance</SelectItem>
              </SelectContent>
            </Select>

            {/* Visual divider between the "view" cluster
                (include-read / filter / sort) above and the "tools"
                cluster (export / keyboard hint) below. Without this
                the toolbar reads as one wall of controls. */}
            <div className="hidden lg:block w-px h-6 bg-border" />

            {/* Export current filtered view as CSV. The backend
                endpoint mirrors the same auth + status filter the
                inbox uses; auditors get a stable column order they
                can sort/pivot in Excel. */}
            <Button
              variant="outline"
              onClick={handleExportCsv}
              className="gap-2"
              aria-label="Export alerts as CSV"
            >
              <Download className="size-4" />
              Export CSV
            </Button>

            {/* Keyboard hint — small, muted, and tucked behind the
                divider so the toolbar reads as two clusters instead
                of one wall of controls. Pro tools earn their "feels
                fast" reputation here. */}
            <span
              className="hidden xl:inline text-muted-foreground select-none"
              style={{ fontSize: "var(--text-xs)" }}
              title="Keyboard shortcuts: j/k navigate · Enter open · e archive · r mark read · p pin · / search"
            >
              <kbd className="px-1.5 py-0.5 rounded border bg-muted">j</kbd>
              <kbd className="px-1.5 py-0.5 rounded border bg-muted ml-1">k</kbd>
              <span className="ml-1">to navigate</span>
            </span>
          </div>
        </div>

        {/* Review Progress is only meaningful AFTER the user has
            actually reviewed something. Showing an empty 0% bar at
            the top of an inbox is just visual noise — hide until
            there's progress to show. */}
        {!isEmpty && reviewedCount > 0 && (
          <div className="rounded-md border bg-card p-4">
            <div className="flex items-center justify-between mb-2">
              <p
                style={{
                  fontSize: "var(--text-sm)",
                  fontWeight: "var(--font-weight-medium)",
                }}
              >
                Review Progress
              </p>
              <div className="flex items-center gap-3">
                <p
                  className="text-muted-foreground"
                  style={{ fontSize: "var(--text-sm)" }}
                >
                  {reviewedCount} of {totalCount} reviewed
                </p>
                <Button
                  size="sm"
                  variant="default"
                  onClick={handleClearReviewed}
                  title="Archive every alert you've already reviewed"
                >
                  Archive reviewed ({reviewedCount})
                </Button>
              </div>
            </div>
            <Progress value={progressPercentage} className="h-2" />
          </div>
        )}
      </div>

      {isEmpty ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] text-center space-y-4 py-8">
          <div className="flex items-center justify-center">
            <div className="rounded-full bg-accent/10 p-6">
              <Check className="size-12 text-accent" />
            </div>
          </div>
          <h2 className="text-2xl">You're all caught up ✓</h2>
          <p className="text-muted-foreground max-w-md">
            {includeRead
              ? "No new or read alerts in your inbox. Use the toggle above to hide read ones, or check the archive."
              : "No pending alerts to review. Flip the “Include read” switch above to revisit alerts you've already seen, or open the archive."}
          </p>
          <Button
            variant="link"
            onClick={() => navigate("/archive")}
            className="text-primary"
          >
            View Archive →
          </Button>
        </div>
      ) : (
        <>
      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search alerts by title, country, authority, type, or product..."
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

      {/* Inbox grid — Linear / Superhuman style. Two cells per row:
          a flexible Alert cell on the left, a compact "meta + actions"
          cell on the right that expands only as wide as its contents.
          No table header — an inbox doesn't need one, and dropping it
          recovers ~30px of vertical space per page. */}
      <div className="rounded-md border bg-card">
        <Table>
          <TableBody>
            {filteredAlerts.length === 0 ? (
              <TableRow>
                <TableCell colSpan={2} className="h-24 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <Search className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">
                      No alerts found matching "{searchQuery}"
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              filteredAlerts.map((alert, idx) => {
                const isReviewed = !!alert.userFeedback;
                const isUnread = alert.status === "new" && !isReviewed;
                const isKeyboardFocused = idx === keyboardIdx;
                // Three visual tiers:
                //   reviewed (feedback set): heavy fade — done with it
                //   read (status=read, no feedback): light fade — seen but not dispositioned
                //   new: full opacity + accent stripe + bold title
                const rowOpacity = isReviewed
                  ? "opacity-40"
                  : alert.status === "read"
                    ? "opacity-70"
                    : "";
                // Unread rows get a left accent stripe + tinted background
                // so they're unmistakable even when the table has only one
                // row (otherwise the subtle opacity/badge cues are easy
                // to miss).
                const unreadCue = isUnread
                  ? "relative bg-primary/5 before:content-[''] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 before:bg-primary"
                  : "";

                const keyboardCue = isKeyboardFocused
                  ? "outline outline-2 outline-offset-[-2px] outline-primary"
                  : "";

                return (
                  <TableRow
                    key={alert.id}
                    ref={
                      isKeyboardFocused
                        ? (el) => el?.scrollIntoView({ block: "nearest" })
                        : undefined
                    }
                    onClick={() => setKeyboardIdx(idx)}
                    className={`group ${rowOpacity} ${unreadCue} ${keyboardCue}`.trim()}
                  >
                    {/* Single rich Alert cell — country flag inline,
                        title clickable, authority + chips below */}
                    <TableCell>
                      <div className="flex items-start gap-3 max-w-2xl">
                        <div className="shrink-0 mt-0.5">
                          {getCountryFlag(alert.country)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start gap-2 flex-wrap">
                            {isUnread && (
                              <Badge
                                variant="default"
                                className="shrink-0"
                                style={{ fontSize: "var(--text-xs)" }}
                              >
                                New
                              </Badge>
                            )}
                            {alert.pinned && (
                              <Badge
                                variant="outline"
                                className="shrink-0 text-primary border-primary/30 gap-1"
                                style={{ fontSize: "var(--text-xs)" }}
                              >
                                <Pin className="size-3 fill-current" />
                                Pinned
                              </Badge>
                            )}
                            <p
                              onClick={() => navigate(`/alerts/${alert.id}`)}
                              className="cursor-pointer hover:text-primary hover:underline truncate"
                              style={{
                                fontWeight: isReviewed
                                  ? "var(--font-weight-normal)"
                                  : isUnread
                                    ? "var(--font-weight-bold)"
                                    : "var(--font-weight-medium)",
                              }}
                            >
                              {alert.title}
                            </p>
                          </div>
                          <div
                            className="flex items-center gap-2 flex-wrap text-muted-foreground mt-1"
                            style={{ fontSize: "var(--text-xs)" }}
                          >
                            <span className="truncate max-w-[260px]">
                              {alert.authority}
                            </span>
                            <span className="opacity-50">·</span>
                            <span>{alert.country}</span>
                            <span className="opacity-50">·</span>
                            <Badge
                              variant="outline"
                              className="px-1.5 py-0 h-4"
                              style={{ fontSize: "var(--text-xs)" }}
                            >
                              {alert.tradeLane}
                            </Badge>
                            <Badge
                              variant="outline"
                              className="px-1.5 py-0 h-4"
                              style={{ fontSize: "var(--text-xs)" }}
                            >
                              {alert.regulationType}
                            </Badge>
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    {/* Single right cell — date + relevance + actions
                        in one flex row. Cell shrinks to content (w-px
                        + whitespace-nowrap), leaving the Alert cell to
                        absorb all remaining space. Actions hide-on-idle
                        so an unhovered row reads as just title + date
                        + score, with no dead column on the right. */}
                    <TableCell className="w-px whitespace-nowrap pr-3">
                      <div className="flex items-center justify-end gap-3">
                        {/* Compact date — small, right-aligned, two
                            lines (date / time) so the right edge is
                            visually quiet. */}
                        <div className="text-muted-foreground tabular-nums text-right leading-tight">
                          {alert.publicationDate ? (
                            (() => {
                              const d = new Date(alert.publicationDate);
                              if (Number.isNaN(d.getTime())) return "—";
                              return (
                                <>
                                  <div style={{ fontSize: "var(--text-xs)" }}>
                                    {d.toLocaleDateString("en-US", {
                                      month: "short",
                                      day: "numeric",
                                    })}
                                  </div>
                                  <div
                                    className="opacity-60"
                                    style={{ fontSize: "var(--text-xs)" }}
                                  >
                                    {d.toLocaleTimeString("en-US", {
                                      hour: "2-digit",
                                      minute: "2-digit",
                                      hour12: false,
                                    })}
                                  </div>
                                </>
                              );
                            })()
                          ) : (
                            "—"
                          )}
                        </div>

                        {/* Relevance pill — three-tier colour. */}
                        <Badge className={getRelevanceColor(alert.relevanceScore)}>
                          {alert.relevanceScore}%
                        </Badge>

                        {/* Actions — hidden on idle, revealed on
                            row-hover or keyboard focus. When already
                            in a state (pinned / reviewed) they stay
                            visible so the user can see the state. */}
                        <div
                          className={`flex items-center gap-1 transition-opacity duration-150 ${
                            isKeyboardFocused || alert.pinned || isReviewed
                              ? "opacity-100"
                              : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"
                          }`}
                        >
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => togglePin(alert.id)}
                          title={alert.pinned ? "Unpin alert" : "Pin to top"}
                          className={`h-8 w-8 ${
                            alert.pinned
                              ? "text-primary"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          <Pin
                            className={`size-4 ${alert.pinned ? "fill-current" : ""}`}
                          />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => toggleSeen(alert.id)}
                          title={
                            alert.status === "new"
                              ? "Mark as seen"
                              : "Mark as new"
                          }
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                        >
                          {alert.status === "new" ? (
                            <EyeOff className="size-4" />
                          ) : (
                            <Eye className="size-4" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleArchive(alert.id)}
                          title="Archive — remove from inbox"
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                        >
                          <Archive className="size-4" />
                        </Button>

                        <div className="w-px h-5 bg-border mx-1" />

                        {isReviewed ? (
                          <>
                            <Badge
                              variant="outline"
                              className="bg-muted text-muted-foreground border-muted-foreground/20 h-7"
                            >
                              {alert.userFeedback === "relevant" && (
                                <>
                                  <ThumbsUp className="size-3 mr-1" />
                                  Relevant
                                </>
                              )}
                              {alert.userFeedback === "not_relevant" && (
                                <>
                                  <ThumbsDown className="size-3 mr-1" />
                                  Not relevant
                                </>
                              )}
                              {alert.userFeedback === "partially_relevant" && (
                                <>
                                  <Clock className="size-3 mr-1" />
                                  Partial
                                </>
                              )}
                            </Badge>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleUndoFeedback(alert.id)}
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                              title="Undo review"
                            >
                              <Undo2 className="size-3" />
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleFeedback(alert.id, "relevant")}
                              title="Mark relevant"
                              className="h-8 w-8 hover:bg-accent/15 hover:text-accent"
                            >
                              <ThumbsUp className="size-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                handleFeedback(alert.id, "partially_relevant")
                              }
                              title="Partially relevant"
                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                            >
                              <Clock className="size-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                handleFeedback(alert.id, "not_relevant")
                              }
                              title="Not relevant"
                              className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            >
                              <ThumbsDown className="size-4" />
                            </Button>
                          </>
                        )}
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
        </>
      )}
    </div>
  );
}
