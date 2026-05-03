import express from 'express';
import path from 'path';
import fs from 'fs';
import { spawn } from 'child_process';

const app = express();
const PORT = 3001;
const ROOT = process.cwd();

// Source-of-truth JSON dir (editable via admin API)
const DATA_DIR = path.join(ROOT, 'data');

// Generated output dir served as the public website
const OUT_DIR = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.join(ROOT, 'mock_server', 'data');

// Python interpreter — defaults to `python3`. Override to `python` in
// containers where only the unversioned binary exists.
const PYTHON = process.env.PYTHON || 'python3';

app.use(express.json({ limit: '5mb' }));

// ─── Helpers ──────────────────────────────────────────────────
const CATEGORIES = ['regulations', 'notices', 'guidance'] as const;
type Category = (typeof CATEGORIES)[number];

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,80}$/;

function listJsonFiles(): { category: Category; slug: string; path: string }[] {
  const out: { category: Category; slug: string; path: string }[] = [];
  for (const cat of CATEGORIES) {
    const dir = path.join(DATA_DIR, cat);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith('.json')) continue;
      out.push({ category: cat, slug: f.replace(/\.json$/, ''), path: path.join(dir, f) });
    }
  }
  return out;
}

function findRegulation(slug: string) {
  return listJsonFiles().find((r) => r.slug === slug) || null;
}

function runScript(cmd: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const proc = spawn(cmd, args, { cwd: ROOT });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (b) => (stdout += b.toString()));
    proc.stderr.on('data', (b) => (stderr += b.toString()));
    proc.on('close', (code) => resolve({ code: code ?? 0, stdout, stderr }));
  });
}

async function rebuildSite() {
  // Single-file --input regen doesn't refresh category indexes / home / rss.
  // After any create/edit/delete, do a full rebuild so cross-page links
  // stay accurate.
  const html = await runScript('npx', ['tsx', 'scripts/generate_html.ts', '--all']);
  const pdf = await runScript(PYTHON, ['scripts/generate_pdf.py', '--all']);
  return { html, pdf };
}

// ─── CRUD: regulations ────────────────────────────────────────

app.get('/api/regulations', (_req, res) => {
  const items = listJsonFiles().map((r) => {
    const stat = fs.statSync(r.path);
    const json = JSON.parse(fs.readFileSync(r.path, 'utf8'));
    return {
      slug: r.slug,
      category: r.category,
      title: json.title,
      effective_date: json.effective_date,
      reference_number: json.reference_number,
      updated_at: json.updated_at,
      mtime: stat.mtimeMs,
      has_pdf: !!json.pdf?.enabled,
    };
  });
  res.json({ items });
});

app.get('/api/regulations/:slug', (req, res) => {
  const rec = findRegulation(req.params.slug);
  if (!rec) return res.status(404).json({ error: 'not found' });
  const json = JSON.parse(fs.readFileSync(rec.path, 'utf8'));
  res.json(json);
});

app.post('/api/regulations', async (req, res) => {
  const incoming = req.body;
  if (!incoming || typeof incoming !== 'object') {
    return res.status(400).json({ error: 'invalid body' });
  }
  const { slug, category, title } = incoming;
  if (!slug || !SLUG_RE.test(slug)) {
    return res.status(400).json({ error: 'slug must match [a-z0-9-], 2–80 chars' });
  }
  if (!CATEGORIES.includes(category)) {
    return res.status(400).json({ error: `category must be one of ${CATEGORIES.join('|')}` });
  }
  if (!title || typeof title !== 'string') {
    return res.status(400).json({ error: 'title is required' });
  }
  if (findRegulation(slug)) {
    return res.status(409).json({ error: `slug '${slug}' already exists` });
  }

  const now = new Date().toISOString();
  const doc = {
    slug,
    category,
    title,
    subtitle: incoming.subtitle ?? '',
    effective_date: incoming.effective_date ?? '',
    reference_number: incoming.reference_number ?? '',
    summary: incoming.summary ?? '',
    sections: Array.isArray(incoming.sections) ? incoming.sections : [],
    pdf: incoming.pdf ?? undefined,
    updated_at: now,
  };

  const dir = path.join(DATA_DIR, category);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${slug}.json`), JSON.stringify(doc, null, 2));

  const result = await rebuildSite();
  if (result.html.code !== 0 || result.pdf.code !== 0) {
    return res.status(500).json({ error: 'regeneration failed', ...result });
  }
  res.status(201).json({ ok: true, slug, category });
});

app.put('/api/regulations/:slug', async (req, res) => {
  const rec = findRegulation(req.params.slug);
  if (!rec) return res.status(404).json({ error: 'not found' });
  const incoming = req.body;
  if (!incoming || typeof incoming !== 'object') {
    return res.status(400).json({ error: 'invalid body' });
  }
  // Slug and category are immutable on PUT — to move/rename, delete + create
  incoming.slug = req.params.slug;
  incoming.category = rec.category;
  incoming.updated_at = new Date().toISOString();
  fs.writeFileSync(rec.path, JSON.stringify(incoming, null, 2));

  const result = await rebuildSite();
  if (result.html.code !== 0 || result.pdf.code !== 0) {
    return res.status(500).json({ error: 'regeneration failed', ...result });
  }
  res.json({ ok: true, slug: req.params.slug });
});

app.delete('/api/regulations/:slug', async (req, res) => {
  const rec = findRegulation(req.params.slug);
  if (!rec) return res.status(404).json({ error: 'not found' });
  const json = JSON.parse(fs.readFileSync(rec.path, 'utf8'));

  // Remove JSON source
  fs.unlinkSync(rec.path);

  // Remove generated HTML if it exists
  const htmlPath = path.join(OUT_DIR, rec.category, `${rec.slug}.html`);
  if (fs.existsSync(htmlPath)) fs.unlinkSync(htmlPath);

  // Remove generated PDF if it exists
  const pdfFilename = json?.pdf?.filename;
  if (pdfFilename) {
    const pdfPath = path.join(OUT_DIR, 'documents', pdfFilename);
    if (fs.existsSync(pdfPath)) fs.unlinkSync(pdfPath);
  }

  // Rebuild indexes + RSS so links don't point at the deleted file
  const result = await rebuildSite();
  if (result.html.code !== 0) {
    return res.status(500).json({ error: 'regeneration failed', ...result });
  }
  res.json({ ok: true, deleted: req.params.slug });
});

app.post('/api/regenerate', async (_req, res) => {
  const result = await rebuildSite();
  res.json({ ok: result.html.code === 0 && result.pdf.code === 0, ...result });
});

// ─── Admin SPA (built by `npm run build:admin`) ───────────────
const ADMIN_DIST = path.join(ROOT, 'dist', 'admin');
if (fs.existsSync(ADMIN_DIST)) {
  app.use('/admin', express.static(ADMIN_DIST));
  // SPA fallback: any unknown /admin/* path returns index.html so the
  // React router can handle it client-side.
  app.get(/^\/admin(\/.*)?$/, (_req, res) => {
    res.sendFile(path.join(ADMIN_DIST, 'index.html'));
  });
} else {
  app.get(/^\/admin(\/.*)?$/, (_req, res) => {
    res
      .status(503)
      .type('text/html')
      .send(
        '<h1>Admin UI not built</h1>' +
          '<p>Run <code>npm run build:admin</code> to build it, then refresh.</p>',
      );
  });
}

// ─── Static public site ───────────────────────────────────────
app.use(express.static(OUT_DIR, { index: 'index.html' }));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Mock website running on http://0.0.0.0:${PORT}`);
  console.log(`  Static dir : ${OUT_DIR}`);
  console.log(`  Data dir   : ${DATA_DIR}`);
  console.log(`  Admin dist : ${ADMIN_DIST} (${fs.existsSync(ADMIN_DIST) ? 'built' : 'NOT built'})`);
});
