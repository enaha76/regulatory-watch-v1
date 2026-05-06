"""One-shot backfill: produce a headline for every scored ChangeEvent
that doesn't already have one.

Why a separate script:
  - Existing rows were scored before migration 019 added the field, so
    they're stuck with whatever derive_title infers from the summary.
  - The full re-score path is overkill (and re-spends scoring tokens we
    already paid for). This script only generates the missing field
    from the already-stored summary + topic + affected_entities, so it
    runs at <10% of the cost of a re-score.

Usage (inside the api or worker container):
    python -m scripts.backfill_headlines [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional
from uuid import UUID

from openai import OpenAI
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.logging_setup import get_logger
from app.models import ChangeEvent
from app.services import llm_usage

log = get_logger(__name__)


SYSTEM = (
    "You write short, newspaper-style headlines for regulatory change "
    "alerts. Each headline IDENTIFIES the change at a glance for a "
    "compliance officer scanning an inbox.\n\n"
    "Rules:\n"
    "- 6 to 12 words, max 120 characters.\n"
    "- Lead with the actor when known: 'ATF:', 'CBP:', 'EU Commission:', "
    "'India DGFT:'.\n"
    "- State the action as a verb noun phrase: 'Cut', 'Reduce', 'Add', "
    "'Extend', 'Remove', 'Open Comment Period'.\n"
    "- Quote the most important number when there is one: 'PRC "
    "Anti-Dumping Rate Cut: 194% → 82%'.\n"
    "- Sentence-style title case (not ALL CAPS, not lowercase).\n"
    "- NEVER start with 'You must', 'You need', 'You should', 'It is "
    "important', 'The document', 'This rule'.\n"
    "- NEVER paste a URL or filename.\n"
    "- NEVER end with '...' or '…'. If 12 words isn't enough, drop the "
    "least essential word — do not truncate.\n\n"
    "Reply with JSON: {\"headline\": \"<headline>\"}. No prose, no "
    "markdown fences."
)


def _build_prompt(event: ChangeEvent) -> str:
    lines = [
        f"Topic: {event.topic or 'unknown'}",
    ]
    if event.affected_entities:
        ent = ", ".join(str(e) for e in event.affected_entities[:6])
        lines.append(f"Entities: {ent}")
    if event.origin_countries:
        lines.append(f"Origin: {', '.join(event.origin_countries)}")
    if event.destination_countries:
        lines.append(f"Destination: {', '.join(event.destination_countries)}")
    lines.append("")
    lines.append("Compliance summary:")
    lines.append(event.summary or "(no summary)")
    return "\n".join(lines)


def _generate_headline(client: OpenAI, model: str, event: ChangeEvent) -> Optional[str]:
    user = _build_prompt(event)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=120,
        )
    except Exception as exc:
        log.warning("headline_llm_call_failed", event_id=str(event.id), error=str(exc))
        return None

    elapsed_ms = int((time.time() - t0) * 1000)
    usage_obj = getattr(resp, "usage", None)
    usage_dict = (
        usage_obj.model_dump() if hasattr(usage_obj, "model_dump")
        else (dict(usage_obj) if usage_obj else None)
    )
    llm_usage.record(
        scope="headline_backfill",
        model=model,
        usage=usage_dict,
        latency_ms=elapsed_ms,
        request_hash="headline-bf",
        event_id=str(event.id),
    )

    try:
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        h = (data.get("headline") or "").strip()
    except Exception as exc:
        log.warning("headline_parse_failed", event_id=str(event.id), error=str(exc))
        return None

    if not h:
        return None
    # Sanity strip — clip if model went over.
    return h[:160]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    s = get_settings()
    if not s.OPENAI_API_KEY:
        print("OPENAI_API_KEY missing — cannot backfill", file=sys.stderr)
        return 1
    client = OpenAI(api_key=s.OPENAI_API_KEY)
    model = getattr(s, "OPENAI_MODEL", None) or "gpt-4o-mini"

    with Session(engine) as session:
        # Only backfill events that actually produce an inbox row.
        # Cosmetic / typo events score 0.0 and never generate alerts —
        # paying to title them would be wasted spend.
        rows = session.exec(
            select(ChangeEvent)
            .where(ChangeEvent.summary.is_not(None))  # type: ignore[union-attr]
            .where(ChangeEvent.headline.is_(None))    # type: ignore[union-attr]
            .where(ChangeEvent.scored_at.is_not(None))  # type: ignore[union-attr]
            .where(ChangeEvent.significance_score >= 0.3)  # type: ignore[union-attr]
            .order_by(ChangeEvent.scored_at.desc())
            .limit(args.limit)
        ).all()

        print(f"Found {len(rows)} events needing a headline")
        for i, ev in enumerate(rows, 1):
            preview = (ev.summary or "")[:80].replace("\n", " ")
            print(f"  [{i}/{len(rows)}] {str(ev.id)[:8]}  {preview}…")
            if args.dry_run:
                continue
            h = _generate_headline(client, model, ev)
            if h is None:
                continue
            print(f"      → {h}")
            ev.headline = h
            session.add(ev)
            session.commit()

    print("Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
