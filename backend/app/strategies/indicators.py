"""Reusable, dependency-light technical indicators.

Every function here is *causal*: the value it returns for the most recent
point is computed only from that point and earlier ones. None of them look
at future data, which is what lets the strategy templates in
app.strategies.library stay free of look-ahead bias by construction.

Inputs are plain sequences of floats (a strategy keeps its own rolling
buffer, usually a collections.deque with maxlen). Functions return either a
single scalar (the latest value) or, where noted, a list aligned to the
input. ``None`` is returned when there is not enough data yet.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as _np


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: Sequence[float], period: int) -> float | None:
    """Standard EMA seeded with the SMA of the first ``period`` points."""
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def rolling_mean(values: Sequence[float], period: int) -> float | None:
    return sma(values, period)


def rolling_std(values: Sequence[float], period: int, *, ddof: int = 1) -> float | None:
    if period <= 1 or len(values) < period:
        return None
    window = values[-period:]
    m = sum(window) / period
    var = sum((x - m) ** 2 for x in window) / (period - ddof)
    return math.sqrt(var) if var > 0 else 0.0


def zscore(values: Sequence[float], period: int) -> float | None:
    m = rolling_mean(values, period)
    s = rolling_std(values, period)
    if m is None or s is None or s == 0:
        return None
    return (values[-1] - m) / s


def roc(values: Sequence[float], period: int) -> float | None:
    """Rate of change over ``period`` steps, as a fraction (0.05 == +5%)."""
    if period <= 0 or len(values) <= period:
        return None
    past = values[-period - 1]
    if past == 0:
        return None
    return values[-1] / past - 1.0


def rolling_volatility(values: Sequence[float], period: int) -> float | None:
    """Stdev of simple returns over the last ``period`` bars (per-bar vol)."""
    if period <= 1 or len(values) < period + 1:
        return None
    window = values[-period - 1:]
    rets = [
        window[i] / window[i - 1] - 1.0
        for i in range(1, len(window))
        if window[i - 1] != 0
    ]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) if var > 0 else 0.0


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> float | None:
    """Wilder's ATR. Needs ``period + 1`` bars."""
    n = len(closes)
    if period <= 0 or n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = [true_range(highs[i], lows[i], closes[i - 1]) for i in range(1, n)]
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if period <= 0 or len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def bollinger(
    values: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float] | None:
    """Returns (lower, mid, upper)."""
    mid = rolling_mean(values, period)
    sd = rolling_std(values, period)
    if mid is None or sd is None:
        return None
    return (mid - num_std * sd, mid, mid + num_std * sd)


def vwap(prices: Sequence[float], volumes: Sequence[float]) -> float | None:
    """Cumulative VWAP over the sequences given (typically one session)."""
    if not prices or len(prices) != len(volumes):
        return None
    tv = sum(volumes)
    if tv <= 0:
        return None
    return sum(p * v for p, v in zip(prices, volumes, strict=True)) / tv


def crossed_above(fast_prev: float, slow_prev: float, fast_now: float, slow_now: float) -> bool:
    return fast_prev <= slow_prev and fast_now > slow_now


def crossed_below(fast_prev: float, slow_prev: float, fast_now: float, slow_now: float) -> bool:
    return fast_prev >= slow_prev and fast_now < slow_now


def rolling_correlation(x: Sequence[float], y: Sequence[float], period: int) -> float | None:
    """Pearson correlation of the last ``period`` overlapping samples."""
    if period < 3 or len(x) < period or len(y) < period:
        return None
    xs = list(x[-period:])
    ys = list(y[-period:])
    n = float(period)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(period))
    vx = sum((xs[i] - mx) ** 2 for i in range(period))
    vy = sum((ys[i] - my) ** 2 for i in range(period))
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def rolling_beta(y: Sequence[float], x: Sequence[float], period: int) -> float | None:
    """OLS slope of ``y`` on ``x`` over the last ``period`` points (hedge
    ratio for pairs trading). Uses the last ``period`` overlapping samples."""
    if period < 3 or len(y) < period or len(x) < period:
        return None
    ys = list(y[-period:])
    xs = list(x[-period:])
    n = float(period)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(period))
    var = sum((xs[i] - mx) ** 2 for i in range(period))
    if var == 0:
        return None
    return cov / var


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline as a positive fraction (0.2 == -20%)."""
    peak = -math.inf
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def adf_tstat(series: Sequence[float], max_lag: int = 1) -> float | None:
    """Augmented Dickey-Fuller t-statistic on the AR(1) coefficient.

    A more negative value is stronger evidence the series is stationary
    (mean-reverting). Rough critical values: ~-2.9 (5%), ~-3.5 (1%). Used by
    the pairs template's optional cointegration gate; deliberately a light
    hand-rolled OLS rather than pulling in statsmodels.
    """
    y = _np.asarray(series, dtype=float)
    if y.size < max_lag + 10:
        return None
    dy = _np.diff(y)
    lag_y = y[:-1]
    rows = dy.size - max_lag
    if rows < 5:
        return None
    X = [lag_y[max_lag:]]
    for i in range(1, max_lag + 1):
        X.append(dy[max_lag - i : -i])
    X.append(_np.ones(rows))
    Xm = _np.column_stack(X)
    yv = dy[max_lag:]
    beta, *_ = _np.linalg.lstsq(Xm, yv, rcond=None)
    resid = yv - Xm @ beta
    dof = rows - Xm.shape[1]
    if dof <= 0:
        return None
    sigma2 = float(resid @ resid) / dof
    xtx_inv = _np.linalg.pinv(Xm.T @ Xm)
    se_gamma = math.sqrt(sigma2 * xtx_inv[0, 0]) if xtx_inv[0, 0] > 0 else None
    if not se_gamma:
        return None
    return float(beta[0] / se_gamma)
