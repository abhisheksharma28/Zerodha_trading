"""Unit tests for the reusable indicator library (no DB, no engine)."""

import math

from app.strategies.indicators import (
    adf_tstat,
    adx,
    atr,
    bollinger,
    crossed_above,
    crossed_below,
    ema,
    max_drawdown,
    roc,
    rolling_beta,
    rolling_correlation,
    rolling_std,
    rolling_volatility,
    rsi,
    sma,
    zscore,
)


def test_sma_and_ema_basic():
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2], 5) is None
    # EMA seeded with SMA of first `period`, then recursed.
    e = ema([1, 2, 3, 4, 5, 6], 3)
    assert e is not None and 3.5 < e < 6


def test_rolling_std_and_zscore():
    vals = [10, 12, 14, 16, 18]  # mean 14, population-ish spread
    sd = rolling_std(vals, 5)
    assert sd is not None and abs(sd - math.sqrt(sum((v - 14) ** 2 for v in vals) / 4)) < 1e-9
    z = zscore(vals + [22], 5)  # last window [12,14,16,18,22], mean 16.4
    assert z is not None and z > 1


def test_roc_and_volatility():
    assert abs(roc([100, 110], 1) - 0.1) < 1e-9
    v = rolling_volatility([100, 101, 100, 101, 100, 101, 100], 6)
    assert v is not None and v > 0


def test_atr_needs_period_plus_one_and_is_positive():
    highs = [11, 12, 13, 12, 14, 15]
    lows = [9, 10, 11, 10, 12, 13]
    closes = [10, 11, 12, 11, 13, 14]
    assert atr(highs, lows, closes, 10) is None
    a = atr(highs, lows, closes, 3)
    assert a is not None and a > 0


def test_adx_low_in_chop_high_in_trend():
    # choppy: alternating up/down bars around a flat level
    n = 60
    chop_c = [100 + (i % 2) for i in range(n)]
    chop_h = [c + 0.5 for c in chop_c]
    chop_l = [c - 0.5 for c in chop_c]
    assert adx(chop_h, chop_l, chop_c, 5) is None or adx(chop_h, chop_l, chop_c, 14) < 30

    # clean uptrend
    tr_c = [100 + 2 * i for i in range(n)]
    tr_h = [c + 1 for c in tr_c]
    tr_l = [c - 1 for c in tr_c]
    strong = adx(tr_h, tr_l, tr_c, 14)
    assert strong is not None and strong > 40
    assert adx(tr_h, tr_l, tr_c, 100) is None  # not enough bars


def test_rsi_bounds_and_direction():
    rising = list(range(1, 40))
    falling = list(range(40, 1, -1))
    assert rsi(rising, 14) > 90
    assert rsi(falling, 14) < 10


def test_bollinger_ordering():
    band = bollinger([10, 11, 12, 13, 14, 13, 12, 11, 10, 11] * 3, 20, 2.0)
    assert band is not None
    lo, mid, hi = band
    assert lo < mid < hi


def test_rolling_beta_recovers_known_slope():
    x = [float(i) for i in range(50)]
    y = [3.0 * xi + 7.0 for xi in x]  # exact slope 3
    b = rolling_beta(y, x, 30)
    assert b is not None and abs(b - 3.0) < 1e-6


def test_rolling_correlation_extremes():
    x = [float(i) for i in range(40)]
    perfect = rolling_correlation(x, [2 * v + 1 for v in x], 30)
    inverse = rolling_correlation(x, [-v for v in x], 30)
    assert perfect is not None and abs(perfect - 1.0) < 1e-9
    assert inverse is not None and abs(inverse + 1.0) < 1e-9


def test_crossed_helpers():
    assert crossed_above(9, 10, 11, 10.5)
    assert not crossed_above(11, 10, 12, 10.5)
    assert crossed_below(11, 10, 9, 10.5)


def test_max_drawdown():
    assert abs(max_drawdown([100, 120, 90, 110]) - (30 / 120)) < 1e-9
    assert max_drawdown([100, 101, 102]) == 0.0


def test_adf_more_negative_for_stationary_series():
    import random

    random.seed(0)
    # Mean-reverting (AR(1) with phi ~ 0.2) vs a random walk.
    stat = [0.0]
    walk = [0.0]
    for _ in range(300):
        stat.append(0.2 * stat[-1] + random.gauss(0, 1))
        walk.append(walk[-1] + random.gauss(0, 1))
    t_stat = adf_tstat(stat)
    t_walk = adf_tstat(walk)
    assert t_stat is not None and t_walk is not None
    assert t_stat < t_walk  # stationary series has the more negative t-stat
