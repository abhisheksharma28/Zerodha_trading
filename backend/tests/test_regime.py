"""Shared 5-state market regime engine."""

from __future__ import annotations

from app.regime import classify, exposure_scale, factor_tilt
from app.regime.engine import REGIMES


def _series(n: int, daily: float, start: float = 100.0, noise=None) -> list[float]:
    out = [start]
    for i in range(n - 1):
        bump = 1.0 + daily + (noise(i) if noise else 0.0)
        out.append(max(out[-1] * bump, 0.01))
    return out


def test_strong_uptrend_is_a_bull_regime():
    st = classify(_series(320, 0.0015))
    assert st.regime in ("bull", "strong_bull")
    assert st.score > 60
    assert st.signals["trend"] >= 0.9


def test_choppy_decline_is_caution_or_risk_off():
    st = classify(_series(320, -0.005, noise=lambda i: 0.03 if i % 2 else -0.028))
    assert st.regime in ("caution", "risk_off")
    assert st.score < 42
    assert st.signals["drawdown"] < 0.4


def test_high_vix_pushes_the_volatility_signal_down():
    closes = _series(320, 0.0005)
    calm = classify(closes, vix_closes=[11.0])
    stressed = classify(closes, vix_closes=[26.0])
    assert calm.signals["volatility"] > stressed.signals["volatility"]
    assert stressed.regime in REGIMES


def test_short_history_falls_back_to_neutral():
    st = classify(_series(15, 0.001))
    assert st.regime == "neutral" and "insufficient" in st.drivers[0]


def test_exposure_scale_never_below_the_basket_floor_and_full_in_a_bull():
    assert exposure_scale("strong_bull", floor=0.4) == 1.0
    assert exposure_scale("bull", floor=0.4) == 1.0
    assert exposure_scale("neutral", floor=0.4) == 0.85
    assert exposure_scale("caution", floor=0.4) == 0.55  # weak tape -> defensive
    assert exposure_scale("caution", floor=0.7) == 0.7   # floor wins
    assert exposure_scale("risk_off", floor=0.4) == 0.4  # risk_off is the floor
    assert exposure_scale("risk_off", floor=0.5) == 0.5


def test_hard_cut_drops_straight_to_the_floor_outside_a_bull():
    assert exposure_scale("neutral", floor=0.4, hard_cut=True) == 0.4
    assert exposure_scale("caution", floor=0.4, hard_cut=True) == 0.4
    assert exposure_scale("risk_off", floor=0.4, hard_cut=True) == 0.4
    # a bull is still full exposure even with hard_cut
    assert exposure_scale("bull", floor=0.4, hard_cut=True) == 1.0
    assert exposure_scale("strong_bull", floor=0.4, hard_cut=True) == 1.0


def test_factor_tilt_shifts_toward_defensives_in_risk_off_and_renormalises():
    w = {"momentum": 0.5, "trend": 0.2, "low_vol": 0.15, "quality": 0.15}
    ro = factor_tilt("risk_off", w)
    assert abs(sum(ro.values()) - 1.0) < 1e-9
    assert ro["low_vol"] > w["low_vol"] and ro["quality"] > w["quality"]
    assert ro["momentum"] < w["momentum"]

    sb = factor_tilt("strong_bull", w)
    assert sb["momentum"] > w["momentum"] and sb["low_vol"] < w["low_vol"]

    # neutral and unknown regimes are a no-op
    assert factor_tilt("neutral", w) == w
    assert factor_tilt("whatever", w) == w


def test_factor_tilt_only_moves_factors_already_in_the_profile():
    w = {"momentum": 0.7, "trend": 0.3}  # no low_vol / quality
    ro = factor_tilt("risk_off", w)
    assert set(ro) == {"momentum", "trend"}
    assert abs(sum(ro.values()) - 1.0) < 1e-9
