"""Unit tests for app.services.geo helpers."""
from __future__ import annotations

import pytest

from app.services.geo import (
    normalize_country_codes,
    resolve_destination_countries,
)


class TestResolveDestinationCountries:
    @pytest.mark.parametrize("url, expected", [
        ("https://www.cbp.gov/trade/rulings/ny-123456",            ["US"]),
        ("https://rulings.cbp.gov/foo",                            ["US"]),
        ("https://eur-lex.europa.eu/legal-content/EN/TXT/foo",     ["EU"]),
        ("https://ec.europa.eu/commission/presscorner/detail",     ["EU"]),
        ("https://trade.ec.europa.eu/doc/foo",                     ["EU"]),
        ("https://www.fca.org.uk/news/market-abuse",               ["GB"]),
        ("https://www.gov.uk/guidance/customs",                    ["GB"]),
        ("https://www.customs.gov.cn/bulletin",                    ["CN"]),
        ("https://www.gov.cn/xinwen/foo.htm",                      ["CN"]),
        ("https://finma.ch/en/news/foo",                           ["CH"]),
        ("https://www.canada.ca/en/revenue-agency",                ["CA"]),
    ])
    def test_known_hosts_map_correctly(self, url, expected):
        assert resolve_destination_countries(url) == expected

    def test_unknown_host_returns_empty(self):
        assert resolve_destination_countries("https://example.com/foo") == []

    @pytest.mark.parametrize("url", ["", None])
    def test_empty_inputs(self, url):
        assert resolve_destination_countries(url or "") == []

    def test_longest_suffix_wins(self):
        # .eu would match "eu" but ec.europa.eu should bind to EU via
        # the europa.eu rule, not the generic one.
        assert resolve_destination_countries("https://ec.europa.eu/x") == ["EU"]


class TestNormalizeCountryCodes:
    def test_full_names_map_to_iso2(self):
        assert normalize_country_codes(
            ["United States", "China", "European Union"]
        ) == ["US", "CN", "EU"]

    def test_already_iso2_is_preserved(self):
        assert normalize_country_codes(["US", "CN", "EU"]) == ["US", "CN", "EU"]

    def test_uk_normalised_to_gb(self):
        assert normalize_country_codes(["UK"]) == ["GB"]
        assert normalize_country_codes(["United Kingdom"]) == ["GB"]

    def test_unknown_strings_are_dropped(self):
        assert normalize_country_codes(["Narnia", "Atlantis"]) == []

    def test_mixed_known_and_unknown(self):
        assert normalize_country_codes(
            ["China", "???", "Japan", "Wakanda"]
        ) == ["CN", "JP"]

    def test_dedupe_preserves_first_order(self):
        assert normalize_country_codes(
            ["China", "CN", "china", "People's Republic of China"]
        ) == ["CN"]

    def test_empty_and_none_inputs(self):
        assert normalize_country_codes(None) == []
        assert normalize_country_codes([]) == []
        assert normalize_country_codes(["", "   ", None]) == []

    def test_caps_long_list(self):
        # Feed 30 distinct names, expect ≤ 12 kept.
        names = [
            "United States", "China", "Japan", "Germany", "France",
            "United Kingdom", "Italy", "Spain", "Canada", "Mexico",
            "Brazil", "Russia", "India", "Australia", "South Korea",
            "Indonesia", "Turkey", "Netherlands", "Switzerland", "Sweden",
            "Poland", "Norway", "Belgium", "Ireland", "Israel",
            "Denmark", "Austria", "Portugal", "Greece", "Finland",
        ]
        got = normalize_country_codes(names)
        assert len(got) == 12
