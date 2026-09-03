"""Turn raw candle series into the technical inputs the signal engine
scores. Pure functions over ``{open,high,low,close,volume}`` dict lists
(oldest-first); every indicator is reused from
``app.strategies.indicators`` so the numbers match the rest of the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.strategies.indicators import (
    adx,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
    vwap,
)


def _col(bars: list[dict[str, Any]], k: str) -> list[float]:
    return [float(b[k]) for b in bars]


@dataclass
class Features:
    timeframe: str
    bars: int
    close: float
    prev_close: float | None

    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    ema_stack: str = "MIXED"  # BULL | BEAR | MIXED  (20>50>200 / 20<50<200)
    golden_cross_age: int | None = None  # bars since 50 crossed above 200 (death cross -> negative)

    rsi14: float | None = None
    rsi_state: str = "NEUTRAL"  # OVERBOUGHT | BULLISH | NEUTRAL | BEARISH | OVERSOLD
    macd_hist: float | None = None
    macd_hist_prev: float | None = None
    macd_state: str = "FLAT"  # RISING_POS | RISING_NEG | FALLING_POS | FALLING_NEG | FLAT

    adx14: float | None = None
    atr14: float | None = None
    atr_pct: float | None = None

    bb_pctb: float | None = None  # position within the Bollinger band, 0..1 (can exceed)
    sma20: float | None = None

    vwap: float | None = None
    above_vwap: bool | None = None
    vwap_dist_pct: float | None = None

    day_high: float | None = None
    day_low: float | None = None
    prev_day_high: float | None = None
    prev_day_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None

    rel_volume: float | None = None  # today / 20-bar average
    notes: list[str] = field(default_factory=list)


def _cross_age(fast: list[float], slow: list[float], *, want: str) -> int | None:
    """Bars since the last fast/slow crossover of the requested kind
    ('above' or 'below'). None if no such cross in the series."""
    for i in range(len(fast) - 1, 0, -1):
        up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
        dn = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
        if want == "above" and up:
            return len(fast) - 1 - i
        if want == "below" and dn:
            return len(fast) - 1 - i
    return None


def _ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def daily_features(bars: list[dict[str, Any]]) -> Features:
    """Swing-timeframe read from ~250 daily bars."""
    n = len(bars)
    c = _col(bars, "close")
    h = _col(bars, "high")
    lo = _col(bars, "low")
    v = _col(bars, "volume")
    f = Features(timeframe="1d", bars=n, close=c[-1] if c else 0.0,
                 prev_close=c[-2] if n > 1 else None)
    if n < 30:
        f.notes.append(f"only {n} daily bars")
        return f

    f.ema20, f.ema50, f.ema200 = ema(c, 20), ema(c, 50), ema(c, 200)
    if f.ema20 and f.ema50 and f.ema200:
        if f.ema20 > f.ema50 > f.ema200:
            f.ema_stack = "BULL"
        elif f.ema20 < f.ema50 < f.ema200:
            f.ema_stack = "BEAR"
    e50s, e200s = _ema_series(c, 50), _ema_series(c, 200)
    if len(e50s) > 2 and len(e200s) > 2:
        m = min(len(e50s), len(e200s))
        up = _cross_age(e50s[-m:], e200s[-m:], want="above")
        dn = _cross_age(e50s[-m:], e200s[-m:], want="below")
        if up is not None and (dn is None or up < dn):
            f.golden_cross_age = up
        elif dn is not None:
            f.golden_cross_age = -dn

    f.rsi14 = rsi(c, 14)
    if f.rsi14 is not None:
        f.rsi_state = (
            "OVERBOUGHT" if f.rsi14 >= 70 else "BULLISH" if f.rsi14 >= 55
            else "OVERSOLD" if f.rsi14 <= 30 else "BEARISH" if f.rsi14 <= 45 else "NEUTRAL"
        )
    m_now = macd(c)
    if m_now is not None:
        hist = m_now[2]
        f.macd_hist = hist
        m_prev = macd(c[:-1]) if n > 35 else None
        hist_prev = m_prev[2] if m_prev is not None else None
        f.macd_hist_prev = hist_prev
        if hist_prev is not None:
            rising = hist > hist_prev
            f.macd_state = (
                ("RISING_POS" if hist >= 0 else "RISING_NEG") if rising
                else ("FALLING_POS" if hist >= 0 else "FALLING_NEG")
            )

    f.adx14 = adx(h, lo, c, 14)
    f.atr14 = atr(h, lo, c, 14)
    if f.atr14 and c[-1]:
        f.atr_pct = 100.0 * f.atr14 / c[-1]
    bb = bollinger(c, 20, 2.0)
    if bb:
        low_b, _mid, up_b = bb
        rng = up_b - low_b
        f.bb_pctb = (c[-1] - low_b) / rng if rng > 0 else None
    f.sma20 = sma(c, 20)

    f.day_high, f.day_low = h[-1], lo[-1]
    f.prev_day_high, f.prev_day_low = (h[-2], lo[-2]) if n > 1 else (None, None)
    if len(v) >= 21 and sum(v[-21:-1]) > 0:
        avg = sum(v[-21:-1]) / 20.0
        f.rel_volume = v[-1] / avg if avg > 0 else None
    return f


def intraday_features(bars: list[dict[str, Any]], *, opening_range_bars: int = 2) -> Features:
    """Entry-timeframe read from 15-minute bars of the current + prior session.
    ``bars`` should already be trimmed to a sensible window (~5 sessions)."""
    n = len(bars)
    c = _col(bars, "close")
    h = _col(bars, "high")
    lo = _col(bars, "low")
    v = _col(bars, "volume")
    f = Features(timeframe="15m", bars=n, close=c[-1] if c else 0.0,
                 prev_close=c[-2] if n > 1 else None)
    if n < 20:
        f.notes.append(f"only {n} intraday bars")
        return f

    f.ema20, f.ema50 = ema(c, 20), ema(c, 50)
    f.rsi14 = rsi(c, 14)
    m_now = macd(c)
    f.macd_hist = m_now[2] if m_now is not None else None
    f.adx14 = adx(h, lo, c, 14)
    f.atr14 = atr(h, lo, c, 14)
    if f.atr14 and c[-1]:
        f.atr_pct = 100.0 * f.atr14 / c[-1]

    # session VWAP: bars from the last calendar day present
    day_key = str(bars[-1].get("time") or "")[:10] if bars[-1].get("time") else None
    sess = [b for b in bars if str(b.get("time") or "")[:10] == day_key] if day_key else bars[-25:]
    sp = [(float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0 for b in sess]
    sv = [float(b["volume"]) for b in sess]
    f.vwap = vwap(sp, sv)
    if f.vwap and c[-1]:
        f.above_vwap = c[-1] >= f.vwap
        f.vwap_dist_pct = 100.0 * (c[-1] - f.vwap) / f.vwap
    if sess:
        f.day_high = max(float(b["high"]) for b in sess)
        f.day_low = min(float(b["low"]) for b in sess)
        orb = sess[:opening_range_bars]
        if orb:
            f.opening_range_high = max(float(b["high"]) for b in orb)
            f.opening_range_low = min(float(b["low"]) for b in orb)
    if len(v) >= 21 and sum(v[-21:-1]) > 0:
        avg = sum(v[-21:-1]) / 20.0
        f.rel_volume = v[-1] / avg if avg > 0 else None
    return f
