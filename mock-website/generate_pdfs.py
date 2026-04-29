"""
Generate 4 realistic regulatory PDF documents for the mock ATCA website.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "mock_server", "data", "documents")
os.makedirs(OUT_DIR, exist_ok=True)

W, H = A4
styles = getSampleStyleSheet()

def _style(name, **kw):
    s = ParagraphStyle(name, parent=styles["Normal"], **kw)
    return s

HEADER   = _style("Header",   fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=6, textColor=colors.HexColor("#1a3a6b"), fontName="Helvetica-Bold")
SUBHEAD  = _style("Subhead",  fontSize=13, leading=16, alignment=TA_CENTER, spaceAfter=4, textColor=colors.HexColor("#2c5f9e"), fontName="Helvetica-Bold")
H2       = _style("H2",       fontSize=12, leading=15, spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#1a3a6b"), fontName="Helvetica-Bold")
H3       = _style("H3",       fontSize=10, leading=13, spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#333333"), fontName="Helvetica-BoldOblique")
BODY     = _style("Body",     fontSize=9,  leading=13, spaceAfter=4, alignment=TA_JUSTIFY)
SMALL    = _style("Small",    fontSize=8,  leading=10, spaceAfter=2, textColor=colors.grey)
BOLD     = _style("Bold",     fontSize=9,  leading=13, fontName="Helvetica-Bold")
CENTER   = _style("Center",   fontSize=9,  leading=13, alignment=TA_CENTER)

def rule():
    return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2c5f9e"), spaceAfter=6)

def thin_rule():
    return HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=4)

def tbl(data, col_widths, header_rows=1):
    t = Table(data, colWidths=col_widths)
    style = TableStyle([
        ("BACKGROUND",  (0,0), (-1, header_rows-1), colors.HexColor("#1a3a6b")),
        ("TEXTCOLOR",   (0,0), (-1, header_rows-1), colors.white),
        ("FONTNAME",    (0,0), (-1, header_rows-1), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("ALIGN",       (0,0), (-1,-1), "LEFT"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f4fa")]),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
    ])
    t.setStyle(style)
    return t

# ──────────────────────────────────────────────────────────────
# 1. TARIFF SCHEDULE 2026
# ──────────────────────────────────────────────────────────────
def gen_tariff_schedule():
    path = os.path.join(OUT_DIR, "tariff-schedule-2026.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story += [
        Paragraph("ATCA CUSTOMS AUTHORITY", HEADER),
        Paragraph("GENERAL TARIFF SCHEDULE — 2026 EDITION", SUBHEAD),
        Paragraph("Effective Date: 1 January 2026 | Reference: ATCA/TS/2026/001", CENTER),
        Spacer(1, 0.3*cm), rule(),
    ]

    story.append(Paragraph("1. Scope and Legal Basis", H2))
    story.append(Paragraph(
        "This Schedule establishes the applicable import duty rates for goods entering the Arcadian Trade and "
        "Customs Authority (ATCA) territory for the fiscal year 2026. It is issued pursuant to Article 34 of the "
        "ATCA Customs Code (as amended by Regulation 2025/88) and supersedes the 2025 Tariff Schedule in its entirety. "
        "Importers are required to apply the rates set out herein from 1 January 2026.", BODY))

    story.append(Paragraph("2. Chapter 84 — Nuclear Reactors, Boilers, Machinery", H2))
    data = [
        ["HS Code", "Description", "Duty Rate", "VAT", "Notes"],
        ["8401.10", "Nuclear reactors", "0%", "20%", "License required"],
        ["8403.10", "Central heating boilers", "3.5%", "20%", ""],
        ["8408.20", "Compression-ignition engines for vehicles", "5.0%", "20%", ""],
        ["8411.11", "Turbojets, thrust ≤ 25 kN", "2.5%", "20%", "Dual-use check"],
        ["8414.51", "Table, floor, wall fans", "8.0%", "20%", ""],
        ["8415.10", "Air conditioning — window/wall type", "8.0%", "20%", ""],
        ["8418.10", "Combined refrigerator-freezers", "7.5%", "20%", "Energy label req."],
        ["8443.31", "Machines performing 2+ printing functions", "3.0%", "20%", ""],
    ]
    story.append(tbl(data, [2.5*cm, 6*cm, 2*cm, 1.5*cm, 3.5*cm]))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3. Chapter 85 — Electrical Machinery and Equipment", H2))
    data2 = [
        ["HS Code", "Description", "Duty Rate", "VAT", "Notes"],
        ["8501.10", "Motors, output ≤ 37.5 W", "4.0%", "20%", ""],
        ["8507.60", "Lithium-ion accumulators", "7.5%", "20%", "REVISED May 2026 — was 2.5%. UN 38.3 req."],
        ["8507.60.10", "EV traction battery packs (>100 kWh)", "12.0%", "20%", "NEW — effective May 1, 2026"],
        ["8507.80", "Other electric accumulators", "3.5%", "20%", ""],
        ["8517.12", "Telephones for cellular networks (smartphones)", "0%", "20%", ""],
        ["8528.72", "Colour TVs, LCD, ≤ 55\"", "10.0%", "20%", ""],
        ["8536.50", "Switches, rated ≤ 1000V", "4.5%", "20%", ""],
        ["8544.42", "Electrical conductors, fitted with connectors", "5.0%", "20%", ""],
    ]
    story.append(tbl(data2, [2.5*cm, 6*cm, 2*cm, 1.5*cm, 3.5*cm]))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("4. Chapter 61–62 — Apparel and Clothing Accessories", H2))
    data3 = [
        ["HS Code", "Description", "Duty Rate", "VAT", "Notes"],
        ["6101.20", "Men's overcoats, cotton", "12.0%", "20%", "Origin rule: 50% VA"],
        ["6109.10", "T-shirts, cotton", "12.0%", "20%", ""],
        ["6110.20", "Jerseys, pullovers, cotton", "12.0%", "20%", ""],
        ["6203.42", "Men's trousers, cotton", "12.0%", "20%", ""],
        ["6204.62", "Women's trousers, cotton", "12.0%", "20%", ""],
        ["6211.43", "Garments, man-made fibres", "12.0%", "20%", "Anti-dumping duty may apply"],
    ]
    story.append(tbl(data3, [2.5*cm, 6*cm, 2*cm, 1.5*cm, 3.5*cm]))

    story.append(Paragraph("5. Preferential Rates — Free Trade Agreements", H2))
    story.append(Paragraph(
        "The following FTA partners benefit from reduced or zero duty rates subject to proof of origin "
        "(Form EUR.1 or REX declaration). The standard MFN rates in this schedule do not apply to qualifying goods.", BODY))
    data4 = [
        ["Partner Country / Bloc", "Agreement", "Effective Since", "Coverage"],
        ["European Union", "ATCA–EU Comprehensive Agreement", "2021-03-01", "Goods + Services"],
        ["United Kingdom", "ATCA–UK Trade Agreement", "2021-01-01", "Goods only"],
        ["Canada", "ATCA–Canada FTA", "2023-06-15", "Goods + IP"],
        ["Japan", "ATCA–Japan EPA", "2022-04-01", "Goods + Services"],
        ["Singapore", "ATCA–SGP Digital Economy Agreement", "2024-01-01", "Digital + Goods"],
    ]
    story.append(tbl(data4, [4*cm, 5.5*cm, 3*cm, 3*cm]))

    story.append(Paragraph("6. Anti-Dumping and Countervailing Measures", H2))
    story.append(Paragraph(
        "Certain product categories are subject to provisional or definitive anti-dumping duties in addition to "
        "the standard rates above. Importers must declare the country of origin of such goods at the time of "
        "customs entry. Current measures in force (as at 1 January 2026) are published in ATCA Official Journal "
        "Supplement C-2025/448.", BODY))

    story.append(Paragraph("7. Amendment Procedure", H2))
    story.append(Paragraph(
        "Rates in this Schedule may be amended by the ATCA Tariff Committee by notice published in the ATCA "
        "Official Journal with a minimum of 30 days' prior notice, except in cases of emergency measures under "
        "Article 78 of the Customs Code, which take effect immediately upon publication.", BODY))

    story.append(Spacer(1, 0.5*cm))
    story.append(thin_rule())
    story.append(Paragraph(
        "Issued by the ATCA Directorate of Customs Tariffs | Approved: Director-General, 15 December 2025 | "
        "Next review: 1 December 2026", SMALL))

    doc.build(story)
    print(f"  ✓ {path}")


# ──────────────────────────────────────────────────────────────
# 2. IMPORTER HANDBOOK 2026
# ──────────────────────────────────────────────────────────────
def gen_importer_handbook():
    path = os.path.join(OUT_DIR, "importer-handbook-2026.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story += [
        Paragraph("ARCADIAN TRADE AND CUSTOMS AUTHORITY", HEADER),
        Paragraph("IMPORTER'S COMPLIANCE HANDBOOK — 2026", SUBHEAD),
        Paragraph("ATCA/ICH/2026 | For use from 1 January 2026", CENTER),
        Spacer(1, 0.3*cm), rule(),
    ]

    story.append(Paragraph("FOREWORD", H2))
    story.append(Paragraph(
        "This Handbook provides practical guidance for importers bringing goods into ATCA territory. It consolidates "
        "requirements from the Customs Code, the Import Licensing Regulations, and guidance circulars issued during "
        "2025. It replaces the 2025 Importer Handbook in full. Importers are strongly advised to review the changes "
        "highlighted in Appendix A before lodging declarations from 1 January 2026.", BODY))

    story.append(Paragraph("CHAPTER 1 — REGISTRATION AND ECONOMIC OPERATOR STATUS", H2))
    story.append(Paragraph("1.1 EORI Registration", H3))
    story.append(Paragraph(
        "All importers must hold a valid Economic Operator Registration and Identification (EORI) number issued by "
        "the ATCA Customs Authority before submitting any import declaration. Applications are made through the ATCA "
        "Trader Portal (portal.atca.gov). Processing time is 3–5 working days.", BODY))

    story.append(Paragraph("1.2 Authorised Economic Operator (AEO)", H3))
    story.append(Paragraph(
        "Importers who hold AEO-C (Customs Simplifications) or AEO-S (Security and Safety) status benefit from "
        "reduced examination rates, priority treatment at border posts, and access to simplified procedures including "
        "Entry in Declarant's Records (EIDR). AEO applications require a self-assessment questionnaire and site visit "
        "by a ATCA Customs compliance officer.", BODY))

    story.append(Paragraph("CHAPTER 2 — IMPORT DECLARATION REQUIREMENTS", H2))
    story.append(Paragraph("2.1 SAD Form — Required Data Elements", H3))
    story.append(Paragraph(
        "Import declarations must be lodged on the Single Administrative Document (SAD) via the ATCA Electronic "
        "Customs Declaration System (ECDS). The following data elements are mandatory for all consignments:", BODY))
    items = [
        ("Box 1", "Declaration type (IM for import; IP for inward processing)"),
        ("Box 8", "Consignee EORI number and full legal address"),
        ("Box 14", "Declarant / Representative EORI and authorisation reference"),
        ("Box 22", "Invoice currency and total invoice amount"),
        ("Box 31", "Package marks, numbers, and description of goods"),
        ("Box 33", "Commodity code (10-digit HS code)"),
        ("Box 36", "Preference code (e.g. 300 for FTA, 100 for MFN)"),
        ("Box 44", "Additional information codes and document references"),
        ("Box 47", "Calculation of taxes — duty, VAT, excise"),
    ]
    data = [["Box", "Description"]] + [[b, d] for b, d in items]
    story.append(tbl(data, [2.5*cm, 13*cm]))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.2 Supporting Documents", H3))
    story.append(Paragraph(
        "The following documents must be available at the time of declaration and retained for 4 years:", BODY))
    for doc_name in [
        "Commercial invoice (original or certified copy)",
        "Packing list",
        "Bill of lading or airway bill",
        "Certificate of origin (where preferential rates are claimed)",
        "Import licence (for restricted goods — see Chapter 4)",
        "Test certificates or conformity declarations (where required by product regulation)",
        "Insurance certificate (CIF shipments)",
    ]:
        story.append(Paragraph(f"• {doc_name}", BODY))

    story.append(Paragraph("CHAPTER 3 — CUSTOMS VALUE", H2))
    story.append(Paragraph(
        "The customs value is normally the transaction value (CIF) — the price actually paid or payable for the "
        "goods, plus cost of transport and insurance to the ATCA frontier. Where related-party transactions exist, "
        "the declarant must demonstrate that the price is not influenced by the relationship (Method 1). Fallback "
        "methods (deductive value, computed value) apply in order as set out in Article 55–62 of the Customs Code.", BODY))

    story.append(Paragraph("CHAPTER 4 — IMPORT LICENSING", H2))
    story.append(Paragraph(
        "The following categories require an import licence issued by the competent authority before the goods "
        "may be released to free circulation:", BODY))
    data5 = [
        ["Category", "Authority", "Lead Time", "Form"],
        ["Agricultural quota goods", "Ministry of Agriculture", "15 working days", "ILA-01"],
        ["Dual-use goods (Annex I, Reg. 428/2009)", "Export Control Unit, MoD", "20–30 working days", "DU-2025"],
        ["Endangered species (CITES)", "Environment Agency", "10 working days", "CITES-IM"],
        ["Pharmaceuticals / biologics", "Medicines Regulatory Authority", "30 working days", "MRA-IMP"],
        ["Radio equipment (non-EU conformity)", "Spectrum Management Office", "5 working days", "SMO-R"],
        ["Firearms and parts", "National Police Authority", "40 working days", "NPA-FA"],
    ]
    story.append(tbl(data5, [4*cm, 4.5*cm, 3*cm, 2*cm]))

    story.append(Paragraph("CHAPTER 5 — KEY CHANGES FOR 2026", H2))
    story.append(Paragraph(
        "The following material changes apply from 1 January 2026 and were not present in the 2025 edition:", BODY))
    changes = [
        ("Lithium battery declaration", "All shipments containing lithium cells or batteries (HS 8507.60) must include UN 38.3 test summary and state of charge (≤ 30% for sea freight). See new Form BATT-2026."),
        ("Carbon Border Adjustment Mechanism (CBAM) reporting", "Importers of steel, aluminium, cement, fertilisers, and electricity must file quarterly CBAM declarations from Q1 2026. Pre-registration closed 31 October 2025; late registration incurs a EUR 250 fee."),
        ("Deforestation Regulation due diligence", "Operators placing cattle, soy, palm oil, wood, cocoa, coffee, and derived products on the ATCA market must submit a due diligence statement (DDS) via the ATCA Deforestation Portal from 30 December 2025."),
        ("Revised penalty tariff for mis-declaration", "The fixed-penalty uplift for deliberate mis-declaration (Box 33 commodity code) increases from 15% to 25% of the duty shortfall, effective 1 March 2026."),
    ]
    for title, text in changes:
        story.append(Paragraph(title, H3))
        story.append(Paragraph(text, BODY))

    story.append(Spacer(1, 0.5*cm))
    story.append(thin_rule())
    story.append(Paragraph(
        "ATCA Customs Authority — Compliance and Trader Services Division | ATCA/ICH/2026 | "
        "Published 1 December 2025 | Supersedes ATCA/ICH/2025", SMALL))

    doc.build(story)
    print(f"  ✓ {path}")


# ──────────────────────────────────────────────────────────────
# 3. HS CLASSIFICATION GUIDE
# ──────────────────────────────────────────────────────────────
def gen_hs_guide():
    path = os.path.join(OUT_DIR, "hs-classification-guide.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story += [
        Paragraph("ATCA CUSTOMS AUTHORITY", HEADER),
        Paragraph("PRACTICAL GUIDE TO HS CODE CLASSIFICATION", SUBHEAD),
        Paragraph("Ref: ATCA/CLASS/2026/G01 | Based on HS 2022 Nomenclature", CENTER),
        Spacer(1, 0.3*cm), rule(),
    ]

    story.append(Paragraph("1. Introduction", H2))
    story.append(Paragraph(
        "The Harmonized System (HS) is an internationally standardised nomenclature for classifying traded "
        "products, maintained by the World Customs Organization (WCO). Correct classification is a legal "
        "obligation: it determines the applicable duty rate, whether a licence or permit is required, "
        "and the application of trade policy measures (anti-dumping duties, safeguards, embargoes). "
        "ATCA uses the 10-digit Combined Nomenclature (CN), which extends the 6-digit HS code with two "
        "further digits for EU-derived sub-headings and a further two for ATCA-specific statistical purposes.", BODY))

    story.append(Paragraph("2. Structure of the HS Code", H2))
    data = [
        ["Digits", "Level", "Example", "Meaning"],
        ["1–2", "Chapter", "84", "Nuclear reactors, boilers, machinery"],
        ["3–4", "Heading", "8471", "Automatic data processing machines"],
        ["5–6", "Subheading", "847130", "Portable ADP machines (≤ 10 kg)"],
        ["7–8", "CN subheading", "84713000", "ATCA tariff line"],
        ["9–10", "TARIC/statistical", "8471300000", "Full ATCA 10-digit code"],
    ]
    story.append(tbl(data, [2*cm, 3.5*cm, 3.5*cm, 6.5*cm]))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3. General Rules of Interpretation (GRI)", H2))
    story.append(Paragraph(
        "Classification is governed by the six GRIs, which must be applied in strict numerical order. "
        "Only if a rule does not resolve the classification should the next rule be applied.", BODY))
    rules = [
        ("GRI 1", "Classification is determined by the terms of the headings and any relative section or chapter notes."),
        ("GRI 2(a)", "Incomplete or unfinished articles are classified with the complete or finished article (if they have the essential character of the complete article)."),
        ("GRI 2(b)", "Mixtures or combinations of materials: each heading is treated as referring to the pure material plus mixtures or combinations."),
        ("GRI 3(a)", "Where two headings could apply, the most specific description takes precedence."),
        ("GRI 3(b)", "Composite goods and sets: classified by the component that gives them their essential character."),
        ("GRI 3(c)", "If GRI 3(a) and 3(b) cannot decide: classify under the heading that occurs last in numerical order."),
        ("GRI 4", "Goods not classifiable under GRIs 1–3 are classified under the heading for the most similar goods."),
        ("GRI 5", "Camera cases, musical instrument cases, etc. are classified with the article when entered together."),
        ("GRI 6", "Classification at sub-heading level follows the same principles applied at heading level."),
    ]
    data_r = [["Rule", "Description"]] + [[r, d] for r, d in rules]
    story.append(tbl(data_r, [2.5*cm, 13*cm]))

    story.append(Paragraph("4. Worked Examples", H2))

    story.append(Paragraph("4.1 Laptop Computer", H3))
    story.append(Paragraph(
        "A laptop computer with a built-in keyboard, screen, and battery, weighing 1.8 kg. "
        "Apply GRI 1: Chapter 84, Note 5 defines ADP machines. Heading 8471 covers ADP machines. "
        "Subheading 8471.30 covers portable ADP machines weighing ≤ 10 kg. "
        "<b>Correct code: 8471 30 00 00</b> — duty rate 0%.", BODY))

    story.append(Paragraph("4.2 Lithium-Ion Power Bank", H3))
    story.append(Paragraph(
        "A portable battery pack of 20,000 mAh with two USB-A outputs and one USB-C output, "
        "using lithium-ion cells. Not an accumulator designed for a specific application — "
        "it functions primarily as a portable power supply. "
        "Heading 8507 covers electric accumulators. Subheading 8507.60 covers lithium-ion accumulators. "
        "<b>Correct code: 8507 60 00 00</b> — duty rate 2.5%. UN 38.3 certificate required.", BODY))

    story.append(Paragraph("4.3 Men's Cotton T-Shirt", H3))
    story.append(Paragraph(
        "A plain cotton T-shirt for adult men. Chapter 61 covers knitted garments; Chapter 62 covers woven. "
        "T-shirts are typically knitted fabric: Chapter 61. Heading 6109 — T-shirts, singlets, and other vests, "
        "knitted or crocheted. Subheading 6109.10 — of cotton. "
        "<b>Correct code: 6109 10 00 10</b> — duty rate 12%.", BODY))

    story.append(Paragraph("4.4 Electric Vehicle Battery Pack", H3))
    story.append(Paragraph(
        "A complete lithium-ion battery pack designed for installation in a battery electric vehicle (BEV), "
        "composed of 96 cells arranged in modules, with integrated BMS and thermal management system. "
        "As an assembly, classify as lithium-ion accumulator under 8507.60 (not under 8708 as a vehicle part), "
        "since Note 2 to Section XVII excludes accumulators. "
        "<b>Correct code: 8507 60 00 00</b> — duty rate 2.5%. CBAM reporting required from Q1 2026.", BODY))

    story.append(Paragraph("5. Binding Tariff Information (BTI)", H2))
    story.append(Paragraph(
        "Importers uncertain about the correct classification may apply for a Binding Tariff Information (BTI) "
        "decision from the ATCA Customs Authority. A BTI is legally binding on ATCA Customs for a period of 3 years "
        "from its date of issue and may be relied upon by the holder. Applications are submitted via the ATCA "
        "Trader Portal; processing time is up to 90 days. Fee: EUR 200 per application.", BODY))

    story.append(Paragraph("6. Common Classification Errors and Penalties", H2))
    data_e = [
        ["Error Type", "Consequence", "Penalty"],
        ["Under-declaration (lower duty heading)", "Duty shortfall + interest", "25% of shortfall (from 1 Mar 2026)"],
        ["Incorrect origin declaration", "Preferential rate clawed back", "Duty + 15% surcharge"],
        ["Missing licence code in Box 44", "Goods detained", "Storage costs + EUR 500 admin fee"],
        ["Wrong statistical suffix (digits 9–10)", "Customs hold for correction", "EUR 50 amendment fee"],
    ]
    story.append(tbl(data_e, [4.5*cm, 5*cm, 5*cm]))

    story.append(Spacer(1, 0.5*cm))
    story.append(thin_rule())
    story.append(Paragraph(
        "ATCA Customs Classification Unit | ATCA/CLASS/2026/G01 | Published December 2025 | "
        "Questions: classification@customs.atca.gov", SMALL))

    doc.build(story)
    print(f"  ✓ {path}")


# ──────────────────────────────────────────────────────────────
# 4. LITHIUM BATTERY IMPORT NOTICE
# ──────────────────────────────────────────────────────────────
def gen_battery_notice():
    path = os.path.join(OUT_DIR, "lithium-battery-import-notice.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story += [
        Paragraph("ATCA CUSTOMS AUTHORITY", HEADER),
        Paragraph("OFFICIAL IMPORT NOTICE", SUBHEAD),
        Paragraph("NOTICE NO.: ATCA/BATT/2026/N01", CENTER),
        Paragraph("SUBJECT: Mandatory Compliance Requirements for Lithium Cell and Battery Imports", CENTER),
        Paragraph("Effective Date: 1 March 2026 | Issued: 15 January 2026", CENTER),
        Spacer(1, 0.3*cm), rule(),
    ]

    story.append(Paragraph("1. Purpose", H2))
    story.append(Paragraph(
        "This Notice sets out updated compliance requirements for the importation of lithium cells, lithium "
        "batteries, and products containing lithium cells or batteries into ATCA territory, effective "
        "1 March 2026. It supersedes Import Notice ATCA/BATT/2024/N03 in its entirety. "
        "Non-compliance will result in refusal of release to free circulation and may attract civil penalties.", BODY))

    story.append(Paragraph("2. Scope", H2))
    story.append(Paragraph(
        "This Notice applies to all shipments containing one or more of the following:", BODY))
    for item in [
        "Lithium metal cells and batteries (HS 8506.50)",
        "Lithium-ion accumulators and battery packs (HS 8507.60)",
        "Portable electronic devices (smartphones, laptops, tablets, cameras) containing built-in lithium batteries",
        "Electric vehicle battery packs and modules (HS 8507.60)",
        "Electric bicycles and scooters with lithium battery systems (HS 8714.99 / 8711.60)",
        "Power tools with integrated lithium battery (HS 8467.xx)",
        "Lithium battery storage systems for renewable energy (HS 8507.60)",
    ]:
        story.append(Paragraph(f"• {item}", BODY))

    story.append(Paragraph("3. Mandatory Documentation Requirements", H2))
    story.append(Paragraph(
        "All shipments within the scope of this Notice must be accompanied by the following documentation "
        "at the time of import declaration:", BODY))

    story.append(Paragraph("3.1 UN 38.3 Test Summary", H3))
    story.append(Paragraph(
        "A UN 38.3 Test Summary confirming that the cells and batteries have successfully passed all applicable "
        "tests under the UN Manual of Tests and Criteria, Part III, Sub-section 38.3 (Transport of Dangerous "
        "Goods). The summary must identify: the manufacturer, cell/battery model, test laboratory, "
        "accreditation number, and date of testing. Test reports older than 3 years are not accepted unless "
        "accompanied by a declaration of no design change.", BODY))

    story.append(Paragraph("3.2 New for 2026 — Form BATT-2026 Declaration", H3))
    story.append(Paragraph(
        "From 1 March 2026, a completed Form BATT-2026 (downloadable from portal.atca.gov) must be submitted "
        "with every import declaration for goods within the scope of this Notice. The form requires:", BODY))
    items_b = [
        "Importer EORI number",
        "Consignment reference and bill of lading / airway bill number",
        "HS code (6-digit minimum)",
        "Cell chemistry (lithium-ion, lithium polymer, lithium iron phosphate, lithium metal, other)",
        "Nominal energy content per cell (Wh) and per battery/pack (Wh)",
        "State of charge at time of shipment (must be ≤ 30% of rated capacity for sea freight; ≤ 30% for air freight per IATA DGR)",
        "Quantity of cells per battery and batteries per consignment",
        "UN number and Packing Group (UN 3480, UN 3481, UN 3090, or UN 3091 as applicable)",
        "Name and address of manufacturer and country of origin of cells",
    ]
    for i in items_b:
        story.append(Paragraph(f"• {i}", BODY))

    story.append(Paragraph("3.3 Battery Safety Certificate (BSC)", H3))
    story.append(Paragraph(
        "Battery packs with a rated energy content of 100 Wh or more (per battery) must also carry a "
        "Battery Safety Certificate issued by a notified body accredited under ATCA Technical Regulation "
        "TR-2025/44. Acceptable standards: IEC 62133-2:2017 (portable), IEC 62619:2022 (industrial), "
        "UN ECE R100 (EV traction batteries). CE marking (or ATCA-CA equivalent) satisfies this requirement "
        "for batteries placed on the ATCA market through normal retail channels.", BODY))

    story.append(Paragraph("4. State of Charge (SoC) Requirements", H2))
    data_s = [
        ["Transport Mode", "Max SoC at Time of Shipment", "Basis"],
        ["Sea freight (container)", "≤ 30% rated capacity", "IMDG Code Amendment 41-22"],
        ["Air freight (IATA DGR)", "≤ 30% rated capacity", "IATA DGR 65th Edition, Section 3.9.2"],
        ["Road / rail (ADR/RID)", "No SoC limit (packaging rules apply)", "ADR 2025, SP 376"],
        ["EV battery packs (sea)", "≤ 30% SoC", "ATCA Circular BATT-2025/07"],
        ["EV battery packs (air)", "Not permitted unless special approval", "IATA DGR 65th Edition"],
    ]
    story.append(tbl(data_s, [3.5*cm, 5*cm, 7*cm]))

    story.append(Paragraph("5. Penalties for Non-Compliance", H2))
    story.append(Paragraph(
        "Failure to comply with the requirements of this Notice will result in the following consequences:", BODY))
    data_p = [
        ["Infringement", "Immediate action", "Civil penalty"],
        ["Missing UN 38.3 Test Summary", "Goods detained pending documentary compliance", "EUR 3,000 per consignment (REVISED — was EUR 1,000)"],
        ["SoC exceeds 30% (sea/air)", "Goods refused entry; carrier notified", "EUR 5,000 per consignment (REVISED — was EUR 2,500)"],
        ["Missing Form BATT-2026 (from 1 Mar 2026)", "Declaration rejected; re-submission required", "EUR 1,000 per consignment (REVISED — was EUR 500)"],
        ["Missing BSC for ≥ 100 Wh batteries", "Goods detained", "EUR 4,000 per consignment (REVISED — was EUR 1,500)"],
        ["Repeat infringement within 12 months", "Suspension of import privileges + criminal referral", "Up to EUR 100,000 (REVISED — was EUR 25,000)"],
    ]
    story.append(tbl(data_p, [4*cm, 4.5*cm, 5*cm]))

    story.append(Paragraph("6. Transitional Provisions", H2))
    story.append(Paragraph(
        "Shipments for which a transport contract was concluded before 1 January 2026 and which arrive "
        "at an ATCA border post no later than 28 February 2026 may be released under the requirements of "
        "ATCA/BATT/2024/N03 (the previous Notice). No extensions will be granted beyond 28 February 2026.", BODY))

    story.append(Paragraph("7. Further Information", H2))
    story.append(Paragraph(
        "Questions regarding this Notice should be addressed to the ATCA Dangerous Goods and Product Safety "
        "Unit by email at dg.imports@customs.atca.gov or by telephone on +999 (0)1 234 5678 during business "
        "hours (Monday to Friday, 09:00–17:00 ATCA time). Form BATT-2026 and additional guidance are "
        "available on the ATCA Trader Portal at portal.atca.gov/batteries.", BODY))

    story.append(Spacer(1, 0.5*cm))
    story.append(thin_rule())
    story.append(Paragraph(
        "Signed: Head of Product Safety and Dangerous Goods, ATCA Customs Authority | "
        "Notice ATCA/BATT/2026/N01 | Issued 15 January 2026 | Effective 1 March 2026", SMALL))

    doc.build(story)
    print(f"  ✓ {path}")


if __name__ == "__main__":
    print("Generating PDFs...")
    gen_tariff_schedule()
    gen_importer_handbook()
    gen_hs_guide()
    gen_battery_notice()
    print("Done.")
