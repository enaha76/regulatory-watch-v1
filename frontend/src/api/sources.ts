// Typed wrappers around /api/v2/sources — frontend-shaped view over the
// regwatch backend's `domains` table.

export type SourceType = "web" | "rss" | "email" | "api" | "database";
export type SourceStatus = "active" | "inactive";

export interface DataSource {
  id: string;
  name: string;
  url: string;
  type: SourceType;
  status: SourceStatus;
  lastActivity: string | null;
  activityCount: number;
  activityMetric: string;
  addedDate: string;
  frequency: string;
  /** Effective per-crawl page cap (resolved server-side; never null). */
  maxPages: number;
  userSubscribed: boolean;
  countryCode?: string | null;
}

export type SourceFrequency = "Hourly" | "Daily" | "Weekly" | "Monthly";

export interface SourcePatch {
  status?: SourceStatus;
  name?: string;
  frequency?: SourceFrequency;
  maxPages?: number;
  userSubscribed?: boolean;
}

export interface SourceCreate {
  name?: string;
  url: string;
  frequency?: SourceFrequency;
  maxPages?: number;
}

export interface CrawlNowResponse {
  ok: boolean;
  task_id?: string;
  domain: string;
  seed_urls: string[];
}

/** Subset of /api/admin/task/{id} we use in the UI. */
export interface CrawlTaskStatus {
  task_id: string;
  /** Celery state: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE" | "RETRY" */
  state: string;
  ready: boolean;
  successful: boolean | null;
  result: CrawlTaskResult | null;
  error: string | null;
  /** Populated when state == "PROGRESS"; null otherwise. */
  progress: CrawlProgress | null;
}

export interface CrawlProgress {
  /** The most recent event name (crawl_started, heartbeat, page_indexed, …). */
  phase: string;
  /** Rolling buffer of the last ~50 events emitted by the worker. */
  events: CrawlProgressEvent[];
}

/**
 * One progress entry. `event` is required; the rest depends on the type:
 *   crawl_started   → { domain, seeds, max_pages }
 *   heartbeat       → { elapsed_sec }
 *   bestfirst_done  → { pages_returned }
 *   page_indexed    → { url, title?, current, max }
 *   pdf_phase       → { count, max }
 *   xml_phase       → { count, max }
 *   persisting      → { docs }
 *   connector_done  → { html, pdf, xml, total }
 *   done            → { fetched, created, modified, unchanged }
 */
export interface CrawlProgressEvent {
  event: string;
  ts: number;
  [key: string]: unknown;
}

export interface CrawlTaskResult {
  domain: string;
  fetched: number;
  inserted: number;
  updated: number;
  archived: number;
  created: number;
  modified: number;
  unchanged: number;
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

export async function listSources(): Promise<DataSource[]> {
  const res = await fetch("/api/v2/sources");
  return jsonOrThrow<DataSource[]>(res);
}

export async function createSource(body: SourceCreate): Promise<DataSource> {
  const res = await fetch("/api/v2/sources", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow<DataSource>(res);
}

export async function updateSource(
  id: string,
  patch: SourcePatch,
): Promise<DataSource> {
  const res = await fetch(`/api/v2/sources/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow<DataSource>(res);
}

export async function triggerSourceCrawl(
  id: string,
): Promise<CrawlNowResponse> {
  const res = await fetch(
    `/api/v2/sources/${encodeURIComponent(id)}/crawl-now`,
    { method: "POST" },
  );
  return jsonOrThrow<CrawlNowResponse>(res);
}

/** Poll a crawl task one time. Caller is responsible for the polling loop. */
export async function getCrawlTaskStatus(
  taskId: string,
): Promise<CrawlTaskStatus> {
  const res = await fetch(
    `/api/admin/task/${encodeURIComponent(taskId)}`,
  );
  return jsonOrThrow<CrawlTaskStatus>(res);
}
