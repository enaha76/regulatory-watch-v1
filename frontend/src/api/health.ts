// Typed wrappers around the backend /health endpoints.
//
// `service` is omitted from the root /health response but included on
// the per-service ones (DB, Redis). `status` is "healthy" when up; the
// backend returns 503 with `unhealthy` payload when a service is down.

export interface HealthCheck {
  status: "healthy" | "unhealthy" | string;
  service?: string;
  detail?: string;
}

export interface SystemHealth {
  api: HealthCheck;
  db: HealthCheck;
  redis: HealthCheck;
}

async function probe(path: string): Promise<HealthCheck> {
  try {
    const res = await fetch(path, { method: "GET" });
    if (!res.ok) {
      // 503 etc. — try to parse the body, fall back to status text
      try {
        return (await res.json()) as HealthCheck;
      } catch {
        return { status: "unhealthy", detail: `HTTP ${res.status}` };
      }
    }
    return (await res.json()) as HealthCheck;
  } catch (err: any) {
    return {
      status: "unhealthy",
      detail: err?.message || "network error",
    };
  }
}

export async function fetchSystemHealth(): Promise<SystemHealth> {
  const [api, db, redis] = await Promise.all([
    probe("/health"),
    probe("/health/db"),
    probe("/health/redis"),
  ]);
  return { api, db, redis };
}
