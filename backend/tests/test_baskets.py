"""Baskets — spec validation, the rebalance engine, and a synthetic
end-to-end backtest."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from app.baskets import backtest as bt
from app.baskets.engine import plan_orders, resolve_targets
from app.baskets.spec import SpecError, parse_spec
from app.core.exceptions import ValidationError
from app.strategies.base import Bar

# --------------------------------------------------------------------------
# synthetic bars
# --------------------------------------------------------------------------

def _series(symbol: str, start: float, daily_drift: float, n: int, *, noise=None):
    """n daily bars ending today, geometric drift + optional per-bar noise fn(i)."""
    bars: list[Bar] = []
    px = start
    day0 = datetime(2020, 1, 1)
    for i in range(n):
        bump = 1.0 + daily_drift + (noise(i) if noise else 0.0)
        px = max(px * bump, 0.01)
        ts = (day0 + timedelta(days=i)).isoformat()
        bars.append(Bar(timestamp=ts, open=px, high=px, low=px, close=px, volume=1000, instrument=symbol))
    return bars


# --------------------------------------------------------------------------
# spec
# --------------------------------------------------------------------------

def test_parse_spec_ok_and_symbol_normalisation():
    spec = parse_spec(
        {
            "sleeves": [
                {"id": "eq", "name": "Equity", "weight_pct": 60,
                 "weighting": "equal", "members": ["nse:NIFTYBEES"], "rule": {"type": "none"}},
                {"id": "gold", "name": "Gold", "weight_pct": 40,
                 "weighting": "equal", "members": ["GOLDBEES", "goldbees"], "rule": {"type": "none"}},
            ]
        }
    )
    assert [s.id for s in spec.sleeves] == ["eq", "gold"]
    assert spec.sleeves[0].members == ("NIFTYBEES",)
    assert spec.sleeves[1].members == ("GOLDBEES",)  # de-duped
    assert spec.symbols == ["NIFTYBEES", "GOLDBEES"]


def test_parse_spec_rejects_bad_weight_sum():
    with pytest.raises(SpecError):
        parse_spec(
            {"sleeves": [
                {"id": "a", "name": "A", "weight_pct": 60, "members": ["X"]},
                {"id": "b", "name": "B", "weight_pct": 30, "members": ["Y"]},
            ]}
        )


def test_parse_spec_rejects_unknown_weighting_and_top_k_over_members():
    with pytest.raises(SpecError):
        parse_spec({"sleeves": [
            {"id": "a", "name": "A", "weight_pct": 100, "weighting": "magic", "members": ["X"]},
        ]})
    with pytest.raises(SpecError):
        parse_spec({"sleeves": [
            {"id": "a", "name": "A", "weight_pct": 100, "members": ["X", "Y"],
             "rule": {"type": "momentum_top_k", "top_k": 5}},
        ]})


# --------------------------------------------------------------------------
# resolve_targets
# --------------------------------------------------------------------------

def test_resolve_targets_equal_weighting_no_rule():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 60, "weighting": "equal",
         "members": ["A", "B"], "rule": {"type": "none"}},
        {"id": "gold", "name": "Gold", "weight_pct": 40, "weighting": "equal",
         "members": ["G"], "rule": {"type": "none"}},
    ]})
    bars = {
        "A": _series("A", 100, 0.0, 60),
        "B": _series("B", 100, 0.0, 60),
        "G": _series("G", 100, 0.0, 60),
    }
    res = resolve_targets(spec, bars, datetime(2020, 4, 1))
    assert res.weights["A"] == pytest.approx(0.30, abs=1e-6)
    assert res.weights["B"] == pytest.approx(0.30, abs=1e-6)
    assert res.weights["G"] == pytest.approx(0.40, abs=1e-6)
    assert res.cash_weight == pytest.approx(0.0, abs=1e-6)


def test_momentum_top_k_picks_the_leaders():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
         "members": ["WIN1", "WIN2", "FLAT1", "FLAT2"],
         "rule": {"type": "momentum_top_k", "lookback": 60, "top_k": 2, "trend_ma": 0}},
    ]})
    bars = {
        "WIN1": _series("WIN1", 100, 0.004, 200),
        "WIN2": _series("WIN2", 100, 0.003, 200),
        "FLAT1": _series("FLAT1", 100, 0.0, 200),
        "FLAT2": _series("FLAT2", 100, 0.0, 200),
    }
    res = resolve_targets(spec, bars, datetime(2020, 6, 1))
    assert set(res.weights) == {"WIN1", "WIN2"}
    assert res.weights["WIN1"] == pytest.approx(0.5, abs=1e-6)


def test_trend_filter_sends_sleeve_to_cash_in_a_downtrend():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 70, "weighting": "equal",
         "members": ["DN1", "DN2"],
         "rule": {"type": "momentum_top_k", "lookback": 40, "top_k": 2, "trend_ma": 50}},
        {"id": "gold", "name": "Gold", "weight_pct": 30, "weighting": "equal",
         "members": ["G"], "rule": {"type": "none"}},
    ]})
    bars = {
        "DN1": _series("DN1", 200, -0.004, 200),
        "DN2": _series("DN2", 200, -0.003, 200),
        "G": _series("G", 100, 0.0, 200),
    }
    res = resolve_targets(spec, bars, datetime(2020, 6, 1))
    assert "DN1" not in res.weights and "DN2" not in res.weights
    assert res.weights["G"] == pytest.approx(0.30, abs=1e-6)
    assert res.cash_weight == pytest.approx(0.70, abs=1e-6)


def test_inverse_vol_tilts_to_the_calm_name():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "inverse_vol",
         "members": ["CALM", "WILD"], "rule": {"type": "none"}},
    ]})
    bars = {
        "CALM": _series("CALM", 100, 0.0, 160, noise=lambda i: 0.001 * math.sin(i)),
        "WILD": _series("WILD", 100, 0.0, 160, noise=lambda i: 0.03 * math.sin(i)),
    }
    res = resolve_targets(spec, bars, datetime(2020, 5, 1))
    assert res.weights["CALM"] > res.weights["WILD"]
    assert res.weights["CALM"] + res.weights["WILD"] == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------
# plan_orders
# --------------------------------------------------------------------------

def test_plan_orders_respects_the_drift_band():
    prices = {"A": 100.0, "B": 100.0}
    pv = 100_000.0
    holdings = {"A": 500, "B": 500}  # 50 / 50 by value
    targets = {"A": 0.52, "B": 0.48}  # 2-pt drift
    assert plan_orders(targets, holdings, prices, pv, drift_band_pct=3.0) == []
    intents = plan_orders(targets, holdings, prices, pv, drift_band_pct=1.0)
    assert {i.symbol for i in intents} == {"A", "B"}
    a = next(i for i in intents if i.symbol == "A")
    assert a.side == "BUY" and a.qty == 20


def test_plan_orders_always_exits_a_dropped_name():
    prices = {"A": 100.0, "B": 50.0}
    pv = 100_000.0
    holdings = {"A": 300, "B": 100}
    targets = {"A": 1.0}  # B dropped
    intents = plan_orders(targets, holdings, prices, pv, drift_band_pct=90.0)
    b = next(i for i in intents if i.symbol == "B")
    assert b.side == "SELL" and b.qty == 100


# --------------------------------------------------------------------------
# backtest (synthetic, monkeypatched fetch)
# --------------------------------------------------------------------------

def test_run_backtest_synthetic(monkeypatch):
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 60, "weighting": "equal",
         "members": ["UP1", "UP2"], "rule": {"type": "none"}},
        {"id": "gold", "name": "Gold", "weight_pct": 40, "weighting": "equal",
         "members": ["GOLDBEES"], "rule": {"type": "none"}},
    ]})
    n = 420
    fake = {
        "UP1": _series("UP1", 100, 0.0009, n),
        "UP2": _series("UP2", 120, 0.0007, n),
        "GOLDBEES": _series("GOLDBEES", 60, 0.0003, n),
        "NIFTY 50": _series("NIFTY 50", 18000, 0.0005, n),
    }
    monkeypatch.setattr(
        bt, "fetch_candles",
        lambda *a, **k: ({s: b for s, b in fake.items() if s in k["symbols"]}, []),
    )
    res = bt.run_backtest(
        None, None, spec, years=1.5, capital=500_000.0,
        benchmark="NIFTY 50", frequency="monthly", drift_band_pct=3.0,
    )
    d = res.to_dict()
    assert d["equity_curve"][0][1] > 0
    assert d["equity_curve"][-1][1] > d["equity_curve"][0][1]  # up-trending basket grows
    assert d["metrics"]["benchmark_return_pct"] is not None
    assert d["metrics"]["n_rebalances"] >= 10
    assert set(res.final_holdings) <= {"UP1", "UP2", "GOLDBEES"}
    assert d["metrics"]["sharpe_ratio"] is not None


def test_run_backtest_rejects_when_no_history(monkeypatch):
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
         "members": ["X"], "rule": {"type": "none"}},
    ]})
    monkeypatch.setattr(bt, "fetch_candles", lambda *a, **k: ({}, [{"symbol": "X", "reason": "nope"}]))
    with pytest.raises(ValidationError):
        bt.run_backtest(None, None, spec, years=2.0, benchmark="NIFTY 50")


# --------------------------------------------------------------------------
# API smoke
# --------------------------------------------------------------------------

def test_basket_api_crud_roundtrip():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        tpls = client.get("/api/v1/baskets/templates")
        assert tpls.status_code == 200
        body = tpls.json()
        assert "Multi-asset" in body["categories"]
        tlist = body["templates"]
        assert any(t["key"] == "all-weather" for t in tlist)
        assert all(t.get("category") in body["categories"] for t in tlist)

        payload = {
            "name": "pytest basket",
            "description": "temp",
            "category": "Multi-asset",
            "rebalance_frequency": "monthly",
            "drift_band_pct": 3.0,
            "capital": 300_000,
            "spec": next(t["spec"] for t in tlist if t["key"] == "all-weather"),
        }
        created = client.post("/api/v1/baskets", json=payload)
        assert created.status_code == 200, created.text
        bid = created.json()["id"]
        assert created.json()["n_sleeves"] == 3

        got = client.get(f"/api/v1/baskets/{bid}")
        assert got.status_code == 200
        assert got.json()["spec"]["sleeves"][0]["weight_pct"] == 50.0

        upd = client.put(f"/api/v1/baskets/{bid}", json={"drift_band_pct": 5.0})
        assert upd.status_code == 200
        assert upd.json()["drift_band_pct"] == 5.0

        listed = client.get("/api/v1/baskets")
        assert any(b["id"] == bid for b in listed.json())

        deleted = client.delete(f"/api/v1/baskets/{bid}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/api/v1/baskets/{bid}").status_code == 404


def test_all_starter_templates_parse_and_are_categorised():
    from app.baskets.templates import TEMPLATE_CATEGORIES, templates

    seen_keys = set()
    for t in templates():
        assert t["key"] not in seen_keys, f"duplicate template key {t['key']}"
        seen_keys.add(t["key"])
        assert t["category"] in TEMPLATE_CATEGORIES, t["key"]
        spec = parse_spec(t["spec"])  # raises on any bad spec
        assert 1 <= len(spec.sleeves) <= 12
        assert abs(sum(s.weight_pct for s in spec.sleeves) - 100.0) < 0.5
    assert len(seen_keys) >= 15


def test_basket_api_rejects_bad_spec():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/v1/baskets", json={
            "name": "bad", "spec": {"sleeves": [
                {"id": "a", "name": "A", "weight_pct": 70, "members": ["X"]},
            ]},
        })
        assert r.status_code in (400, 422)
