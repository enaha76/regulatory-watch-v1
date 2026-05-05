// Typed wrappers around /api/v2/areas — the user's "areas of interest"
// profile (HS codes, countries, keywords).

export interface AreasProfile {
  email: string;
  hsCodes: string[];
  countries: string[];
  keywords: string[];
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

export async function getAreas(email: string): Promise<AreasProfile> {
  const url = `/api/v2/areas?email=${encodeURIComponent(email)}`;
  const res = await fetch(url);
  return jsonOrThrow<AreasProfile>(res);
}

export async function saveAreas(profile: AreasProfile): Promise<AreasProfile> {
  const res = await fetch("/api/v2/areas", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(profile),
  });
  return jsonOrThrow<AreasProfile>(res);
}
