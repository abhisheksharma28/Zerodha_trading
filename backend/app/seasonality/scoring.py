"""Independent long-score and short-score for a (sector, month) cell, plus
a 0-100 master seasonal-confidence score.

The short score is NOT ``-long_score`` — it independently measures
persistent *downside* behaviour (negative-edge magnitude, negative
frequency, market underperformance, cross-sectional weakness, the
bootstrap probability the edge is negative).
"""

from __future__ import annotations

import math
from typing import Any


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _norm(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return _clip01((x - lo) / (hi - lo))


def _sig_component(t_stat: float, q: float | None) -> float:
    """0..1 from |t| and the FDR q-value together."""
    t_part = _norm(abs(t_stat), 1.0, 3.5)
    if q is None:
        return t_part * 0.5
    q_part = _clip01(1.0 - q / 0.10) if q < 0.10 else 0.0
    return _clip01(0.5 * t_part + 0.5 * q_part)


def long_score(cell: dict[str, Any], horizon: dict[str, Any]) -> float:
    n = cell.get("n", 0)
    if n < 5:
        return 0.0
    mean_e = cell.get("mean_edge_pct", 0.0) or 0.0
    med_e = cell.get("median_edge_pct", 0.0) or 0.0
    win = cell.get("win_rate", 0.0) or 0.0
    madj = cell.get("mean_market_adj_pct", 0.0) or 0.0
    xrank = cell.get("mean_cross_rank")
    boot = (cell.get("bootstrap") or {})
    p_pos = boot.get("prob_positive", 0.5) if boot.get("available") else 0.5
    stab = horizon.get("stability_score") or 0.0
    recency_ok = 1.0 if horizon.get("direction_consistent") else 0.4

    xrank_component = 0.0
    if xrank is not None:
        # rank 1 best; assume up to ~18 sectors
        xrank_component = _clip01(1.0 - (xrank - 1.0) / 17.0)

    s = (
        0.20 * _norm(mean_e, 0.0, 4.0)
        + 0.15 * _norm(med_e, 0.0, 3.0)
        + 0.15 * _norm(win, 0.5, 0.85)
        + 0.10 * _norm(madj, 0.0, 3.0)
        + 0.10 * xrank_component
        + 0.10 * _sig_component(cell.get("t_stat", 0.0), cell.get("q_value"))
        + 0.10 * _norm(p_pos, 0.5, 0.95)
        + 0.05 * _clip01(stab)
        + 0.05 * recency_ok
    )
    # a negative mean edge cannot be a long candidate
    if mean_e <= 0:
        s *= 0.15
    return round(100.0 * _clip01(s), 1)


def short_score(cell: dict[str, Any], horizon: dict[str, Any]) -> float:
    n = cell.get("n", 0)
    if n < 5:
        return 0.0
    mean_e = cell.get("mean_edge_pct", 0.0) or 0.0
    med_e = cell.get("median_edge_pct", 0.0) or 0.0
    loss = cell.get("loss_rate", 0.0) or 0.0
    madj = cell.get("mean_market_adj_pct", 0.0) or 0.0
    xrank = cell.get("mean_cross_rank")
    boot = (cell.get("bootstrap") or {})
    p_neg = boot.get("prob_negative", 0.5) if boot.get("available") else 0.5
    stab = horizon.get("stability_score") or 0.0
    recency_ok = 1.0 if horizon.get("direction_consistent") else 0.4

    xweak = 0.0
    if xrank is not None:
        xweak = _clip01((xrank - 1.0) / 17.0)  # high rank number = weak

    s = (
        0.20 * _norm(-mean_e, 0.0, 4.0)
        + 0.15 * _norm(-med_e, 0.0, 3.0)
        + 0.15 * _norm(loss, 0.5, 0.85)
        + 0.10 * _norm(-madj, 0.0, 3.0)
        + 0.10 * xweak
        + 0.10 * _sig_component(cell.get("t_stat", 0.0), cell.get("q_value"))
        + 0.10 * _norm(p_neg, 0.5, 0.95)
        + 0.05 * _clip01(stab)
        + 0.05 * recency_ok
    )
    if mean_e >= 0:
        s *= 0.15
    return round(100.0 * _clip01(s), 1)


def master_confidence(cell: dict[str, Any], horizon: dict[str, Any]) -> float:
    """0-100. Combines statistical evidence, FDR survival, bootstrap,
    sample size, cross-horizon + recency stability."""
    n = cell.get("n", 0)
    if n < 5:
        return 0.0
    q = cell.get("q_value")
    boot = cell.get("bootstrap") or {}
    p_dir = max(boot.get("prob_positive", 0.5), boot.get("prob_negative", 0.5)) if boot.get("available") else 0.5
    stab = horizon.get("stability_score") or 0.0

    parts = [
        0.30 * _sig_component(cell.get("t_stat", 0.0), q),
        0.15 * (1.0 if (q is not None and q < 0.05) else 0.4 if (q is not None and q < 0.10) else 0.0),
        0.15 * _norm(p_dir, 0.5, 0.95),
        0.15 * _norm(math.log10(max(n, 1)) / math.log10(25), 0.4, 1.0),
        0.15 * _clip01(stab),
        0.10 * (1.0 if horizon.get("direction_consistent") else 0.3),
    ]
    return round(100.0 * _clip01(sum(parts)), 1)


def visual_bucket(mean_edge: float, t_stat: float, q: float | None) -> str:
    """The cell colour for the long/short heatmap.

    gray | light_green | green | dark_green | light_red | red | dark_red
    """
    if abs(t_stat) < 1.0:
        return "gray"
    strong_stat = abs(t_stat) >= 2.26
    survives = q is not None and q < 0.05
    if mean_edge > 0:
        if survives:
            return "dark_green"
        return "green" if strong_stat else "light_green"
    if mean_edge < 0:
        if survives:
            return "dark_red"
        return "red" if strong_stat else "light_red"
    return "gray"
