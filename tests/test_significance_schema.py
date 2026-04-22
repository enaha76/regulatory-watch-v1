"""Tests for SignificanceOutput Pydantic schema + helpers (no LLM)."""

from __future__ import annotations

import pytest

from app.services.significance import (
    CHANGE_TYPES,
    TOPICS,
    SignificanceOutput,
    _build_user_prompt,
    _trim_content,
)


class TestSignificanceOutput:
    def test_minimum_valid_output(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            compliance_summary="No material change.",
        )
        assert out.topic == "other"
        assert out.affected_entities == []

    def test_unknown_change_type_rejected(self):
        with pytest.raises(Exception):
            SignificanceOutput(
                significance_score=0.5,
                change_type="not_real",
                compliance_summary="x",
            )

    def test_score_above_one_rejected(self):
        with pytest.raises(Exception):
            SignificanceOutput(
                significance_score=1.2,
                change_type="critical",
                compliance_summary="x",
            )

    def test_unknown_topic_collapses_to_other(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            topic="invented_topic",
            compliance_summary="x",
        )
        assert out.topic == "other"

    def test_known_topics_preserved(self):
        for t in TOPICS:
            out = SignificanceOutput(
                significance_score=0.5,
                change_type="clarification",
                topic=t,
                compliance_summary="x",
            )
            assert out.topic == t

    def test_affected_entities_dedup_and_cap(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            affected_entities=["FCA", "fca", " FCA  ", "EBA"] + ["x"] * 30,
            compliance_summary="x",
        )
        # FCA dedup'd; cap at 20
        assert len(out.affected_entities) <= 20
        lc = [e.lower() for e in out.affected_entities]
        assert lc.count("fca") == 1

    @pytest.mark.parametrize("value", [
        "inbound", "outbound", "bilateral", "global",
    ])
    def test_trade_flow_direction_known_values_kept(self, value):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            compliance_summary="x",
            trade_flow_direction=value,
        )
        assert out.trade_flow_direction == value

    def test_trade_flow_direction_unknown_value_becomes_none(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            compliance_summary="x",
            trade_flow_direction="diagonal",
        )
        assert out.trade_flow_direction is None

    def test_trade_flow_direction_case_insensitive(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            compliance_summary="x",
            trade_flow_direction="Inbound",
        )
        assert out.trade_flow_direction == "inbound"

    def test_origin_countries_default_empty(self):
        out = SignificanceOutput(
            significance_score=0.5,
            change_type="clarification",
            compliance_summary="x",
        )
        assert out.origin_countries == []


class TestTrimContent:
    def test_short_passes_through_unchanged(self):
        assert _trim_content("short text") == "short text"

    def test_long_content_truncated_with_marker(self):
        text = "X" * 20_000
        out = _trim_content(text)
        assert "truncated for scoring" in out
        assert len(out) < len(text)

    def test_empty_returns_empty(self):
        assert _trim_content("") == ""


class TestBuildUserPrompt:
    def test_created_event_prompt_includes_content(self):
        prompt = _build_user_prompt(
            source_url="https://x.com/y",
            title="Hello",
            diff_kind="created",
            added_chars=100,
            removed_chars=0,
            unified_diff=None,
            new_content="The quick brown fox.",
        )
        assert "https://x.com/y" in prompt
        assert "The quick brown fox." in prompt
        assert "Document content" in prompt

    def test_modified_event_prompt_includes_diff(self):
        prompt = _build_user_prompt(
            source_url="https://x.com/y",
            title="Hello",
            diff_kind="modified",
            added_chars=10,
            removed_chars=5,
            unified_diff="--- a\n+++ b\n@@\n-old\n+new",
            new_content=None,
        )
        assert "Unified diff" in prompt
        assert "+new" in prompt
        assert "Document content" not in prompt
