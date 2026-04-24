"""
Quote → span locator for XAI / explainability.

Why this module exists
----------------------
Users want to see *where* in the source document a score or obligation
came from. The LLM could return character offsets directly, but LLMs
are notoriously bad at counting characters — they hallucinate
positions. Instead we ask the LLM for a verbatim quote and locate it
ourselves in the source text. This is:

  * **Deterministic.** ``str.find`` cannot lie.
  * **Verifiable.** If the quote isn't found, we know the LLM
    hallucinated (or paraphrased) and we can store the quote alone,
    without bogus offsets.
  * **Cheap.** One substring search per quote — microseconds.

Usage
-----
>>> locate_quote(source_text, trigger_quote)
(1240, 1337)          # exact match found
>>> locate_quote(source_text, "text the LLM invented")
None                   # caller stores the quote without offsets
"""

from __future__ import annotations

import re
from typing import Optional

# Min length heuristic: very short quotes ("the", "shall") are too
# ambiguous to locate reliably. Below this the locator always returns
# None — better to drop the span than highlight the wrong sentence.
MIN_QUOTE_LEN = 20

_WS_RE = re.compile(r"\s+")


def _normalize_ws(s: str) -> str:
    """Collapse internal whitespace to single spaces; trim ends."""
    return _WS_RE.sub(" ", s).strip()


def locate_quote(
    source: str,
    quote: Optional[str],
) -> Optional[tuple[int, int]]:
    """
    Find ``quote`` in ``source`` and return ``(start, end)`` character
    offsets, or ``None`` if the quote cannot be located reliably.

    Strategy:
      1. **Exact match** — the happy path. LLMs are good at quoting
         when prompted "copy VERBATIM."
      2. **Whitespace-normalized match** — sometimes LLMs collapse
         multiple spaces or line-break differently than the source.
         We rebuild the quote's offsets back onto the original source
         by scanning the source char-by-char against the normalized
         quote.
      3. **Return None** if neither works. The caller should still
         persist the quote string (so the UI can display the
         LLM-attributed text) but omit the span.

    The minimum quote length (``MIN_QUOTE_LEN``) filters out quotes
    that would match in many places — a 5-char quote like "shall"
    would highlight noise.
    """
    if not source or not quote:
        return None
    q = quote.strip()
    if len(q) < MIN_QUOTE_LEN:
        return None

    # ── 1. Exact match ──────────────────────────────────────────────
    idx = source.find(q)
    if idx >= 0:
        return (idx, idx + len(q))

    # ── 2. Whitespace-normalized match ──────────────────────────────
    # Build the normalized form of the quote. Then walk the source
    # character by character, accumulating into a parallel normalized
    # form until a prefix matches the normalized quote. When it does,
    # we have the original-source span.
    normalized_quote = _normalize_ws(q)
    if len(normalized_quote) < MIN_QUOTE_LEN:
        return None

    # Build a normalized view of the source + a map back to original
    # offsets. This costs O(n) per call, which is fine: source
    # documents are typically <200KB and we do this a handful of
    # times per event.
    norm_chars: list[str] = []
    orig_offsets: list[int] = []
    prev_was_ws = False
    for i, ch in enumerate(source):
        if ch.isspace():
            if prev_was_ws:
                continue
            norm_chars.append(" ")
            orig_offsets.append(i)
            prev_was_ws = True
        else:
            norm_chars.append(ch)
            orig_offsets.append(i)
            prev_was_ws = False
    # Trim leading whitespace so offsets align with normalized_quote's
    # trim behaviour.
    start = 0
    while start < len(norm_chars) and norm_chars[start] == " ":
        start += 1
    norm_src = "".join(norm_chars[start:])
    orig_offsets = orig_offsets[start:]

    idx = norm_src.find(normalized_quote)
    if idx < 0:
        return None

    span_start = orig_offsets[idx]
    end_normalized_index = idx + len(normalized_quote) - 1
    if end_normalized_index >= len(orig_offsets):
        return None
    # End is exclusive → take the original-source index of the last
    # normalized char, then advance one to get the exclusive-end
    # offset.
    span_end = orig_offsets[end_normalized_index] + 1
    return (span_start, span_end)
