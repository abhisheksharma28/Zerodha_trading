"""Calendar-month seasonality of a set of instruments (sectors or stocks).

Method follows the seasonality literature placed in ``docs/`` (Gultekin &
Gultekin 1983; Heston & Sadka 2008; Keloharju et al. 2021; Kapalczynski
2022):

* the seasonal effect is defined as the month's return **relative to that
  year's average month** (``tau_m`` with ``sum(tau_m) ~ 0``), so a name that
  simply had a strong year does not look "seasonally strong" every month
  (``demean=True``);
* monthly returns are fat-tailed, so the per-calendar-month sample is
  winsorised and a rank-based measure (``mean_rank``, Kruskal-Wallis style)
  is offered alongside the mean;
* a Student ``t_stat`` per calendar month lets a caller demand statistical
  strength, not just a positive average.

Lives under ``app.strategies`` (not ``app.leaderboard``) to avoid a circular
import; the leaderboard seasonality report and both SeasonalSectorRotation
strategies call it, the strategy passing only bars seen so far (causal).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from app.strategies.base import Bar

_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# India-specific calendar anchors the literature highlights (fiscal year
# starts 1 April; Union Budget ~1 Feb; December year-end).
INDIA_ANCHORS = {
    3: "fiscal-year-end / tax-loss selling",
    4: "turn of the tax year (fiscal year starts 1 Apr)",
    2: "Union Budget",
    12: "calendar year-end",
}

_METRICS = ("mean_pct", "median_pct", "mean_rank", "t_stat")


def _bar_ym(b: Bar) -> tuple[int, int]:
    dt = datetime.fromisoformat(str(b.timestamp).replace("Z", "+00:00"))
    return dt.year, dt.month


def _monthly_returns(bars: list[Bar]) -> dict[tuple[int, int], float]:
    """(year, month) -> % return, from first to last close in that month."""
    by_month: dict[tuple[int, int], list[Bar]] = defaultdict(list)
    for b in bars:
        by_month[_bar_ym(b)].append(b)
    out: dict[tuple[int, int], float] = {}
    for ym, bs in by_month.items():
        c0, c1 = float(bs[0].close), float(bs[-1].close)
        if c0 > 0 and len(bs) >= 5:
            out[ym] = (c1 / c0 - 1.0) * 100.0
    return out


def _seasonal_by_calendar_month(
    mrets: dict[tuple[int, int], float], *, demean: bool,
) -> dict[int, list[tuple[int, float, float]]]:
    """calendar month -> list of (year, value, within-year rank 1..12).

    ``value`` is the raw monthly % return, or its deviation from that year's
    mean monthly return when ``demean``. Rank is over the months present in
    that same year (higher rank = stronger that year)."""
    by_year: dict[int, dict[int, float]] = defaultdict(dict)
    for (y, m), r in mrets.items():
        by_year[y][m] = r
    out: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for y, months in by_year.items():
        if len(months) < 6:                       # a near-complete year only
            continue
        yr_mean = sum(months.values()) / len(months)
        ordered = sorted(months.items(), key=lambda kv: kv[1])
        rank_of = {m: i + 1 for i, (m, _v) in enumerate(ordered)}
        n = len(ordered)
        for m, r in months.items():
            val = (r - yr_mean) if demean else r
            # normalise rank to a 1..12 scale so partial years compare
            rnk = 1.0 + (rank_of[m] - 1) * (11.0 / max(n - 1, 1))
            out[m].append((y, val, rnk))
    return out


def _winsorise(vals: list[float], sd: float) -> list[float]:
    if len(vals) < 4 or sd <= 0:
        return vals
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    s = math.sqrt(var)
    if s == 0:
        return vals
    lo, hi = mean - sd * s, mean + sd * s
    return [min(hi, max(lo, v)) for v in vals]


def monthly_sector_stats(
    bars_by_sector: dict[str, list[Bar]], *, min_years: int = 5,
    demean: bool = True, winsor_sd: float = 3.0,
) -> dict[str, Any]:
    """name -> {month(1..12) -> {mean_pct, median_pct, hit_rate, years,
    t_stat, mean_rank, raw_mean_pct}}. ``mean_pct`` is the *seasonal edge*
    (de-meaned) unless ``demean=False``."""
    per_sector: dict[str, dict[int, dict[str, float]]] = {}
    for sector, bars in bars_by_sector.items():
        mrets = _monthly_returns(bars)
        if not mrets:
            continue
        cal = _seasonal_by_calendar_month(mrets, demean=demean)
        raw_cal = _seasonal_by_calendar_month(mrets, demean=False)
        months: dict[int, dict[str, float]] = {}
        for m in range(1, 13):
            rows = cal.get(m, [])
            if len(rows) < min_years:
                continue
            vals = _winsorise([v for _y, v, _r in rows], winsor_sd)
            ranks = [rk for _y, _v, rk in rows]
            n = len(vals)
            mean = sum(vals) / n
            var = sum((v - mean) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
            std = math.sqrt(var)
            vs = sorted(vals)
            mid = n // 2
            median = vs[mid] if n % 2 else (vs[mid - 1] + vs[mid]) / 2
            raw_vals = [v for _y, v, _r in raw_cal.get(m, [])]
            months[m] = {
                "mean_pct": round(mean, 2),
                "median_pct": round(median, 2),
                "hit_rate": round(sum(1 for v in vals if v > 0) / n, 2),
                "years": n,
                "t_stat": round(mean / (std / math.sqrt(n)), 2) if std > 0 else 0.0,
                "mean_rank": round(sum(ranks) / len(ranks), 2),
                "raw_mean_pct": round(sum(raw_vals) / len(raw_vals), 2) if raw_vals else 0.0,
            }
        if months:
            per_sector[sector] = months
    return per_sector


def best_sectors_for_month(
    stats: dict[str, Any], month: int, *, top_n: int, metric: str = "mean_pct",
    min_hit_rate: float = 0.5, min_t_stat: float = 0.0,
) -> list[tuple[str, float]]:
    if metric not in _METRICS:
        raise ValueError(f"metric must be one of {_METRICS}")
    ranked = [
        (sector, months[month][metric])
        for sector, months in stats.items()
        if month in months
        and months[month]["hit_rate"] >= min_hit_rate
        and months[month]["t_stat"] >= min_t_stat
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[:top_n]


def report(
    bars_by_sector: dict[str, list[Bar]], *, min_years: int = 5,
) -> dict[str, Any]:
    """Human-facing seasonality tables — raw and de-meaned (seasonal edge) —
    plus the significant months and the India calendar anchors."""
    stats = monthly_sector_stats(bars_by_sector, min_years=min_years, demean=True)
    calendar = {
        _MONTHS[m]: [
            {"sector": s, "seasonal_edge_pct": v,
             "t_stat": stats[s][m]["t_stat"], "hit_rate": stats[s][m]["hit_rate"],
             "raw_mean_pct": stats[s][m]["raw_mean_pct"]}
            for s, v in best_sectors_for_month(stats, m, top_n=3, min_hit_rate=0.5)
        ]
        for m in range(1, 13)
    }
    significant = {
        s: sorted(
            (_MONTHS[m] for m, mm in months.items()
             if mm["t_stat"] >= 1.0 and mm["mean_pct"] > 0),
            key=lambda name: _MONTHS.index(name),
        )
        for s, months in stats.items()
    }
    return {
        "method": ("Seasonal edge = month return minus that year's average month "
                   "(sum ~ 0 across the year); winsorised at 3 SD; t-stat and "
                   "Kruskal-Wallis-style mean rank reported."),
        "sectors": sorted(stats),
        "years_covered": max(
            (mm["years"] for months in stats.values() for mm in months.values()),
            default=0,
        ),
        "india_calendar_anchors": {_MONTHS[m]: why for m, why in INDIA_ANCHORS.items()},
        "per_sector": {
            s: {_MONTHS[m]: v for m, v in months.items()} for s, months in stats.items()
        },
        "calendar_winners": calendar,
        "significant_months_per_sector": {s: v for s, v in significant.items() if v},
    }
