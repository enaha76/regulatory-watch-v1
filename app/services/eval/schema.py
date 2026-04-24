"""
Eval schema — Pydantic models for golden entries, per-entry results,
and aggregate run reports.

A GoldenEntry is the input (one hand-labeled test case). An
EntryResult is the output of running one entry through the scorer.
An EvalRun wraps a set of EntryResults with aggregate metrics and
is what gets serialized to disk.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


DiffKind = Literal["created", "modified"]
ChangeType = Literal[
    "typo_or_cosmetic",
    "minor_wording",
    "clarification",
    "substantive",
    "critical",
]


class ScoreRange(BaseModel):
    """Inclusive tolerance range for numeric expectations."""
    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "ScoreRange":
        if self.min > self.max:
            raise ValueError("ScoreRange.min must be <= max")
        return self

    def contains(self, v: float) -> bool:
        return self.min <= v <= self.max

    def midpoint(self) -> float:
        return (self.min + self.max) / 2


class ExpectedOutput(BaseModel):
    """Hand-labeled expectations for one golden entry.

    The runner compares the LLM's output against these. A field left
    at ``None`` means "don't care" — useful for entries where you
    only want to lock down (say) the topic.
    """
    significance_score: ScoreRange
    change_type: ChangeType
    topic: str  # rubric values live in significance.TOPICS
    # Required ISO-2 codes that MUST appear in the actual output.
    # Additional codes are allowed (the LLM may find more than you
    # thought to label).
    origin_countries: Optional[list[str]] = None
    trade_flow_direction: Optional[Literal[
        "inbound", "outbound", "bilateral", "global",
    ]] = None
    # Whether the event SHOULD pass the OBLIGATIONS_SCORE_GATE —
    # a coarser but important check than the exact score.
    should_trigger_obligations: Optional[bool] = None


class GoldenEntry(BaseModel):
    """One hand-labeled test case for the M3 scorer."""
    id: str = Field(..., min_length=1, max_length=64,
                    description="Stable human-readable id; appears in cost ledger.")
    description: str = Field(default="", max_length=500)
    # Production prompt inputs.
    source_url: str
    title: Optional[str] = None
    diff_kind: DiffKind
    unified_diff: Optional[str] = None
    content: Optional[str] = None
    added_chars: int = 0
    removed_chars: int = 0
    # Ground truth.
    expected: ExpectedOutput


class EntryResult(BaseModel):
    """Outcome of evaluating a single GoldenEntry."""
    entry_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    actual: dict[str, Any]
    expected: ExpectedOutput
    latency_ms: int
    request_hash: Optional[str] = None


class EvalRun(BaseModel):
    """Aggregated run report, written to ``artifacts/eval/eval_*.json``."""
    started_at: str
    model: str
    n_entries: int
    n_passed: int
    pass_rate: float
    # Score quality — mean absolute error between the LLM's score and
    # the midpoint of the expected range.
    score_mae: float
    # Classification accuracy — fraction of entries where the
    # categorical field matched.
    change_type_accuracy: float
    topic_accuracy: float
    # Gate accuracy — fraction of entries where the
    # pass/fail-the-obligations-gate decision was right (only
    # computed over entries that labeled this field).
    gate_accuracy: Optional[float] = None
    total_latency_ms: int
    results: list[EntryResult]
