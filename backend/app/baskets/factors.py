"""Price-based factor library for the basket ranking engine.

Pure functions over a causal list of closing prices (oldest first). Each
returns a raw factor value where **higher is better**; the engine turns
raw values into cross-sectional percentile ranks and blends them per the
sleeve's ``factor_weights``.

Only price factors live here. Quality / growth / value come from latest
fundamentals on the live signal and are handled in the engine, not here.

Phase 2: multi-horizon momentum, multi-MA trend, downside-only volatility,
distance from the 52-week high, relative strength vs a market series, and
a volume / participation trend.
"""

from __future__ import annotations

import math

_YEAR = 252


def roc(closes: list[float], lookback: int) -> float | None:
    """Simple rate of change over ``lookback`` bars, in %."""
    if lookback <= 0 or len(closes) <= lookback:
        return None
    past = closes[-lookback - 1]
    if past <= 0:
        return None
    return (closes[-1] / past - 1.0) * 100.0


def sma(closes: list[float], window: int) -> float | None:
    if window <= 0 or len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def momentum_composite(closes: list[float]) -> float | None:
    """Blend of 12-1 month, 6 month and 3 month returns.

    The 6-month term is the anchor (this is what the single-lookback
    engine used); the 12-1 and 3-month terms refine it. Falls back
    gracefully when there is < ~1y of history.
    """
    r3 = roc(closes, 63)
    r6 = roc(closes, 126)
    if r6 is None and r3 is None:
        return None
    # 12-month excluding the most recent month (252 back to 21 back)
    r12x1 = None
    if len(closes) > _YEAR + 1 and closes[-_YEAR - 1] > 0 and len(closes) > 21:
        r12x1 = (closes[-22] / closes[-_YEAR - 1] - 1.0) * 100.0

    terms: list[tuple[float, float]] = []  # (value, weight)
    if r12x1 is not None:
        terms.append((r12x1, 0.35))
    if r6 is not None:
        terms.append((r6, 0.40))
    if r3 is not None:
        terms.append((r3, 0.25))
    if not terms:
        return None
    wsum = sum(w for _v, w in terms)
    return sum(v * w for v, w in terms) / wsum


def dist_from_high(closes: list[float], window: int = _YEAR) -> float | None:
    """0 at a fresh high, negative the further below the rolling high —
    so 'closer to the 52-week high' ranks higher."""
    seg = closes[-window:] if len(closes) >= 20 else closes
    if len(seg) < 20:
        return None
    hi = max(seg)
    if hi <= 0:
        return None
    return (closes[-1] / hi - 1.0) * 100.0


def trend_composite(closes: list[float], trend_ma: int = 200) -> float | None:
    """Primary term is distance above the main trend MA (what the engine
    used); refined by how many of the shorter MAs price sits above and by
    the slope of the 50-day MA."""
    main = sma(closes, trend_ma or 200)
    if main is None or main <= 0:
        return None
    primary = closes[-1] / main - 1.0

    checks: list[bool] = []
    ma50, ma100, ma200 = sma(closes, 50), sma(closes, 100), sma(closes, 200)
    if ma50 is not None:
        checks.append(closes[-1] > ma50)
    if ma100 is not None:
        checks.append(closes[-1] > ma100)
    if ma200 is not None:
        checks.append(closes[-1] > ma200)
    if ma50 is not None and ma200 is not None:
        checks.append(ma50 > ma200)
    structure = (sum(checks) / len(checks) - 0.5) if checks else 0.0  # -0.5..+0.5

    slope = 0.0
    ma50_prev = sma(closes[:-20], 50) if len(closes) >= 70 else None
    if ma50 is not None and ma50_prev is not None and ma50_prev > 0:
        slope = max(-0.1, min(0.1, ma50 / ma50_prev - 1.0))

    return 0.6 * primary + 0.3 * structure + 0.1 * (slope * 5.0)


def _daily_returns(closes: list[float], window: int) -> list[float]:
    seg = closes[-(window + 1):]
    return [seg[i] / seg[i - 1] - 1.0 for i in range(1, len(seg)) if seg[i - 1] > 0]


def total_vol(closes: list[float], window: int) -> float | None:
    rets = _daily_returns(closes, window)
    if len(rets) < 5:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(_YEAR)


def downside_deviation(closes: list[float], window: int) -> float | None:
    """Annualised standard deviation of *negative* daily returns only.
    Penalises drawdown risk without punishing upside volatility."""
    rets = _daily_returns(closes, window)
    if len(rets) < 5:
        return None
    downs = [r for r in rets if r < 0]
    if len(downs) < 3:
        return 0.0
    dd = math.sqrt(sum(r * r for r in downs) / len(downs))
    return dd * math.sqrt(_YEAR)


def low_vol_score(closes: list[float], window: int) -> float | None:
    """Higher = calmer. Blend of low downside deviation and low total
    volatility, returned negated so 'less vol' ranks higher."""
    dd = downside_deviation(closes, window)
    tv = total_vol(closes, window)
    if dd is None and tv is None:
        return None
    parts = [x for x in (dd, tv) if x is not None]
    return -(sum(parts) / len(parts))


def relative_strength(
    closes: list[float], market_closes: list[float] | None, lookback: int = 126
) -> float | None:
    """Excess return over the market series over ``lookback`` bars, in %.
    Positive means the name is outperforming the benchmark."""
    if not market_closes:
        return None
    r = roc(closes, lookback)
    rm = roc(market_closes, lookback)
    if r is None or rm is None:
        return None
    return r - rm


def volume_trend(
    volumes: list[float], closes: list[float], short: int = 21, long: int = 63
) -> float | None:
    """Relative volume (recent vs longer average), signed by the recent
    price direction — expanding volume into a rising price reads as
    accumulation and ranks higher."""
    if len(volumes) < long + 1 or len(closes) < short + 1:
        return None
    v_short = sum(volumes[-short:]) / short
    v_long = sum(volumes[-long:]) / long
    if v_long <= 0:
        return None
    rel = v_short / v_long - 1.0
    base = closes[-short - 1]
    direction = 1.0 if (base > 0 and closes[-1] >= base) else -1.0
    return rel * direction
