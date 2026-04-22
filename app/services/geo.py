"""
Geographic helpers for change events.

Two responsibilities:

1. `resolve_destination_countries(url)`  — deterministically map a source
   URL's host to the jurisdiction its regulator governs. Zero LLM cost.
   This is the `destination_countries` column on change_events.

2. `normalize_country_codes(codes)`      — clean an LLM-produced list of
   country strings into deduped uppercase ISO-3166 alpha-2 codes
   (with a couple of allowed pseudo-codes: "EU", "GB" for UK).
   This is fed into the `origin_countries` column.

The host→jurisdiction table is deliberately small and conservative: when
in doubt we return an empty list rather than guessing. Unknown sources
simply leave `destination_countries` NULL.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse


# ── Host → destination jurisdiction mapping ─────────────────────────────────
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


def resolve_destination_countries(url: str) -> list[str]:
    """
    Map the source URL to the ISO-2 code(s) of the jurisdiction whose
    regulator published it. Returns [] for unknown sources so callers
    can fall back to NULL.

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
