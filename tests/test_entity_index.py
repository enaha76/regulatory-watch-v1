"""Tests for entity normalization + type inference."""

from __future__ import annotations

import pytest

from app.services.entity_index import normalize


class TestAcronymExpansion:
    def test_known_acronym_expands_and_typed_agency(self):
        result = normalize("FCA")
        assert result is not None
        canonical, display, etype = result
        assert canonical == "financial conduct authority"
        assert display == "Financial Conduct Authority"
        assert etype == "agency"

    def test_acronym_expansion_is_case_insensitive(self):
        a = normalize("fca")
        b = normalize("FCA")
        assert a == b


class TestTypeInferenceAgency:
    @pytest.mark.parametrize("name", [
        "U.S. Customs and Border Protection",
        "European Securities and Markets Authority",
        "Federal Trade Commission",
        "Office of the Comptroller of the Currency",
        "Department of Labor",
        "Bureau of Industry and Security",
        "Ministry of Finance",
    ])
    def test_full_agency_name_resolves_to_agency(self, name):
        result = normalize(name)
        assert result is not None
        _, _, etype = result
        assert etype == "agency", f"{name!r} got {etype}, expected 'agency'"


class TestTypeInferenceRegulation:
    @pytest.mark.parametrize("name", [
        "19 CFR 149",
        "12 USC 1841",
        "EU 2016/679",
        "GDPR",
        "MiFID II",
        "Section 404",
        "Title 21",
    ])
    def test_regulation_patterns(self, name):
        result = normalize(name)
        assert result is not None
        _, _, etype = result
        assert etype == "regulation", f"{name!r} got {etype}"


class TestTypeInferenceCode:
    @pytest.mark.parametrize("name", [
        "HS code 8471",
        "HTS",
        "HTSUS",
        "Schedule B",
        "NAICS",
        "1234567",  # bare numeric
    ])
    def test_code_patterns(self, name):
        result = normalize(name)
        assert result is not None
        _, _, etype = result
        assert etype == "code"

    @pytest.mark.parametrize("name", [
        "0304.29.00",       # HS8
        "0405.20.3000",     # HS10
        "9401.61.4010",     # HS10
        "0511.91.90",       # HS8
    ])
    def test_dotted_hs_codes_are_code(self, name):
        result = normalize(name)
        assert result is not None, f"{name!r} should normalize"
        _, _, etype = result
        assert etype == "code", f"{name!r} got {etype}, expected 'code'"

    @pytest.mark.parametrize("name", [
        "HTS 9401.61",
        "HTSUS 0304.29.00",
        "Schedule B 0405.20.3000",
        "HS 3506",
    ])
    def test_classifier_prefixed_codes(self, name):
        result = normalize(name)
        assert result is not None
        _, _, etype = result
        assert etype == "code", f"{name!r} got {etype}, expected 'code'"

    @pytest.mark.parametrize("name", [
        "Heading 39.09",
        "heading 35.06",
        "Chapter 69.07",
        "CHAPTER 84.71",
    ])
    def test_heading_and_chapter_patterns(self, name):
        result = normalize(name)
        assert result is not None
        _, _, etype = result
        assert etype == "code", f"{name!r} got {etype}, expected 'code'"

    def test_dotted_code_does_not_match_regulation(self):
        # Regulation patterns must not hijack pure dotted HS codes.
        _, _, etype = normalize("0304.29.00")
        assert etype == "code"


class TestNormalizationEdgeCases:
    def test_empty_returns_none(self):
        assert normalize("") is None
        assert normalize(" ") is None

    def test_too_short_returns_none(self):
        assert normalize("a") is None

    def test_truncates_pathological_long_string(self):
        long = "x" * 1000
        result = normalize(long)
        assert result is not None
        canonical, display, _ = result
        assert len(canonical) <= 255
        assert len(display) <= 255

    def test_canonical_key_is_lowercased_and_collapsed(self):
        result = normalize("  Some\t Random   Industry  ")
        assert result is not None
        canonical, display, _ = result
        assert canonical == "some random industry"
        # display preserves original (sans surrounding whitespace + collapsed inner)
        assert display == "Some Random Industry"

    def test_unknown_type_falls_back_to_other(self):
        result = normalize("zzzfoobar quux")
        assert result is not None
        _, _, etype = result
        assert etype == "other"
