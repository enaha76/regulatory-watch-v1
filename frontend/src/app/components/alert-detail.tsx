import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router";
import {
  AlertDetail as ApiAlertDetail,
  AlertDiff,
  Obligation,
  getAlert,
} from "@/api/alerts";
import { Button } from "@/app/components/ui/button";
import { Badge } from "@/app/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/app/components/ui/card";
import {
  ArrowLeft,
  ExternalLink,
  Calendar,
  MapPin,
  FileText,
  Download,
  GitCompare,
  ListChecks,
  AlertTriangle,
  Clock,
  Users,
  Sparkles,
} from "lucide-react";
import { IN, CN, EU, US } from "country-flag-icons/react/3x2";

// Detail page reuses the API model — adds summary[], sourceUrl, pdfUrl?.
type Alert = ApiAlertDetail;

// Dev-only fallback used when the API isn't reachable (e.g. backend down).
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
    summary: [
      "The Directorate General of Foreign Trade (DGFT) has announced revised tariff rates for semiconductor imports, effective March 1, 2026. This measure aims to support domestic semiconductor manufacturing while managing import dependencies. The new rates will apply to HS codes 854140 and 850440, with increases ranging from 5% to 12% depending on the product category.",
      "The tariff adjustments are part of India's broader strategy to strengthen its electronics manufacturing sector under the 'Make in India' initiative. Industry stakeholders have been given a two-month transition period to adjust their supply chains and pricing structures.",
      "Importers and manufacturers are advised to review their current inventory levels and procurement contracts in light of these changes. Companies should submit any requests for exemptions through the designated online portal by February 15, 2026.",
    ],
    sourceUrl: "https://www.dgft.gov.in/CP/",
    pdfUrl: "/downloads/ALT-001-tariff-rates-semiconductor-2026.pdf",
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
    summary: [
      "China's Ministry of Commerce has issued updated import licensing requirements for electrical machinery and equipment, effective February 1, 2026. The new regulations introduce enhanced documentation requirements and mandatory pre-shipment inspections for products classified under HS codes 850440 and 851770.",
      "Under the revised framework, importers must obtain an Automatic Import License (AIL) for all covered products before customs clearance. Processing time for licenses is estimated at 15-20 business days, and licenses remain valid for six months.",
      "MOFCOM has established a dedicated helpdesk to assist foreign manufacturers and importers with the transition to the new licensing system.",
    ],
    sourceUrl: "http://english.mofcom.gov.cn/",
    pdfUrl: "/downloads/ALT-002-licensing-electrical-machinery-2026.pdf",
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
    summary: [
      "The European Commission has introduced updated conformity assessment procedures for consumer electronics entering the EU market. These changes, taking effect July 1, 2026, strengthen requirements for CE marking, technical documentation, and third-party testing for products classified under HS codes 854140 and 851762.",
      "Manufacturers and importers must now provide more comprehensive technical files including detailed design specifications, risk assessments, and test reports from EU-notified bodies.",
      "A six-month grace period has been established to allow market participants to adapt to the new requirements.",
    ],
    sourceUrl: "https://commission.europa.eu/",
    pdfUrl: "/downloads/ALT-003-conformity-assessment-electronics-2026.pdf",
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
    summary: [
      "The Bureau of Industry and Security (BIS) has implemented immediate export restrictions on advanced semiconductor manufacturing equipment classified under HS code 854140. The restrictions apply to equipment capable of producing semiconductors with node sizes of 14 nanometers or below.",
      "Exporters must now obtain specific licenses from BIS before shipping covered equipment to most destinations worldwide. The licensing process includes detailed end-use and end-user verification requirements.",
      "Companies are advised to conduct immediate reviews of their export compliance programs and pending shipments to ensure full compliance with the new controls.",
    ],
    sourceUrl: "https://www.bis.doc.gov/",
    pdfUrl: "/downloads/ALT-004-export-controls-semiconductor-2026.pdf",
    tradeLane: "US->*",
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
    summary: [
      "The European Commission's Directorate-General for Trade has initiated an anti-dumping investigation concerning imports of lithium-ion batteries from China, classified under HS codes 850760 and 850720.",
      "During the investigation period, which is expected to last 12-15 months, the Commission will collect detailed data on production costs, sales prices, and market conditions from both complainants and exporters.",
      "If the investigation confirms dumping, the Commission could impose anti-dumping duties ranging from 15% to 60% depending on the cooperation level of individual exporters.",
    ],
    sourceUrl: "https://policy.trade.ec.europa.eu/",
    tradeLane: "CN->EU",
  },
];

// ─────────────────────────────────────────────────────────────────────
// Diff section — renders the unified-diff payload from the backend with
// per-line color coding so the user can see exactly what changed at the
// source. Designed to be informative without overwhelming: cosmetic
// edits get a muted strip, substantive changes get full color.
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// Obligations section — surfaces the structured "who must do what by
// when" rows the LLM extracted for this regulation. Designed to be
// scannable: type badge on the left, deadline pinned to the right.
// ─────────────────────────────────────────────────────────────────────

const OBLIGATION_TYPE_LABEL: Record<string, string> = {
  reporting: "Reporting",
  prohibition: "Prohibition",
  threshold: "Threshold",
  disclosure: "Disclosure",
  registration: "Registration",
  penalty: "Penalty",
  other: "Action",
};

const OBLIGATION_TYPE_TONE: Record<string, string> = {
  reporting: "bg-primary/10 text-primary border-primary/20",
  prohibition: "bg-destructive/10 text-destructive border-destructive/20",
  threshold: "bg-amber-500/10 text-amber-700 border-amber-500/30",
  disclosure: "bg-primary/10 text-primary border-primary/20",
  registration: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30",
  penalty: "bg-destructive/10 text-destructive border-destructive/20",
  other: "bg-muted text-muted-foreground border-border",
};

function isOverdue(iso: string): boolean {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.getTime() < Date.now();
}

function daysUntil(iso: string): number | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

function ObligationsSection({ obligations }: { obligations: Obligation[] }) {
  // Group: overdue + soon (within 30 days) bubble to the top of the
  // user's attention, followed by everything else.
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <ListChecks className="size-5 text-muted-foreground" />
        <h3 className="font-semibold text-lg">Compliance Obligations</h3>
        <Badge variant="outline" className="ml-1">
          {obligations.length}
        </Badge>
      </div>
      <div className="space-y-3">
        {obligations.map((o) => (
          <ObligationCard key={o.id} obligation={o} />
        ))}
      </div>
    </div>
  );
}

function ObligationCard({ obligation: o }: { obligation: Obligation }) {
  const typeLabel = OBLIGATION_TYPE_LABEL[o.type] ?? "Action";
  const typeTone =
    OBLIGATION_TYPE_TONE[o.type] ??
    "bg-muted text-muted-foreground border-border";

  const deadlineMeta = (() => {
    if (!o.deadlineDate && !o.deadlineText) return null;
    if (!o.deadlineDate) {
      return { text: o.deadlineText || "", overdue: false, soon: false };
    }
    const overdue = isOverdue(o.deadlineDate);
    const days = daysUntil(o.deadlineDate);
    const soon = days !== null && days >= 0 && days <= 30;
    const formatted = new Date(o.deadlineDate).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    return {
      text: formatted,
      overdue,
      soon,
      days,
    };
  })();

  return (
    <div className="rounded-md border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge
              variant="outline"
              className={`${typeTone} uppercase tracking-wider`}
              style={{ fontSize: "var(--text-xs)" }}
            >
              {typeLabel}
            </Badge>
            <span
              className="text-muted-foreground flex items-center gap-1"
              style={{ fontSize: "var(--text-xs)" }}
            >
              <Users className="size-3" />
              {o.actor}
            </span>
          </div>
          <p className="leading-relaxed">{o.action}</p>
          {o.condition && (
            <p
              className="text-muted-foreground"
              style={{ fontSize: "var(--text-sm)" }}
            >
              <span style={{ fontWeight: "var(--font-weight-medium)" }}>
                If:
              </span>{" "}
              {o.condition}
            </p>
          )}
          {o.penalty && (
            <p
              className="flex items-start gap-1.5"
              style={{ fontSize: "var(--text-sm)" }}
            >
              <AlertTriangle className="size-4 text-destructive shrink-0 mt-0.5" />
              <span>
                <span
                  className="text-destructive"
                  style={{ fontWeight: "var(--font-weight-medium)" }}
                >
                  Penalty:
                </span>{" "}
                <span className="text-muted-foreground">{o.penalty}</span>
              </span>
            </p>
          )}
        </div>
        {deadlineMeta && (
          <div className="text-right shrink-0">
            <div
              className={`flex items-center gap-1 justify-end ${
                deadlineMeta.overdue
                  ? "text-destructive"
                  : deadlineMeta.soon
                    ? "text-amber-700"
                    : "text-muted-foreground"
              }`}
              style={{ fontSize: "var(--text-xs)" }}
            >
              <Clock className="size-3" />
              <span style={{ fontWeight: "var(--font-weight-medium)" }}>
                {deadlineMeta.overdue
                  ? "Overdue"
                  : deadlineMeta.soon && deadlineMeta.days !== undefined
                    ? `In ${deadlineMeta.days} day${deadlineMeta.days === 1 ? "" : "s"}`
                    : "Deadline"}
              </span>
            </div>
            <p
              className="tabular-nums"
              style={{
                fontSize: "var(--text-sm)",
                fontWeight: "var(--font-weight-medium)",
              }}
            >
              {deadlineMeta.text}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

const CHANGE_TYPE_LABEL: Record<string, string> = {
  typo_or_cosmetic: "Cosmetic edit",
  minor_wording: "Minor wording",
  clarification: "Clarification",
  substantive: "Substantive change",
  critical: "Critical change",
};

function changeTypeTone(kind: AlertDiff["changeType"]): {
  badge: string;
  border: string;
} {
  switch (kind) {
    case "critical":
      return {
        badge: "bg-destructive text-destructive-foreground",
        border: "border-destructive/50",
      };
    case "substantive":
      return {
        badge: "bg-accent text-accent-foreground",
        border: "border-accent/50",
      };
    case "clarification":
    case "minor_wording":
      return {
        badge: "bg-primary text-primary-foreground",
        border: "border-primary/40",
      };
    case "typo_or_cosmetic":
    default:
      return {
        badge: "bg-muted text-muted-foreground",
        border: "border-border",
      };
  }
}

function DiffSection({ diff }: { diff: AlertDiff }) {
  // Default to the readable view; power users can flip to the raw
  // unified-diff format if they want hunk markers and context lines.
  const [viewMode, setViewMode] = useState<"readable" | "raw">("readable");

  // For "created" alerts there's no previous version to diff against.
  // Show a small notice rather than hiding the whole section so the
  // user knows the alert is a brand-new document, not just unchanged.
  if (diff.kind === "created") {
    return (
      <div className="pt-4 border-t">
        <div className="flex items-center gap-2 mb-3">
          <GitCompare className="size-5 text-muted-foreground" />
          <h3 className="font-semibold">What changed</h3>
        </div>
        <p className="text-muted-foreground" style={{ fontSize: "var(--text-sm)" }}>
          This is a newly-detected document — no previous version to
          compare against. The full content is summarized above.
        </p>
      </div>
    );
  }

  const tone = changeTypeTone(diff.changeType);
  const label = diff.changeType
    ? (CHANGE_TYPE_LABEL[diff.changeType] ?? diff.changeType)
    : "Modified";

  return (
    <div className="pt-4 border-t">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <GitCompare className="size-5 text-muted-foreground" />
        <h3 className="font-semibold">What changed</h3>
        <Badge className={`ml-1 ${tone.badge}`}>{label}</Badge>
        <span
          className="text-muted-foreground"
          style={{ fontSize: "var(--text-xs)" }}
        >
          <span className="text-emerald-600 dark:text-emerald-500">
            +{diff.addedChars}
          </span>{" "}
          ·{" "}
          <span className="text-destructive">−{diff.removedChars}</span>{" "}
          chars
        </span>
        {diff.unifiedDiff && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() =>
              setViewMode(viewMode === "readable" ? "raw" : "readable")
            }
          >
            {viewMode === "readable" ? "Show raw diff" : "Show readable view"}
          </Button>
        )}
      </div>

      {diff.unifiedDiff ? (
        viewMode === "readable" ? (
          <DiffReadable patch={diff.unifiedDiff} borderClass={tone.border} />
        ) : (
          <DiffBody patch={diff.unifiedDiff} borderClass={tone.border} />
        )
      ) : (
        <p
          className="text-muted-foreground"
          style={{ fontSize: "var(--text-sm)" }}
        >
          The diff isn't available for this alert (older event or
          truncated).
        </p>
      )}
    </div>
  );
}

/**
 * Parse a unified diff into structured hunks the readable view can
 * group. Each hunk is one contiguous patch region; we keep removed
 * and added lines separately so the readable view can render them as
 * "Before/After" blocks.
 */
type DiffHunk = { removed: string[]; added: string[] };

function parseHunks(patch: string): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  let current: DiffHunk | null = null;
  for (const raw of patch.split("\n")) {
    if (raw.startsWith("--- ") || raw.startsWith("+++ ")) continue;
    if (raw.startsWith("@@")) {
      // New hunk boundary — flush the previous one if it had any
      // edits in it, then start fresh.
      if (current && (current.added.length || current.removed.length)) {
        hunks.push(current);
      }
      current = { removed: [], added: [] };
      continue;
    }
    if (!current) current = { removed: [], added: [] };
    if (raw.startsWith("+")) current.added.push(raw.slice(1));
    else if (raw.startsWith("-")) current.removed.push(raw.slice(1));
    // Context lines are ignored in the readable view.
  }
  if (current && (current.added.length || current.removed.length)) {
    hunks.push(current);
  }
  return hunks;
}

/**
 * Human-readable rendering: drop file headers, hunk markers, and
 * unchanged context. Just show "Before" (red) and "After" (green) for
 * each contiguous region of edits, separated by horizontal rules.
 *
 * Also collapses adjacent blank lines so a 100-line addition with
 * scattered empty lines reads as prose, not a sparse pre-formatted
 * block.
 */
function DiffReadable({
  patch,
  borderClass,
}: {
  patch: string;
  borderClass: string;
}) {
  const hunks = parseHunks(patch);
  if (hunks.length === 0) {
    return (
      <p
        className="text-muted-foreground"
        style={{ fontSize: "var(--text-sm)" }}
      >
        No textual changes in this revision (whitespace-only).
      </p>
    );
  }

  const collapseBlanks = (lines: string[]) => {
    const out: string[] = [];
    let blankRun = 0;
    for (const line of lines) {
      const isBlank = line.trim() === "";
      if (isBlank) {
        blankRun++;
        if (blankRun <= 1) out.push("");
      } else {
        blankRun = 0;
        out.push(line);
      }
    }
    return out;
  };

  return (
    <div className={`rounded-md border ${borderClass} bg-card`}>
      {hunks.map((h, idx) => (
        <div
          key={idx}
          className={
            idx > 0 ? "border-t px-4 py-3 space-y-3" : "px-4 py-3 space-y-3"
          }
        >
          {h.removed.length > 0 && (
            <div>
              <p
                className="text-destructive mb-1.5"
                style={{
                  fontSize: "var(--text-xs)",
                  fontWeight: "var(--font-weight-medium)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                Before
              </p>
              <div
                className="rounded bg-destructive/5 border border-destructive/20 p-3 leading-relaxed whitespace-pre-wrap break-words"
                style={{ fontSize: "var(--text-sm)" }}
              >
                <span className="line-through decoration-destructive/40 text-foreground/80">
                  {collapseBlanks(h.removed).join("\n").trim() || " "}
                </span>
              </div>
            </div>
          )}
          {h.added.length > 0 && (
            <div>
              <p
                className="text-emerald-600 dark:text-emerald-500 mb-1.5"
                style={{
                  fontSize: "var(--text-xs)",
                  fontWeight: "var(--font-weight-medium)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                After
              </p>
              <div
                className="rounded bg-emerald-500/5 border border-emerald-500/20 p-3 leading-relaxed whitespace-pre-wrap break-words text-foreground"
                style={{ fontSize: "var(--text-sm)" }}
              >
                {collapseBlanks(h.added).join("\n").trim() || " "}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Render a unified-diff string. Strips the `--- previous` / `+++ current`
 * file headers, shows hunk markers as section labels, colour-codes added
 * (+) / removed (-) / context ( ) lines.
 */
function DiffBody({
  patch,
  borderClass,
}: {
  patch: string;
  borderClass: string;
}) {
  const lines = patch.split("\n");
  return (
    <div
      className={`rounded-md border ${borderClass} bg-muted/20 overflow-x-auto`}
    >
      <pre
        className="font-mono p-4 m-0 leading-relaxed"
        style={{ fontSize: "var(--text-xs)" }}
      >
        {lines.map((line, idx) => {
          // Skip the "--- previous" / "+++ current" file headers — the
          // user already knows what they're looking at.
          if (line.startsWith("--- ") || line.startsWith("+++ ")) return null;

          if (line.startsWith("@@")) {
            return (
              <div
                key={idx}
                className="text-muted-foreground bg-muted/40 -mx-4 px-4 py-1 my-1"
              >
                {line}
              </div>
            );
          }
          if (line.startsWith("+")) {
            return (
              <div
                key={idx}
                className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 -mx-4 px-4 whitespace-pre-wrap break-words"
              >
                {line}
              </div>
            );
          }
          if (line.startsWith("-")) {
            return (
              <div
                key={idx}
                className="bg-destructive/10 text-destructive -mx-4 px-4 whitespace-pre-wrap break-words"
              >
                {line}
              </div>
            );
          }
          return (
            <div
              key={idx}
              className="text-muted-foreground whitespace-pre-wrap break-words"
            >
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

export function AlertDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) {
      setLoading(false);
      setNotFound(true);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    getAlert(id)
      .then((data) => {
        if (!cancelled) setAlert(data);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        // Distinguish "API unreachable" from "id not found".
        //   - HTTP 4xx (404 / 422 …) means the server answered but the
        //     id doesn't exist → show "Alert not found", DON'T fall back
        //     to mock data (which has fake URLs that 404 elsewhere).
        //   - Network errors (TypeError "Failed to fetch") mean the API
        //     is down → mock fallback is acceptable for dev.
        const msg = err.message || "";
        const looksLikeNetworkError =
          err instanceof TypeError ||
          msg.toLowerCase().includes("failed to fetch") ||
          msg.toLowerCase().includes("network");
        if (looksLikeNetworkError) {
          const fallback = mockAlerts.find((a) => a.id === id);
          if (fallback) {
            console.warn("API unreachable, using mock data:", msg);
            setAlert(fallback);
            return;
          }
        }
        setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <p className="text-muted-foreground">Loading alert…</p>
      </div>
    );
  }

  if (notFound || !alert) {
    return (
      <div className="flex flex-col items-center justify-center h-full space-y-4">
        <h2>Alert not found</h2>
        <Button onClick={() => navigate("/alerts")}>
          <ArrowLeft className="size-4 mr-2" />
          Back to Alerts
        </Button>
      </div>
    );
  }

  const getCountryFlag = (country: string) => {
    const flagMap: { [key: string]: React.ReactNode } = {
      India: <IN className="size-8" />,
      China: <CN className="size-8" />,
      EU: <EU className="size-8" />,
      "United States": <US className="size-8" />,
    };
    return flagMap[country] || "🌐";
  };

  const getRelevanceColor = (score: number) => {
    if (score >= 80) return "bg-accent text-accent-foreground";
    if (score >= 60) return "bg-primary text-primary-foreground";
    return "bg-muted text-muted-foreground";
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate("/alerts")}>
          <ArrowLeft className="size-4 mr-2" />
          Back to Alerts
        </Button>
        <Badge className={getRelevanceColor(alert.relevanceScore)}>
          {alert.relevanceScore}% Relevance
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start gap-4 mb-4">
            {getCountryFlag(alert.country)}
            <div className="flex-1">
              <CardTitle className="text-2xl mb-2">{alert.title}</CardTitle>
              <CardDescription className="flex flex-wrap gap-4 text-base">
                <span className="flex items-center gap-2">
                  <FileText className="size-4" />
                  {alert.authority}
                </span>
                <span className="flex items-center gap-2">
                  <MapPin className="size-4" />
                  {alert.country}
                </span>
                <span className="flex items-center gap-2">
                  <Calendar className="size-4" />
                  {new Date(alert.publicationDate).toLocaleDateString("en-US", {
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                </span>
              </CardDescription>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{alert.regulationType}</Badge>
            {alert.affectedProducts.map((product, idx) => (
              <Badge
                key={idx}
                variant="secondary"
                className="bg-muted text-foreground"
              >
                {product}
              </Badge>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Authority is already shown in the card header's meta row;
              repeating it as its own section was duplication. */}
          <div>
            <h3 className="font-semibold mb-3 text-lg">Summary</h3>
            <div className="rounded-md border-l-4 border-primary bg-primary/5 p-4 space-y-3">
              {alert.summary.map((paragraph, idx) => (
                <p
                  key={idx}
                  className="text-foreground text-base leading-relaxed"
                >
                  {paragraph}
                </p>
              ))}
            </div>
          </div>

          {alert.obligations && alert.obligations.length > 0 && (
            <ObligationsSection obligations={alert.obligations} />
          )}

          {alert.diff && <DiffSection diff={alert.diff} />}

          <div className="pt-4 border-t space-y-4">
            <div>
              <h3 className="font-semibold mb-3">Documents & Source</h3>
              <div className="space-y-2">
                {alert.pdfUrl && (
                  <div>
                    <a
                      href={alert.pdfUrl}
                      download
                      className="inline-flex items-center gap-2 text-primary hover:underline"
                    >
                      <Download className="size-4" />
                      Download Official Document (PDF)
                    </a>
                  </div>
                )}
                <div>
                  <a
                    href={alert.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 text-primary hover:underline"
                  >
                    <ExternalLink className="size-4" />
                    View Original Source
                  </a>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Floating "Ask AI" affordance — sits above the page content
          at bottom-right, doesn't dominate the layout. Animated
          gradient + sparkle is intentionally a bit playful so it
          *looks* alive even though the LLM endpoint isn't wired yet.
          When it lands we swap the disabled cursor for a real click
          handler and slide out a chat panel. */}
      <AskAIPlaceholder />
    </div>
  );
}

function AskAIPlaceholder() {
  return (
    <div className="fixed bottom-6 right-6 z-30 group" aria-hidden="false">
      <button
        type="button"
        disabled
        title="AI assistant — coming soon"
        aria-label="Ask AI about this alert (coming soon)"
        className="
          relative inline-flex items-center gap-2 rounded-full
          px-4 py-2.5 cursor-not-allowed
          bg-gradient-to-r from-primary via-primary to-accent
          text-primary-foreground shadow-lg shadow-primary/30
          transition-transform hover:scale-[1.02]
          before:absolute before:inset-0 before:rounded-full
          before:bg-gradient-to-r before:from-primary/0 before:via-white/20 before:to-primary/0
          before:opacity-0 before:transition-opacity before:duration-700
          group-hover:before:opacity-100
        "
        style={{ fontSize: "var(--text-sm)", fontWeight: "var(--font-weight-medium)" }}
      >
        <Sparkles
          className="size-4 animate-pulse"
          style={{ animationDuration: "2.4s" }}
        />
        <span>Ask AI</span>
        <span
          className="rounded-full bg-white/20 px-2 py-0.5 leading-none tabular-nums"
          style={{ fontSize: "var(--text-xs)" }}
        >
          soon
        </span>
      </button>
    </div>
  );
}

