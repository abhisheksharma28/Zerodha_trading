"""Deterministic unit tests for the order-flow analytics package."""

from __future__ import annotations

import math

from app.orderflow import (
    ORDERFLOW_DELTA,
    Candle,
    assess_historical,
    assess_live,
    build_volume_profile,
    session_anchor_ts,
    vwap_series,
)
from app.orderflow.estimated_delta import EstimatedDeltaEngine
from app.orderflow.types import DataTier

# --- capabilities -------------------------------------------------

def test_capabilities_are_honest_about_kite():
    live = assess_live()
    hist = assess_historical()
    assert live.tier is DataTier.ESTIMATED
    assert hist.tier is DataTier.LIMITED
    assert live.has_trade_side is False
    assert live.has_tick_data is False
    assert hist.has_bid_ask_quotes is False
    # footprint must be listed as explicitly unsupported, never silently offered
    assert any("footprint" in u.lower() for u in live.unsupported)
    assert any("footprint" in u.lower() for u in hist.unsupported)
    d = live.as_dict()
    assert d["flags"]["depthLevels"] == 5
    assert d["tier"] == "ESTIMATED_ORDER_FLOW"


# --- volume profile --------------------------------------------

def _c(ts, o, hi, lo, cl, v):
    return Candle(ts=ts, open=o, high=hi, low=lo, close=cl, volume=v)


def test_volume_profile_poc_is_the_max_volume_price():
    # three dojis: all volume lands in one bin each
    candles = [
        _c(0, 100.0, 100.0, 100.0, 100.0, 50),
        _c(60, 101.0, 101.0, 101.0, 101.0, 30),
        _c(120, 100.0, 100.0, 100.0, 100.0, 400),
        _c(180, 102.0, 102.0, 102.0, 102.0, 20),
    ]
    prof = build_volume_profile(candles, tick_size=1.0, value_area=0.70)
    assert prof.poc_price == 100.0
    assert prof.total_volume == 500.0
    assert prof.tier is DataTier.LIMITED
    # value area holds >= 70% of 500 = 350; POC alone is 400 so VA collapses to POC
    assert prof.val_price <= prof.poc_price <= prof.vah_price


def test_volume_profile_value_area_expands_pairwise():
    candles = [
        _c(0, 10, 10, 10, 10, 10),
        _c(1, 11, 11, 11, 11, 40),
        _c(2, 12, 12, 12, 12, 100),   # POC
        _c(3, 13, 13, 13, 13, 35),
        _c(4, 14, 14, 14, 14, 15),
    ]
    prof = build_volume_profile(candles, tick_size=1.0, value_area=0.70)
    total = 200
    assert prof.poc_price == 12.0
    # target = 0.70 * 200 = 140. POC bin = 100; annex 11 (40 > 35) -> 140 >= 140, stop.
    assert prof.val_price == 11.0
    assert prof.vah_price == 12.0
    # cumulative VA volume must clear the 70% bar
    va_levels = [pl for pl in prof.levels if prof.val_price <= pl.price <= prof.vah_price]
    assert sum(pl.volume for pl in va_levels) >= 0.70 * total


def test_volume_profile_spreads_range_bars_across_bins():
    # one bar spanning 100..104 with volume 400 -> ~100 per 1.0 bin
    prof = build_volume_profile([_c(0, 100, 104, 100, 102, 400)], tick_size=1.0)
    assert prof.bars_used == 1
    assert math.isclose(prof.total_volume, 400.0, rel_tol=1e-6)
    assert len(prof.levels) >= 4
    assert all(pl.volume > 0 for pl in prof.levels)
    # no side data from OHLC
    assert all(pl.delta is None for pl in prof.levels)


def test_volume_profile_empty_is_safe():
    prof = build_volume_profile([], tick_size=0.05)
    assert prof.poc_price is None
    assert prof.levels == []
    assert prof.bars_used == 0


# --- VWAP ------------------------------------------------------

def test_vwap_matches_manual_cumulative():
    candles = [
        _c(0, 10, 10, 10, 10, 100),   # tp 10
        _c(60, 12, 12, 12, 12, 300),  # tp 12
    ]
    series = vwap_series(candles, anchor_ts=0, band_multiples=(1.0, 2.0))
    assert series.points[0].vwap == 10.0
    # (10*100 + 12*300) / 400 = 11.5
    assert math.isclose(series.points[1].vwap, 11.5, rel_tol=1e-9)
    # var = (100*100 + 144*300)/400 - 11.5^2 = (10000+43200)/400 - 132.25 = 133 - 132.25 = .75
    assert math.isclose(series.points[1].bands["upper1"], 11.5 + math.sqrt(0.75), rel_tol=1e-9)
    assert math.isclose(series.points[1].bands["lower2"], 11.5 - 2 * math.sqrt(0.75), rel_tol=1e-9)


def test_session_anchor_picks_last_day_open():
    day = 20000 * 86400  # arbitrary day boundary (IST-shifted epoch space)
    open_sec = 9 * 3600 + 15 * 60
    candles = [
        _c(day - 3600, 1, 1, 1, 1, 1),               # previous day
        _c(day + open_sec, 1, 1, 1, 1, 1),           # today's open
        _c(day + open_sec + 300, 1, 1, 1, 1, 1),
    ]
    assert session_anchor_ts(candles) == day + open_sec


# --- estimated delta (deterministic tick replay) --------------

def _tick(token, price, cum_vol, bid, ask):
    return {
        "instrument_token": token,
        "last_price": price,
        "volume_traded": cum_vol,
        "depth": {"buy": [{"price": bid, "quantity": 1}], "sell": [{"price": ask, "quantity": 1}]},
    }


def test_estimated_delta_quote_rule_classification():
    eng = EstimatedDeltaEngine(bar_seconds=60)
    tok = 111
    # first snapshot: baseline, opening slice dropped
    eng._ingest(_tick(tok, 100.0, 1000, 99.9, 100.1))
    # +50 traded, last price at ask -> BUY
    eng._ingest(_tick(tok, 100.1, 1050, 100.0, 100.1))
    # +30 traded, last price at bid -> SELL
    eng._ingest(_tick(tok, 100.0, 1080, 100.0, 100.2))
    snap = eng.snapshot(tok)
    assert snap["available"] is True
    assert snap["tier"] == "ESTIMATED_ORDER_FLOW"
    assert snap["session_cvd"] == 20.0  # +50 buy, -30 sell
    assert snap["dropped_opening_slices"] == 1
    cur = snap["current_bar"]
    assert cur["buy_volume"] == 50.0
    assert cur["sell_volume"] == 30.0
    assert cur["delta"] == 20.0


def test_estimated_delta_tick_rule_fallback_inside_spread():
    eng = EstimatedDeltaEngine(bar_seconds=60)
    tok = 222
    eng._ingest(_tick(tok, 50.0, 0, 49.0, 51.0))
    # price rose but still inside spread -> tick rule BUY
    eng._ingest(_tick(tok, 50.5, 100, 49.0, 51.0))
    # price fell, inside spread -> tick rule SELL
    eng._ingest(_tick(tok, 50.2, 160, 49.0, 51.0))
    snap = eng.snapshot(tok)
    assert snap["session_cvd"] == 40.0  # +100 -60
    assert "TICK_RULE" in snap["classification_mix"]


def test_estimated_delta_unknown_instrument_is_flagged_not_faked():
    eng = EstimatedDeltaEngine()
    snap = eng.snapshot(999999)
    assert snap["available"] is False
    assert snap["tier"] == "ESTIMATED_ORDER_FLOW"
    assert "caveats" in snap


def test_global_delta_engine_reset_hook():
    ORDERFLOW_DELTA.reset()
    ORDERFLOW_DELTA.on_tick(_tick(7, 10.0, 5, 9.0, 11.0))
    ORDERFLOW_DELTA.on_tick(_tick(7, 10.5, 25, 9.0, 11.0))
    assert ORDERFLOW_DELTA.snapshot(7)["available"] is True
    ORDERFLOW_DELTA.reset()
    assert ORDERFLOW_DELTA.snapshot(7)["available"] is False


# --- API surface --------------------------------------------

def test_capabilities_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/orderflow/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"]["tier"] == "ESTIMATED_ORDER_FLOW"
    assert body["historical"]["tier"] == "LIMITED_DATA"


def test_volume_profile_endpoint_degrades_without_broker():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/orderflow/volume-profile", params={"symbol": "NSE:RELIANCE"})
    assert resp.status_code == 200
    body = resp.json()
    # no connected Zerodha session in tests -> honest "unavailable", not fake data
    assert body["available"] is False
    assert "capabilities" in body
