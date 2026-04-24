"""
Small metric helpers shared by the runner.

Keep these dead simple — a reviewer should be able to read the whole
file in under a minute.
"""

from __future__ import annotations

from typing import Iterable, Optional


def iso_set_contains_all(
    actual: Optional[Iterable[str]],
    required: Optional[Iterable[str]],
) -> bool:
    """
    True if every code in ``required`` appears (case-insensitive) in
    ``actual``. ``None`` or empty ``required`` → always True (the
    entry isn't asserting on this field).
    """
    if not required:
        return True
    actual_set = {str(c).upper() for c in (actual or [])}
    return all(str(r).upper() in actual_set for r in required)


def mean_absolute_error(values: list[float]) -> float:
    """MAE over a list of already-computed per-entry errors. 0 when empty."""
    if not values:
        return 0.0
    return sum(values) / len(values)
