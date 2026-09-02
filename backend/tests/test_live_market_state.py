"""In-memory market state: apply ticks, read back, staleness."""

from __future__ import annotations

import time

from app.live.market_state import MarketState


def test_apply_and_read_last_price():
    ms = MarketState()
    ms.apply_tick({"instrument_token": 1, "last_price": 100.5, "mode": "ltp"})
    assert ms.last_price(1) == 100.5
    ms.apply_tick({"instrument_token": 1, "last_price": 101.0})
    st = ms.get(1)
    assert st is not None
    assert st.last_price == 101.0
    assert st.updates == 2


def test_depth_exposes_best_bid_ask():
    ms = MarketState()
    ms.apply_tick(
        {
            "instrument_token": 7,
            "last_price": 50.0,
            "depth": {
                "buy": [{"quantity": 10, "price": 49.9, "orders": 1}],
                "sell": [{"quantity": 12, "price": 50.1, "orders": 2}],
            },
        }
    )
    st = ms.get(7)
    assert st is not None
    assert st.best_bid == 49.9
    assert st.best_ask == 50.1


def test_unknown_token_is_none():
    ms = MarketState()
    assert ms.get(999) is None
    assert ms.last_price(999) is None
    assert ms.age_seconds(999) is None


def test_staleness_detection():
    ms = MarketState()
    ms.apply_tick({"instrument_token": 1, "last_price": 1.0})
    ms._by_token[1].recv_monotonic = time.monotonic() - 10.0  # age it
    ms.apply_tick({"instrument_token": 2, "last_price": 2.0})   # fresh

    stale = ms.stale_tokens(threshold_seconds=5.0)
    assert stale == [1]


def test_snapshot_shape():
    ms = MarketState()
    ms.apply_tick({"instrument_token": 1, "last_price": 10.0, "ohlc": {"open": 9.0}})
    snap = ms.snapshot()
    assert snap["instrument_count"] == 1
    assert snap["total_updates"] == 1
    assert "1" in snap["instruments"]
    assert snap["instruments"]["1"]["last_price"] == 10.0


def test_reset():
    ms = MarketState()
    ms.apply_tick({"instrument_token": 1, "last_price": 1.0})
    ms.reset()
    assert ms.get(1) is None
    assert ms.seconds_since_any_tick() is None
