"""Feature engineering for IMIE — pure functions over 1-minute bars.

Six blocks, each returning a 0-100 score plus the raw readings that fed
it (for the explainability panel):

  * volatility_compression   — ATR / Bollinger-width / range percentiles
  * relative_volume          — TIME-OF-DAY adjusted, not daily-average
  * vwap                     — session VWAP direction / slope / compression
  * market_structure         — day & prior-day levels, opening range, breakout proximity
  * absorption               — ESTIMATED: volume-without-price-movement on 1m bars
  * (relative_strength lives in relative_strength() and needs the index/sector series)
"""

from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from app.imie.data import Bar
from app.strategies.indicators import atr, ema, rolling_std, roc, sma

_MIN_HISTORY_SESSIONS = 5


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _pct_rank(value: float, sample: list[float]) -> float:
    """Percentile of ``value`` within ``sample`` (0..100)."""
    if not sample:
        return 50.0
    below = sum(1 for s in sample if s < value)
    return _clip(below / len(sample) * 100.0)


# ---------------------------------------------------------------- volatility

def volatility_compression(session: list[Bar], hist_sessions: list[list[Bar]]) -> dict[str, Any]:
    if len(session) < 15:
        return {"score": None, "reason": "not enough intraday bars yet"}

    c = [b.close for b in session]
    h = [b.high for b in session]
    lo = [b.low for b in session]

    cur_atr = atr(h, lo, c, min(14, len(c) - 1))
    # Bollinger band width on 20-bar close
    n = min(20, len(c))
    mid = sma(c, n)
    sd = rolling_std(c, n)
    bbw = ((4 * sd) / mid) if (mid and sd) else None  # (upper-lower)/mid, 2 std

    session_range_pct = (max(h) - min(lo)) / c[0] * 100.0 if c[0] else None
    last15 = session[-15:]
    range15_pct = (max(b.high for b in last15) - min(b.low for b in last15)) / c[-1] * 100.0

    # historical same-length-of-session comparison
    hist_atr: list[float] = []
    hist_bbw: list[float] = []
    hist_r15: list[float] = []
    cutoff = session[-1].minute_of_day
    for hs in hist_sessions:
        upto = [b for b in hs if b.minute_of_day <= cutoff]
        if len(upto) < 15:
            continue
        hc = [b.close for b in upto]
        hh = [b.high for b in upto]
        hl = [b.low for b in upto]
        a = atr(hh, hl, hc, min(14, len(hc) - 1))
        if a:
            hist_atr.append(a / hc[-1])
        m = sma(hc, min(20, len(hc)))
        s = rolling_std(hc, min(20, len(hc)))
        if m and s:
            hist_bbw.append((4 * s) / m)
        l15 = upto[-15:]
        hist_r15.append((max(b.high for b in l15) - min(b.low for b in l15)) / hc[-1] * 100.0)

    enough = len(hist_atr) >= _MIN_HISTORY_SESSIONS
    atr_pctile = _pct_rank(cur_atr / c[-1], hist_atr) if (enough and cur_atr) else None
    bbw_pctile = _pct_rank(bbw, hist_bbw) if (enough and bbw is not None) else None
    r15_pctile = _pct_rank(range15_pct, hist_r15) if enough else None

    parts = [100.0 - p for p in (atr_pctile, bbw_pctile, r15_pctile) if p is not None]
    score = _clip(mean(parts)) if parts else None

    return {
        "score": round(score, 1) if score is not None else None,
        "atr_pct_of_price": round(cur_atr / c[-1] * 100.0, 3) if cur_atr else None,
        "atr_percentile": round(atr_pctile, 1) if atr_pctile is not None else None,
        "bollinger_width": round(bbw, 4) if bbw is not None else None,
        "bollinger_width_percentile": round(bbw_pctile, 1) if bbw_pctile is not None else None,
        "session_range_pct": round(session_range_pct, 2) if session_range_pct else None,
        "range_15m_pct": round(range15_pct, 3),
        "range_15m_percentile": round(r15_pctile, 1) if r15_pctile is not None else None,
        "history_sessions": len(hist_atr),
    }


# --------------------------------------------------- time-adjusted rel. volume

def relative_volume(session: list[Bar], hist_sessions: list[list[Bar]]) -> dict[str, Any]:
    if len(session) < 3:
        return {"score": None, "reason": "session just opened"}

    # baseline: mean & std of volume for the SAME minute-of-day across history
    by_minute: dict[int, list[float]] = {}
    for hs in hist_sessions:
        for b in hs:
            by_minute.setdefault(b.minute_of_day, []).append(b.volume)

    recent = session[-5:]
    rvols: list[float] = []
    zs: list[float] = []
    for b in recent:
        base = by_minute.get(b.minute_of_day, [])
        if len(base) < _MIN_HISTORY_SESSIONS:
            continue
        mu = mean(base)
        sd = pstdev(base) or 1.0
        if mu > 0:
            rvols.append(b.volume / mu)
        zs.append((b.volume - mu) / sd)

    if not rvols:
        return {"score": None, "reason": "not enough history for a time-of-day baseline"}

    rvol = mean(rvols)
    zscore = mean(zs) if zs else 0.0
    # cumulative session volume vs its historical same-time cumulative
    cutoff = session[-1].minute_of_day
    cur_cum = sum(b.volume for b in session)
    hist_cum = [
        sum(b.volume for b in hs if b.minute_of_day <= cutoff)
        for hs in hist_sessions
        if any(b.minute_of_day <= cutoff for b in hs)
    ]
    cum_pctile = _pct_rank(cur_cum, hist_cum) if len(hist_cum) >= _MIN_HISTORY_SESSIONS else None

    # acceleration: last 3 minutes rvol vs prior 3
    accel = None
    if len(session) >= 6:
        a = [b.volume for b in session[-3:]]
        p = [b.volume for b in session[-6:-3]]
        if sum(p) > 0:
            accel = sum(a) / sum(p)

    score = _clip(
        45.0 * min(rvol / 3.0, 1.0)          # 3x normal -> full marks on this leg
        + 30.0 * min(max(zscore, 0) / 3.0, 1.0)
        + 25.0 * ((cum_pctile or 50.0) / 100.0)
    )
    return {
        "score": round(score, 1),
        "rvol": round(rvol, 2),
        "volume_zscore": round(zscore, 2),
        "cumulative_percentile": round(cum_pctile, 1) if cum_pctile is not None else None,
        "acceleration": round(accel, 2) if accel is not None else None,
        "baseline_sessions": len(hist_sessions),
    }


# ------------------------------------------------------------------- vwap

def vwap_analysis(session: list[Bar]) -> dict[str, Any]:
    if len(session) < 10:
        return {"score": None, "reason": "not enough intraday bars yet"}
    tpv = 0.0
    vol = 0.0
    vwap_series: list[float] = []
    crosses = 0
    prev_side = 0
    for b in session:
        typ = (b.high + b.low + b.close) / 3.0
        tpv += typ * b.volume
        vol += b.volume
        v = tpv / vol if vol > 0 else b.close
        vwap_series.append(v)
        side = 1 if b.close > v else -1 if b.close < v else prev_side
        if prev_side and side and side != prev_side:
            crosses += 1
        prev_side = side

    v_now = vwap_series[-1]
    price = session[-1].close
    c = [b.close for b in session]
    atr_now = atr([b.high for b in session], [b.low for b in session], c, min(14, len(c) - 1)) or (
        abs(price) * 0.005
    )
    dist_atr = (price - v_now) / atr_now if atr_now else 0.0

    # slope: linear fit of the last 15 vwap points, normalised to % per bar
    tail = vwap_series[-15:]
    k = len(tail)
    xs = list(range(k))
    xm = sum(xs) / k
    ym = sum(tail) / k
    denom = sum((x - xm) ** 2 for x in xs) or 1.0
    slope = sum((xs[i] - xm) * (tail[i] - ym) for i in range(k)) / denom
    slope_pct = slope / v_now * 100.0 if v_now else 0.0

    direction_score = _clip(50.0 + dist_atr * 20.0 + slope_pct * 400.0)
    compression_score = _clip(100.0 - crosses * 12.0 - abs(slope_pct) * 300.0)
    return {
        "score": round(direction_score, 1),
        "direction_score": round(direction_score, 1),
        "compression_score": round(compression_score, 1),
        "vwap": round(v_now, 2),
        "distance_atr": round(dist_atr, 2),
        "slope_pct_per_bar": round(slope_pct, 4),
        "crosses": crosses,
        "side": "above" if price > v_now else "below" if price < v_now else "at",
    }


# -------------------------------------------------------- market structure

def market_structure(
    session: list[Bar], prev_day: dict[str, float] | None, opening_range_minutes: list[int]
) -> dict[str, Any]:
    if len(session) < 6:
        return {"score": None, "reason": "session just opened"}
    price = session[-1].close
    day_high = max(b.high for b in session)
    day_low = min(b.low for b in session)
    open_min = session[0].minute_of_day

    ors: dict[str, dict[str, float]] = {}
    for m in opening_range_minutes:
        win = [b for b in session if b.minute_of_day < open_min + m]
        if len(win) >= 2:
            ors[str(m)] = {"high": max(b.high for b in win), "low": min(b.low for b in win)}

    ref = ors.get(str(opening_range_minutes[0])) if opening_range_minutes else None
    or_high = ref["high"] if ref else day_high
    or_low = ref["low"] if ref else day_low
    c = [b.close for b in session]
    atr_now = atr([b.high for b in session], [b.low for b in session], c, min(14, len(c) - 1)) or (
        price * 0.005
    )

    up_room = (or_high - price) / atr_now if atr_now else None
    dn_room = (price - or_low) / atr_now if atr_now else None
    nearest = min(abs(up_room or 9), abs(dn_room or 9))

    # breakout test count: touches of the OR band without a close beyond it
    tests = sum(
        1 for b in session
        if (b.high >= or_high * 0.999 and b.close < or_high)
        or (b.low <= or_low * 1.001 and b.close > or_low)
    )
    # swing sequence over the last ~20 bars
    seq = _swing_bias(session[-20:])

    # score: tighter to a level + fewer failed tests + a clean swing sequence
    score = _clip(
        60.0 * (1.0 - min(nearest, 3.0) / 3.0)
        + 20.0 * (1.0 - min(tests, 5) / 5.0)
        + 20.0 * (abs(seq) )
    )
    breakout_side = "up" if (up_room is not None and up_room <= (dn_room or 9)) else "down"
    return {
        "score": round(score, 1),
        "day_high": round(day_high, 2),
        "day_low": round(day_low, 2),
        "prev_day_high": prev_day.get("high") if prev_day else None,
        "prev_day_low": prev_day.get("low") if prev_day else None,
        "opening_ranges": ors,
        "distance_to_breakout_atr": round(nearest, 2),
        "breakout_side": breakout_side,
        "breakout_tests": tests,
        "swing_bias": round(seq, 2),
    }


def _swing_bias(bars: list[Bar]) -> float:
    """+1 clean higher-highs/higher-lows, -1 clean lower sequence, ~0 chop."""
    if len(bars) < 6:
        return 0.0
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    mid = len(bars) // 2
    hh = max(highs[mid:]) > max(highs[:mid])
    hl = min(lows[mid:]) > min(lows[:mid])
    lh = max(highs[mid:]) < max(highs[:mid])
    ll = min(lows[mid:]) < min(lows[:mid])
    if hh and hl:
        return 1.0
    if lh and ll:
        return -1.0
    return 0.3 if (hh or hl) else -0.3 if (lh or ll) else 0.0


# ---------------------------------------------------- absorption (ESTIMATED)

def absorption(session: list[Bar], hist_sessions: list[list[Bar]]) -> dict[str, Any]:
    """Volume-without-price-movement. ESTIMATED — from 1-minute bars only;
    no trade prints / aggressor flag, so it cannot confirm true absorption."""
    if len(session) < 10:
        return {"score": None, "reason": "not enough intraday bars yet", "tier": "ESTIMATED"}
    recent = session[-5:]
    # volume efficiency = |net price move| / volume, normalised to the session
    effs = []
    for b in session:
        if b.volume > 0:
            effs.append(abs(b.close - b.open) / b.close / b.volume)
    if not effs:
        return {"score": None, "reason": "no volume", "tier": "ESTIMATED"}
    med_eff = sorted(effs)[len(effs) // 2] or 1e-12

    heavy_low_move = 0
    net_dir = 0.0
    for b in recent:
        if b.volume <= 0:
            continue
        eff = abs(b.close - b.open) / b.close / b.volume
        move_pct = abs(b.close - b.open) / b.open * 100.0 if b.open else 0.0
        # baseline volume for this minute
        base = [x.volume for hs in hist_sessions for x in hs if x.minute_of_day == b.minute_of_day]
        rvol = b.volume / (mean(base) if base else b.volume or 1.0)
        if rvol >= 2.0 and move_pct <= 0.15 and eff < med_eff:
            heavy_low_move += 1
            # which side is being absorbed: close vs bar midpoint
            net_dir += 1.0 if b.close >= (b.high + b.low) / 2 else -1.0

    score = _clip(heavy_low_move / len(recent) * 100.0)
    side = "bullish" if net_dir > 0 else "bearish" if net_dir < 0 else "neutral"
    return {
        "score": round(score, 1),
        "tier": "ESTIMATED",
        "heavy_low_move_bars": heavy_low_move,
        "implied_side": side if score > 0 else "neutral",
        "note": "from 1-minute OHLCV only — not confirmed by trade prints",
    }


# --------------------------------------------------------- relative strength

def relative_strength(
    session: list[Bar],
    index_session: list[Bar] | None,
    sector_session: list[Bar] | None,
) -> dict[str, Any]:
    if len(session) < 5 or not session[0].open:
        return {"score": None, "reason": "session just opened"}
    stock_ret = (session[-1].close - session[0].open) / session[0].open * 100.0

    def _ret(s: list[Bar] | None) -> float | None:
        if not s or len(s) < 2 or not s[0].open:
            return None
        return (s[-1].close - s[0].open) / s[0].open * 100.0

    idx_ret = _ret(index_session)
    sec_ret = _ret(sector_session)
    rs_index = stock_ret - idx_ret if idx_ret is not None else None
    rs_sector = stock_ret - sec_ret if sec_ret is not None else None

    # slope of relative strength over the last 15 bars vs the index
    rs_slope = None
    if index_session and len(index_session) >= 15 and len(session) >= 15:
        n = min(len(session), len(index_session), 15)
        srs = [
            (session[-n + i].close / session[0].open - 1.0)
            - (index_session[-n + i].close / index_session[0].open - 1.0)
            for i in range(n)
        ]
        rs_slope = (srs[-1] - srs[0]) / n * 100.0

    base = 50.0
    if rs_index is not None:
        base += rs_index * 12.0
    if rs_sector is not None:
        base += rs_sector * 6.0
    if rs_slope is not None:
        base += rs_slope * 200.0
    score = _clip(base)
    return {
        "score": round(score, 1),
        "stock_return_pct": round(stock_ret, 2),
        "index_return_pct": round(idx_ret, 2) if idx_ret is not None else None,
        "sector_return_pct": round(sec_ret, 2) if sec_ret is not None else None,
        "rs_vs_index": round(rs_index, 2) if rs_index is not None else None,
        "rs_vs_sector": round(rs_sector, 2) if rs_sector is not None else None,
        "rs_slope": round(rs_slope, 4) if rs_slope is not None else None,
    }


def momentum_readings(session: list[Bar]) -> dict[str, Any]:
    c = [b.close for b in session]
    return {
        "roc_10m_pct": round((roc(c, 10) or 0.0) * 100.0, 2) if len(c) > 10 else None,
        "ema9_vs_ema21": (
            "up" if (ema(c, 9) or 0) > (ema(c, 21) or 0) else "down"
        ) if len(c) >= 21 else None,
    }
