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


def test_hysteresis_keeps_a_held_name_in_the_buffer_zone():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
         "members": ["A", "B", "C", "D"],
         "rule": {"type": "momentum_top_k", "lookback": 40, "top_k": 2, "hold_k": 3, "trend_ma": 0}},
    ]})
    # ranking by ROC: A > B > C > D
    bars = {
        "A": _series("A", 100, 0.004, 120),
        "B": _series("B", 100, 0.003, 120),
        "C": _series("C", 100, 0.002, 120),
        "D": _series("D", 100, 0.0, 120),
    }
    fresh = resolve_targets(spec, bars, datetime(2020, 4, 1))
    assert set(fresh.weights) == {"A", "B"}  # top_k = 2
    # C is rank 3 — held, so it stays (hold_k = 3); D (rank 4) does not
    withheld = resolve_targets(spec, bars, datetime(2020, 4, 1), current_holdings={"C": 10, "D": 10})
    assert set(withheld.weights) == {"A", "B", "C"}


def test_global_position_cap_waterfills_excess():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "momentum_weighted",
         "members": ["BIG", "M1", "M2", "M3"],
         "rule": {"type": "momentum_top_k", "lookback": 30, "top_k": 4, "trend_ma": 0}},
    ], "risk": {"max_position_pct": 30}})
    bars = {
        "BIG": _series("BIG", 100, 0.02, 120),   # dominates momentum weighting
        "M1": _series("M1", 100, 0.001, 120),
        "M2": _series("M2", 100, 0.001, 120),
        "M3": _series("M3", 100, 0.001, 120),
    }
    res = resolve_targets(spec, bars, datetime(2020, 4, 1))
    assert res.weights["BIG"] <= 0.30 + 1e-6
    assert sum(res.weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_regime_gate_trims_risk_assets_in_a_risk_off_market():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Equity", "weight_pct": 70, "weighting": "equal",
         "members": ["E"], "rule": {"type": "none"}, "risk_asset": True},
        {"id": "gold", "name": "Gold", "weight_pct": 30, "weighting": "equal",
         "members": ["G"], "rule": {"type": "none"}, "risk_asset": False},
    ], "risk": {"regime": {"benchmark": "NIFTY 50", "ma": 50, "risk_off_scale": 0.5}}})
    # a choppy 15-month decline: downtrend + drawdown + elevated volatility -> risk_off
    down = _series("NIFTY 50", 400, -0.005, 320,
                   noise=lambda i: 0.03 if i % 2 else -0.028)
    bars = {"E": _series("E", 100, 0.0, 320), "G": _series("G", 100, 0.0, 320),
            "NIFTY 50": down}
    res = resolve_targets(spec, bars, datetime(2020, 11, 1))
    assert res.regime in ("risk_off", "caution")
    # equity sleeve is scaled down; gold (risk_asset=False) is untouched
    assert res.weights["E"] < 0.70
    assert res.weights["G"] == pytest.approx(0.30, abs=1e-6)
    assert res.cash_weight == pytest.approx(0.70 - res.weights["E"], abs=1e-6)

    # a healthy uptrend -> full risk-asset exposure, no scaling
    up = _series("NIFTY 50", 100, 0.0015, 320)
    res2 = resolve_targets(
        spec, {"E": bars["E"], "G": bars["G"], "NIFTY 50": up}, datetime(2020, 11, 1)
    )
    assert res2.regime in ("bull", "strong_bull")
    assert res2.weights["E"] == pytest.approx(0.70, abs=1e-6)


def test_composite_score_rule_ranks_and_exposes_scores():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "score_weighted",
         "members": ["WIN", "MID", "LOSE"],
         "rule": {"type": "composite_score", "lookback": 40, "top_k": 2, "trend_ma": 0,
                  "factor_weights": {"momentum": 0.7, "low_vol": 0.3}}},
    ]})
    bars = {
        "WIN": _series("WIN", 100, 0.004, 120),
        "MID": _series("MID", 100, 0.002, 120),
        "LOSE": _series("LOSE", 100, 0.0, 120),
    }
    res = resolve_targets(spec, bars, datetime(2020, 4, 1))
    assert set(res.weights) == {"WIN", "MID"}
    assert res.score_of("WIN") is not None and res.score_of("WIN") >= res.score_of("MID")


def test_sector_concentration_cap_trims_an_over_weight_sector():
    from app.baskets.engine import _sector_cap

    # HDFCBANK / ICICIBANK / SBIN bucket as "Bank"; NIFTYBEES is an Index ETF
    # bucket (not an equity sector); TCS/INFY are IT.
    w = {
        "HDFCBANK": 0.25, "ICICIBANK": 0.20, "SBIN": 0.15,   # 60% Bank
        "TCS": 0.10, "INFY": 0.10,                            # 20% IT
        "NIFTYBEES": 0.20,                                    # not a sector
    }
    out, notes = _sector_cap(w, 0.30)
    bank = out["HDFCBANK"] + out["ICICIBANK"] + out["SBIN"]
    assert bank == pytest.approx(0.30, abs=1e-6)              # capped
    assert out["NIFTYBEES"] == pytest.approx(0.20, abs=1e-6)  # ETF untouched
    assert out["TCS"] + out["INFY"] == pytest.approx(0.30, abs=1e-6)  # IT filled to its cap
    # the rest of the freed weight (0.20) is no longer invested -> held in cash
    assert sum(out.values()) == pytest.approx(0.80, abs=1e-6)
    assert any("Bank" in n for n in notes)


def test_resolve_targets_applies_the_spec_sector_cap():
    spec = parse_spec({
        "sleeves": [
            {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
             "members": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "TCS", "INFY"],
             "rule": {"type": "none"}},
        ],
        "risk": {"max_sector_pct": 40.0},
    })
    bars = {s: _series(s, 100, 0.0, 60) for s in
            ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "TCS", "INFY")}
    res = resolve_targets(spec, bars, datetime(2020, 4, 1))
    bank = sum(res.weights[s] for s in ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"))
    assert bank <= 0.40 + 1e-6
    assert res.invested <= 1.0 + 1e-6
    assert res.cash_weight == pytest.approx(1.0 - res.invested, abs=1e-6)


def test_composite_score_uses_relative_strength_and_exposes_factor_ranks():
    spec = parse_spec({"sleeves": [
        {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "score_weighted",
         "members": ["LEAD", "LAG"],
         "rule": {"type": "composite_score", "lookback": 60, "top_k": 1, "trend_ma": 0,
                  "factor_weights": {"momentum": 0.4, "rs": 0.6}}},
    ]})
    bars = {
        "LEAD": _series("LEAD", 100, 0.004, 200),
        "LAG": _series("LAG", 100, 0.001, 200),
    }
    market = _series("NIFTY 50", 100, 0.002, 200)

    # with a market series the rs factor participates and LEAD (out-performer) wins
    res = resolve_targets(spec, bars, datetime(2020, 6, 1), market_bars=market)
    assert set(res.weights) == {"LEAD"}
    ranks = res.per_sleeve[0].factor_ranks
    assert "LEAD" in ranks and set(ranks["LEAD"]) == {"momentum", "rs"}
    assert ranks["LEAD"]["rs"] >= ranks.get("LAG", {}).get("rs", 0)

    # without a market series the rs weight is renormalised away, no rs rank
    res2 = resolve_targets(spec, bars, datetime(2020, 6, 1))
    assert set(res2.per_sleeve[0].factor_ranks.get("LEAD", {})) == {"momentum"}


def test_replace_margin_keeps_a_held_name_over_a_marginally_better_newcomer():
    # 5 members -> composite percentile scores land at 0 / 25 / 50 / 75 / 100
    members = ["A", "B", "C", "D", "E"]
    drifts = [0.005, 0.004, 0.003, 0.002, 0.001]  # A strongest -> E weakest
    bars = {m: _series(m, 100, d, 120) for m, d in zip(members, drifts, strict=True)}
    base = {"sleeves": [{
        "id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
        "members": members,
        "rule": {"type": "composite_score", "lookback": 40, "top_k": 3, "trend_ma": 0,
                 "factor_weights": {"momentum": 1.0}},
    }]}
    # no margin: top 3 by score are A, B, C; D (held, score ~25) is dropped
    r0 = resolve_targets(parse_spec(base), bars, datetime(2020, 4, 1),
                         current_holdings={"D": 10})
    assert set(r0.weights) == {"A", "B", "C"}

    # +40-point margin: D's effective score (~65) beats C (~50), so the held
    # name D is kept and the marginally-better newcomer C is not swapped in
    base["sleeves"][0]["rule"]["replace_margin_pct"] = 0.40
    r1 = resolve_targets(parse_spec(base), bars, datetime(2020, 4, 1),
                         current_holdings={"D": 10})
    assert "D" in r1.weights and "C" not in r1.weights


def test_plan_orders_tiers_drift_into_no_trade_partial_and_full():
    prices = {"X": 100.0, "Y": 100.0, "Z": 100.0}
    pv = 100_000.0
    holdings = {"X": 300, "Y": 300, "Z": 300}  # each 30% of pv
    targets = {
        "X": 0.315,   # +1.5% drift  -> under a 3% band -> no trade
        "Y": 0.34,    # +4.0% drift  -> band..2*band   -> partial (half step)
        "Z": 0.40,    # +10% drift   -> >= 2*band       -> full
    }
    intents = {i.symbol: i for i in plan_orders(targets, holdings, prices, pv, drift_band_pct=3.0)}
    assert "X" not in intents
    # partial: move halfway from 300 to the full target of 340 -> +20
    assert intents["Y"].side == "BUY" and intents["Y"].qty == 20
    assert "partial" in intents["Y"].reason
    # full: 300 -> 400 -> +100
    assert intents["Z"].side == "BUY" and intents["Z"].qty == 100


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
    # extended credibility metrics are populated
    for k in ("sortino_ratio", "calmar_ratio", "beta", "alpha_pct", "tracking_error_pct",
              "information_ratio", "monthly_win_rate_pct", "avg_holding_days"):
        assert k in d["metrics"]
    assert d["oos"]["out_of_sample"]["return_pct"] is not None
    assert "bull_tape" in d["regime_breakdown"]


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
        assert "Multi-Asset" in body["categories"]
        assert body["journeys"] and body["risk_labels"]
        tlist = body["templates"]
        assert len(tlist) == 12  # the flagship catalog, not the internal library
        assert any(t["key"] == "all-weather-wealth" for t in tlist)
        assert all(t.get("category") in body["categories"] for t in tlist)
        aww = next(t for t in tlist if t["key"] == "all-weather-wealth")
        assert 1 <= aww["risk_level"] <= 5
        assert aww["objective"] and aww["how_it_works"]

        # the ~14 back-pocket models only appear with include_internal
        assert "internal_models" not in body
        internal = client.get("/api/v1/baskets/templates?include_internal=true").json()
        assert len(internal["internal_models"]) >= 15

        payload = {
            "name": "pytest basket",
            "description": "temp",
            "category": "Multi-Asset",
            "risk_level": aww["risk_level"],
            "objective": aww["objective"],
            "how_it_works": aww["how_it_works"],
            "rebalance_frequency": "monthly",
            "drift_band_pct": 3.0,
            "capital": 300_000,
            "spec": aww["spec"],
        }
        created = client.post("/api/v1/baskets", json=payload)
        assert created.status_code == 200, created.text
        bid = created.json()["id"]
        assert created.json()["n_sleeves"] == 6
        assert created.json()["risk_level"] == aww["risk_level"]
        assert created.json()["how_it_works"] == aww["how_it_works"]

        got = client.get(f"/api/v1/baskets/{bid}")
        assert got.status_code == 200
        assert got.json()["spec"]["sleeves"][0]["weight_pct"] == 33.0

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


# --------------------------------------------------------------------------
# correlation control + risk contribution
# --------------------------------------------------------------------------

def _corr_series(symbol: str, shared, own_scale: float, seed: int):
    """A series driven mostly by a shared shock stream plus its own jitter."""
    import random

    rng = random.Random(seed)
    return _series(
        symbol, 100.0, 0.0004, len(shared),
        noise=lambda i: shared[i] + own_scale * (rng.random() - 0.5) * 0.01,
    )


def test_correlation_control_tapers_a_redundant_holding():
    import random

    from app.baskets.engine import _correlation_deconcentrate

    rng = random.Random(0)
    shared = [(rng.random() - 0.5) * 0.03 for _ in range(200)]
    bars = {
        # A and B ride the same shock stream -> highly correlated
        "A": _corr_series("A", shared, 0.2, 1),
        "B": _corr_series("B", shared, 0.2, 2),
        # C has its own independent path -> a genuine diversifier
        "C": _series("C", 100.0, 0.0003, 200,
                     noise=lambda i: (random.Random(i + 99).random() - 0.5) * 0.03),
    }
    w = {"A": 0.4, "B": 0.4, "C": 0.2}
    out, notes = _correlation_deconcentrate(
        w, bars, datetime(2020, 6, 1), threshold=0.8, lookback=126,
    )
    # the lower/equal-weight member of the correlated pair is tapered
    assert min(out["A"], out["B"]) < 0.4 - 1e-6
    # freed weight moves to the diversifier, total stays invested here
    assert out["C"] > 0.2 + 1e-6
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)
    assert any("corr control" in n for n in notes)


def test_correlation_control_noop_when_all_holdings_are_distinct():
    import random

    from app.baskets.engine import _correlation_deconcentrate

    bars = {}
    for k, s in enumerate(("A", "B", "C", "D")):
        rng = random.Random(1000 + k * 97)
        bars[s] = _series(s, 100.0, 0.0003, 200,
                          noise=lambda i, rng=rng: (rng.random() - 0.5) * 0.04)
    w = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    out, notes = _correlation_deconcentrate(
        w, bars, datetime(2020, 6, 1), threshold=0.85, lookback=126,
    )
    assert out == w
    assert notes == []


def test_resolve_targets_reports_risk_contribution():
    spec = parse_spec({
        "sleeves": [
            {"id": "eq", "name": "Eq", "weight_pct": 100, "weighting": "equal",
             "members": ["P", "Q", "R", "S"], "rule": {"type": "none"}},
        ],
    })
    bars = {s: _series(s, 100, 0.0005, 180,
                       noise=lambda i, s=s: (hash((s, i)) % 100 - 50) / 8000.0)
            for s in ("P", "Q", "R", "S")}
    res = resolve_targets(spec, bars, datetime(2020, 5, 1))
    assert set(res.risk_contribution) == set(res.weights)
    assert sum(res.risk_contribution.values()) == pytest.approx(100.0, abs=1.0)


def test_spec_parses_and_round_trips_max_pair_corr():
    spec = parse_spec({
        "sleeves": [
            {"id": "a", "name": "A", "weight_pct": 100, "weighting": "equal",
             "members": ["X", "Y", "Z"], "rule": {"type": "none"}},
        ],
        "risk": {"max_pair_corr": 0.9, "corr_lookback": 90},
    })
    assert spec.risk.max_pair_corr == 0.9
    assert spec.risk.corr_lookback == 90
    assert spec.risk.active is True
    assert spec.to_dict()["risk"]["max_pair_corr"] == 0.9

    with pytest.raises(SpecError):
        parse_spec({
            "sleeves": [{"id": "a", "name": "A", "weight_pct": 100,
                         "members": ["X"], "rule": {"type": "none"}}],
            "risk": {"max_pair_corr": 1.5},
        })
