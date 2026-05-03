// Typed API client for the mock-website admin UI.
// Mirrors the schema in mock-website/data/schema.ts so the editor can
// round-trip a Regulation without losing fields.

export type Section =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; columns: string[]; rows: string[][] }
  | { type: 'note'; style: 'critical' | 'info' | 'warning'; title?: string; text: string };

export type Category = 'regulations' | 'notices' | 'guidance';

export interface Regulation {
  slug: string;
  category: Category;
  title: string;
  subtitle?: string;
  effective_date?: string;
  reference_number?: string;
  summary: string;
  sections: Section[];
  pdf?: { enabled: boolean; filename: string; document_title?: string };
  updated_at: string;
}

export interface RegulationListItem {
  slug: string;
  category: Category;
  title: string;
  effective_date?: string;
  reference_number?: string;
  updated_at: string;
  mtime: number;
  has_pdf: boolean;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* keep null */
  }
  if (!res.ok) {
    const detail = body?.error || text || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body as T;
}

export async function listRegulations(): Promise<RegulationListItem[]> {
  const res = await fetch('/api/regulations');
  const body = await jsonOrThrow<{ items: RegulationListItem[] }>(res);
  return body.items;
}

export async function getRegulation(slug: string): Promise<Regulation> {
  const res = await fetch(`/api/regulations/${encodeURIComponent(slug)}`);
  return jsonOrThrow<Regulation>(res);
}

export async function createRegulation(
  reg: Omit<Regulation, 'updated_at'>,
): Promise<{ ok: true; slug: string }> {
  const res = await fetch('/api/regulations', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(reg),
  });
  return jsonOrThrow(res);
}

export async function updateRegulation(
  slug: string,
  reg: Regulation,
): Promise<{ ok: true; slug: string }> {
  const res = await fetch(`/api/regulations/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(reg),
  });
  return jsonOrThrow(res);
}

export async function deleteRegulation(slug: string): Promise<void> {
  const res = await fetch(`/api/regulations/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  });
  await jsonOrThrow(res);
}
