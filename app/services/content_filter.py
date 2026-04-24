"""
Pre-ingest content filter.

The crawler discovers thousands of URLs per domain. Most are NOT
regulatory content — careers pages, events, press releases, about
pages, blog posts, contact forms. Left unfiltered, every one becomes
a ``RawDocument``, triggers a ``ChangeEvent``, and costs an LLM
scoring call.

Rather than hand-curating per-domain allow/deny URL patterns (which
does not scale across 20→100 regulators with different CMS
conventions and languages), this filter works on the **content**
itself. It's one universal rule: regulations share a distinctive
*linguistic fingerprint* — structural markers (§, Article, Section),
compliance verbs (shall, must, pursuant, gemäß, conformément), and
statutory phrasing — that chit-chat content doesn't have.

The filter is:

* **Universal.** Works on any regulator, any URL structure, any CMS.
* **Multilingual.** English, French, German, Spanish, Italian cover
  ~95% of G20 regulatory sources.
* **Deterministic + cheap.** Pure string operations; ~0.1ms per
  page. Runs BEFORE the DB insert and BEFORE the LLM.
* **Conservative.** When in doubt, lets the doc through — the M3
  scorer is the final arbiter. Better to waste one LLM call than
  drop a real regulation.

Public API
----------
``is_regulatory_content(text, *, title=None) -> tuple[bool, dict]``
    Returns ``(pass, reason_dict)``. ``pass=False`` → drop the doc.
    ``reason_dict`` is structured for logging.
"""

from __future__ import annotations

import re
from typing import Optional

from app.config import get_settings

# ── Keyword dictionary ──────────────────────────────────────────────────────
# One list, maintained centrally, covers every regulator. Grows slowly as
# you add languages. Lowercase; matched via word-boundary tokenization so
# "muster" does not match "must".
_KEYWORDS: frozenset[str] = frozenset({
    # ── English ──────────────────────────────────────────────────
    # Compliance verbs — the strongest single signal of regulation.
    "shall", "must", "required", "requires", "requirement",
    "prohibited", "prohibits", "obligated", "obligation",
    "pursuant", "effective", "compliance", "comply",
    # Structural markers
    "section", "subsection", "paragraph", "subparagraph",
    "article", "clause", "provision", "chapter", "title", "part",
    # Instrument nouns
    "regulation", "regulations", "directive", "statute", "statutes",
    "rule", "rules", "act", "amendment", "ordinance", "bylaw",
    "guidance", "handbook", "code",
    # Enforcement / consequence
    "penalty", "penalties", "fine", "fines", "violation", "violates",
    "enforcement", "sanctioned", "sanctions",
    # ── French ───────────────────────────────────────────────────
    "doit", "doivent", "conformément", "règlement", "règle",
    "directive", "article", "paragraphe", "alinéa", "disposition",
    "obligation", "interdiction", "sanction", "pénalité",
    # ── German ───────────────────────────────────────────────────
    "muss", "müssen", "gemäß", "verordnung", "artikel", "absatz",
    "paragraph", "vorschrift", "pflicht", "verbot", "strafe",
    # ── Spanish ──────────────────────────────────────────────────
    "debe", "deberá", "deberán", "conforme", "artículo",
    "reglamento", "párrafo", "disposición", "obligación",
    "prohibición", "sanción",
    # ── Italian ──────────────────────────────────────────────────
    "deve", "devono", "ai sensi", "articolo", "regolamento",
    "comma", "disposizione", "divieto", "sanzione",
})

# Strong structural markers — finding any ONE of these is enough to
# pass, because plain prose rarely contains them. "§ 12.3",
# "Article 4(2)", "Section 1256(b)", "CFR 40.1", "USC 15".
_STRUCTURAL_MARKER_RE = re.compile(
    r"(?:"
    r"§\s*\d"                                 # § 12
    r"|\b(?:Art(?:icle|\.)|Sec(?:tion|\.)"    # Article 3, Sec. 5
    r"|Chapter|Title|Part)\s+\d"
    r"|\b\d+\s*(?:CFR|U\.?S\.?C\.?|USC)\b"    # 40 CFR, 15 USC
    r"|\b(?:EU|EC|EEC)\s*\d+/\d{2,4}"         # EU 2016/679
    r")",
    re.IGNORECASE,
)

# Word tokenizer — matches words across Latin-1 + extended Latin (French
# accents, German umlauts, Spanish tildes) plus the legal § symbol.
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ɏ]+", re.UNICODE)


def _count_keyword_hits(text_lower: str, tokens: list[str]) -> int:
    """
    Count regulatory-keyword appearances.

    Single-word keywords match against the tokenized word list
    (word-boundary exact match). Two-word keywords like "ai sensi"
    are substring-matched against the lowercased full text.
    """
    hits = 0
    token_set = set(tokens)
    for kw in _KEYWORDS:
        if " " in kw:
            # Multi-word phrase — substring match in lowercased text.
            # Rare (only "ai sensi" right now), so the cost is trivial.
            if kw in text_lower:
                hits += 1
        else:
            if kw in token_set:
                hits += 1
    return hits


def is_regulatory_content(
    text: str,
    *,
    title: Optional[str] = None,
) -> tuple[bool, dict]:
    """
    Decide whether ``text`` is plausibly regulatory content.

    Returns ``(pass, info)`` where ``info`` contains ``reason`` plus
    enough telemetry for a log line:

    * ``word_count``
    * ``keyword_hits``
    * ``density``          (keywords / words)
    * ``structural``       (True if a §, Article N, CFR ref was found)

    Decision rules (short-circuit in order):

    1. Empty / trivial text  → drop.
    2. A *structural* marker ("§ 12", "Article 3", "40 CFR Part 63")
       is a near-certain regulatory signal → pass regardless of
       word count or density.
    3. Below ``CONTENT_FILTER_MIN_WORDS`` → drop (landing pages,
       nav stubs).
    4. Below ``CONTENT_FILTER_MIN_KEYWORD_HITS`` absolute keywords
       → drop (about pages, careers, events — use compliance
       vocabulary rarely).
    5. Below ``CONTENT_FILTER_MIN_DENSITY`` keywords/word → drop
       (long-form marketing content that mentions "regulation"
       once in passing).
    6. Otherwise → pass.

    The title is included in the matched corpus but not separately
    required — a rule can have a boring title ("PS26-3") and still
    pass on its body.
    """
    s = get_settings()
    combined = text or ""
    if title:
        combined = f"{title}\n\n{combined}"
    combined_strip = combined.strip()
    if not combined_strip:
        return False, {"reason": "empty"}

    # Structural marker short-circuit.
    struct_match = _STRUCTURAL_MARKER_RE.search(combined_strip)
    structural = struct_match is not None

    tokens = [t.lower() for t in _TOKEN_RE.findall(combined_strip)]
    word_count = len(tokens)

    if structural and word_count >= 50:
        # 50 is a very loose floor — even a short regulatory blurb
        # that cites § 12.3 is worth ingesting. A page with just
        # "§" in a footer still won't pass the 50-token bar.
        return True, {
            "reason": "structural_marker",
            "word_count": word_count,
            "structural": True,
            "marker": struct_match.group(0)[:40],
        }

    keyword_hits = _count_keyword_hits(combined_strip.lower(), tokens)

    # ── Short-but-dense bypass ──────────────────────────────────────
    # A 150-word enforcement notice or rule amendment can carry the
    # regulatory signal as densely as a 10K-word policy paper. Allow
    # through any doc that clears the absolute keyword bar AND has
    # an unusually high density (≥2% — ~7× the steady-state floor).
    # This catches real short documents without admitting noisy
    # marketing that merely drops "regulation" once.
    DENSE_SHORT_MIN_WORDS = 50
    DENSE_SHORT_MIN_DENSITY = 0.02
    if (
        word_count >= DENSE_SHORT_MIN_WORDS
        and keyword_hits >= s.CONTENT_FILTER_MIN_KEYWORD_HITS
        and (keyword_hits / word_count) >= DENSE_SHORT_MIN_DENSITY
    ):
        return True, {
            "reason": "dense_short",
            "word_count": word_count,
            "keyword_hits": keyword_hits,
            "density": round(keyword_hits / word_count, 4),
            "structural": structural,
        }

    if word_count < s.CONTENT_FILTER_MIN_WORDS:
        return False, {
            "reason": "too_short",
            "word_count": word_count,
            "keyword_hits": keyword_hits,
            "structural": structural,
        }

    if keyword_hits < s.CONTENT_FILTER_MIN_KEYWORD_HITS:
        return False, {
            "reason": "no_regulatory_keywords",
            "word_count": word_count,
            "keyword_hits": keyword_hits,
            "structural": structural,
        }

    density = keyword_hits / word_count
    if density < s.CONTENT_FILTER_MIN_DENSITY:
        return False, {
            "reason": "low_keyword_density",
            "word_count": word_count,
            "keyword_hits": keyword_hits,
            "density": round(density, 4),
            "structural": structural,
        }

    return True, {
        "reason": "passed",
        "word_count": word_count,
        "keyword_hits": keyword_hits,
        "density": round(density, 4),
        "structural": structural,
    }
