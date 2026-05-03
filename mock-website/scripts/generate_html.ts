// JSON-driven HTML generator for the mock ATCA website.
//
// Reads regulation JSON files in data/{regulations,notices,guidance}/*.json and
// renders one HTML file per record into mock_server/data/<category>/<slug>.html.
// Also rebuilds category index pages and the home page so links stay valid.
//
// Usage:
//   tsx scripts/generate_html.ts --input data/regulations/tariff-schedule-2026.json
//   tsx scripts/generate_html.ts --all

import * as fs from 'fs';
import * as path from 'path';

type Section =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; columns: string[]; rows: string[][] }
  | { type: 'note'; style: 'critical' | 'info' | 'warning'; title?: string; text: string };

interface Regulation {
  slug: string;
  category: 'regulations' | 'notices' | 'guidance';
  title: string;
  subtitle?: string;
  effective_date?: string;
  reference_number?: string;
  summary: string;
  sections: Section[];
  pdf?: { enabled: boolean; filename: string; document_title?: string };
  updated_at: string;
}

// Run from the mock-website project root (`npm run` and the Express
// server already cwd here).
const ROOT = process.cwd();
const DATA_DIR = path.join(ROOT, 'data');
const OUT_DIR = path.join(ROOT, 'mock_server', 'data');

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderSection(s: Section): string {
  switch (s.type) {
    case 'heading':
      return `<h${s.level}>${escapeHtml(s.text)}</h${s.level}>`;
    case 'paragraph':
      return `<p>${escapeHtml(s.text)}</p>`;
    case 'list': {
      const tag = s.ordered ? 'ol' : 'ul';
      const items = s.items.map((i) => `<li>${escapeHtml(i)}</li>`).join('');
      return `<${tag}>${items}</${tag}>`;
    }
    case 'table': {
      const head = s.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join('');
      const body = s.rows
        .map(
          (row) =>
            `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`,
        )
        .join('');
      return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }
    case 'note': {
      const cls =
        s.style === 'critical'
          ? 'critical-box'
          : s.style === 'warning'
            ? 'critical-box'
            : 'info-box';
      const title = s.title ? `<h3>${escapeHtml(s.title)}</h3>` : '';
      return `<div class="${cls}">${title}<p>${escapeHtml(s.text)}</p></div>`;
    }
  }
}

function renderBody(reg: Regulation): string {
  const subtitle = reg.subtitle
    ? `<p class="text-xs uppercase tracking-widest text-slate-500 font-bold mb-2">${escapeHtml(reg.subtitle)}</p>`
    : '';
  const meta = [
    reg.effective_date ? `<strong>Effective:</strong> ${escapeHtml(reg.effective_date)}` : '',
    reg.reference_number ? `<strong>Ref:</strong> ${escapeHtml(reg.reference_number)}` : '',
  ]
    .filter(Boolean)
    .join(' &nbsp;|&nbsp; ');
  const metaBlock = meta ? `<p class="text-xs text-slate-500">${meta}</p>` : '';
  const sectionsHtml = reg.sections.map(renderSection).join('\n  ');
  return `
  ${subtitle}
  <h1>${escapeHtml(reg.title)}</h1>
  ${metaBlock}
  <p>${escapeHtml(reg.summary)}</p>
  ${sectionsHtml}
  `;
}

const sidebarFor = (category: string): string => {
  if (category === 'regulations')
    return `
      <li><a href="/regulations/index.html">All Regulations</a></li>
      <li><a href="/regulations/tariff-schedule-2026.html">2026 Tariff Schedule</a></li>
      <li><a href="/regulations/import-licensing-requirements.html">Import Licensing Rules</a></li>
      <li><a href="/regulations/cbam-implementation-notice.html">CBAM Implementation</a></li>`;
  if (category === 'notices')
    return `
      <li><a href="/notices/index.html">All Notices</a></li>
      <li><a href="/notices/notice-2026-041.html">Notice 2026-041 (Lithium Batteries)</a></li>`;
  if (category === 'guidance')
    return `
      <li><a href="/guidance/index.html">All Guidance</a></li>`;
  return `
      <li><a href="/regulations/index.html">Current Regulations</a></li>
      <li><a href="/guidance/index.html">Compliance Guidance</a></li>
      <li><a href="/notices/index.html">Recent Notices</a></li>`;
};

const SHELL_CSS = `
<style>
  html, body { height: 100%; margin: 0; }
  .content h1, .content h2, .content h3 { font-family: ui-serif, Georgia, "Times New Roman", serif; color: #1e293b; }
  .content h1 { font-size: 1.5rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.5rem; margin: 0 0 1rem; }
  .content h2 { font-size: 1.25rem; margin: 1.5rem 0 0.75rem; }
  .content h3 { font-size: 1.125rem; margin: 1.5rem 0 0.5rem; }
  .content p, .content ul, .content ol { margin-bottom: 1rem; line-height: 1.625; color: #475569; font-size: 0.875rem; }
  .content ul { list-style: disc; padding-left: 1.5rem; }
  .content ol { list-style: decimal; padding-left: 1.5rem; }
  .content li { margin-bottom: 0.5rem; }
  .content a { color: #003366; text-decoration: underline; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; margin: 1.25rem 0; font-size: 0.75rem; }
  th, td { border: 1px solid #e2e8f0; padding: 0.5rem; text-align: left; }
  th { background-color: #f1f5f9; font-weight: 700; }
  .critical-box { padding: 1rem; margin: 1.25rem 0; border-left: 4px solid #dc2626; background-color: #fef2f2; }
  .critical-box h3 { color: #991b1b; margin-top: 0; font-size: 0.875rem; font-weight: 700; }
  .critical-box p { color: #b91c1c; font-size: 0.75rem; margin-bottom: 0; }
  .info-box { border-left: 4px solid #003366; background-color: #f8fafc; padding: 1rem; margin: 1rem 0; border: 1px solid #e2e8f0; border-left-width: 4px; border-radius: 0.25rem; }
  .sidebar ul { list-style: none; padding-left: 0; }
  .sidebar li { margin-bottom: 0.5rem; }
  .sidebar a { display: flex; align-items: center; color: #003366; font-size: 13px; font-weight: 500; text-decoration: none; }
  .sidebar a:before { content: "▶"; margin-right: 0.5rem; color: #cbd5e1; font-size: 0.75rem; }
  .sidebar a:hover { text-decoration: underline; }
</style>`;

function renderShell(title: string, sidebarLinks: string, contentHtml: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATCA - ${escapeHtml(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
${SHELL_CSS}
</head>
<body class="flex flex-col h-screen min-h-screen bg-white text-slate-900 font-sans overflow-hidden">
  <div class="bg-slate-100 border-b border-slate-200 px-4 py-1 flex items-center justify-between text-[10px] uppercase tracking-wider font-bold text-slate-600 shrink-0">
    <div class="flex items-center"><span class="mr-2 text-blue-800 italic font-serif">ADIAS</span><span>An official website of the ADIAS Government</span></div>
    <div class="flex space-x-4"><span>English</span><span class="opacity-50">Accessibility</span></div>
  </div>
  <header class="bg-[#003366] text-white border-b-4 border-[#ffcc00] px-6 py-4 flex items-center justify-between shadow-md shrink-0">
    <div class="flex items-center space-x-4">
      <div class="w-12 h-12 bg-white rounded-full flex items-center justify-center"><div class="border-2 border-[#003366] w-9 h-9 rounded-full flex items-center justify-center"><span class="text-[#003366] font-serif text-xl font-black">A</span></div></div>
      <div><h1 class="font-serif text-2xl leading-tight font-bold tracking-tight">ADIAS Trade & Compliance Authority</h1><p class="text-[11px] uppercase tracking-widest opacity-80 font-semibold">Regulation • Enforcement • Trade Facilitation</p></div>
    </div>
    <nav class="flex space-x-6 text-sm font-semibold">
      <a href="/index.html" class="opacity-80 hover:opacity-100">Home</a>
      <a href="/regulations/index.html" class="opacity-80 hover:opacity-100">Regulations</a>
      <a href="/guidance/index.html" class="opacity-80 hover:opacity-100">Guidance</a>
      <a href="/notices/index.html" class="opacity-80 hover:opacity-100">Notices</a>
      <a href="/about.html" class="opacity-80 hover:opacity-100">About</a>
    </nav>
  </header>
  <div class="flex-1 flex overflow-hidden">
    <aside class="w-64 bg-slate-50 border-r border-slate-200 p-6 flex flex-col sidebar overflow-y-auto shrink-0">
      <div class="mb-8"><h2 class="text-xs font-black uppercase text-slate-500 mb-4 tracking-widest">Quick Links</h2><ul>${sidebarLinks}</ul></div>
    </aside>
    <main class="flex-1 p-8 bg-white overflow-y-auto content">
      ${contentHtml}
    </main>
  </div>
  <footer class="bg-slate-800 text-slate-300 py-3 px-6 text-[10px] flex items-center justify-between border-t-2 border-[#ffcc00] shrink-0">
    <div class="flex space-x-6"><span>© 2026 ADIAS Trade & Compliance Authority</span><a href="/rss.xml" class="hover:text-white">RSS Feed</a></div>
  </footer>
</body>
</html>`;
}

function loadAll(): Regulation[] {
  const out: Regulation[] = [];
  for (const sub of ['regulations', 'notices', 'guidance']) {
    const dir = path.join(DATA_DIR, sub);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith('.json')) continue;
      const raw = fs.readFileSync(path.join(dir, f), 'utf8');
      out.push(JSON.parse(raw) as Regulation);
    }
  }
  return out;
}

function writePage(category: string, file: string, html: string) {
  const dir = path.join(OUT_DIR, category);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, file), html);
}

function generateOne(reg: Regulation) {
  const html = renderShell(reg.title, sidebarFor(reg.category), renderBody(reg));
  const dir = reg.category;
  fs.mkdirSync(path.join(OUT_DIR, dir), { recursive: true });
  fs.writeFileSync(path.join(OUT_DIR, dir, `${reg.slug}.html`), html);
}

function generateCategoryIndex(category: string, regs: Regulation[]) {
  const items = regs
    .map(
      (r) => `
      <li>
        ${r.subtitle ? `<strong>${escapeHtml(r.subtitle)}</strong><br>` : ''}
        <a href="/${category}/${r.slug}.html">${escapeHtml(r.title)}</a>
        <p>${escapeHtml(r.summary.slice(0, 200))}${r.summary.length > 200 ? '…' : ''}</p>
      </li>`,
    )
    .join('');
  const titleMap: Record<string, string> = {
    regulations: 'Regulatory Frameworks',
    notices: 'Notices and Updates',
    guidance: 'Compliance Guidance',
  };
  const heading = titleMap[category] || category;
  const html = renderShell(
    heading,
    sidebarFor(category),
    `<h1>${heading}</h1><p>Browse ${category} administered by ATCA.</p><ul>${items}</ul>`,
  );
  writePage(category, 'index.html', html);
}

function generateHome(allRegs: Regulation[]) {
  const recent = [...allRegs]
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    .slice(0, 6);
  const list = recent
    .map(
      (r) =>
        `<li><strong>${escapeHtml((r.updated_at || '').slice(0, 10))}:</strong> <a href="/${r.category}/${r.slug}.html">${escapeHtml(r.title)}</a></li>`,
    )
    .join('');
  const html = renderShell(
    'Home',
    sidebarFor(''),
    `
  <div style="background-color: #003366; color: white; padding: 40px 20px; text-align: center; margin-bottom: 30px;">
    <h1 style="color: white; border: none; font-size: 36px; margin-bottom: 20px;">Protecting Trade, Ensuring Compliance</h1>
    <p style="font-size: 18px; max-width: 800px; margin: 0 auto; line-height: 1.5;">The ADIAS Trade & Compliance Authority (ATCA) oversees the enforcement of international trade regulations.</p>
  </div>
  <h2>Latest Updates</h2>
  <ul>${list}</ul>`,
  );
  writePage('', 'index.html', html);
}

function generateRss(allRegs: Regulation[]) {
  const items = allRegs
    .map(
      (r) => `
    <item>
      <title>${escapeHtml(r.title)}</title>
      <link>http://localhost:3001/${r.category}/${r.slug}.html</link>
      <category>${r.category}</category>
      <pubDate>${r.updated_at}</pubDate>
      <description><![CDATA[${r.summary}]]></description>
    </item>`,
    )
    .join('\n');
  const xml = `<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>ATCA Updates</title>
    <link>http://localhost:3001/</link>
    <description>Latest regulations and notices from ATCA</description>
${items}
  </channel>
</rss>`;
  fs.writeFileSync(path.join(OUT_DIR, 'rss.xml'), xml);
}

function main() {
  const args = process.argv.slice(2);
  const all = args.includes('--all');
  const inputIdx = args.indexOf('--input');
  const inputFile = inputIdx >= 0 ? args[inputIdx + 1] : null;

  const allRegs = loadAll();

  if (inputFile) {
    const reg = JSON.parse(fs.readFileSync(inputFile, 'utf8')) as Regulation;
    generateOne(reg);
    console.log(`  ✓ ${reg.category}/${reg.slug}.html`);
  } else if (all) {
    for (const reg of allRegs) {
      generateOne(reg);
      console.log(`  ✓ ${reg.category}/${reg.slug}.html`);
    }
  }

  // Always rebuild indexes + home + rss so cross-page links stay correct
  for (const cat of ['regulations', 'notices', 'guidance']) {
    const regs = allRegs.filter((r) => r.category === cat);
    if (regs.length) generateCategoryIndex(cat, regs);
  }
  generateHome(allRegs);
  generateRss(allRegs);
  console.log('  ✓ index pages + rss.xml');
}

main();
