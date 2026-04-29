import * as fs from 'fs';
import * as path from 'path';

const outDir = path.join(process.cwd(), 'mock_server', 'data');

// Create directories
['', 'regulations', 'guidance', 'notices', 'documents'].forEach(dir => {
  fs.mkdirSync(path.join(outDir, dir), { recursive: true });
});

// PDF Dummy generation
['tariff-schedule-2026.pdf', 'importer-handbook-2026.pdf', 'hs-classification-guide.pdf', 'lithium-battery-import-notice.pdf'].forEach(pdf => {
  fs.writeFileSync(path.join(outDir, 'documents', pdf), '%PDF-1.4\n% Dummy PDF Content');
});

const generateHTML = (title: string, currentPath: string, sidebarLinks: string, content: string) => {
  const depth = currentPath.split('/').filter(Boolean).length;
  const rootPrefix = depth > 0 ? '../'.repeat(depth) : './';

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATCA - ${title}</title>
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
<style>
  html, body {
    height: 100%;
    margin: 0;
  }
  .content h1, .content h2, .content h3 {
    font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
    color: #1e293b; /* text-slate-800 */
  }
  .content h1 {
    font-size: 1.5rem; /* text-2xl */
    line-height: 2rem;
    border-bottom: 1px solid #e2e8f0; /* border-slate-200 */
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
    margin-top: 0;
  }
  .content h2 {
    font-size: 1.25rem; /* text-xl */
    line-height: 1.75rem;
    margin-top: 1.5rem;
    margin-bottom: 0.75rem;
  }
  .content h3 {
    font-size: 1.125rem;
    line-height: 1.75rem;
    margin-top: 1.5rem;
    margin-bottom: 0.5rem;
  }
  .content p, .content ul, .content ol {
    margin-bottom: 1rem;
    line-height: 1.625;
    color: #475569; /* text-slate-600 */
    font-size: 0.875rem; /* text-sm */
  }
  .content ul {
    list-style-type: disc;
    padding-left: 1.5rem;
  }
  .content ol {
    list-style-type: decimal;
    padding-left: 1.5rem;
  }
  .content li {
    margin-bottom: 0.5rem;
  }
  .content a {
    color: #003366;
    text-decoration: underline;
    font-weight: 600;
  }
  .content a:hover {
    color: #002244;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 1.25rem 0;
    font-size: 0.75rem; /* text-xs */
  }
  th, td {
    border: 1px solid #e2e8f0;
    padding: 0.5rem;
    text-align: left;
  }
  th {
    background-color: #f1f5f9; /* bg-slate-100 */
    font-weight: 700;
  }
  td.font-mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }
  .notice-box, .critical-box {
    padding: 1rem;
    margin: 1.25rem 0;
  }
  .critical-box {
    border-left: 4px solid #dc2626; /* border-red-600 */
    background-color: #fef2f2; /* bg-red-50 */
  }
  .critical-box h3, .critical-box h1 {
    color: #991b1b; /* text-red-800 */
    margin-top: 0;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 0.875rem;
    font-weight: 700;
  }
  .critical-box p {
    color: #b91c1c; /* text-red-700 */
    font-size: 0.75rem;
    margin-bottom: 0;
  }
  .info-box {
    border-left: 4px solid #003366;
    background-color: #f8fafc; /* bg-slate-50 */
    padding: 1rem;
    margin: 1rem 0;
    border: 1px solid #e2e8f0;
    border-left-width: 4px;
    border-radius: 0.25rem;
  }
  .btn {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    background-color: #dc2626;
    color: white !important;
    text-decoration: none !important;
    border-radius: 0.25rem;
    font-weight: 700;
    font-size: 0.625rem;
    text-transform: uppercase;
    margin-top: 0.75rem;
  }
  .btn:hover {
    background-color: #b91c1c;
  }
  .search-container {
    margin-bottom: 1.5rem;
    display: flex;
    position: relative;
  }
  .search-container input[type="text"] {
    width: 100%;
    font-size: 0.75rem;
    border: 1px solid #cbd5e1;
    border-radius: 0.25rem;
    padding: 0.5rem 0.75rem;
    background-color: white;
  }
  .search-container button {
    position: absolute;
    right: 0.5rem;
    top: 50%;
    transform: translateY(-50%);
    background: transparent;
    color: #94a3b8;
    border: none;
    cursor: pointer;
    font-size: 0.75rem;
  }
  .search-container button:hover {
    color: #475569;
  }
  
  /* Sidebar Links custom styling */
  .sidebar ul {
    list-style: none; /* Removed default listing */
    padding-left: 0;
  }
  .sidebar li {
    margin-bottom: 0.5rem;
  }
  .sidebar a {
    display: flex;
    align-items: center;
    color: #003366;
    font-size: 13px; /* text-[13px] */
    font-weight: 500;
    text-decoration: none;
  }
  .sidebar a:before {
    content: "▶";
    margin-right: 0.5rem;
    color: #cbd5e1; /* text-slate-300 */
    font-size: 0.75rem; /* text-xs */
  }
  .sidebar a:hover {
    text-decoration: underline;
  }
</style>
</head>
<body class="flex flex-col h-screen min-h-screen bg-white text-slate-900 font-sans overflow-hidden">
  <!-- Top Gov Banner -->
  <div class="bg-slate-100 border-b border-slate-200 px-4 py-1 flex items-center justify-between text-[10px] uppercase tracking-wider font-bold text-slate-600 shrink-0">
    <div class="flex items-center">
      <span class="mr-2 text-blue-800 italic font-serif">ADIAS</span>
      <span>An official website of the ADIAS Government</span>
    </div>
    <div class="flex space-x-4">
      <span>English</span>
      <span class="opacity-50">Accessibility</span>
    </div>
  </div>

  <!-- Authority Header -->
  <header class="bg-[#003366] text-white border-b-4 border-[#ffcc00] px-6 py-4 flex items-center justify-between shadow-md shrink-0">
    <div class="flex items-center space-x-4">
      <div class="w-12 h-12 bg-white rounded-full flex items-center justify-center">
        <div class="border-2 border-[#003366] w-9 h-9 rounded-full flex items-center justify-center">
          <span class="text-[#003366] font-serif text-xl font-black">A</span>
        </div>
      </div>
      <div>
        <h1 class="font-serif text-2xl leading-tight font-bold tracking-tight">ADIAS Trade & Compliance Authority</h1>
        <p class="text-[11px] uppercase tracking-widest opacity-80 font-semibold">Regulation • Enforcement • Trade Facilitation</p>
      </div>
    </div>
    <nav class="flex space-x-6 text-sm font-semibold">
      <a href="${rootPrefix}index.html" class="opacity-80 hover:opacity-100">Home</a>
      <a href="${rootPrefix}regulations/index.html" class="opacity-80 hover:opacity-100">Regulations</a>
      <a href="${rootPrefix}guidance/index.html" class="opacity-80 hover:opacity-100">Guidance</a>
      <a href="${rootPrefix}notices/index.html" class="opacity-80 hover:opacity-100">Notices</a>
      <a href="${rootPrefix}about.html" class="opacity-80 hover:opacity-100">About</a>
    </nav>
  </header>

  <!-- Main Content Layout -->
  <div class="flex-1 flex overflow-hidden">
    
    <!-- Left Sidebar: Quick Links -->
    <aside class="w-64 bg-slate-50 border-r border-slate-200 p-6 flex flex-col sidebar overflow-y-auto shrink-0">
      <div class="mb-8">
        <h2 class="text-xs font-black uppercase text-slate-500 mb-4 tracking-widest">Regulatory Search</h2>
        <div class="relative">
          <input type="text" placeholder="HTS Code, ECCN..." class="w-full text-xs border border-slate-300 rounded px-3 py-2 bg-white">
          <div class="absolute right-2 top-2 text-slate-400">🔍</div>
        </div>
      </div>

      <div class="mb-8">
        <h2 class="text-xs font-black uppercase text-slate-500 mb-4 tracking-widest">Quick Links</h2>
        <ul>
          ${sidebarLinks}
        </ul>
      </div>

      <div class="mt-auto border-t border-slate-200 pt-6">
        <div class="bg-[#fff9e6] p-4 border border-[#ffcc00] rounded">
          <p class="text-[10px] font-bold text-slate-700 uppercase mb-2">Compliance Deadline</p>
          <p class="text-xs text-red-700 font-bold mb-1">July 1, 2026</p>
          <p class="text-[11px] leading-snug">Mandatory Lithium Battery Documentation (Notice 2026-041)</p>
        </div>
      </div>
    </aside>

    <!-- Main Content Area -->
    <main class="flex-1 p-8 bg-white overflow-y-auto content">
      ${content}
    </main>
  </div>

  <!-- Sticky Footer -->
  <footer class="bg-slate-800 text-slate-300 py-3 px-6 text-[10px] flex items-center justify-between border-t-2 border-[#ffcc00] shrink-0">
    <div class="flex space-x-6">
      <span>© 2026 ADIAS Trade & Compliance Authority</span>
      <a href="${rootPrefix}privacy.html" class="hover:text-white">Privacy Policy</a>
      <a href="${rootPrefix}terms.html" class="hover:text-white">Terms of Use</a>
      <a href="${rootPrefix}accessibility.html" class="hover:text-white">Accessibility</a>
      <a href="${rootPrefix}contact.html" class="hover:text-white">Contact Us</a>
    </div>
    <div class="flex items-center space-x-2">
      <span class="w-2 h-2 bg-green-500 rounded-full"></span>
      <span class="uppercase font-bold tracking-widest opacity-60"><a href="${rootPrefix}rss.xml" class="text-slate-300 hover:text-white">RSS Feed</a> | System Status: Optimal</span>
    </div>
  </footer>
</body>
</html>`;
};

const pages: any[] = [];

const addPage = (dir: string, file: string, title: string, sidebar: string, content: string) => {
  pages.push({ dir, file, title, content });
  fs.writeFileSync(path.join(outDir, dir, file), generateHTML(title, dir, sidebar, content));
};

const mainSidebar = `
  <li><a href="/regulations/index.html">Current Regulations</a></li>
  <li><a href="/guidance/index.html">Compliance Guidance</a></li>
  <li><a href="/notices/index.html">Recent Notices</a></li>
`;

const regulationsSidebar = `
  <li><a href="/regulations/index.html">All Regulations</a></li>
  <li><a href="/regulations/tariff-schedule-2026.html">2026 Tariff Schedule</a></li>
  <li><a href="/regulations/import-licensing-requirements.html">Import Licensing Rules</a></li>
  <li><a href="/regulations/cbam-implementation-notice.html">CBAM Implementation</a></li>
`;

const guidanceSidebar = `
  <li><a href="/guidance/index.html">All Guidance</a></li>
  <li><a href="/guidance/importer-compliance-guide.html">Importer Compliance Guide</a></li>
  <li><a href="/guidance/hs-code-classification.html">HS Code Classification</a></li>
`;

const noticesSidebar = `
  <li><a href="/notices/index.html">All Notices</a></li>
  <li><a href="/notices/notice-2026-041.html">Notice 2026-041 (Lithium Batteries)</a></li>
  <li><a href="/notices/notice-2026-038.html">Notice 2026-038 (Section 301)</a></li>
  <li><a href="/notices/notice-2026-035.html">Notice 2026-035 (ECCN Updates)</a></li>
`;

// 1. index.html
addPage('', 'index.html', 'Home', mainSidebar, `
  <div style="background-color: #003366; color: white; padding: 40px 20px; text-align: center; margin-bottom: 30px;">
    <h1 style="color: white; border: none; font-size: 36px; margin-bottom: 20px;">Protecting Trade, Ensuring Compliance</h1>
    <p style="font-size: 18px; max-width: 800px; margin: 0 auto; line-height: 1.5;">The ADIAS Trade & Compliance Authority (ATCA) oversees the enforcement of international trade regulations, tariff schedules, and import/export restrictions to protect national interests.</p>
  </div>
  
  <div class="critical-box">
    <h3>URGENT: New Lithium Battery Import Rules</h3>
    <p>Effective July 1, 2026, all importers of lithium batteries above $50,000 value must comply with new documentation requirements.</p>
    <a href="/notices/notice-2026-041.html" class="btn">Read Notice 2026-041</a>
  </div>

  <h2>Latest Updates</h2>
  <ul>
    <li><strong>April 25, 2026:</strong> <a href="/regulations/cbam-implementation-notice.html">Carbon Border Adjustment Mechanism (CBAM) Initial Guidance Published</a></li>
    <li><strong>April 18, 2026:</strong> <a href="/notices/notice-2026-038.html">Notice 2026-038: Amendments to Section 301 Tariffs on Electronic Components</a></li>
    <li><strong>April 10, 2026:</strong> <a href="/notices/notice-2026-035.html">Notice 2026-035: New ECCN Classification Requirements for Advanced Semiconductors</a></li>
  </ul>
  
  <p><a href="/notices/index.html">View all notices &rarr;</a></p>
`);

// 2. regulations/index.html
addPage('regulations', 'index.html', 'Regulations', regulationsSidebar, `
  <h1>Regulatory Frameworks</h1>
  <p>Browse current trade regulations and enforcement guidelines administered by ATCA.</p>
  
  <div class="search-container">
    <input type="text" placeholder="Search regulations, CFR references, or HTS codes...">
    <button type="button">Search</button>
  </div>

  <h2>Current Regulations</h2>
  <ul>
    <li>
      <strong>CFR Title 19, Chapter IV</strong><br>
      <a href="/regulations/tariff-schedule-2026.html">Harmonized Tariff Schedule of the United States - 2026 Edition</a>
      <p>Current tariff rates, statistical categories, and special duty provisions.</p>
    </li>
    <li>
      <strong>CFR Title 15, Parts 730-774</strong><br>
      <a href="/regulations/import-licensing-requirements.html">Import Licensing & Quota Requirements</a>
      <p>Procedures for obtaining import licenses for restricted commodities.</p>
    </li>
    <li>
      <strong>ATCA Regulation 2026-9A</strong><br>
      <a href="/regulations/cbam-implementation-notice.html">Carbon Border Adjustment Mechanism Implementation</a>
      <p>Reporting rules for carbon-intensive imports effective Q3 2026.</p>
    </li>
  </ul>
`);

// 3. regulations/tariff-schedule-2026.html
addPage('regulations', 'tariff-schedule-2026.html', '2026 Tariff Schedule', regulationsSidebar, `
  <h1>Harmonized Tariff Schedule - 2026</h1>
  <p>The following table outlines the current tariff classifications and duty rates administered by the Authority for select chapters. These rates are effective as of January 1, 2026, unless otherwise noted.</p>
  
  <div class="info-box">
    <p><strong>Available Download:</strong> <a href="/documents/tariff-schedule-2026.pdf">Download Full PDF Archive (15.2 MB)</a></p>
  </div>

  <h2>Chapter 85: Electrical Machinery and Equipment</h2>
  <table>
    <tr>
      <th>HTS Code</th>
      <th>Article Description</th>
      <th>General Rate of Duty</th>
      <th>Special Rate / Section 301</th>
    </tr>
    <tr>
      <td>8507.60.00</td>
      <td>Lithium-ion batteries</td>
      <td>3.4%</td>
      <td>+ 25% (See Notice 2026-041)</td>
    </tr>
    <tr>
      <td>8541.40.60</td>
      <td>Diodes for semiconductor devices</td>
      <td>Free</td>
      <td>Free</td>
    </tr>
    <tr>
      <td>8542.31.00</td>
      <td>Processors and controllers, integrated circuits</td>
      <td>Free</td>
      <td>+ 10% (Restricted ECCN, see Notice 2026-035)</td>
    </tr>
  </table>
  
  <p>For official classification binding rulings, please consult the CBP Cross database or request an administrative ruling through the <a href="/contact.html">ATCA portal</a>.</p>
`);

// 4. regulations/import-licensing-requirements.html
addPage('regulations', 'import-licensing-requirements.html', 'Import Licensing Requirements', regulationsSidebar, `
  <h1>Import Licensing Requirements & Deadlines</h1>
  <p>Pursuant to ATCA Directive 44-B, specific commodities require strict import licensing before goods may be entered into the commerce space.</p>
  
  <h2>Compliance Deadlines for 2026</h2>
  <ul>
    <li><strong>Steel and Aluminum (Section 232):</strong> License applications must be filed at least 15 days prior to vessel departure.</li>
    <li><strong>Controlled Chemicals (EAR99/ECCN 1C350):</strong> End-user certification must be validated by September 30, 2026.</li>
    <li><strong>Agricultural Quotas:</strong> Tariff-rate quota (TRQ) licenses for dairy products renew on November 15, 2026.</li>
  </ul>
  
  <h2>Penalties for Non-Compliance</h2>
  <p>Failure to present a valid ATCA import license at the time of entry summary (CBP Form 7501) shall result in:</p>
  <ol>
    <li>Immediate detention of merchandise.</li>
    <li>Liquidated damages equal to three times the value of the merchandise.</li>
    <li>Civil penalties up to $50,000 per missing document under 19 U.S.C. § 1592.</li>
  </ol>
`);

// 5. regulations/cbam-implementation-notice.html
addPage('regulations', 'cbam-implementation-notice.html', 'CBAM Implementation', regulationsSidebar, `
  <h1>Carbon Border Adjustment Mechanism (CBAM) Implementation</h1>
  <p><strong>Effective Date:</strong> October 1, 2026</p>
  <p>The ATCA is implementing the initial transitional phase of the Carbon Border Adjustment Mechanism (CBAM). During this phase, importers of covered goods must report the greenhouse gas emissions (GHG) embedded in their imports.</p>

  <h2>Covered Commodities</h2>
  <p>The regulation currently applies to the following sectors:</p>
  <ul>
    <li>Iron and Steel (HTS Chapters 72 and 73)</li>
    <li>Aluminum (HTS Chapter 76)</li>
    <li>Cement (HTS 2523)</li>
    <li>Fertilizers (HTS Chapter 31)</li>
  </ul>

  <h2>Reporting Obligations</h2>
  <p>Importers must submit a quarterly CBAM declaration detailing:</p>
  <ul>
    <li>Total quantity of covered goods imported.</li>
    <li>Total embedded direct and indirect emissions (metric tons CO2e).</li>
    <li>Any carbon price paid in the country of origin.</li>
  </ul>
  <p>The first quarterly report (for Q4 2026) is due by <strong>January 31, 2027</strong>. Failure to report may result in a penalty of $50 to $150 per tonne of unreported emissions.</p>
`);

// 6. guidance/index.html
addPage('guidance', 'index.html', 'Guidance', guidanceSidebar, `
  <h1>Compliance Guidance</h1>
  <p>The Authority provides the following guidance documents to assist the trade community in maintaining compliance with complex international trade regulations.</p>

  <ul>
    <li><a href="/guidance/importer-compliance-guide.html">Importer Compliance Guide</a></li>
    <li><a href="/guidance/hs-code-classification.html">HS Code Classification Principles</a></li>
  </ul>
  
  <p><em>Note: Guidance documents do not have the force and effect of law and are not meant to bind the public in any way. They are intended only to provide clarity to the public regarding existing requirements under the law.</em></p>
`);

// 7. guidance/importer-compliance-guide.html
addPage('guidance', 'importer-compliance-guide.html', 'Importer Compliance Guide', guidanceSidebar, `
  <h1>Step-by-Step Importer Compliance Guide</h1>
  <p>This general guide outlines the fiduciary and legal responsibilities of the "Importer of Record" (IOR).</p>

  <div class="info-box">
    <p><strong>Available Download:</strong> <a href="/documents/importer-handbook-2026.pdf">Download Official Importer Handbook 2026 (PDF)</a></p>
  </div>

  <h2>Reasonable Care Checklist</h2>
  <ol>
    <li>
      <strong>Classification:</strong> Have you verified the 10-digit HTSUS code for your goods? You must use the most exact classification.
    </li>
    <li>
      <strong>Valuation:</strong> Does the entered value represent the Price Actually Paid or Payable (PAPP), including assists, packing costs, and royalties?
    </li>
    <li>
      <strong>Country of Origin:</strong> Is the origin marked correctly, and do you have documentation to support the claim if a free trade agreement (e.g., USMCA) is utilized?
    </li>
    <li>
      <strong>Recordkeeping:</strong> Are you maintaining all entry records (commercial invoices, bills of lading) for a minimum of 5 years (a/k/a the (a)(1)(A) list)?
    </li>
  </ol>
`);

// 8. guidance/hs-code-classification.html
addPage('guidance', 'hs-code-classification.html', 'HS Code Classification', guidanceSidebar, `
  <h1>Harmonized System (HS) Code Classification</h1>
  <p>Accurate classification of imported goods under the Harmonized Tariff Schedule (HTS) is a legal requirement.</p>
  
  <div class="info-box">
    <p><strong>Available Download:</strong> <a href="/documents/hs-classification-guide.pdf">Download Classification Principles Guide (PDF)</a></p>
  </div>

  <h2>General Rules of Interpretation (GRIs)</h2>
  <p>Classification is determined according to the GRIs. The most commonly used is GRI 1:</p>
  <blockquote style="font-style: italic; background-color: #f9f9f9; padding: 10px; border-left: 3px solid #666;">
    "Classification shall be determined according to the terms of the headings and any relative Section or Chapter Notes..."
  </blockquote>

  <h2>Case Study Example: Electronics</h2>
  <p>A composite machine consisting of a printer, a copier, and a facsimile machine is presented.</p>
  <ul>
    <li>According to Section XVI, Note 3, composite machines are classified as if consisting only of that component which performs the <strong>principal function</strong>.</li>
    <li>If the device is primarily marketed and used as a printer, it falls under HTS 8443.31.00.</li>
  </ul>
`);

// 9. notices/index.html
addPage('notices', 'index.html', 'Notices', noticesSidebar, `
  <h1>Notices and Updates</h1>
  <p>Official notices from the ATCA Director of Enforcement and Compliance.</p>
  
  <table style="width: 100%;">
    <tr>
      <th>Notice Number</th>
      <th>Subject</th>
      <th>Date Issued</th>
    </tr>
    <tr>
      <td><a href="/notices/notice-2026-041.html">Notice 2026-041</a></td>
      <td><strong>URGENT:</strong> New documentation requirements for lithium battery imports</td>
      <td>April 28, 2026</td>
    </tr>
    <tr>
      <td><a href="/notices/notice-2026-038.html">Notice 2026-038</a></td>
      <td>Amendment to Section 301 tariffs and quota management</td>
      <td>April 15, 2026</td>
    </tr>
    <tr>
      <td><a href="/notices/notice-2026-035.html">Notice 2026-035</a></td>
      <td>New ECCN classification requirements for Export Administration Regulations (EAR)</td>
      <td>April 5, 2026</td>
    </tr>
  </table>
`);

// 10. notices/notice-2026-041.html
addPage('notices', 'notice-2026-041.html', 'Notice 2026-041', noticesSidebar, `
  <div class="critical-box">
    <h1 style="color: #cc0000; font-size: 24px; border: none; padding: 0;">CRITICAL REGULATORY NOTICE 2026-041</h1>
    <strong>Effective Date: July 1, 2026</strong>
  </div>
  
  <h2>Subject: Enhanced Documentation Requirements for Lithium Battery Imports</h2>
  
  <p><strong>AGENCY:</strong> ADIAS Trade & Compliance Authority (ATCA).</p>
  <p><strong>ACTION:</strong> Final Rule and Administrative Command.</p>
  
  <p><strong>SUMMARY:</strong> Due to an increase in supply chain irregularities and to enforce critical infrastructure security measures, the ATCA is mandating strict new documentation requirements for all lithium-ion battery imports (specifically classified under HTS 8507.60.00).</p>
  
  <h3>Mandatory Requirements</h3>
  <p>Effective <strong>July 1, 2026</strong>, all importers processing shipments of lithium batteries with an entered aggregate value exceeding <strong>$50,000 USD</strong> must electronically transmit a "Form 8-BAT Supply Chain Provenance Certificate" via the ACE portal before the vessel arrives at the port of entry.</p>
  
  <h3>Penalties for Non-Compliance</h3>
  <p>Failure to provide this documentation by the deadline will be considered a severe violation of 19 U.S.C. § 1592. The authority will enforce:</p>
  <ul>
    <li>An immediate halt on the clearance of goods at the port.</li>
    <li>A mandatory civil penalty of <strong>$25,000 per violation</strong>.</li>
    <li>Potential suspension of the importer's continuous bond.</li>
  </ul>

  <div class="info-box">
    <p><strong>Available Download:</strong> <a href="/documents/lithium-battery-import-notice.pdf">Download Official Signed Notice (PDF)</a></p>
  </div>
`);

// 11. notices/notice-2026-038.html
addPage('notices', 'notice-2026-038.html', 'Notice 2026-038', noticesSidebar, `
  <h1>Notice 2026-038: Amendment to Section 301 Tariffs</h1>
  <p><strong>AGENCY:</strong> ADIAS Trade & Compliance Authority (ATCA), in coordination with the USTR.</p>
  
  <p><strong>SUMMARY:</strong> Pursuant to ongoing trade investigations under Section 301 of the Trade Act of 1974, specific products have been removed from the exclusion list and are now subject to maintaining the 25% additional ad valorem duty.</p>
  
  <h2>Impacted Categories</h2>
  <p>Importers utilizing HTS heading 9403 (Other Furniture) and 8471 (Automatic Data Processing Machines) must note the expiration of previous exclusions. All goods entered for consumption on or after May 1, 2026, will be assessed the additional duties.</p>
  
  <p>For detailed subheadings and exact tariff rate adjustments, please review the <a href="/regulations/tariff-schedule-2026.html">updated 2026 Tariff Schedule</a>.</p>
`);

// 12. notices/notice-2026-035.html
addPage('notices', 'notice-2026-035.html', 'Notice 2026-035', noticesSidebar, `
  <h1>Notice 2026-035: New ECCN Classification Requirements</h1>
  <p><strong>AGENCY:</strong> ADIAS Trade & Compliance Authority (ATCA).</p>
  
  <p><strong>SUMMARY:</strong> Revisions to the Commerce Control List (CCL) under the Export Administration Regulations (EAR) mandate updated Export Control Classification Number (ECCN) reporting for specific advanced computing items.</p>
  
  <h2>Details</h2>
  <p>Integrated circuits previously classified under EAR99 and now meeting the performance thresholds established in Category 3 (ECCN 3A090) must now be licensed prior to export or re-export to restricted D:1, D:4, and D:5 country groups.</p>
  <p>Importers dealing in reciprocal trade of these components must also maintain destination control statements upon import to verify end-use.</p>
`);

// 13. about.html
addPage('', 'about.html', 'About Us', mainSidebar, `
  <h1>About the Authority</h1>
  <p>The ADIAS Trade & Compliance Authority (ATCA) was established to provide centralized oversight for multi-agency border enforcement policies. We ensure a level playing field for domestic industries while facilitating lawful international trade.</p>
  <p>Our mission is to collect revenue, enforce trade laws, and secure borders against illicit economic activities.</p>
`);

// 14. contact.html
addPage('', 'contact.html', 'Contact Us', mainSidebar, `
  <h1>Contact the Authority</h1>
  <p>For general inquiries regarding compliance, tariff classifications, or portal technical support:</p>
  <ul>
    <li><strong>Email:</strong> trade-support@atca.gov.mock</li>
    <li><strong>Phone:</strong> 1-800-555-ATCA</li>
    <li><strong>Address:</strong> 1400 Trade Avenue NW, Washington DC, 20230</li>
  </ul>
  <p><em>Warning: Do not send classified PII or sensitive business proprietary information via unencrypted email.</em></p>
`);

// 15. privacy.html
addPage('', 'privacy.html', 'Privacy Policy', mainSidebar, `
  <h1>Privacy & Security Policy</h1>
  <p>Information presented on this website is considered public information and may be distributed or copied. Use of appropriate byline/photo/image credits is requested.</p>
  <p>For site management, information is collected for statistical purposes. This computer system uses software programs to create summary statistics, which are used for assessing what information is of most and least interest, determining technical design specifications, and identifying system performance or problem areas.</p>
  <p>Unauthorized attempts to upload information or change information on this service are strictly prohibited and may be punishable under the Computer Fraud and Abuse Act of 1986 and the National Information Infrastructure Protection Act.</p>
`);

// terms.html and accessibility.html to avoid 404
addPage('', 'terms.html', 'Terms of Use', mainSidebar, `
  <h1>Terms of Use</h1>
  <p>This is a simulated governmental system for demonstration purposes only. Information contained herein is entirely fictional.</p>
`);

addPage('', 'accessibility.html', 'Accessibility Statement', mainSidebar, `
  <h1>Accessibility</h1>
  <p>The ATCA is committed to ensuring its website is accessible to all individuals, including those with disabilities, in accordance with Section 508 of the Rehabilitation Act.</p>
`);

// 16. rss.xml
const rssItems = pages.map(page => `
    <item>
      <title>${page.title}</title>
      <link>http://localhost:3000/${page.dir ? page.dir + '/' : ''}${page.file}</link>
      <category>${page.dir || 'general'}</category>
      <description><![CDATA[${page.content}]]></description>
    </item>
`).join('\n');

const rssFeed = `<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>ATCA Updates</title>
    <link>http://localhost:3000/</link>
    <description>Latest regulations and notices from the ADIAS Trade & Compliance Authority</description>
${rssItems}
  </channel>
</rss>`;

fs.writeFileSync(path.join(outDir, 'rss.xml'), rssFeed);

console.log('Successfully generated all ATCA mock files in mock_server/data.');
