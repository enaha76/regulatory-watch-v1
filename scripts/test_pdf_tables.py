#!/usr/bin/env python3
"""
TEST-2.2 — PDF Extraction with Tables (smoke test)

Runs PDFConnector against a known regulatory PDF that contains tables
and asserts that table cells are preserved as separately-rendered lines
instead of being merged into a single text run.

This is the canonical acceptance check for T2.3 (M2 milestone).

Usage
-----
    # Recommended — runs inside the API container where all deps
    # (pdfplumber, httpx, langdetect, …) are already installed:
    docker compose exec api python scripts/test_pdf_tables.py

    # Or against a specific URL:
    docker compose exec api python scripts/test_pdf_tables.py \\
        --url https://www.fda.gov/media/123456/download

    # Host-local execution works too, but requires `pip install -r
    # requirements.txt` on the host first.

Exit codes
----------
    0 — pass (tables present, cells not merged)
    1 — fail (extraction worked but tables were not preserved)
    2 — error (PDF couldn't be fetched or parsed at all)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# Allow running from anywhere (e.g. `python3 scripts/test_pdf_tables.py`
# from the host shell) by making the project root importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.ingestion.pdf_connector import PDFConnector  # noqa: E402


# A short, public, table-heavy regulatory PDF.
# IRS Form 1040 is reliably available, small, and contains form fields
# and tables that let us verify cells end up on separate lines.
DEFAULT_URL = "https://www.irs.gov/pub/irs-pdf/f1040.pdf"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


def check_tables_preserved(raw_text: str) -> List[Result]:
    """Run the TEST-2.2 assertions on extracted text."""
    checks: List[Result] = []

    checks.append(Result(
        name="non-empty",
        ok=len(raw_text) >= 500,
        detail=f"{len(raw_text)} chars extracted",
    ))

    # Our PDFConnector wraps extracted tables between explicit markers.
    # The presence of these markers is strong evidence that pdfplumber
    # (or Docling) actually detected at least one table on the page.
    has_table_markers = "--- TABLE ---" in raw_text and "--- END TABLE ---" in raw_text
    checks.append(Result(
        name="table_markers_present",
        ok=has_table_markers,
        detail="--- TABLE --- / --- END TABLE --- blocks found"
        if has_table_markers else
        "no table blocks detected (PDF may contain no tables)",
    ))

    # If we found tables, verify their cells are rendered on separate
    # lines (not merged). Grab one table block and count lines.
    if has_table_markers:
        start = raw_text.index("--- TABLE ---") + len("--- TABLE ---")
        end = raw_text.index("--- END TABLE ---")
        table_block = raw_text[start:end].strip()
        lines = [ln for ln in table_block.splitlines() if ln.strip()]

        # A single-line "table" would mean cells were merged — exactly
        # the anti-pattern TEST-2.2 guards against.
        checks.append(Result(
            name="table_cells_separated",
            ok=len(lines) >= 2,
            detail=f"first table has {len(lines)} rendered rows",
        ))

    return checks


def run(url: str) -> Tuple[int, List[Result]]:
    try:
        connector = PDFConnector(source=url, title="PDF Tables Smoke Test")
        docs = asyncio.run(connector.fetch())
    except Exception as exc:
        return 2, [Result("fetch", ok=False, detail=f"exception: {exc!r}")]

    if not docs:
        return 2, [Result("fetch", ok=False, detail="PDFConnector returned 0 documents")]

    checks = check_tables_preserved(docs[0].raw_text or "")
    if all(c.ok for c in checks):
        return 0, checks
    return 1, checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--url", default=DEFAULT_URL,
        help=f"PDF URL to test (default: {DEFAULT_URL})",
    )
    args = parser.parse_args()

    print(f"TEST-2.2 — PDF Tables")
    print(f"Source: {args.url}")
    print("-" * 60)

    exit_code, checks = run(args.url)
    for c in checks:
        marker = "PASS" if c.ok else "FAIL"
        print(f"  [{marker}] {c.name}: {c.detail}")

    print("-" * 60)
    if exit_code == 0:
        print("TEST-2.2 PASSED")
    elif exit_code == 1:
        print("TEST-2.2 FAILED — see failing checks above")
    else:
        print("TEST-2.2 ERRORED — extraction could not run")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
