"""Benjamini-Hochberg false-discovery-rate control across the whole
sector x month research grid (~18 sectors x 12 months = ~216 hypotheses).

A raw p-value alone is not allowed to label a cell "significant"; the
q-value (BH-adjusted) is the gate.
"""

from __future__ import annotations

from typing import Any


def benjamini_hochberg(p_by_key: dict[Any, float]) -> dict[Any, float]:
    """(-> {key: q-value}). Standard step-up BH with monotonicity enforced."""
    items = [(k, p) for k, p in p_by_key.items() if p is not None]
    if not items:
        return {}
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    q_raw = [(k, min(1.0, p * m / (i + 1))) for i, (k, p) in enumerate(items)]
    # enforce monotone non-decreasing q as p increases (walk from the top)
    q_final: dict[Any, float] = {}
    running = 1.0
    for k, q in reversed(q_raw):
        running = min(running, q)
        q_final[k] = round(running, 4)
    return q_final


def confidence_label(q: float | None) -> str:
    if q is None:
        return "untested"
    if q < 0.05:
        return "high confidence"
    if q < 0.10:
        return "moderate confidence"
    return "unconfirmed after multiple testing"
