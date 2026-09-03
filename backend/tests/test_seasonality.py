"""Calendar-month seasonality helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.strategies.base import Bar
from app.strategies.seasonality import (
    best_sectors_for_month,
    monthly_sector_stats,
    report,
)

IST = "+05:30"


def _series(name: str, dec_gain: float, other: float = 0.0, years: int = 5) -> list[Bar]:
    out = []
    d = datetime(2020, 1, 1)
    for _ in range(365 * years):
        px = 100.0
        if d.month == 12:
            px = 100.0 * (1.0 + dec_gain * (d.day / 31.0))
        elif d.month == 6:
            px = 100.0 * (1.0 + other * (d.day / 30.0))
        ts = d.strftime("%Y-%m-%dT00:00:00") + IST
        out.append(Bar(timestamp=ts, open=px, high=px, low=px, close=px,
                       volume=1_000.0, instrument=name))
        d += timedelta(days=1)
    return out


def test_monthly_stats_capture_a_december_effect():
    bars = {"NIFTY IT": _series("NIFTY IT", 0.12), "NIFTY FMCG": _series("NIFTY FMCG", 0.0)}
    stats = monthly_sector_stats(bars, min_years=3)
    assert stats["NIFTY IT"][12]["mean_pct"] > 8.0
    assert stats["NIFTY IT"][12]["hit_rate"] == 1.0
    # a flat month is roughly zero
    assert abs(stats["NIFTY IT"][3]["mean_pct"]) < 1.0


def test_best_sectors_for_month_ranks_by_metric():
    bars = {
        "NIFTY IT": _series("NIFTY IT", 0.12),
        "NIFTY AUTO": _series("NIFTY AUTO", 0.03),
        "NIFTY FMCG": _series("NIFTY FMCG", 0.0),
    }
    stats = monthly_sector_stats(bars, min_years=3)
    top = best_sectors_for_month(stats, 12, top_n=2)
    assert [s for s, _v in top] == ["NIFTY IT", "NIFTY AUTO"]


def test_report_has_a_calendar_and_per_sector_table():
    bars = {"NIFTY IT": _series("NIFTY IT", 0.12), "NIFTY FMCG": _series("NIFTY FMCG", 0.0)}
    r = report(bars, min_years=3)
    assert "NIFTY IT" in r["per_sector"]
    assert r["calendar_winners"]["Dec"][0]["sector"] == "NIFTY IT"
    assert r["years_covered"] >= 3
