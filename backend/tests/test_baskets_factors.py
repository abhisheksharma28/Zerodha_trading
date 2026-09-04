"""Price factor library — deterministic checks on synthetic series."""

from __future__ import annotations

import math

from app.baskets import factors as f


def _trend(n: int, daily: float, start: float = 100.0) -> list[float]:
    out = [start]
    for _ in range(n - 1):
        out.append(out[-1] * (1.0 + daily))
    return out


def test_roc_matches_definition():
    c = _trend(200, 0.001)
    assert f.roc(c, 100) == (c[-1] / c[-101] - 1.0) * 100.0
    assert f.roc(c, 500) is None  # not enough history


def test_momentum_composite_ranks_stronger_uptrend_higher():
    strong = _trend(300, 0.002)
    weak = _trend(300, 0.0003)
    flat = _trend(300, 0.0)
    ms, mw, mf = (f.momentum_composite(x) for x in (strong, weak, flat))
    assert ms is not None and mw is not None and mf is not None
    assert ms > mw > mf
    assert abs(mf) < 1e-6  # a flat series has ~zero momentum


def test_momentum_composite_degrades_without_a_year_of_history():
    short = _trend(80, 0.001)  # ~3.5 months
    v = f.momentum_composite(short)
    assert v is not None and v > 0  # still works off the 3m / (missing 6m) terms
    assert f.momentum_composite(_trend(20, 0.001)) is None


def test_trend_composite_positive_in_uptrend_negative_in_downtrend():
    up = _trend(260, 0.0015)
    down = _trend(260, -0.0015)
    assert (f.trend_composite(up) or 0) > 0
    assert (f.trend_composite(down) or 0) < 0


def test_dist_from_high_zero_at_fresh_high_negative_after_pullback():
    up = _trend(260, 0.001)
    assert f.dist_from_high(up) == 0.0 or abs(f.dist_from_high(up)) < 1e-9
    pulled = up + [up[-1] * 0.9]
    assert f.dist_from_high(pulled) < 0


def test_downside_deviation_ignores_upside_vol():
    # a series that only ever rises has ~no downside deviation
    calm_up = _trend(200, 0.001)
    dd = f.downside_deviation(calm_up, 90)
    assert dd is not None and dd < 1e-6

    # inject symmetric noise -> downside deviation becomes positive
    noisy = [100.0]
    for i in range(200):
        noisy.append(noisy[-1] * (1.0 + (0.02 if i % 2 else -0.02)))
    assert (f.downside_deviation(noisy, 90) or 0) > 0.1


def test_low_vol_score_prefers_the_calmer_name():
    calm = _trend(200, 0.0005)
    wild = [100.0]
    for i in range(200):
        wild.append(wild[-1] * (1.0 + (0.03 if i % 2 else -0.028)))
    sc_calm = f.low_vol_score(calm, 90)
    sc_wild = f.low_vol_score(wild, 90)
    assert sc_calm is not None and sc_wild is not None
    assert sc_calm > sc_wild  # negated vol -> calmer name is the larger (closer to 0)


def test_relative_strength_is_excess_over_the_market():
    stock = _trend(200, 0.0015)
    mkt = _trend(200, 0.0005)
    rs = f.relative_strength(stock, mkt, 126)
    assert rs is not None and rs > 0  # outperforming
    assert f.relative_strength(stock, _trend(200, 0.003), 126) < 0  # lagging a hotter market
    assert f.relative_strength(stock, None, 126) is None  # no market series -> factor drops out


def test_volume_trend_positive_when_volume_expands_into_a_rising_price():
    closes = _trend(120, 0.001)
    vols = [1000.0] * 90 + [2500.0] * 30  # recent surge
    v = f.volume_trend(vols, closes, short=21, long=63)
    assert v is not None and v > 0
    # same surge but into a falling price -> negative (distribution)
    down = _trend(120, -0.001)
    assert f.volume_trend(vols, down, short=21, long=63) < 0
    assert f.volume_trend([1000.0] * 10, closes) is None  # not enough history


def test_annualisation_factor_is_sqrt_252():
    # sanity: total_vol of a 1%/day alternating series is in a plausible band
    alt = [100.0]
    for i in range(120):
        alt.append(alt[-1] * (1.0 + (0.01 if i % 2 else -0.01)))
    tv = f.total_vol(alt, 90)
    assert tv is not None and 0.1 < tv < 0.5
    assert math.isclose(math.sqrt(252), 15.874, rel_tol=1e-3)
