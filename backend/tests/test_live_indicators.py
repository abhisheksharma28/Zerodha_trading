"""Incremental live indicators must match the batch functions in
app.strategies.indicators exactly (same seeding / smoothing), so a strategy
behaves the same fed live or backtested."""

from __future__ import annotations

import random

import pytest

from app.live.indicators import (
    EMA,
    MACD,
    RSI,
    Bollinger,
    IndicatorSet,
    RollingExtrema,
    RollingMean,
    RollingStd,
    SessionVWAP,
    WilderATR,
)
from app.strategies import indicators as batch


@pytest.fixture
def series() -> list[float]:
    random.seed(42)
    x = 100.0
    out = []
    for _ in range(200):
        x *= 1.0 + random.uniform(-0.02, 0.02)
        out.append(round(x, 4))
    return out


def _feed_last(ind, values):
    last = None
    for v in values:
        last = ind.update(v)
    return last


def test_rolling_mean_matches_sma(series):
    inc = RollingMean(20)
    assert _feed_last(inc, series) == pytest.approx(batch.sma(series, 20))
    assert RollingMean(5).update(1.0) is None  # not enough data yet


def test_rolling_std_matches(series):
    inc = RollingStd(20)
    assert _feed_last(inc, series) == pytest.approx(batch.rolling_std(series, 20))


def test_ema_matches_and_seeds_like_batch(series):
    inc = EMA(21)
    assert _feed_last(inc, series) == pytest.approx(batch.ema(series, 21))
    # the seed value equals the SMA of the first `period` points
    e = EMA(3)
    assert e.update(1.0) is None
    assert e.update(2.0) is None
    assert e.update(3.0) == pytest.approx(2.0)


def test_rsi_matches_wilder(series):
    inc = RSI(14)
    assert _feed_last(inc, series) == pytest.approx(batch.rsi(series, 14))


def test_atr_matches_wilder(series):
    highs = [v * 1.01 for v in series]
    lows = [v * 0.99 for v in series]
    closes = series
    inc = WilderATR(14)
    last = None
    for h, lo, c in zip(highs, lows, closes, strict=True):
        last = inc.update(h, lo, c)
    assert last == pytest.approx(batch.atr(highs, lows, closes, 14))


def test_bollinger_matches(series):
    inc = Bollinger(20, 2.0)
    got = _feed_last(inc, series)
    exp = batch.bollinger(series, 20, 2.0)  # (lower, mid, upper)
    assert got == pytest.approx(exp)


def test_session_vwap_matches(series):
    vols = [1000.0 + i for i in range(len(series))]
    inc = SessionVWAP()
    last = None
    for p, v in zip(series, vols, strict=True):
        last = inc.update(p, v)
    assert last == pytest.approx(batch.vwap(series, vols))
    inc.reset()
    assert inc.value is None


def test_rolling_extrema(series):
    inc = RollingExtrema(10)
    lo, hi = _feed_last(inc, series)
    assert lo == min(series[-10:])
    assert hi == max(series[-10:])


def test_macd_shapes(series):
    inc = MACD(12, 26, 9)
    out = _feed_last(inc, series)
    assert out is not None and len(out) == 3
    macd, sig, hist = out
    assert hist == pytest.approx(macd - sig)


def test_indicator_set_snapshot_is_incremental(series):
    s = IndicatorSet()
    for c in series:
        s.update_bar(high=c * 1.005, low=c * 0.995, close=c, volume=1000.0)
    snap = s.snapshot()
    assert snap["bars"] == len(series)
    # snapshot values are rounded to 4dp for JSON; the raw primitives have
    # exact-parity tests above.
    assert snap["ema20"] == pytest.approx(batch.ema(series, 20), abs=1e-3)
    assert snap["rsi14"] == pytest.approx(batch.rsi(series, 14), abs=1e-3)
    assert snap["sma20"] == pytest.approx(batch.sma(series, 20), abs=1e-3)
