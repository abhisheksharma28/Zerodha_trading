"""Per-instrument return / risk / consistency metrics for the discovery
screen. Pure functions over a periodic return series (monthly in P1).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

_MONTHS_Y = 12


def _equity_curve(rets: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + rets)


def _drawdown_series(curve: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(curve)
    return curve / peak - 1.0


def instrument_metrics(
    returns: list[float],
    *,
    periods_per_year: int = _MONTHS_Y,
    market_returns: list[float] | None = None,
) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 6:
        return {"n": n, "insufficient": True}

    ppy = periods_per_year
    years = n / ppy
    curve = _equity_curve(r)
    total_return = float(curve[-1] - 1.0)
    cagr = float(curve[-1] ** (1.0 / years) - 1.0) if curve[-1] > 0 else -1.0

    mean = float(r.mean())
    vol = float(r.std(ddof=1))
    ann_vol = vol * math.sqrt(ppy)
    downs = r[r < 0.0]
    dd_dev = float(math.sqrt((downs**2).mean())) if downs.size else 0.0
    ann_dd = dd_dev * math.sqrt(ppy)

    sharpe = (mean / vol) * math.sqrt(ppy) if vol > 1e-12 else 0.0
    # with no downside periods Sortino is undefined-high; fall back to Sharpe
    # so the "Sortino >= Sharpe" invariant holds
    sortino = (mean / dd_dev) * math.sqrt(ppy) if dd_dev > 1e-12 else sharpe

    dds = _drawdown_series(curve)
    max_dd = float(dds.min())
    avg_dd = float(dds[dds < 0].mean()) if (dds < 0).any() else 0.0
    ulcer = float(math.sqrt((dds**2).mean())) * 100.0

    calmar = cagr / abs(max_dd) if max_dd < -1e-6 else 0.0
    sterling = cagr / (abs(max_dd) + 0.10) if abs(max_dd) > 0 else 0.0
    gains = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())
    omega = gains / losses if losses > 1e-12 else float("inf")

    var95 = float(np.percentile(r, 5))
    tail = r[r <= var95]
    cvar95 = float(tail.mean()) if tail.size else var95

    pos_pct = float((r > 0).mean() * 100.0)
    best, worst = float(r.max()), float(r.min())

    # rolling 12-period compounded return — consistency + dispersion
    roll_w = min(ppy, n - 1)
    roll_rets: list[float] = []
    roll_sharpe: list[float] = []
    for i in range(0, n - roll_w + 1):
        w = r[i : i + roll_w]
        roll_rets.append(float(np.prod(1.0 + w) - 1.0))
        sd = w.std(ddof=1)
        roll_sharpe.append(float((w.mean() / sd) * math.sqrt(ppy)) if sd > 1e-12 else 0.0)
    rr = np.asarray(roll_rets) if roll_rets else np.zeros(1)
    rs = np.asarray(roll_sharpe) if roll_sharpe else np.zeros(1)

    corr_mkt = None
    if market_returns is not None:
        m = np.asarray(market_returns, dtype=float)
        if m.size == n and m.std() > 1e-12 and r.std() > 1e-12:
            corr_mkt = float(np.corrcoef(r, m)[0, 1])

    return {
        "n": n,
        "years": round(years, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "ann_vol_pct": round(ann_vol * 100.0, 2),
        "downside_dev_pct": round(ann_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "sterling": round(sterling, 3),
        "omega": round(omega, 3) if math.isfinite(omega) else None,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "avg_drawdown_pct": round(avg_dd * 100.0, 2),
        "ulcer_index": round(ulcer, 2),
        "var_95_pct": round(var95 * 100.0, 2),
        "cvar_95_pct": round(cvar95 * 100.0, 2),
        "positive_period_pct": round(pos_pct, 1),
        "best_period_pct": round(best * 100.0, 2),
        "worst_period_pct": round(worst * 100.0, 2),
        "rolling_return_mean_pct": round(float(rr.mean()) * 100.0, 2),
        "rolling_return_min_pct": round(float(rr.min()) * 100.0, 2),
        "rolling_return_std_pct": round(float(rr.std()) * 100.0, 2),
        "rolling_sharpe_std": round(float(rs.std()), 3),
        "corr_to_market": round(corr_mkt, 3) if corr_mkt is not None else None,
    }
