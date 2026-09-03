"""Market-regime classification, point-in-time.

Each completed calendar month is labelled by the market's state as of the
*prior* month-end (so a regime label never uses information from inside
the month it describes):

  trend  : NIFTY 50 prior month-end close vs its trailing 12-month average
           and its trailing 12-month return
             bull    -> above the average and 12m return > 0
             bear    -> below the average and 12m return < 0
             neutral -> otherwise
  vol    : INDIA VIX average over the prior month vs its own history
             high_vol -> top third (or >= 20 absolute)
             low_vol  -> bottom third
             normal   -> middle
"""

from __future__ import annotations

from typing import Any

from app.seasonality import MARKET_INDEX, VIX_INDEX
from app.seasonality.returns import _key, monthly_closes


def _prev(ym: tuple[int, int]) -> tuple[int, int]:
    y, m = ym
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _monthly_avg(bars: list[Any]) -> dict[tuple[int, int], float]:
    acc: dict[tuple[int, int], list[float]] = {}
    for b in bars:
        d = _key(b.timestamp)
        c = float(getattr(b, "close", 0.0) or 0.0)
        if c > 0:
            acc.setdefault((d.year, d.month), []).append(c)
    return {ym: sum(v) / len(v) for ym, v in acc.items()}


def classify_months(
    bars_by_index: dict[str, list[Any]], months: list[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, str]]:
    """(-> {(y,m): {"trend": ..., "vol": ...}}) for each requested month."""
    mkt_closes = monthly_closes(bars_by_index.get(MARKET_INDEX, []))
    ordered = sorted(mkt_closes)
    idx = {ym: i for i, ym in enumerate(ordered)}

    vix_avg = _monthly_avg(bars_by_index.get(VIX_INDEX, []))
    vix_hist = sorted(vix_avg.values())
    vix_lo = vix_hist[len(vix_hist) // 3] if len(vix_hist) >= 6 else None
    vix_hi = vix_hist[2 * len(vix_hist) // 3] if len(vix_hist) >= 6 else None

    out: dict[tuple[int, int], dict[str, str]] = {}
    for ym in months:
        p = _prev(ym)
        trend = "unknown"
        if p in idx and idx[p] >= 12:
            i = idx[p]
            window = [mkt_closes[ordered[j]] for j in range(i - 11, i + 1)]
            avg12 = sum(window) / len(window)
            ret12 = mkt_closes[p] / mkt_closes[ordered[i - 12]] - 1.0
            above = mkt_closes[p] > avg12
            if above and ret12 > 0:
                trend = "bull"
            elif not above and ret12 < 0:
                trend = "bear"
            else:
                trend = "neutral"

        vol = "unknown"
        v = vix_avg.get(p)
        if v is not None:
            if v >= 20 or (vix_hi is not None and v >= vix_hi):
                vol = "high_vol"
            elif vix_lo is not None and v <= vix_lo:
                vol = "low_vol"
            else:
                vol = "normal"
        out[ym] = {"trend": trend, "vol": vol}
    return out


def edges_by_regime(
    year_month_edges: dict[tuple[int, int], float],
    regimes: dict[tuple[int, int], dict[str, str]],
) -> dict[str, Any]:
    """Split one (sector, calendar-month) edge series by the market regime
    of each observation. Returns mean + n per bucket and a dependency flag."""
    buckets: dict[str, list[float]] = {
        "all": [], "bull": [], "bear": [], "neutral": [], "high_vol": [], "low_vol": [],
    }
    for ym, e in year_month_edges.items():
        buckets["all"].append(e)
        r = regimes.get(ym, {})
        if r.get("trend") in ("bull", "bear", "neutral"):
            buckets[r["trend"]].append(e)
        if r.get("vol") in ("high_vol", "low_vol"):
            buckets[r["vol"]].append(e)

    def _agg(xs: list[float]) -> dict[str, Any]:
        if len(xs) < 3:
            return {"n": len(xs), "mean_edge_pct": None}
        return {"n": len(xs), "mean_edge_pct": round(sum(xs) / len(xs), 3)}

    res = {k: _agg(v) for k, v in buckets.items()}
    means = [res[k]["mean_edge_pct"] for k in ("bull", "bear") if res[k]["mean_edge_pct"] is not None]
    dependency = None
    if len(means) == 2:
        spread = abs(means[0] - means[1])
        base = abs(res["all"]["mean_edge_pct"] or 0.0) + 1e-6
        dependency = round(min(spread / base, 3.0), 2)  # >1 => edge flips a lot with regime
    res["regime_dependency"] = dependency
    res["regime_dependent"] = dependency is not None and dependency > 1.0
    return res
