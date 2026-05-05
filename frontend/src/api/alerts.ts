// Typed wrappers around the regwatch FastAPI v2 alerts endpoints.
// Mirrors the Alert interface used by the views so swap-in is a one-liner
// (replace `useState(mockAlerts)` with `listAlerts()` in useEffect).

export type AlertStatus = "new" | "read" | "archived";
export type AlertFeedback =
  | "relevant"
  | "not_relevant"
  | "partially_relevant";

export interface Alert {
  id: string;
  title: string;
  country: string;
  authority: string;
  regulationType: string;
  publicationDate: string;
  affectedProducts: string[];
  relevanceScore: number;
  status: AlertStatus;
  userFeedback?: AlertFeedback | null;
  pinned?: boolean;
  tradeLane: string;
}

export interface AlertDetail extends Alert {
  summary: string[];
  sourceUrl: string;
  pdfUrl?: string;
  /** Document-level diff. Present on detail responses only. */
  diff?: AlertDiff | null;
  /**
   * Compliance obligations the LLM extracted for this regulation —
   * who must do what, by when, with what penalty. Empty array if
   * obligation-extraction hasn't run for this event yet.
   */
  obligations?: Obligation[];
}

export type ObligationType =
  | "reporting"
  | "prohibition"
  | "threshold"
  | "disclosure"
  | "registration"
  | "penalty"
  | "other";

export interface Obligation {
  id: string;
  type: ObligationType | string;
  /** Who has to act — e.g. "importers of lithium-ion batteries". */
  actor: string;
  /** What they must do — the imperative verb phrase. */
  action: string;
  /** Optional precondition that triggers the obligation. */
  condition: string | null;
  /** Free-text deadline as written ("by July 1, 2026"). */
  deadlineText: string | null;
  /** Resolved ISO date when the LLM was able to parse one. */
  deadlineDate: string | null;
  /** What happens on non-compliance. */
  penalty: string | null;
}

/**
 * What actually changed at the source.
 * - `kind` is "modified" → unifiedDiff is the standard --- / +++ patch
 * - `kind` is "created"  → unifiedDiff is null (the whole doc is new)
 */
export interface AlertDiff {
  kind: "created" | "modified";
  addedChars: number;
  removedChars: number;
  /**
   * LLM-assigned change_type. Lets the UI tint cosmetic-only diffs
   * differently from substantive ones.
   */
  changeType:
    | "typo_or_cosmetic"
    | "minor_wording"
    | "clarification"
    | "substantive"
    | "critical"
    | null;
  unifiedDiff: string | null;
}

export interface ListAlertsParams {
  email?: string;
  status?: AlertStatus;
  limit?: number;
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

export async function listAlerts(
  params: ListAlertsParams = {},
): Promise<Alert[]> {
  const qs = new URLSearchParams();
  if (params.email) qs.set("email", params.email);
  if (params.status) qs.set("status", params.status);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const url = `/api/v2/alerts${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  return jsonOrThrow<Alert[]>(res);
}

export async function getAlert(id: string): Promise<AlertDetail> {
  const res = await fetch(`/api/v2/alerts/${encodeURIComponent(id)}`);
  return jsonOrThrow<AlertDetail>(res);
}

export interface AlertPatch {
  status?: AlertStatus;
  pinned?: boolean;
  userFeedback?: AlertFeedback | null;
}

export async function updateAlert(
  id: string,
  patch: AlertPatch,
): Promise<AlertDetail> {
  const res = await fetch(`/api/v2/alerts/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow<AlertDetail>(res);
}
