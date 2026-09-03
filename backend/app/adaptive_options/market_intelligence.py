"""Phase 2 — Market Intelligence: price / trend / structure / volume features
from the underlying's candles. Indicators are *features and confirmations*,
not standalone signals.

Inputs:
  daily_bars    — needed; trend, structure, ADX, ATR, RSI, BB-width history
  intraday_bars — optional; session VWAP, intraday & previous-day H/L,
                  relative volume
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import IntelReport
from app.strategies.indicators import (
    adx,
    atr,
    bollinger,
    ema,
    rolling_volatility,
    rsi,
    sma,
)


def _f(v: Any) -> float:
    return float(v)


def _bar_date(b: Any) -> date | None:
    ts = getattr(b, "timestamp", None)
    if ts is None:
        return None
    s = str(ts)
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _swings(highs: list[float], lows: list[float], k: int = 2) -> tuple[list[float], list[float]]:
    sh, sl = [], []
    for i in range(k, len(highs) - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            sh.append(highs[i])
        if lows[i] == min(lows[i - k:i + k + 1]):
            sl.append(lows[i])
    return sh, sl


def _structure(highs: list[float], lows: list[float], closes: list[float],
               atr_now: float | None, atr_ref: float | None, bbw_pctile: float | None) -> str:
    if len(closes) < 12:
        return "RANGE"
    sh, sl = _swings(highs[-40:], lows[-40:])
    hh = len(sh) >= 2 and sh[-1] > sh[-2]
    hl = len(sl) >= 2 and sl[-1] > sl[-2]
    lh = len(sh) >= 2 and sh[-1] < sh[-2]
    ll = len(sl) >= 2 and sl[-1] < sl[-2]

    expanding = atr_now is not None and atr_ref is not None and atr_now > atr_ref * 1.25
    compressing = (atr_now is not None and atr_ref is not None and atr_now < atr_ref * 0.8) or \
                  (bbw_pctile is not None and bbw_pctile < 20.0)

    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    if hh and ll:
        return "EXPANSION" if expanding else "RANGE"
    if lh and hl:
        return "COMPRESSION" if compressing else "RANGE"
    if expanding:
        return "EXPANSION"
    if compressing:
        return "COMPRESSION"
    # a fresh flip vs the prior leg
    if len(sh) >= 3 and len(sl) >= 3:
        if sh[-1] > sh[-2] and sh[-2] < sh[-3]:
            return "REVERSAL_UP"
        if sl[-1] < sl[-2] and sl[-2] > sl[-3]:
            return "REVERSAL_DOWN"
    return "RANGE"


def _bb_width_percentile(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 30:
        return None
    widths: list[float] = []
    for i in range(period, len(closes) + 1):
        bb = bollinger(closes[:i], period)
        if bb:
            lo, mid, hi = bb
            if mid:
                widths.append((hi - lo) / mid)
    if len(widths) < 20:
        return None
    cur = widths[-1]
    return 100.0 * sum(1 for w in widths if w <= cur) / len(widths)


def _session_vwap(bars: list[Any]) -> float | None:
    if not bars:
        return None
    last_d = _bar_date(bars[-1])
    pv = v = 0.0
    for b in bars:
        if _bar_date(b) != last_d:
            continue
        typ = (_f(b.high) + _f(b.low) + _f(b.close)) / 3.0
        vol = _f(getattr(b, "volume", 0.0) or 0.0)
        pv += typ * vol
        v += vol
    return pv / v if v > 0 else None


def _prev_and_today(bars: list[Any]) -> tuple[float | None, float | None, float | None, float | None]:
    if not bars:
        return None, None, None, None
    by_day: dict[date, list[Any]] = {}
    for b in bars:
        d = _bar_date(b)
        if d:
            by_day.setdefault(d, []).append(b)
    days = sorted(by_day)
    today_hi = today_lo = prev_hi = prev_lo = None
    if days:
        t = by_day[days[-1]]
        today_hi = max(_f(x.high) for x in t)
        today_lo = min(_f(x.low) for x in t)
    if len(days) >= 2:
        p = by_day[days[-2]]
        prev_hi = max(_f(x.high) for x in p)
        prev_lo = min(_f(x.low) for x in p)
    return prev_hi, prev_lo, today_hi, today_lo


def analyse(
    daily_bars: list[Any], cfg: AdaptiveConfig, *, intraday_bars: list[Any] | None = None
) -> IntelReport:
    intraday_bars = intraday_bars or []
    dc = [_f(b.close) for b in daily_bars]
    dh = [_f(b.high) for b in daily_bars]
    dl = [_f(b.low) for b in daily_bars]
    dvol = [_f(getattr(b, "volume", 0.0) or 0.0) for b in daily_bars]

    ef = ema(dc, cfg.ema_fast)
    es = ema(dc, cfg.ema_slow)
    et = ema(dc, cfg.ema_trend)
    price = dc[-1] if dc else 0.0

    if ef and es and et:
        if price > ef > es > et:
            stack = "BULLISH"
        elif price < ef < es < et:
            stack = "BEARISH"
        else:
            stack = "MIXED"
    elif ef and es:
        stack = "BULLISH" if ef > es and price > es else "BEARISH" if ef < es and price < es else "MIXED"
    else:
        stack = "MIXED"

    adx_v = adx(dh, dl, dc, cfg.adx_period)
    rsi_v = rsi(dc, cfg.rsi_period)
    atr_v = atr(dh, dl, dc, cfg.atr_period)
    atr_ref = atr(dh[:-10], dl[:-10], dc[:-10], cfg.atr_period) if len(dc) > cfg.atr_period + 12 else None
    atr_pct = (atr_v / price * 100.0) if (atr_v and price) else None
    bbw_pctile = _bb_width_percentile(dc, 20)

    # trend
    slope_ref = sma(dc[:-5], cfg.ema_slow) if len(dc) > cfg.ema_slow + 6 else None
    slope = ((es - slope_ref) / slope_ref) if (es and slope_ref) else 0.0
    if adx_v is not None and adx_v >= cfg.adx_trend_min and abs(slope) > 1e-4:
        direction = "UP" if slope > 0 else "DOWN"
    else:
        direction = "SIDEWAYS"
    trend_strength = min(100.0, (adx_v or 0.0) / max(cfg.adx_strong_min, 1e-6) * 70.0)

    # momentum from a short MACD-like read
    m_now = ema(dc, 12)
    m_slow = ema(dc, 26)
    prev = ema(dc[:-3], 12), ema(dc[:-3], 26)
    hist_now = (m_now - m_slow) if (m_now and m_slow) else 0.0
    hist_prev = (prev[0] - prev[1]) if (prev[0] and prev[1]) else 0.0
    momentum = "RISING" if hist_now > hist_prev * 1.02 and hist_now > 0 else \
               "FALLING" if hist_now < hist_prev * 1.02 and hist_now < 0 else "FLAT"

    structure = _structure(dh, dl, dc, atr_v, atr_ref, bbw_pctile)

    # VWAP / intraday / prev-day (from intraday bars if we have them)
    vwap = _session_vwap(intraday_bars)
    prev_hi, prev_lo, today_hi, today_lo = _prev_and_today(intraday_bars)
    if prev_hi is None and len(daily_bars) >= 2:
        prev_hi, prev_lo = dh[-2], dl[-2]
    if today_hi is None and daily_bars:
        today_hi, today_lo = dh[-1], dl[-1]

    if vwap and vwap > 0:
        vwap_dist = (price - vwap) / vwap * 100.0
        above_vwap = price >= vwap
    else:
        vwap_dist = 0.0
        above_vwap = bool(es and price >= es)   # fall back to the slow EMA

    # volume
    src_vol = [_f(getattr(b, "volume", 0.0) or 0.0) for b in intraday_bars] if intraday_bars else dvol
    rel_vol = None
    vol_trend = "STABLE"
    pv_rel = "NEUTRAL"
    if len(src_vol) > cfg.rel_volume_lookback + 2:
        base = sum(src_vol[-cfg.rel_volume_lookback - 1:-1]) / cfg.rel_volume_lookback
        rel_vol = src_vol[-1] / base if base > 0 else None
        recent = sum(src_vol[-5:]) / 5.0
        older = sum(src_vol[-15:-5]) / 10.0 if len(src_vol) >= 15 else recent
        vol_trend = "EXPANDING" if recent > older * 1.2 else "CONTRACTING" if recent < older * 0.8 else "STABLE"
        # price-volume confirmation over the same short window
        ref_c = dc if not intraday_bars else [_f(b.close) for b in intraday_bars]
        if len(ref_c) >= 6:
            up = ref_c[-1] > ref_c[-6]
            if (up and vol_trend == "EXPANDING") or (not up and vol_trend == "EXPANDING" and ref_c[-1] < ref_c[-6]):
                pv_rel = "CONFIRMING"
            elif up and vol_trend == "CONTRACTING":
                pv_rel = "DIVERGING"

    # support / resistance from recent swings + prev day levels
    sh, sl = _swings(dh[-60:], dl[-60:])
    below = [s for s in ([prev_lo] if prev_lo else []) + sl if s and s < price]
    above = [s for s in ([prev_hi] if prev_hi else []) + sh if s and s > price]
    support = max(below) if below else None
    resistance = min(above) if above else None

    rv = rolling_volatility(dc, cfg.rv_lookback_days)

    return IntelReport(
        trend_direction=direction,
        trend_strength=round(trend_strength, 1),
        momentum=momentum,
        market_structure=structure,
        vwap_distance_pct=round(vwap_dist, 3),
        above_vwap=above_vwap,
        ema_stack=stack,
        rsi=round(rsi_v, 1) if rsi_v is not None else None,
        adx=round(adx_v, 1) if adx_v is not None else None,
        atr_pct=round(atr_pct, 3) if atr_pct is not None else None,
        bb_width_pctile=round(bbw_pctile, 1) if bbw_pctile is not None else None,
        rel_volume=round(rel_vol, 2) if rel_vol is not None else None,
        volume_trend=vol_trend,
        price_volume=pv_rel,
        prev_day_high=prev_hi, prev_day_low=prev_lo,
        intraday_high=today_hi, intraday_low=today_lo,
        support=support, resistance=resistance,
        features={
            "ema_fast": ef, "ema_slow": es, "ema_trend": et, "vwap": vwap,
            "slope_pct": round(slope * 100.0, 3),
            "realized_vol": round(rv, 4) if rv is not None else None,
            "close": price,
        },
    )
