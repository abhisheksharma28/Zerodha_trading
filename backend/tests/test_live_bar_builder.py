"""Tick -> bar aggregation + the live indicator engine."""

from __future__ import annotations

from app.live.bar_builder import BarBuilder
from app.live.indicator_engine import IndicatorEngine


def test_bar_closes_on_bucket_rollover():
    b = BarBuilder(interval_seconds=60)
    assert b.on_tick(100.0, 0, 0) is None       # opens bucket [0, 60)
    assert b.on_tick(101.0, 10, 15) is None     # same bucket
    assert b.on_tick(99.0, 25, 45) is None      # same bucket
    bar = b.on_tick(100.5, 40, 61)             # bucket [60, 120) -> closes prev
    assert bar is not None
    assert bar["open"] == 100.0
    assert bar["high"] == 101.0
    assert bar["low"] == 99.0
    assert bar["close"] == 99.0            # last tick inside the closed bucket
    assert bar["volume"] == 25             # 25 - 0


def test_volume_is_delta_of_cumulative():
    b = BarBuilder(60)
    b.on_tick(10.0, 5000, 600)   # bucket [600, 660)
    b.on_tick(11.0, 5200, 630)   # same bucket
    bar = b.on_tick(12.0, 5300, 661)  # bucket [660, 720) -> closes prev
    assert bar["volume"] == 200   # 5200 - 5000 (the 5300 tick is in the new bucket)


def test_indicator_engine_steps_once_per_bar():
    eng = IndicatorEngine(interval_seconds=60)
    token = 738561
    # 40 one-minute buckets of a gently rising series
    px = 100.0
    for i in range(40):
        base = 600 + i * 60
        eng.on_tick({"instrument_token": token, "last_price": px, "volume_traded": i * 100,
                     "exchange_timestamp": base})
        eng.on_tick({"instrument_token": token, "last_price": px + 0.5, "volume_traded": i * 100 + 50,
                     "exchange_timestamp": base + 30})
        px += 0.7
    # one more tick in a fresh bucket to close bar #40
    eng.on_tick({"instrument_token": token, "last_price": px, "volume_traded": 4100,
                 "exchange_timestamp": 600 + 40 * 60})

    snap = eng.snapshot(token)
    assert snap is not None
    assert snap["bars"] == 40
    assert snap["ema20"] is not None
    assert snap["rsi14"] is not None and snap["rsi14"] > 50   # uptrend
    assert snap["vwap"] is not None


def test_engine_ignores_ticks_without_price():
    eng = IndicatorEngine()
    eng.on_tick({"instrument_token": 1})            # no last_price
    eng.on_tick({"last_price": 10.0})               # no token
    assert eng.snapshot(1) is None
    assert eng.snapshot_all() == {}
