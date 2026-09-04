"""Portfolio fitness — one 0-100 composite that no single metric can
dominate (spec Part 8). Absolute scoring bands so a lone portfolio can be
scored without a reference pool; weights are configurable.

Also the multi-objective vector used for the Pareto frontier.
"""

from __future__ import annotations

from typing import Any

# category weights — must sum to 1.0 (re-normalised if not)
DEFAULT_WEIGHTS: dict[str, float] = {
    "risk_adjusted": 0.20,   # Sharpe / Sortino / Omega
    "absolute_return": 0.20,  # CAGR
    "drawdown": 0.15,         # max drawdown, Ulcer
    "consistency": 0.15,      # positive periods, low rolling-return dispersion
    "diversification": 0.10,  # effective N, low corr to market
    "robustness": 0.10,       # out-of-sample vs in-sample
    "simplicity": 0.10,       # low turnover, low concentration
}


def _band(x: float | None, lo: float, hi: float) -> float:
    """Map ``x`` in [lo, hi] onto [0, 1] (clamped). lo>hi flips it."""
    if x is None:
        return 0.5
    if lo == hi:
        return 0.5
    t = (x - lo) / (hi - lo)
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def score(ev: dict[str, Any], *, weights: dict[str, float] | None = None) -> dict[str, Any]:
    """``ev`` is the output of ``portfolio.evaluate``. Returns
    {alpha_score, category_scores}."""
    w = weights or DEFAULT_WEIGHTS
    wsum = sum(w.values()) or 1.0
    w = {k: v / wsum for k, v in w.items()}

    m = ev.get("metrics", {})
    isr = ev.get("in_sample", {}) or {}
    oos = ev.get("out_of_sample", {}) or {}

    sharpe = m.get("sharpe")
    sortino = m.get("sortino")
    omega = m.get("omega")
    risk_adjusted = (
        0.5 * _band(sharpe, 0.0, 1.5)
        + 0.3 * _band(sortino, 0.0, 2.2)
        + 0.2 * _band(omega, 1.0, 2.5)
    )

    absolute_return = _band(m.get("cagr_pct"), 2.0, 18.0)

    drawdown = (
        0.7 * _band(m.get("max_drawdown_pct"), -45.0, -8.0)   # less negative = better
        + 0.3 * _band(m.get("ulcer_index"), 20.0, 3.0)
    )

    consistency = (
        0.6 * _band(m.get("positive_period_pct"), 45.0, 75.0)
        + 0.4 * _band(m.get("rolling_return_std_pct"), 25.0, 4.0)
    )

    diversification = (
        0.6 * _band(m.get("effective_n"), 2.0, 8.0)
        + 0.4 * _band(m.get("corr_to_market"), 0.95, 0.20)
    )

    # robustness: OOS Sharpe should not collapse vs IS
    is_s, oos_s = isr.get("sharpe"), oos.get("sharpe")
    robustness = (
        _band(oos_s / is_s, 0.3, 1.1)
        if (is_s and is_s > 0.1 and oos_s is not None)
        else 0.5
    )

    simplicity = (
        0.6 * _band(m.get("annual_turnover_pct"), 200.0, 20.0)
        + 0.4 * _band(max(ev.get("weights", {}).values() or [1.0]), 0.45, 0.15)
    )

    cats = {
        "risk_adjusted": risk_adjusted,
        "absolute_return": absolute_return,
        "drawdown": drawdown,
        "consistency": consistency,
        "diversification": diversification,
        "robustness": robustness,
        "simplicity": simplicity,
    }
    alpha = 100.0 * sum(w[k] * cats[k] for k in w)
    return {
        "alpha_score": round(alpha, 2),
        "category_scores": {k: round(v * 100.0, 1) for k, v in cats.items()},
    }


# --- multi-objective (Pareto) ----------------------------------------

_OBJECTIVES = ("cagr_pct", "sharpe", "neg_max_dd", "effective_n", "sortino")


def objective_vector(ev: dict[str, Any]) -> tuple[float, ...]:
    m = ev.get("metrics", {})
    return (
        float(m.get("cagr_pct") or -999),
        float(m.get("sharpe") or -999),
        -float(m.get("max_drawdown_pct") or -999),   # maximise (less negative dd)
        float(m.get("effective_n") or 0),
        float(m.get("sortino") or -999),
    )


def _dominates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(x >= y for x, y in zip(a, b, strict=True)) and any(x > y for x, y in zip(a, b, strict=True))


def pareto_frontier(evals: list[dict[str, Any]]) -> list[int]:
    """Indices of the non-dominated portfolios."""
    vecs = [objective_vector(e) for e in evals]
    front: list[int] = []
    for i, vi in enumerate(vecs):
        if not any(j != i and _dominates(vj, vi) for j, vj in enumerate(vecs)):
            front.append(i)
    return front
