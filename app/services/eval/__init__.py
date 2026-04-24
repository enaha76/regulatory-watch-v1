"""
M3 significance-scoring eval harness.

The harness re-runs the production LLM scorer against a hand-curated
set of "golden" events and reports where the model's output diverges
from the expected judgement. It is the only thing that lets you
change a prompt, upgrade a model, or tune a truncation budget *with
confidence* — otherwise you're shipping blind.

Design choices worth knowing:

* Zero DB. The runner calls ``_build_user_prompt`` + ``_call_llm`` +
  ``SignificanceOutput`` directly. No events are inserted; no tables
  are touched. Runs safely in CI without Postgres.

* Real API calls. The whole point is to exercise the live model +
  live prompt + live parser. If you want faster or offline runs, mock
  at the ``_call_llm`` boundary.

* Tolerance ranges, not exact matches. Scoring with LLMs is naturally
  non-deterministic within a small band; each golden entry specifies
  ``{min, max}`` for the expected score. Classification fields
  (change_type, topic, trade_flow_direction) use exact match.

* Cost is real. Every run bills the OpenAI account and appends to
  ``artifacts/llm_usage/llm_usage.jsonl`` exactly like production
  scoring calls. Ledger entries are distinguishable by the
  ``event_id`` field, which the runner sets to the golden entry's
  stable human-readable id ("cbp_tariff_hike_2024" etc.).

Public API
----------
``run_eval(golden_path: Path, model: str | None = None) -> EvalRun``
    Load the golden JSONL at ``golden_path``, score each entry, return
    an aggregated run report.

``evaluate_entry(entry, model, api_key) -> EntryResult``
    Run one entry. Exposed mostly for tests + ad-hoc debugging.
"""

from app.services.eval.runner import evaluate_entry, load_golden, run_eval
from app.services.eval.schema import (
    EntryResult,
    EvalRun,
    ExpectedOutput,
    GoldenEntry,
    ScoreRange,
)

__all__ = [
    "run_eval",
    "evaluate_entry",
    "load_golden",
    "GoldenEntry",
    "ExpectedOutput",
    "ScoreRange",
    "EntryResult",
    "EvalRun",
]
