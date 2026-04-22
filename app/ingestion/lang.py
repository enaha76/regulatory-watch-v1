"""
Language detection helper used by every connector.

Why not just `langdetect.detect()` directly?
------------------------------------------------------------
`langdetect` is a trigram classifier that becomes unreliable on short or
mostly-CJK text. In live ingestion we hit several misclassifications:

  * Traditional Chinese (zh-Hant) pages from gov.cn returned as "ko"
  * Pages where the non-CJK title was longer than the CJK body were
    tagged as "en" even when the main content was Chinese

Both cases are actually trivial to resolve with a Unicode-block
pre-classifier: if the dominant character range is in the CJK blocks we
can assign the language deterministically without asking a probabilistic
model. langdetect is used only as a fallback for non-CJK text.

Public API
----------
detect(text: str) -> Optional[str]
    Returns an ISO 639-1 language code ("en", "zh", "ja", "ko", "fr", …)
    or None when no reliable guess can be made.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# Unicode ranges that unambiguously identify each CJK script.
# Sources: https://www.unicode.org/charts/
_HAN_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
)
_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_HANGUL_RANGES = (
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0x1100, 0x11FF),    # Hangul Jamo
    (0x3130, 0x318F),    # Hangul Compatibility Jamo
)

# Below this fraction of recognisable CJK characters we fall back to
# langdetect. Tuned empirically: 10% dominance is already enough to be
# confident about the script. Pages with 0–10% CJK are almost always
# Latin-script pages that happen to contain a few ideographs.
_CJK_DOMINANCE_THRESHOLD = 0.10


def _in_ranges(cp: int, ranges) -> bool:
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False


def _cjk_profile(text: str) -> dict:
    """
    Count the number of characters in each CJK script plus the total
    number of non-space/non-punctuation characters.
    """
    han = hira = kata = hangul = letters = 0
    for ch in text:
        cp = ord(ch)

        # Skip whitespace and punctuation (both ASCII and Unicode)
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S") or cat.startswith("Z"):
            continue

        letters += 1
        if _in_ranges(cp, _HAN_RANGES):
            han += 1
        elif _in_ranges(cp, (_HIRAGANA,)):
            hira += 1
        elif _in_ranges(cp, (_KATAKANA,)):
            kata += 1
        elif _in_ranges(cp, _HANGUL_RANGES):
            hangul += 1

    return {
        "letters": letters,
        "han": han,
        "hiragana": hira,
        "katakana": kata,
        "hangul": hangul,
    }


def _classify_cjk(profile: dict) -> Optional[str]:
    """
    Return "zh", "ja", "ko" when the profile points to one of them with
    high confidence, else None. Logic:

      * Any Hangul at all → Korean (Hangul is not shared with Chinese/JP)
      * Any Hiragana / Katakana → Japanese (kana is exclusive to JP)
      * Han dominance above threshold → Chinese
    """
    letters = profile["letters"]
    if letters == 0:
        return None

    if profile["hangul"] > 0 and profile["hangul"] / letters > _CJK_DOMINANCE_THRESHOLD:
        return "ko"
    if (profile["hiragana"] + profile["katakana"]) / letters > _CJK_DOMINANCE_THRESHOLD:
        return "ja"
    if profile["han"] / letters > _CJK_DOMINANCE_THRESHOLD:
        return "zh"

    return None


def detect(text: str) -> Optional[str]:
    """
    Return an ISO 639-1 language code, or None if detection fails.
    Uses a deterministic CJK pre-classifier so that Chinese / Japanese
    / Korean pages are never misclassified as each other or as "en".
    Non-CJK text falls through to langdetect.
    """
    if not text or not text.strip():
        return None

    # Take a larger slice than langdetect uses on its own — enough to
    # give both the script detector and langdetect a stable signal.
    sample = text[:4000]

    profile = _cjk_profile(sample)
    cjk_guess = _classify_cjk(profile)
    if cjk_guess:
        return cjk_guess

    try:
        from langdetect import detect as _ld_detect  # type: ignore
        from langdetect import DetectorFactory  # type: ignore

        # Seed for reproducibility — langdetect is stochastic by default.
        DetectorFactory.seed = 0
        return _ld_detect(sample)
    except Exception as exc:
        logger.debug("langdetect failed: %s", exc)
        return None
