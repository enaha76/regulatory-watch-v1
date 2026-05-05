import React, { useEffect, useState } from "react";
import { fetchSystemHealth, type SystemHealth } from "@/api/health";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/app/components/ui/tooltip";

/**
 * Tiny green/yellow/red dot in the header showing API + DB + Redis
 * status. Polls every 30s and on tab focus, so it stays current
 * without thrashing the API. Hover for the full breakdown.
 */
const POLL_INTERVAL_MS = 30_000;

type Tier = "healthy" | "degraded" | "down" | "loading";

function tierFromHealth(h: SystemHealth | null): Tier {
  if (!h) return "loading";
  const all = [h.api, h.db, h.redis];
  const healthy = all.every((c) => c.status === "healthy");
  if (healthy) return "healthy";
  const allDown = all.every((c) => c.status !== "healthy");
  return allDown ? "down" : "degraded";
}

const TIER_COLORS: Record<Tier, string> = {
  healthy: "bg-green-500",
  degraded: "bg-amber-500",
  down: "bg-destructive",
  loading: "bg-muted-foreground/40",
};

const TIER_LABELS: Record<Tier, string> = {
  healthy: "All systems operational",
  degraded: "Some services degraded",
  down: "Backend unreachable",
  loading: "Checking system status…",
};

export function SystemHealthIndicator() {
  const [health, setHealth] = useState<SystemHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const h = await fetchSystemHealth();
      if (!cancelled) setHealth(h);
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
    const onFocus = () => void tick();
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  const tier = tierFromHealth(health);

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={TIER_LABELS[tier]}
            className="flex items-center gap-2 px-2 py-1 rounded hover:bg-muted/40 transition-colors"
          >
            <span
              className={`size-2.5 rounded-full ${TIER_COLORS[tier]} ${
                tier === "healthy" ? "" : "animate-pulse"
              }`}
              aria-hidden="true"
            />
            <span
              className="text-muted-foreground"
              style={{ fontSize: "var(--text-xs)" }}
            >
              {tier === "healthy"
                ? "Healthy"
                : tier === "degraded"
                  ? "Degraded"
                  : tier === "down"
                    ? "Down"
                    : "…"}
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="end" className="px-3 py-2">
          <div className="space-y-1">
            <p
              style={{
                fontSize: "var(--text-xs)",
                fontWeight: "var(--font-weight-medium)",
              }}
            >
              {TIER_LABELS[tier]}
            </p>
            {health && (
              <ul
                className="space-y-0.5 mt-1"
                style={{ fontSize: "var(--text-xs)" }}
              >
                <ServiceLine label="API" check={health.api} />
                <ServiceLine label="Postgres" check={health.db} />
                <ServiceLine label="Redis" check={health.redis} />
              </ul>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function ServiceLine({
  label,
  check,
}: {
  label: string;
  check: { status: string; detail?: string };
}) {
  const ok = check.status === "healthy";
  return (
    <li className="flex items-center gap-2 tabular-nums">
      <span
        className={`size-1.5 rounded-full shrink-0 ${
          ok ? "bg-green-500" : "bg-destructive"
        }`}
        aria-hidden="true"
      />
      <span className="font-medium">{label}</span>
      <span className="opacity-70">{check.status}</span>
      {check.detail && <span className="opacity-50">· {check.detail}</span>}
    </li>
  );
}
