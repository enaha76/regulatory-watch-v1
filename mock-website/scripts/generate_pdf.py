"""
JSON-driven PDF generator for the mock ATCA website.

Reads a regulation JSON file (matching data/schema.ts) and emits a single PDF
into mock_server/data/documents/<filename>.pdf.

Usage:
  python scripts/generate_pdf.py --input data/regulations/tariff-schedule-2026.json
  python scripts/generate_pdf.py --all
"""
import argparse
import json
import os
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "mock_server" / "data" / "documents"

styles = getSampleStyleSheet()


def _style(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)


HEADER = _style("Header", fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=6,
                textColor=colors.HexColor("#1a3a6b"), fontName="Helvetica-Bold")
SUBHEAD = _style("Subhead", fontSize=13, leading=16, alignment=TA_CENTER, spaceAfter=4,
                 textColor=colors.HexColor("#2c5f9e"), fontName="Helvetica-Bold")
H2 = _style("H2", fontSize=12, leading=15, spaceBefore=12, spaceAfter=4,
            textColor=colors.HexColor("#1a3a6b"), fontName="Helvetica-Bold")
H3 = _style("H3", fontSize=10, leading=13, spaceBefore=8, spaceAfter=3,
            textColor=colors.HexColor("#333333"), fontName="Helvetica-BoldOblique")
BODY = _style("Body", fontSize=9, leading=13, spaceAfter=4, alignment=TA_JUSTIFY)
SMALL = _style("Small", fontSize=8, leading=10, spaceAfter=2, textColor=colors.grey)
CENTER = _style("Center", fontSize=9, leading=13, alignment=TA_CENTER)
NOTE_CRIT = _style("NoteCrit", fontSize=9, leading=13, spaceAfter=4,
                   textColor=colors.HexColor("#991b1b"), fontName="Helvetica-Bold")
NOTE_INFO = _style("NoteInfo", fontSize=9, leading=13, spaceAfter=4,
                   textColor=colors.HexColor("#1a3a6b"))


def _rule():
    return HRFlowable(width="100%", thickness=1,
                      color=colors.HexColor("#2c5f9e"), spaceAfter=6)


def _thin_rule():
    return HRFlowable(width="100%", thickness=0.5,
                      color=colors.lightgrey, spaceAfter=4)


def _table(columns, rows):
    data = [columns] + rows
    n = len(columns)
    # Distribute width evenly
    avail = 16.0  # cm
    col_widths = [avail / n * cm] * n
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a6b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f0f4fa")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _render_section(section):
    t = section.get("type")
    if t == "heading":
        level = section.get("level", 2)
        style = {1: HEADER, 2: H2, 3: H3}.get(level, H2)
        return [Paragraph(section.get("text", ""), style)]
    if t == "paragraph":
        return [Paragraph(section.get("text", ""), BODY)]
    if t == "list":
        prefix = "•" if not section.get("ordered") else "{i}."
        items = section.get("items", [])
        return [
            Paragraph(
                f"{(prefix.format(i=i+1) if section.get('ordered') else prefix)} {item}",
                BODY,
            )
            for i, item in enumerate(items)
        ]
    if t == "table":
        return [_table(section.get("columns", []), section.get("rows", [])),
                Spacer(1, 0.3 * cm)]
    if t == "note":
        style = {
            "critical": NOTE_CRIT,
            "info": NOTE_INFO,
            "warning": NOTE_CRIT,
        }.get(section.get("style", "info"), NOTE_INFO)
        flowables = []
        if section.get("title"):
            flowables.append(Paragraph(f"<b>{section['title']}</b>", style))
        flowables.append(Paragraph(section.get("text", ""), style))
        flowables.append(Spacer(1, 0.2 * cm))
        return flowables
    return []


def render_pdf(doc_json, out_path):
    pdf = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    story = []

    title = (
        doc_json.get("pdf", {}).get("document_title")
        or doc_json.get("title", "")
    ).upper()
    story += [
        Paragraph("ATCA CUSTOMS AUTHORITY", HEADER),
        Paragraph(title, SUBHEAD),
    ]
    meta_parts = []
    if doc_json.get("effective_date"):
        meta_parts.append(f"Effective: {doc_json['effective_date']}")
    if doc_json.get("reference_number"):
        meta_parts.append(f"Ref: {doc_json['reference_number']}")
    if meta_parts:
        story.append(Paragraph(" | ".join(meta_parts), CENTER))
    story += [Spacer(1, 0.3 * cm), _rule()]

    if doc_json.get("summary"):
        story.append(Paragraph(doc_json["summary"], BODY))
        story.append(Spacer(1, 0.3 * cm))

    for section in doc_json.get("sections", []):
        story.extend(_render_section(section))

    story += [
        Spacer(1, 0.5 * cm),
        _thin_rule(),
        Paragraph(
            f"Issued by ATCA Customs Authority | {doc_json.get('reference_number', '')} | "
            f"Updated: {doc_json.get('updated_at', '')}",
            SMALL,
        ),
    ]

    pdf.build(story)


def find_json_files():
    out = []
    for sub in ("regulations", "notices", "guidance"):
        d = DATA_DIR / sub
        if d.is_dir():
            out.extend(sorted(d.glob("*.json")))
    return out


def generate_one(json_path):
    with open(json_path) as f:
        doc = json.load(f)
    pdf_cfg = doc.get("pdf") or {}
    if not pdf_cfg.get("enabled"):
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / pdf_cfg["filename"]
    render_pdf(doc, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Path to regulation JSON file")
    ap.add_argument("--all", action="store_true", help="Regenerate every PDF")
    args = ap.parse_args()

    targets = []
    if args.all:
        targets = find_json_files()
    elif args.input:
        targets = [Path(args.input)]
    else:
        ap.error("Pass --input <file> or --all")

    for path in targets:
        out = generate_one(path)
        if out:
            print(f"  ✓ {out}")
        else:
            print(f"  - {path.name} (no PDF configured)")


if __name__ == "__main__":
    main()
