"""
CLI entrypoint for the M3 significance eval harness.

Usage
-----
    # Default: eval/golden/significance.jsonl, OPENAI_MODEL from env
    python scripts/run_eval.py

    # Override model (useful for comparing 4o-mini vs 4.1-mini)
    python scripts/run_eval.py --model gpt-4.1-mini

    # Point at a different golden file
    python scripts/run_eval.py --golden eval/golden/custom.jsonl

Output
------
* Prints a summary + every failing entry's diff to stdout.
* Writes a full JSON report to ``artifacts/eval/eval_<ISO>.json`` so
  you can diff this run against prior runs (regression catch).
* Exits with code 1 if any entry failed, 0 otherwise — CI-friendly.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `app` importable when run from the repo root without pip-install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.eval import run_eval  # noqa: E402


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _print_summary(run) -> None:
    print()
    print("═" * 72)
    print(f"  Eval Run — {run.started_at}")
    print(f"  Model: {run.model}")
    print("─" * 72)
    print(f"  Entries         : {run.n_entries}")
    print(f"  Passed          : {run.n_passed} / {run.n_entries}  "
          f"({_fmt_pct(run.pass_rate)})")
    print(f"  Score MAE       : {run.score_mae:.3f}")
    print(f"  Change-type acc.: {_fmt_pct(run.change_type_accuracy)}")
    print(f"  Topic accuracy  : {_fmt_pct(run.topic_accuracy)}")
    if run.gate_accuracy is not None:
        print(f"  Obligation gate : {_fmt_pct(run.gate_accuracy)}")
    print(f"  Total latency   : {run.total_latency_ms} ms")
    print("═" * 72)

    failures = [r for r in run.results if not r.passed]
    if not failures:
        print("  ✓ all entries passed")
        return

    print(f"  ✗ {len(failures)} failing entr{'y' if len(failures) == 1 else 'ies'}:")
    for r in failures:
        print(f"\n  ── {r.entry_id}")
        for f in r.failures:
            print(f"     - {f}")
        actual_score = r.actual.get("significance_score")
        actual_type = r.actual.get("change_type")
        actual_topic = r.actual.get("topic")
        if actual_score is not None or actual_type or actual_topic:
            print(f"     actual: score={actual_score} "
                  f"type={actual_type!r} topic={actual_topic!r}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the M3 significance eval harness.",
    )
    p.add_argument(
        "--golden",
        type=Path,
        default=_REPO_ROOT / "eval" / "golden" / "significance.jsonl",
        help="Path to the golden JSONL dataset.",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override OPENAI_MODEL for this run (e.g. gpt-4.1-mini).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "eval",
        help="Directory where the JSON report is written.",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing a JSON report file (summary to stdout only).",
    )
    args = p.parse_args()

    try:
        run = run_eval(args.golden, model=args.model)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _print_summary(run)

    if not args.no_report:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        out = args.output_dir / f"eval_{ts}.json"
        out.write_text(
            json.dumps(run.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n  report → {out.relative_to(_REPO_ROOT)}")

    return 0 if run.n_passed == run.n_entries else 1


if __name__ == "__main__":
    sys.exit(main())
