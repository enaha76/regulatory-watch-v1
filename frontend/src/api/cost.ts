// Typed wrappers around /api/admin/cost-report.
//
// The backend serves an aggregated rollup of the append-only LLM usage
// ledger written by every scoring / obligations / web_extract call.
// Pure read; no DB writes.

export interface CostBucket {
  /** Number of LLM calls in this bucket. */
  calls: number;
  /** Sum of prompt tokens. */
  prompt: number;
  /** Sum of completion tokens. */
  completion: number;
  /** Sum of cost in USD. Already rounded to 6 decimals server-side. */
  cost: number;
}

export interface CostTotals {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
}

/** One raw record from the JSONL ledger — top-N most expensive calls. */
export interface CostTopCall {
  ts?: string;
  scope?: string;
  model?: string;
  event_id?: string;
  url?: string | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  total_cost_usd?: number;
  latency_ms?: number;
}

export interface CostReport {
  ledgerPath: string;
  ledgerExists: boolean;
  filters: { since: string | null; scope: string | null };
  totals: CostTotals;
  by_scope: Record<string, CostBucket>;
  by_model: Record<string, CostBucket>;
  by_day: Record<string, CostBucket>;
  top_calls: CostTopCall[];
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* body stays null */
  }
  if (!res.ok) {
    const detail = body?.detail || body?.error || text || `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body as T;
}

export async function fetchCostReport(opts: {
  since?: string;
  scope?: "scoring" | "obligations" | "web_extract";
} = {}): Promise<CostReport> {
  const qs = new URLSearchParams();
  if (opts.since) qs.set("since", opts.since);
  if (opts.scope) qs.set("scope", opts.scope);
  const url = `/api/admin/cost-report${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  return jsonOrThrow<CostReport>(res);
}
