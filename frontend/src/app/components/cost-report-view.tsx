import React, { useEffect, useState } from "react";
import {
  CostBucket,
  CostReport,
  CostTopCall,
  fetchCostReport,
} from "@/api/cost";
import { Badge } from "@/app/components/ui/badge";
import { Button } from "@/app/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/app/components/ui/select";
import {
  DollarSign,
  Coins,
  Hash,
  Receipt,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";

type ScopeFilter = "" | "scoring" | "obligations" | "web_extract";

const SINCE_OPTIONS: { value: string; label: string; days: number | null }[] =
  [
    { value: "all", label: "All time", days: null },
    { value: "30d", label: "Last 30 days", days: 30 },
    { value: "7d", label: "Last 7 days", days: 7 },
    { value: "today", label: "Today", days: 0 },
  ];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function formatUSD(x: number): string {
  if (x >= 1) return `$${x.toFixed(2)}`;
  if (x >= 0.01) return `$${x.toFixed(4)}`;
  if (x >= 0.0001) return `$${x.toFixed(6)}`;
  if (x === 0) return "$0";
  return x.toExponential(2);
}

function formatNum(n: number): string {
  return n.toLocaleString("en-US");
}

export function CostReportView() {
  const [report, setReport] = useState<CostReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [since, setSince] = useState<string>("all");
  const [scope, setScope] = useState<ScopeFilter>("");

  const load = async () => {
    setError(null);
    try {
      const sinceParam =
        SINCE_OPTIONS.find((o) => o.value === since)?.days ?? null;
      const r = await fetchCostReport({
        since:
          sinceParam !== null && sinceParam >= 0
            ? isoDaysAgo(sinceParam)
            : undefined,
        scope: scope || undefined,
      });
      setReport(r);
    } catch (err: any) {
      setError(err?.message || "Failed to load cost report");
    }
  };

  useEffect(() => {
    setLoading(true);
    load().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [since, scope]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <p className="text-muted-foreground">Loading cost report…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <AlertTriangle className="size-10 text-destructive" />
        <p className="text-destructive">{error}</p>
        <Button onClick={() => load()} variant="outline">
          Retry
        </Button>
      </div>
    );
  }

  if (!report || !report.ledgerExists) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-2 text-center">
        <Coins className="size-10 text-muted-foreground" />
        <p>No usage ledger yet.</p>
        <p className="text-muted-foreground" style={{ fontSize: "var(--text-sm)" }}>
          The ledger gets written on the first real LLM call (scoring,
          obligations, or web extraction). Trigger a crawl to seed it.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-muted-foreground">
            Token usage and spend across every LLM call the pipeline made.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={since} onValueChange={(v) => setSince(v)}>
            <SelectTrigger className="w-[140px]" aria-label="Time window">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SINCE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={scope || "all"}
            onValueChange={(v) => setScope((v === "all" ? "" : v) as ScopeFilter)}
          >
            <SelectTrigger className="w-[150px]" aria-label="Scope filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All scopes</SelectItem>
              <SelectItem value="scoring">Scoring</SelectItem>
              <SelectItem value="obligations">Obligations</SelectItem>
              <SelectItem value="web_extract">Web extract</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={handleRefresh}
            disabled={refreshing}
            className="gap-2"
          >
            <RefreshCw
              className={`size-4 ${refreshing ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Headline tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <HeadlineTile
          icon={<DollarSign className="size-4" />}
          label="Total spend"
          value={formatUSD(report.totals.total_cost_usd)}
          tone="primary"
        />
        <HeadlineTile
          icon={<Receipt className="size-4" />}
          label="LLM calls"
          value={formatNum(report.totals.calls)}
          tone="accent"
        />
        <HeadlineTile
          icon={<Hash className="size-4" />}
          label="Total tokens"
          value={formatNum(report.totals.total_tokens)}
          tone="muted"
        />
        <HeadlineTile
          icon={<Coins className="size-4" />}
          label="Avg / call"
          value={
            report.totals.calls
              ? formatUSD(
                  report.totals.total_cost_usd / report.totals.calls,
                )
              : "—"
          }
          tone="muted"
        />
      </div>

      {/* Breakdowns */}
      <div className="grid lg:grid-cols-2 gap-4">
        <BreakdownCard
          title="By scope"
          data={report.by_scope}
          totalCost={report.totals.total_cost_usd}
        />
        <BreakdownCard
          title="By model"
          data={report.by_model}
          totalCost={report.totals.total_cost_usd}
        />
      </div>

      <DayTimelineCard data={report.by_day} />

      <TopCallsCard rows={report.top_calls} />

      <p
        className="text-muted-foreground"
        style={{ fontSize: "var(--text-xs)" }}
      >
        Source: <span className="font-mono">{report.ledgerPath}</span>
      </p>
    </div>
  );
}

// ── Headline tile ────────────────────────────────────────────────────

function HeadlineTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: "primary" | "accent" | "muted";
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
        ${accent}`}
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

// ── Breakdown bars ───────────────────────────────────────────────────

function BreakdownCard({
  title,
  data,
  totalCost,
}: {
  title: string;
  data: Record<string, CostBucket>;
  totalCost: number;
}) {
  const entries = Object.entries(data).sort(
    (a, b) => b[1].cost - a[1].cost,
  );
  const max = entries.reduce((m, [, v]) => Math.max(m, v.cost), 0);

  return (
    <div className="rounded-md border bg-card">
      <div className="px-4 py-3 border-b">
        <p style={{ fontWeight: "var(--font-weight-medium)" }}>{title}</p>
      </div>
      <div className="px-4 py-3 space-y-3">
        {entries.length === 0 && (
          <p className="text-muted-foreground" style={{ fontSize: "var(--text-sm)" }}>
            No data.
          </p>
        )}
        {entries.map(([key, b]) => {
          const widthPct = max > 0 ? (b.cost / max) * 100 : 0;
          const sharePct = totalCost > 0 ? (b.cost / totalCost) * 100 : 0;
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2">
                <span
                  className="font-mono truncate"
                  style={{ fontSize: "var(--text-sm)" }}
                >
                  {key}
                </span>
                <span
                  className="text-muted-foreground tabular-nums shrink-0"
                  style={{ fontSize: "var(--text-xs)" }}
                >
                  {formatNum(b.calls)} calls ·{" "}
                  {formatNum(b.prompt + b.completion)} tok
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-primary"
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
                <span
                  className="tabular-nums shrink-0"
                  style={{
                    fontSize: "var(--text-sm)",
                    fontWeight: "var(--font-weight-medium)",
                    minWidth: "5.5rem",
                    textAlign: "right",
                  }}
                >
                  {formatUSD(b.cost)}
                </span>
                <span
                  className="text-muted-foreground tabular-nums shrink-0"
                  style={{ fontSize: "var(--text-xs)", minWidth: "3rem" }}
                >
                  {sharePct.toFixed(1)}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Day timeline (mini bar chart) ────────────────────────────────────

function DayTimelineCard({ data }: { data: Record<string, CostBucket> }) {
  const entries = Object.entries(data)
    .filter(([k]) => k !== "unknown")
    .sort((a, b) => a[0].localeCompare(b[0]));
  const max = entries.reduce((m, [, v]) => Math.max(m, v.cost), 0);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="rounded-md border bg-card">
      <div className="px-4 py-3 border-b">
        <p style={{ fontWeight: "var(--font-weight-medium)" }}>
          Daily spend
        </p>
        <p
          className="text-muted-foreground"
          style={{ fontSize: "var(--text-xs)", marginTop: "2px" }}
        >
          {entries.length} day{entries.length === 1 ? "" : "s"} of activity
          · max {formatUSD(max)}
        </p>
      </div>
      <div className="px-4 py-4">
        <div className="flex items-end gap-1 h-32">
          {entries.map(([day, b]) => {
            const heightPct = max > 0 ? (b.cost / max) * 100 : 0;
            return (
              <div
                key={day}
                title={`${day} · ${formatUSD(b.cost)} · ${b.calls} calls`}
                className="flex-1 min-w-[6px] bg-primary/80 hover:bg-primary rounded-sm transition-colors"
                style={{ height: `${Math.max(heightPct, 4)}%` }}
              />
            );
          })}
        </div>
        <div
          className="flex justify-between mt-2 text-muted-foreground tabular-nums"
          style={{ fontSize: "var(--text-xs)" }}
        >
          <span>{entries[0][0]}</span>
          <span>{entries[entries.length - 1][0]}</span>
        </div>
      </div>
    </div>
  );
}

// ── Top expensive calls ──────────────────────────────────────────────

function TopCallsCard({ rows }: { rows: CostTopCall[] }) {
  if (rows.length === 0) return null;

  return (
    <div className="rounded-md border bg-card">
      <div className="px-4 py-3 border-b">
        <p style={{ fontWeight: "var(--font-weight-medium)" }}>
          Most expensive single calls
        </p>
        <p
          className="text-muted-foreground"
          style={{ fontSize: "var(--text-xs)", marginTop: "2px" }}
        >
          Top {rows.length} — useful for spotting prompt bloat
        </p>
      </div>
      <div className="divide-y">
        {rows.map((r, idx) => (
          <div
            key={idx}
            className="px-4 py-3 flex items-center gap-3 hover:bg-muted/30"
          >
            <Badge
              variant="outline"
              className="font-mono"
              style={{ fontSize: "var(--text-xs)" }}
            >
              #{idx + 1}
            </Badge>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span style={{ fontWeight: "var(--font-weight-medium)" }}>
                  {formatUSD(r.total_cost_usd ?? 0)}
                </span>
                <span
                  className="text-muted-foreground tabular-nums"
                  style={{ fontSize: "var(--text-xs)" }}
                >
                  {formatNum(r.total_tokens ?? 0)} tok
                </span>
                {r.scope && (
                  <Badge
                    variant="outline"
                    style={{ fontSize: "var(--text-xs)" }}
                  >
                    {r.scope}
                  </Badge>
                )}
                {r.model && (
                  <span
                    className="text-muted-foreground font-mono"
                    style={{ fontSize: "var(--text-xs)" }}
                  >
                    {r.model}
                  </span>
                )}
                {r.latency_ms !== undefined && (
                  <span
                    className="text-muted-foreground tabular-nums"
                    style={{ fontSize: "var(--text-xs)" }}
                  >
                    {r.latency_ms} ms
                  </span>
                )}
              </div>
              <p
                className="text-muted-foreground truncate mt-0.5"
                style={{ fontSize: "var(--text-xs)" }}
                title={r.event_id || r.url || ""}
              >
                {r.event_id ? `event ${r.event_id.slice(0, 8)}` : r.url || "—"}
              </p>
            </div>
            <span
              className="text-muted-foreground tabular-nums shrink-0"
              style={{ fontSize: "var(--text-xs)" }}
            >
              {r.ts ? new Date(r.ts).toLocaleString() : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
