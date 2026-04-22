"""Tests for obligation deadline parsing + Pydantic validation."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.obligations import (
    ObligationItem,
    ObligationOutput,
    _parse_deadline,
)


class TestDeadlineParsing:
    @pytest.mark.parametrize("text,expected", [
        ("2026-06-30", date(2026, 6, 30)),
        ("Effective by 2026-12-31.", date(2026, 12, 31)),
        ("30 June 2026", date(2026, 6, 30)),
        ("June 30, 2026", date(2026, 6, 30)),
        ("By December 1, 2026", date(2026, 12, 1)),
        ("file before 1 January 2027", date(2027, 1, 1)),
    ])
    def test_known_formats_parse(self, text, expected):
        assert _parse_deadline(text) == expected

    @pytest.mark.parametrize("text", [
        None, "", "next quarter", "Q3 2026", "as soon as practicable",
        "no later than the end of the fiscal year",
    ])
    def test_unparseable_returns_none(self, text):
        assert _parse_deadline(text) is None

    def test_invalid_date_does_not_crash(self):
        assert _parse_deadline("February 30, 2026") is None
        assert _parse_deadline("2026-13-40") is None


class TestObligationItemValidation:
    def test_minimum_valid(self):
        item = ObligationItem(actor="banks", action="file Form 8-K")
        assert item.obligation_type == "other"

    def test_unknown_obligation_type_falls_back_to_other(self):
        item = ObligationItem(actor="x", action="y", obligation_type="invented_type")
        assert item.obligation_type == "other"

    def test_known_obligation_types_preserved(self):
        for t in ("reporting", "prohibition", "threshold", "disclosure",
                  "registration", "penalty"):
            item = ObligationItem(actor="x", action="y", obligation_type=t)
            assert item.obligation_type == t

    def test_empty_actor_rejected(self):
        with pytest.raises(Exception):
            ObligationItem(actor="", action="something")

    def test_empty_obligations_list_is_valid(self):
        out = ObligationOutput(obligations=[])
        assert out.obligations == []
