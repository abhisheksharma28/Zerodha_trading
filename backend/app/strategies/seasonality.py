"""Calendar-month seasonality of a set of instruments (used for sectors).

``monthly_sector_stats`` takes daily bars per name and returns, for each
name and each calendar month (1..12), the historical mean / median monthly
return, the hit rate (share of years the month was positive) and the sample
size. ``best_sectors_for_month`` ranks them for a given month.

Lives under ``app.strategies`` (not ``app.leaderboard``) so a strategy
template can import it without a circular import; the leaderboard's
seasonality report and the SeasonalSectorRotation strategy both call it,
the strategy passing only the bars seen so far to keep the ranking causal.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.strategies.base import Bar

_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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


def monthly_sector_stats(
    bars_by_sector: dict[str, list[Bar]], *, min_years: int = 3,
) -> dict[str, Any]:
    per_sector: dict[str, dict[int, dict[str, float]]] = {}
    for sector, bars in bars_by_sector.items():
        mrets = _monthly_returns(bars)
        if not mrets:
            continue
        by_cal: dict[int, list[float]] = defaultdict(list)
        for (_y, m), r in mrets.items():
            by_cal[m].append(r)
        months: dict[int, dict[str, float]] = {}
        for m in range(1, 13):
            vals = by_cal.get(m, [])
            if len(vals) < min_years:
                continue
            vals_sorted = sorted(vals)
            mid = len(vals_sorted) // 2
            median = (vals_sorted[mid] if len(vals_sorted) % 2
                      else (vals_sorted[mid - 1] + vals_sorted[mid]) / 2)
            months[m] = {
                "mean_pct": round(sum(vals) / len(vals), 2),
                "median_pct": round(median, 2),
                "hit_rate": round(sum(1 for v in vals if v > 0) / len(vals), 2),
                "years": len(vals),
            }
        if months:
            per_sector[sector] = months
    return per_sector


def best_sectors_for_month(
    stats: dict[str, Any], month: int, *, top_n: int, metric: str = "mean_pct",
    min_hit_rate: float = 0.5,
) -> list[tuple[str, float]]:
    ranked = [
        (sector, months[month][metric])
        for sector, months in stats.items()
        if month in months and months[month]["hit_rate"] >= min_hit_rate
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[:top_n]


def report(bars_by_sector: dict[str, list[Bar]], *, min_years: int = 3) -> dict[str, Any]:
    """Human-facing seasonality table + the month-by-month winners."""
    stats = monthly_sector_stats(bars_by_sector, min_years=min_years)
    calendar = {
        _MONTHS[m]: [
            {"sector": s, "mean_pct": v} for s, v in best_sectors_for_month(
                stats, m, top_n=3, min_hit_rate=0.5)
        ]
        for m in range(1, 13)
    }
    return {
        "sectors": sorted(stats),
        "years_covered": max(
            (mm["years"] for months in stats.values() for mm in months.values()),
            default=0,
        ),
        "per_sector": {
            s: {_MONTHS[m]: v for m, v in months.items()} for s, months in stats.items()
        },
        "calendar_winners": calendar,
    }
