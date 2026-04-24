"""
Eval runner — orchestrates loading the golden set, calling the LLM
through the production prompt + parser, and aggregating results.

The runner reuses the SAME functions the Celery scoring task uses
(``_build_user_prompt``, ``_call_llm``, ``SignificanceOutput``) so
there is zero drift between what production scores and what eval
measures. The only difference: the eval path never touches the DB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.config import get_settings
from app.logging_setup import get_logger
from app.services.eval.metrics import iso_set_contains_all, mean_absolute_error
from app.services.eval.schema import (
    EntryResult,
    EvalRun,
    GoldenEntry,
)

logger = get_logger(__name__)


# ── Golden set loading ───────────────────────────────────────────────────────

def load_golden(path: Path) -> list[GoldenEntry]:
    """Load JSONL golden entries from disk.

    Blank lines and lines starting with ``#`` are skipped so humans
    can leave comments in the file during curation.
    """
    entries: list[GoldenEntry] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entries.append(GoldenEntry.model_validate_json(line))
            except ValidationError as exc:
                raise ValueError(
                    f"{path}:{lineno}: invalid golden entry: {exc}"
                ) from exc
    return entries


# ── Per-entry evaluation ─────────────────────────────────────────────────────

def evaluate_entry(
    entry: GoldenEntry,
    *,
    model: str,
    api_key: str,
) -> EntryResult:
    """
    Run the LLM scorer on one entry and compare to expected.

    Uses the production prompt + parser via lazy-imports of
    ``app.services.significance`` so this module is cheap to import
    without pulling the whole scoring stack.
    """
    # Lazy imports so `from app.services.eval import run_eval` doesn't
    # drag in httpx / pydantic-heavy modules until you actually run.
    from app.services.significance import (
        _SYSTEM_PROMPT,
        _build_user_prompt,
        _call_llm,
        SignificanceOutput,
    )

    user_prompt = _build_user_prompt(
        source_url=entry.source_url,
        title=entry.title,
        diff_kind=entry.diff_kind,
        added_chars=entry.added_chars,
        removed_chars=entry.removed_chars,
        unified_diff=entry.unified_diff,
        new_content=entry.content,
        # For modified entries, reuse the content field as context.
        context_snippet=(
            entry.content if entry.diff_kind == "modified" else None
        ),
    )

    try:
        raw, latency_ms, request_hash = _call_llm(
            _SYSTEM_PROMPT, user_prompt,
            model=model, api_key=api_key,
            event_id=f"eval:{entry.id}",  # tag for ledger filtering
        )
    except Exception as exc:  # noqa: BLE001 — HTTP/DNS/timeout all surface here
        return EntryResult(
            entry_id=entry.id,
            passed=False,
            failures=[f"llm_error: {exc.__class__.__name__}: {exc}"],
            actual={},
            expected=entry.expected,
            latency_ms=0,
            request_hash=None,
        )

    try:
        data = json.loads(raw)
        parsed = SignificanceOutput(**data)
    except (json.JSONDecodeError, ValidationError) as exc:
        return EntryResult(
            entry_id=entry.id,
            passed=False,
            failures=[f"parse_error: {exc.__class__.__name__}: {exc}"],
            actual={"raw_response": raw[:500]},
            expected=entry.expected,
            latency_ms=latency_ms,
            request_hash=request_hash,
        )

    # ── Compare ──────────────────────────────────────────────────────
    exp = entry.expected
    failures: list[str] = []

    if not exp.significance_score.contains(parsed.significance_score):
        failures.append(
            f"score {parsed.significance_score:.2f} not in "
            f"[{exp.significance_score.min:.2f}, {exp.significance_score.max:.2f}]"
        )

    if parsed.change_type != exp.change_type:
        failures.append(
            f"change_type={parsed.change_type!r} expected {exp.change_type!r}"
        )

    if parsed.topic != exp.topic:
        failures.append(f"topic={parsed.topic!r} expected {exp.topic!r}")

    if exp.origin_countries is not None:
        if not iso_set_contains_all(parsed.origin_countries, exp.origin_countries):
            failures.append(
                f"origin_countries={parsed.origin_countries} "
                f"missing one of {exp.origin_countries}"
            )

    if exp.trade_flow_direction is not None:
        if parsed.trade_flow_direction != exp.trade_flow_direction:
            failures.append(
                f"trade_flow_direction={parsed.trade_flow_direction!r} "
                f"expected {exp.trade_flow_direction!r}"
            )

    if exp.should_trigger_obligations is not None:
        gate = get_settings().OBLIGATIONS_SCORE_GATE
        actual_triggers = parsed.significance_score >= gate
        if actual_triggers != exp.should_trigger_obligations:
            failures.append(
                f"obligations_gate: expected triggers="
                f"{exp.should_trigger_obligations}, got {actual_triggers} "
                f"(score={parsed.significance_score:.2f}, gate={gate})"
            )

    return EntryResult(
        entry_id=entry.id,
        passed=len(failures) == 0,
        failures=failures,
        actual=parsed.model_dump(),
        expected=exp,
        latency_ms=latency_ms,
        request_hash=request_hash,
    )


# ── Full run ─────────────────────────────────────────────────────────────────

def run_eval(
    golden_path: Path,
    *,
    model: Optional[str] = None,
) -> EvalRun:
    """
    Execute the full eval against the golden set at ``golden_path``.

    Returns an :class:`EvalRun` with aggregate metrics and per-entry
    results. Raises ``RuntimeError`` if OPENAI_API_KEY is missing.
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY not configured — cannot run the eval harness."
        )

    use_model = model or settings.OPENAI_MODEL
    entries = load_golden(golden_path)
    if not entries:
        raise ValueError(f"No golden entries found in {golden_path}")

    logger.info("eval_run_starting",
                model=use_model, n_entries=len(entries),
                golden_path=str(golden_path))

    started = datetime.now(timezone.utc)
    results: list[EntryResult] = []
    for entry in entries:
        try:
            r = evaluate_entry(
                entry, model=use_model, api_key=settings.OPENAI_API_KEY,
            )
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            r = EntryResult(
                entry_id=entry.id,
                passed=False,
                failures=[f"runtime_error: {type(exc).__name__}: {exc}"],
                actual={},
                expected=entry.expected,
                latency_ms=0,
                request_hash=None,
            )
        results.append(r)

    # ── Aggregate ────────────────────────────────────────────────────
    n_passed = sum(1 for r in results if r.passed)
    score_errors: list[float] = []
    change_type_correct = 0
    topic_correct = 0
    gate_total = 0
    gate_correct = 0
    gate_threshold = settings.OBLIGATIONS_SCORE_GATE

    for r in results:
        actual_score = r.actual.get("significance_score")
        if isinstance(actual_score, (int, float)):
            score_errors.append(
                abs(actual_score - r.expected.significance_score.midpoint())
            )
        if r.actual.get("change_type") == r.expected.change_type:
            change_type_correct += 1
        if r.actual.get("topic") == r.expected.topic:
            topic_correct += 1
        if r.expected.should_trigger_obligations is not None:
            gate_total += 1
            if isinstance(actual_score, (int, float)):
                if (actual_score >= gate_threshold) == r.expected.should_trigger_obligations:
                    gate_correct += 1

    run = EvalRun(
        started_at=started.isoformat(),
        model=use_model,
        n_entries=len(entries),
        n_passed=n_passed,
        pass_rate=n_passed / len(entries),
        score_mae=mean_absolute_error(score_errors),
        change_type_accuracy=change_type_correct / len(entries),
        topic_accuracy=topic_correct / len(entries),
        gate_accuracy=(
            gate_correct / gate_total if gate_total else None
        ),
        total_latency_ms=sum(r.latency_ms for r in results),
        results=results,
    )

    logger.info("eval_run_done",
                model=use_model,
                pass_rate=run.pass_rate,
                score_mae=run.score_mae,
                change_type_accuracy=run.change_type_accuracy,
                topic_accuracy=run.topic_accuracy)
    return run
