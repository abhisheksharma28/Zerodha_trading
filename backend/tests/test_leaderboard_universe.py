"""Dynamic universe screens: each picks names that fit a class of strategy."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.leaderboard import universe
from app.strategies.base import Bar

AS_OF = date(2026, 9, 1)


def _bars(name: str, closes: list[float], vol: float = 1_000_000.0) -> list[Bar]:
    out = []
    for c in closes:
        px = max(float(c), 1.0)
        out.append(Bar(
            timestamp="2025-01-01T00:00:00+05:30",
            open=px, high=px * 1.01, low=px * 0.99, close=px, volume=vol, instrument=name,
        ))
    return out


def _trend(n: int, slope: float, start: float = 100.0) -> list[float]:
    return [start * (1.0 + slope) ** i for i in range(n)]


def _sawtooth(n: int, amp: float, start: float = 100.0) -> list[float]:
    return [start + (amp if i % 2 else -amp) for i in range(n)]


def test_liquid_base_ranks_by_turnover_and_applies_filters():
    bars = {
        "BIG": _bars("BIG", _trend(300, 0.0005), vol=5_000_000.0),
        "SMALL": _bars("SMALL", _trend(300, 0.0005), vol=1_000.0),
        "CHEAP": _bars("CHEAP", [5.0] * 300, vol=9_000_000.0),
        "SHORT": _bars("SHORT", _trend(50, 0.001), vol=9_000_000.0),
    }
    res = universe.liquid_base(bars, AS_OF, n=10, min_price=30.0, min_bars=260)
    assert res.symbols[0] == "BIG"                   # most turnover ranks first
    assert "CHEAP" not in res.symbols                # price filter
    assert "SHORT" not in res.symbols                # history filter
    assert "liquid" in res.rationale.lower()


def test_mean_reverting_prefers_negative_autocorrelation():
    bars = {f"MR{k}": _bars(f"MR{k}", _sawtooth(320, 4.0 + k)) for k in range(4)}
    bars.update({f"TR{k}": _bars(f"TR{k}", _trend(320, 0.0009 + 0.0001 * k)) for k in range(4)})
    res = universe.mean_reverting(bars, AS_OF, n=4, base_n=50, ac_window=252)
    assert set(res.symbols) == {"MR0", "MR1", "MR2", "MR3"}
    assert res.metrics["median_lag1_autocorr"] < 0


def test_trend_persistent_prefers_trending_names():
    bars = {f"MR{k}": _bars(f"MR{k}", _sawtooth(320, 5.0)) for k in range(4)}
    bars.update({f"TR{k}": _bars(f"TR{k}", _trend(320, 0.0010 + 0.0002 * k)) for k in range(4)})
    res = universe.trend_persistent(bars, AS_OF, n=4, base_n=50)
    assert set(res.symbols) == {"TR0", "TR1", "TR2", "TR3"}


def test_volatility_screens_split_calm_from_wild():
    rng = np.random.default_rng(0)
    bars = {}
    for k in range(4):
        drift = _trend(300, 0.0003)
        bars[f"CALM{k}"] = _bars(f"CALM{k}", [d * (1 + rng.normal(0, 0.002)) for d in drift])
        bars[f"WILD{k}"] = _bars(f"WILD{k}", [d * (1 + rng.normal(0, 0.05)) for d in drift])
    lo = universe.low_volatility(bars, AS_OF, n=4, base_n=50, vol_window=120)
    hi = universe.high_volatility(bars, AS_OF, n=4, base_n=50, vol_window=120)
    assert set(lo.symbols) == {"CALM0", "CALM1", "CALM2", "CALM3"}
    assert set(hi.symbols) == {"WILD0", "WILD1", "WILD2", "WILD3"}


def test_cointegrated_pair_finds_the_linked_names():
    rng = np.random.default_rng(7)
    log_walk = np.log(100.0 + np.cumsum(rng.normal(0, 1.0, 300)))
    # AA / BB are linear in LOG space (the Engle-Granger assumption): their
    # log-spread is near-white-noise -> strongly stationary.
    linked_a = np.exp(log_walk + rng.normal(0, 0.01, 300))
    linked_b = np.exp(0.5 + 0.8 * log_walk + rng.normal(0, 0.01, 300))
    indep_c = 100.0 + np.cumsum(rng.normal(0, 1.0, 300))   # unrelated random walk
    indep_d = 100.0 + np.cumsum(rng.normal(0, 1.0, 300))   # another one
    bars = {
        "AA": _bars("AA", list(linked_a)),
        "BB": _bars("BB", list(linked_b)),
        "CC": _bars("CC", list(indep_c)),
        "DD": _bars("DD", list(indep_d)),
    }
    res = universe.cointegrated_pair(bars, AS_OF, base_n=10, window=252, max_half_life=120.0)
    assert set(res.symbols) == {"AA", "BB"}
    assert res.metrics["adf_tstat"] < -3.0


def test_cointegrated_pair_returns_nothing_when_no_spread_is_stationary():
    rng = np.random.default_rng(1)
    bars = {
        s: _bars(s, list(100.0 + np.cumsum(rng.normal(0, 1.0, 300))))
        for s in ("PP", "QQ", "RR")
    }
    res = universe.cointegrated_pair(bars, AS_OF, base_n=10, window=252)
    assert res.symbols == []
    assert "stationary enough" in res.rationale


def test_run_screen_dispatches_and_rejects_unknown():
    bars = {f"X{k}": _bars(f"X{k}", _trend(300, 0.0005)) for k in range(3)}
    res = universe.run_screen("broad_cross_section", bars, AS_OF, {"n": 2})
    assert len(res.symbols) == 2
    with pytest.raises(ValueError, match="Unknown universe screen"):
        universe.run_screen("does_not_exist", bars, AS_OF)
