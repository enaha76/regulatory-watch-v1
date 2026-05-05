"""
Crawl-frequency presets and bidirectional translation.

The frontend uses friendly labels ("Hourly", "Daily", …); the DB stores
an integer second count. This module is the single source of truth for
the mapping. Keep the dicts here in sync with the dropdown options in
sources-view.tsx.
"""

from __future__ import annotations

from typing import Optional


# Default crawl interval applied when `Domain.crawl_interval_seconds` is NULL.
DEFAULT_INTERVAL_SECONDS = 86_400  # 1 day


# Frontend label → seconds. Order here drives the dropdown order.
LABEL_TO_SECONDS: dict[str, int] = {
    "Hourly": 3_600,
    "Daily": 86_400,
    "Weekly": 604_800,
    "Monthly": 2_592_000,  # 30-day month — close enough
}

# Reverse map for serialization.
_SECONDS_TO_LABEL: dict[int, str] = {v: k for k, v in LABEL_TO_SECONDS.items()}


def label_for_seconds(seconds: Optional[int]) -> str:
    """
    Translate a stored interval back to a frontend label.

    NULL → "Daily" (the platform default).
    Unrecognized custom values → fall back to the closest preset.
    """
    if seconds is None:
        return "Daily"
    if seconds in _SECONDS_TO_LABEL:
        return _SECONDS_TO_LABEL[seconds]
    # Snap to the nearest preset so the dropdown always has a sensible
    # selected value even if a row was set via raw SQL.
    closest = min(LABEL_TO_SECONDS.values(), key=lambda v: abs(v - seconds))
    return _SECONDS_TO_LABEL[closest]


def seconds_for_label(label: Optional[str]) -> Optional[int]:
    """
    Translate a frontend label to a seconds value.

    None / blank / unknown → None (use the platform default).
    """
    if not label:
        return None
    return LABEL_TO_SECONDS.get(label)


def effective_interval(domain_interval_seconds: Optional[int]) -> int:
    """The interval the beat task should actually use for a given domain."""
    if domain_interval_seconds is None or domain_interval_seconds <= 0:
        return DEFAULT_INTERVAL_SECONDS
    return domain_interval_seconds


def valid_labels() -> list[str]:
    """Frontend pattern: only these strings are accepted in PATCH/POST."""
    return list(LABEL_TO_SECONDS.keys())
