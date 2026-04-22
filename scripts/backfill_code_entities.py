#!/usr/bin/env python
"""
scripts/backfill_code_entities.py

Zero-LLM backfill of customs / tariff codes from existing raw_documents
into the `entities` table.

Rationale:
  Change events only fire on v1 -> v2 diffs, and most tariff PDFs were
  ingested once. That means their HS/HTS codes never reach the
  significance LLM, so `entities.entity_type = 'code'` stays empty.

This script walks `raw_documents`, extracts tariff-code surface forms
with conservative regex patterns, runs them through the same
`app.services.entity_index.normalize` classifier, and upserts every
match that classifies as `code`. Each distinct (document, code) pair
bumps `mention_count` by 1.

Usage:
    python scripts/backfill_code_entities.py            # apply
    python scripts/backfill_code_entities.py --dry-run  # preview only
    python scripts/backfill_code_entities.py --limit 500
    python scripts/backfill_code_entities.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from sqlmodel import Session, select

from app.database import engine
from app.models import Entity, RawDocument
from app.services.entity_index import _upsert_entity, normalize


# ── Extractor patterns ──────────────────────────────────────────────────────
# Deliberately *conservative*: dotted 4+2+2(+2) is very unlikely to be a
# software version or OJ reference. We skip bare HS6 (NN.NN) and bare 6–10
# digit patterns because they match too many false positives in free text
# (page numbers, phone fragments, timestamps, OJ C-series numbers…).

_EXTRACTORS: list[tuple[str, re.Pattern[str]]] = [
    # HS8 / HS10 dotted: 9401.61.4010 , 0304.29.00
    ("hs_dotted", re.compile(r"\b\d{4}\.\d{2}\.\d{2,4}\b")),
    # Prefixed: "HTS 9401.61", "HTSUS 0304.29.00",
    # "Schedule B 0405.20.3000", "HS code 3506"
    ("prefixed", re.compile(
        r"\b(?:hts(?:us)?|hs(?:\s*codes?)?|schedule\s*b)\s+\d{4}(?:\.\d{2,4}){0,2}\b",
        re.IGNORECASE,
    )),
    # PDF extraction artefact: "HScode3814.00" (whitespace stripped)
    ("squashed", re.compile(
        r"\bhs\s?codes?\s?\d{4}(?:\.\d{2,4}){0,2}\b",
        re.IGNORECASE,
    )),
]


def _iter_candidates(text: str) -> Iterable[tuple[str, str]]:
    """Yield (pattern_name, surface) candidates from a document body."""
    if not text:
        return
    for name, pat in _EXTRACTORS:
        for m in pat.finditer(text):
            surface = m.group(0).strip()
            if surface:
                yield name, surface


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan and report, but don't write to the DB.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only scan N documents (useful for smoke testing).")
    ap.add_argument("--verbose", action="store_true",
                    help="Print every distinct code extracted per document.")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)

    docs_scanned = 0
    docs_with_code = 0
    total_mentions = 0
    pattern_hits: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    upserts = 0

    with Session(engine) as session:
        q = select(RawDocument.id, RawDocument.source_url, RawDocument.raw_text)
        if args.limit:
            q = q.limit(args.limit)

        # Streaming-ish: fetch all ids first, then process one at a time to
        # avoid loading 5k full PDFs into memory.
        rows = session.exec(q).all()

        for doc_id, url, text in rows:
            docs_scanned += 1
            if not text:
                continue

            seen_in_doc: dict[str, str] = {}  # canonical_key -> display_name
            seen_types: dict[str, str] = {}   # canonical_key -> entity_type

            for pattern_name, surface in _iter_candidates(text):
                norm = normalize(surface)
                if norm is None:
                    continue
                canonical_key, display_name, etype = norm
                if etype != "code":
                    continue
                if canonical_key in seen_in_doc:
                    continue  # one bump per (doc, code), not per occurrence
                seen_in_doc[canonical_key] = display_name
                seen_types[canonical_key] = etype
                pattern_hits[pattern_name] += 1

            if not seen_in_doc:
                continue

            docs_with_code += 1
            total_mentions += len(seen_in_doc)

            if args.verbose:
                head = url[:72] + ("…" if len(url) > 72 else "")
                codes = ", ".join(sorted(seen_in_doc.values())[:8])
                extra = f" +{len(seen_in_doc) - 8}" if len(seen_in_doc) > 8 else ""
                print(f"  [{len(seen_in_doc):>2}] {head}")
                print(f"        {codes}{extra}")

            for canonical_key, display_name in seen_in_doc.items():
                code_counts[canonical_key] += 1
                if args.dry_run:
                    continue
                _upsert_entity(
                    session=session,
                    canonical_key=canonical_key,
                    display_name=display_name,
                    entity_type=seen_types[canonical_key],
                    now=now,
                )
                upserts += 1

            if not args.dry_run and docs_with_code % 50 == 0:
                session.commit()

        if not args.dry_run:
            session.commit()

    # ── Report ─────────────────────────────────────────────────────────────
    print()
    print("── Backfill summary " + "─" * 40)
    print(f"  docs scanned       : {docs_scanned:>7}")
    print(f"  docs with ≥1 code  : {docs_with_code:>7}")
    print(f"  total (doc, code)  : {total_mentions:>7}")
    print(f"  distinct codes     : {len(code_counts):>7}")
    if not args.dry_run:
        print(f"  upserts performed  : {upserts:>7}")
    else:
        print("  [dry-run] no DB writes performed")

    print()
    print("── Pattern hit counts ")
    for name, c in pattern_hits.most_common():
        print(f"  {name:<12} {c:>6}")

    print()
    print("── Top 15 codes by # of documents mentioning them ")
    for code, n in code_counts.most_common(15):
        print(f"  {n:>4}   {code}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
