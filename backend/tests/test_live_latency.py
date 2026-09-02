"""Latency instrumentation: ring buffer, percentiles, span, snapshot shape."""

from __future__ import annotations

import time

import pytest

from app.live.latency import (
    STAGE_INTERNAL_DECISION,
    STAGE_MARKET_DATA,
    STAGE_STRATEGY_EVAL,
    LatencyRegistry,
    _percentile,
)


def test_percentile_interpolates():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(data, 0) == 1.0
    assert _percentile(data, 100) == 5.0
    assert _percentile(data, 50) == 3.0
    assert _percentile([], 95) == 0.0
    assert _percentile([7.0], 95) == 7.0


def test_records_and_aggregates():
    reg = LatencyRegistry(window=100)
    for ms in (2.0, 4.0, 6.0, 8.0, 10.0):
        reg.record_ms("x", ms)

    s = reg.stats("x")
    assert s is not None
    assert s.count == 5
    assert s.last_ms == 10.0
    assert s.min_ms == 2.0
    assert s.max_ms == 10.0
    assert s.avg_ms == pytest.approx(6.0)
    assert s.p50_ms == pytest.approx(6.0)
    assert s.p99_ms == pytest.approx(9.92, abs=0.1)


def test_ring_buffer_bounded():
    reg = LatencyRegistry(window=10)
    for i in range(1000):
        reg.record_ms("y", float(i))
    s = reg.stats("y")
    assert s is not None
    assert s.count == 10          # only the last 10 kept
    assert s.min_ms == 990.0
    assert s.last_ms == 999.0


def test_span_measures_monotonically():
    reg = LatencyRegistry()
    with reg.span("sleep"):
        time.sleep(0.01)
    s = reg.stats("sleep")
    assert s is not None
    assert s.last_ms >= 9.0        # ~10ms, allow scheduler slack
    assert s.last_ms < 200.0


def test_unknown_stage_is_none():
    assert LatencyRegistry().stats("nope") is None


def test_snapshot_shape_and_headline():
    reg = LatencyRegistry()
    reg.record_ms(STAGE_MARKET_DATA, 0.12)
    reg.record_ms(STAGE_STRATEGY_EVAL, 0.08)
    reg.record_ms(STAGE_INTERNAL_DECISION, 4.5)

    snap = reg.snapshot()
    assert set(snap) == {"stages", "headline"}
    assert STAGE_MARKET_DATA in snap["stages"]
    hl = snap["headline"]
    assert hl["idle_ms"] == pytest.approx(0.20, abs=1e-6)
    assert hl["internal_decision_ms"] == pytest.approx(4.5)
    assert hl["broker_rtt_ms"] is None


def test_reset_clears():
    reg = LatencyRegistry()
    reg.record_ms("z", 1.0)
    reg.reset()
    assert reg.stats("z") is None
