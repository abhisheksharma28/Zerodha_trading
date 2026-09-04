"""Baskets — the tactical allocation overlay (tilt within bands)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.baskets import tactical as tac
from app.baskets.engine import resolve_targets
from app.baskets.spec import SpecError, parse_spec
from app.strategies.base import Bar


def _closes(drift: float, n: int = 320, start: float = 100.0):
    out, p = [], start
    for _ in range(n):
        out.append(round(p, 4))
        p *= 1.0 + drift
    return out


def _bars(symbol: str, drift: float, n: int = 320):
    day0 = datetime(2020, 1, 1)
    bars, p = [], 100.0
    for i in range(n):
        p *= 1.0 + drift
        ts = (day0 + timedelta(days=i)).isoformat()
        bars.append(Bar(timestamp=ts, open=p, high=p, low=p, close=p, volume=1000, instrument=symbol))
    return bars


def _sleeves():
    return {
        "equity": {"asset": "EQ", "band": (40.0, 35.0, 60.0), "name": "Indian Equity"},
        "gsec": {"asset": "GS", "band": (20.0, 15.0, 30.0), "name": "Government Bonds"},
        "gold": {"asset": "GD", "band": (20.0, 10.0, 30.0), "name": "Gold"},
        "cash": {"asset": "CA", "band": (20.0, 10.0, 30.0), "name": "Liquid"},
    }


def test_trend_tilt_leans_into_the_strong_asset_within_bands():
    closes = {"EQ": _closes(0.004), "GS": _closes(0.0002), "GD": _closes(0.0003), "CA": _closes(0.00005)}
    out, notes = tac.tilt("trend_tilt", _sleeves(), closes, max_step_pct=8.0)
    assert abs(sum(out.values()) - 100.0) < 0.05
    assert out["equity"] > 40.0            # equity trending hardest -> tilt up
    assert 35.0 - 1e-6 <= out["equity"] <= 60.0 + 1e-6
    for sid, (_s, lo, hi) in ((k, v["band"]) for k, v in _sleeves().items()):
        assert lo - 1e-6 <= out[sid] <= hi + 1e-6
    # step cap respected
    assert out["equity"] - 40.0 <= 8.0 + 1e-6
    assert notes and "trend_tilt" in notes[0]


def test_trend_tilt_will_not_lean_growth_up_in_a_risk_off_tape():
    closes = {"EQ": _closes(0.004), "GS": _closes(0.0002), "GD": _closes(0.0003), "CA": _closes(0.00005)}
    out, _ = tac.tilt("trend_tilt", _sleeves(), closes, regime="risk_off", max_step_pct=8.0)
    assert out["equity"] <= 40.0 + 1e-6


def test_strategic_model_is_identity():
    closes = {k: _closes(0.001) for k in ("EQ", "GS", "GD", "CA")}
    out, notes = tac.tilt("strategic", _sleeves(), closes)
    assert out == {"equity": 40.0, "gsec": 20.0, "gold": 20.0, "cash": 20.0}
    assert notes == []


def test_permanent_portfolio_pulls_to_equal_then_clamps():
    closes = {k: _closes(0.001) for k in ("EQ", "GS", "GD", "CA")}
    out, _ = tac.tilt("permanent_portfolio", _sleeves(), closes, max_step_pct=50.0)
    assert abs(sum(out.values()) - 100.0) < 0.05
    # equal would be 25 each; equity floor 35 forces it up, others absorb
    assert out["equity"] == pytest.approx(35.0, abs=0.5)


def test_risk_parity_lite_downweights_the_volatile_asset():
    # EQ very choppy, GS calm
    import random

    rng = random.Random(0)

    def choppy(vol):
        out, p = [], 100.0
        for _ in range(320):
            out.append(round(p, 4))
            p *= 1.0 + rng.uniform(-vol, vol)
        return out

    closes = {"EQ": choppy(0.03), "GS": choppy(0.002), "GD": choppy(0.01), "CA": choppy(0.0005)}
    out, _ = tac.tilt("risk_parity_lite", _sleeves(), closes, max_step_pct=50.0)
    assert abs(sum(out.values()) - 100.0) < 0.05
    assert out["equity"] < 40.0          # choppiest asset pulled below strategic
    assert out["gsec"] >= 20.0 - 1e-6    # calmest asset held at/above strategic


def test_resolve_targets_applies_the_tactical_overlay():
    spec = parse_spec({
        "sleeves": [
            {"id": "equity", "name": "Indian Equity", "weight_pct": 40.0, "weighting": "equal",
             "members": ["NIFTYBEES"], "rule": {"type": "none"}, "risk_asset": False},
            {"id": "gsec", "name": "Government Bonds", "weight_pct": 30.0, "weighting": "equal",
             "members": ["GSEC10IETF"], "rule": {"type": "none"}, "risk_asset": False},
            {"id": "gold", "name": "Gold", "weight_pct": 30.0, "weighting": "equal",
             "members": ["GOLDBEES"], "rule": {"type": "none"}, "risk_asset": False},
        ],
        "tactical": {
            "model": "trend_tilt", "max_step_pct": 8.0,
            "bands": {"equity": [40, 30, 55], "gsec": [30, 20, 40], "gold": [30, 15, 45]},
        },
    })
    bars = {
        "NIFTYBEES": _bars("NIFTYBEES", 0.004),
        "GSEC10IETF": _bars("GSEC10IETF", 0.0002),
        "GOLDBEES": _bars("GOLDBEES", 0.0003),
    }
    res = resolve_targets(spec, bars, datetime(2020, 11, 1))
    assert res.weights["NIFTYBEES"] > 0.40         # equity tilted up from 40%
    assert res.weights["NIFTYBEES"] <= 0.48 + 1e-6  # 40 + 8 step cap
    assert abs(res.invested - 1.0) < 1e-6
    assert any("tactical" in n for n in res.notes)
    eq = next(s for s in res.per_sleeve if s.sleeve_id == "equity")
    assert eq.target_pct > 40.0


def test_tactical_spec_validation():
    base = {
        "sleeves": [
            {"id": "a", "name": "A", "weight_pct": 60.0, "members": ["X"], "rule": {"type": "none"}},
            {"id": "b", "name": "B", "weight_pct": 40.0, "members": ["Y"], "rule": {"type": "none"}},
        ],
    }
    ok = parse_spec({**base, "tactical": {
        "model": "trend_tilt",
        "bands": {"a": [60, 40, 80], "b": [40, 20, 60]},
    }})
    assert ok.tactical is not None and ok.tactical.active
    assert ok.to_dict()["tactical"]["model"] == "trend_tilt"

    # strategic must match the sleeve weight
    with pytest.raises(SpecError):
        parse_spec({**base, "tactical": {"model": "trend_tilt",
                                         "bands": {"a": [55, 40, 80], "b": [40, 20, 60]}}})
    # a sleeve is missing a band
    with pytest.raises(SpecError):
        parse_spec({**base, "tactical": {"model": "trend_tilt", "bands": {"a": [60, 40, 80]}}})
    # unknown model
    with pytest.raises(SpecError):
        parse_spec({**base, "tactical": {"model": "wizardry",
                                         "bands": {"a": [60, 40, 80], "b": [40, 20, 60]}}})
    # ceilings cannot cover 100
    with pytest.raises(SpecError):
        parse_spec({**base, "tactical": {"model": "trend_tilt",
                                         "bands": {"a": [60, 40, 45], "b": [40, 20, 50]}}})
