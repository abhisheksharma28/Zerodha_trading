"""Recompute the seasonal edge across multiple trailing windows and score
its stability. A pattern that holds at 20y / 15y / 10y / 5y / 3y is very
different from one that only shows up in the last 3 years.
"""

from __future__ import annotations

from typing import Any

HORIZONS = ("max", "20y", "15y", "10y", "5y", "3y")
_YEARS = {"20y": 20, "15y": 15, "10y": 10, "5y": 5, "3y": 3}

_STABILITY = (
    (0.90, "highly stable"),
    (0.70, "stable"),
    (0.50, "mixed"),
    (0.30, "weakening"),
    (0.0, "broken"),
)


def _window_edges(
    year_edges: dict[int, float], *, last_year: int, horizon: str
) -> list[float]:
    if horizon == "max":
        return list(year_edges.values())
    cut = last_year - _YEARS[horizon] + 1
    return [e for y, e in year_edges.items() if y >= cut]


def multi_horizon(
    year_edges: dict[int, float], *, last_year: int
) -> dict[str, Any]:
    """``year_edges`` = {calendar year: that year's seasonal edge for one
    (sector, month)}. Returns per-horizon mean + a stability verdict."""
    out: dict[str, Any] = {"by_horizon": {}}
    signs: list[int] = []
    means: list[float] = []
    for h in HORIZONS:
        seg = _window_edges(year_edges, last_year=last_year, horizon=h)
        if len(seg) < 3:
            out["by_horizon"][h] = {"n": len(seg), "mean_edge_pct": None}
            continue
        mean = sum(seg) / len(seg)
        pos = sum(1 for e in seg if e > 0) / len(seg)
        out["by_horizon"][h] = {
            "n": len(seg),
            "mean_edge_pct": round(mean, 3),
            "win_rate": round(pos, 3),
        }
        means.append(mean)
        # a horizon whose mean has faded toward zero counts as neutral, not
        # as agreeing with the long-run direction
        signs.append(1 if mean > 0.5 else -1 if mean < -0.5 else 0)

    if len(signs) < 3:
        out["stability_score"] = None
        out["stability"] = "insufficient horizons"
        out["direction_consistent"] = None
        return out

    n_pos = sum(1 for s in signs if s > 0)
    n_neg = sum(1 for s in signs if s < 0)
    dominant = 1 if n_pos >= n_neg else -1
    # agreement is over ALL horizons — neutral / faded horizons dilute it
    agree = sum(1 for s in signs if s == dominant) / len(signs)

    recent = out["by_horizon"].get("3y", {}).get("mean_edge_pct")
    recent5 = out["by_horizon"].get("5y", {}).get("mean_edge_pct")
    longrun = out["by_horizon"].get("max", {}).get("mean_edge_pct")
    penalty = 0.0
    if recent is not None and longrun is not None:
        if (recent > 0) != (longrun > 0):
            penalty += 0.30                                  # sign flip vs long run
        elif abs(recent) < abs(longrun) * 0.5:
            penalty += 0.25                                  # magnitude decayed by half+
    if recent5 is not None and longrun is not None and abs(recent5) < abs(longrun) * 0.5:
        penalty += 0.10
    score = max(0.0, agree - penalty)

    verdict = next(label for thr, label in _STABILITY if score >= thr)
    # a strengthening pattern: recent horizon magnitude exceeds the long-run
    trend = "flat"
    if recent is not None and longrun is not None:
        if abs(recent) > abs(longrun) * 1.25 and (recent > 0) == (longrun > 0):
            trend = "strengthening"
        elif abs(recent) < abs(longrun) * 0.75:
            trend = "weakening"

    out["stability_score"] = round(score, 3)
    out["stability"] = verdict
    out["trend"] = trend
    out["direction_consistent"] = agree >= 0.8
    return out
