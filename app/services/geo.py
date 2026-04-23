"""
Geographic helpers for change events.

Three responsibilities:

1. `resolve_jurisdiction(url)`            — deterministically map a source
   URL's host to the ISO-2 code(s) of the jurisdiction whose regulator
   published it. Zero LLM cost.

2. `normalize_country_codes(codes)`       — clean an LLM-produced list of
   country strings into deduped uppercase ISO-3166 alpha-2 codes
   (with a couple of allowed pseudo-codes: "EU", "GB" for UK).

3. `assign_trade_countries(…)`            — combine the deterministic
   jurisdiction with the LLM-extracted countries using the
   `trade_flow_direction` to correctly decide which are origins and
   which are destinations.  Fixes the "hardcoded trade flow" flaw
   where the regulator was always assumed to be the destination.

The host→jurisdiction table is deliberately small and conservative: when
in doubt we return an empty list rather than guessing. Unknown sources
simply leave the jurisdiction empty.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse


# ── Host → regulator jurisdiction mapping ────────────────────────────────────
#
# Domain suffix match: the LONGEST suffix wins, so
# `trade.ec.europa.eu`  → EU,
# `ec.europa.eu`        → EU,
# `gov.uk`              → GB,
# `finance.gov.au`      → AU.
#
# ISO-3166 alpha-2 everywhere (we use "EU" for European Union and "GB"
# for the United Kingdom so they fit the same column type; the LLM is
# allowed to emit those too).
_HOST_TO_JURISDICTION: dict[str, tuple[str, ...]] = {
    # United States (federal regulators)
    "cbp.gov":           ("US",),
    "ustr.gov":          ("US",),
    "federalregister.gov": ("US",),
    "regulations.gov":   ("US",),
    "sec.gov":           ("US",),
    "cftc.gov":          ("US",),
    "fda.gov":           ("US",),
    "treasury.gov":      ("US",),
    "ofac.treasury.gov": ("US",),
    "state.gov":         ("US",),
    "gov":               ("US",),  # fallback for .gov generic (not used alone)

    # European Union
    "europa.eu":         ("EU",),
    "ec.europa.eu":      ("EU",),
    "eur-lex.europa.eu": ("EU",),
    "eba.europa.eu":     ("EU",),
    "esma.europa.eu":    ("EU",),
    "edpb.europa.eu":    ("EU",),

    # United Kingdom
    "gov.uk":            ("GB",),
    "fca.org.uk":        ("GB",),
    "bankofengland.co.uk": ("GB",),
    "hmrc.gov.uk":       ("GB",),

    # Switzerland
    "admin.ch":          ("CH",),
    "finma.ch":          ("CH",),

    # China
    "gov.cn":            ("CN",),
    "customs.gov.cn":    ("CN",),
    "mof.gov.cn":        ("CN",),

    # Other G20 (starter set — extend as you add sources)
    "gov.au":            ("AU",),
    "canada.ca":         ("CA",),
    "gov.sg":            ("SG",),
    "meti.go.jp":        ("JP",),
    "go.jp":             ("JP",),
    "gov.kr":            ("KR",),
    "gov.br":            ("BR",),
    "gov.in":            ("IN",),
}


def _host_of(url: str) -> str:
    """Lowercase host (netloc minus port). Empty string if invalid."""
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.netloc or parsed.path).lower().split(":")[0]
    return host.rstrip(".")


def resolve_jurisdiction(url: str) -> list[str]:
    """
    Map the source URL to the ISO-2 code(s) of the *regulator's*
    jurisdiction. This is NOT necessarily the trade destination — use
    `assign_trade_countries()` to place the jurisdiction in the correct
    origin/destination bucket based on `trade_flow_direction`.

    Returns [] for unknown sources so callers can fall back to NULL.

    Uses longest-suffix match: `www.trade.ec.europa.eu/foo/bar` matches
    `ec.europa.eu` before `europa.eu`.
    """
    host = _host_of(url)
    if not host:
        return []
    # Generate all suffixes from longest to shortest:
    # ["www.trade.ec.europa.eu", "trade.ec.europa.eu", "ec.europa.eu",
    #  "europa.eu", "eu"]
    parts = host.split(".")
    for i in range(len(parts)):
        suffix = ".".join(parts[i:])
        hit = _HOST_TO_JURISDICTION.get(suffix)
        if hit is not None:
            return list(hit)
    return []


def assign_trade_countries(
    *,
    jurisdiction: list[str],
    llm_origin_countries: list[str],
    trade_flow_direction: Optional[str],
) -> tuple[list[str], list[str]]:
    """
    Combine the deterministic jurisdiction with LLM-extracted countries,
    respecting the trade flow direction.

    Returns ``(origin_countries, destination_countries)``.

    Logic:
      - **inbound**  — goods entering the regulator's jurisdiction.
                        Jurisdiction → destination; LLM countries → origin.
      - **outbound** — goods leaving the regulator's jurisdiction.
                        Jurisdiction → origin; LLM countries → destination.
      - **bilateral** — both ways (FTA, mutual sanctions, MRA).
                         Jurisdiction + LLM countries appear in BOTH buckets.
      - **global / None** — multilateral or no trade aspect.
                            Jurisdiction → destination (default behaviour);
                            LLM countries → origin (if any).
    """
    def _dedup(a: list[str], b: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for code in a + b:
            if code not in seen:
                seen.add(code)
                out.append(code)
        return out

    direction = (trade_flow_direction or "").strip().lower()

    if direction == "inbound":
        # Goods coming IN → jurisdiction is destination
        return (llm_origin_countries, jurisdiction)

    elif direction == "outbound":
        # Goods going OUT → jurisdiction is origin
        return (jurisdiction, llm_origin_countries)

    elif direction == "bilateral":
        # Both ways → jurisdiction + LLM countries in BOTH buckets
        combined = _dedup(jurisdiction, llm_origin_countries)
        return (combined, combined)

    else:
        # global / None / unknown → default: jurisdiction as destination
        return (llm_origin_countries, jurisdiction)


# Keep backward-compatible alias so any external caller doesn't break.
resolve_destination_countries = resolve_jurisdiction


# ── LLM output sanitisation ────────────────────────────────────────────────

# Full country names the LLM is most likely to emit → ISO-2.
# Intentionally narrow: we'd rather drop an ambiguous string than mislabel
# it. Extend this dictionary as new sources come online.
_NAME_TO_ISO2: dict[str, str] = {
    "united states": "US", "united states of america": "US", "usa": "US",
    "u.s.": "US", "u.s": "US", "us": "US", "america": "US",
    "european union": "EU", "eu": "EU", "europe": "EU",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "britain": "GB", "england": "GB",
    "china": "CN", "people's republic of china": "CN", "prc": "CN",
    "canada": "CA", "mexico": "MX", "japan": "JP",
    "switzerland": "CH", "australia": "AU", "new zealand": "NZ",
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES",
    "netherlands": "NL", "belgium": "BE", "poland": "PL", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "ireland": "IE",
    "austria": "AT", "portugal": "PT", "greece": "GR",
    "india": "IN", "south korea": "KR", "republic of korea": "KR", "korea": "KR",
    "vietnam": "VN", "thailand": "TH", "indonesia": "ID", "malaysia": "MY",
    "singapore": "SG", "philippines": "PH", "taiwan": "TW",
    "brazil": "BR", "argentina": "AR", "chile": "CL", "colombia": "CO",
    "russia": "RU", "russian federation": "RU",
    "turkey": "TR", "saudi arabia": "SA", "united arab emirates": "AE",
    "uae": "AE", "israel": "IL", "egypt": "EG", "south africa": "ZA",
    "nigeria": "NG", "kenya": "KE", "morocco": "MA",
    "hong kong": "HK", "macau": "MO", "macao": "MO",
    "iran": "IR", "iraq": "IQ", "north korea": "KP", "dprk": "KP",
    "pakistan": "PK", "bangladesh": "BD", "ukraine": "UA",
}

_ISO2_RE = re.compile(r"^[A-Z]{2}$")


def normalize_country_codes(
    raw: Optional[Iterable[str]],
) -> list[str]:
    """
    Clean and validate an LLM-produced iterable of country strings.

    - Uppercase.
    - Map known full names → ISO-2.
    - Accept existing ISO-2 codes (including pseudo-codes EU, GB, UK→GB).
    - Drop anything that doesn't resolve to a 2-letter code.
    - Dedupe, preserve first-seen order.
    """
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not item:
            continue
        s = str(item).strip()
        if not s:
            continue
        lower = s.lower()
        # Full name → ISO-2
        if lower in _NAME_TO_ISO2:
            code = _NAME_TO_ISO2[lower]
        else:
            # Last-resort: if it's already a 2-letter token
            candidate = s.upper()
            if _ISO2_RE.match(candidate):
                # Normalise UK → GB (ISO-3166 uses GB)
                code = "GB" if candidate == "UK" else candidate
            else:
                continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out[:12]  # cap to keep the column sane
