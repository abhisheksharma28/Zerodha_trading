"""Combine technical features + market structure + a fundamental overlay
into a single directional call with a fully transparent factor breakdown.

A setup is emitted only when all of these hold:
  * |bias score| >= ``min_bias``            - enough confirmation
  * a concrete entry trigger exists         - a level, not "buy now" vibes
  * the structure/ATR stop is sane          - risk <= ``max_risk_pct``
  * reward:risk to target 1 >= ``min_rr``

``confidence`` is a 0-100 readout of how much lined up - NOT a claimed
win rate. ``pop`` is filled only by the option overlay (see options_overlay).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.market_scanner.features import Features
from app.market_scanner.fundamentals import FundamentalView
from app.market_scanner.structure import StructureReport, Zone


@dataclass
class SignalConfig:
    min_bias: float = 30.0
    min_rr: float = 1.6
    min_confidence: float = 45.0       # strict gate - below this a setup is not emitted
    max_risk_pct_swing: float = 5.0
    max_risk_pct_intraday: float = 1.8
    sl_atr_mult: float = 1.5
    max_sl_atr_mult: float = 3.0
    zone_proximity_atr: float = 1.75  # an FVG/OB counts as "at price" within this many ATRs
    t2_r_multiple: float = 2.6
    intraday_target_atr_cap: float = 1.6  # T within this many *daily* ATRs for intraday


@dataclass
class Factor:
    name: str
    detail: str
    weight: float  # signed: +long / -short
    group: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "detail": self.detail,
                "weight": round(self.weight, 1), "side": "LONG" if self.weight >= 0 else "SHORT",
                "group": self.group}


@dataclass
class Setup:
    direction: str            # LONG | SHORT
    horizon: str              # INTRADAY | SWING
    setup_type: str
    setup_tags: list[str]
    bias_score: float
    confidence: float
    entry: float
    entry_type: str           # MARKET | LIMIT | STOP
    stop_loss: float
    target_1: float
    target_2: float | None
    rr: float
    atr: float | None
    grade: str = "C"          # A / B / C from the strict score
    score_detail: dict[str, Any] = field(default_factory=dict)
    factors: list[Factor] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def factor_dicts(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in sorted(self.factors, key=lambda x: -abs(x.weight))]


@dataclass
class SignalInput:
    ltp: float
    asset_class: str
    has_options: bool
    daily: Features
    daily_structure: StructureReport
    intraday: Features | None = None
    intraday_structure: StructureReport | None = None
    fundamentals: FundamentalView | None = None
    tick_size: float = 0.05


# --------------------------------------------------------------------------
# factor collection
# --------------------------------------------------------------------------

def _trend_factors(d: Features) -> list[Factor]:
    out: list[Factor] = []
    if d.ema_stack == "BULL":
        out.append(Factor("ema_stack", "20>50>200 EMA - bullish alignment", 18, "trend"))
    elif d.ema_stack == "BEAR":
        out.append(Factor("ema_stack", "20<50<200 EMA - bearish alignment", -18, "trend"))
    if d.golden_cross_age is not None:
        age = d.golden_cross_age
        if age >= 0:
            w = 15.0 if age <= 15 else 10.0 if age <= 40 else 6.0
            out.append(Factor("golden_cross", f"50/200 golden cross {age} bars ago", w, "trend"))
        else:
            a = -age
            w = -15.0 if a <= 15 else -10.0 if a <= 40 else -6.0
            out.append(Factor("death_cross", f"50/200 death cross {a} bars ago", w, "trend"))
    if d.ema200 and d.close:
        if d.close > d.ema200:
            out.append(Factor("above_200ema", "price above the 200 EMA", 8, "trend"))
        else:
            out.append(Factor("below_200ema", "price below the 200 EMA", -8, "trend"))
    if d.adx14 is not None and d.adx14 >= 25:
        # ADX is direction-agnostic - amplify whatever trend side already leads
        lead = sum(f.weight for f in out)
        if abs(lead) > 1:
            sign = 1.0 if lead > 0 else -1.0
            out.append(Factor("adx_strong", f"ADX {d.adx14:.0f} - trend has force", sign * 6, "trend"))
    return out


def _momentum_factors(d: Features) -> list[Factor]:
    out: list[Factor] = []
    if d.rsi14 is not None:
        if d.rsi_state == "BULLISH":
            out.append(Factor("rsi", f"RSI {d.rsi14:.0f} - bullish zone", 8, "momentum"))
        elif d.rsi_state == "BEARISH":
            out.append(Factor("rsi", f"RSI {d.rsi14:.0f} - bearish zone", -8, "momentum"))
        elif d.rsi_state == "OVERSOLD":
            out.append(Factor("rsi_oversold", f"RSI {d.rsi14:.0f} - stretched, bounce risk", 4, "momentum"))
        elif d.rsi_state == "OVERBOUGHT":
            out.append(Factor("rsi_overbought", f"RSI {d.rsi14:.0f} - stretched, fade risk", -4, "momentum"))
    if d.macd_state.startswith("RISING"):
        out.append(Factor("macd", f"MACD histogram rising ({d.macd_state.split('_')[1].lower()})", 8, "momentum"))
    elif d.macd_state.startswith("FALLING"):
        out.append(Factor("macd", f"MACD histogram falling ({d.macd_state.split('_')[1].lower()})", -8, "momentum"))
    return out


def _zone_near(zones: list[Zone], price: float, atr: float, k: float) -> Zone | None:
    if not atr:
        return None
    for z in zones:
        if z.bottom - k * atr <= price <= z.top + k * atr:
            return z
    return None


def _structure_factors(s: StructureReport, price: float, atr: float | None, cfg: SignalConfig, tf: str) -> list[Factor]:
    out: list[Factor] = []
    if s.trend == "UP":
        out.append(Factor("structure_trend", f"{tf} structure: higher highs & lows", 12, "structure"))
    elif s.trend == "DOWN":
        out.append(Factor("structure_trend", f"{tf} structure: lower highs & lows", -12, "structure"))
    if s.last_break == "BOS_UP":
        out.append(Factor("bos", f"{tf} break of structure up", 10, "structure"))
    elif s.last_break == "BOS_DOWN":
        out.append(Factor("bos", f"{tf} break of structure down", -10, "structure"))
    elif s.last_break == "CHOCH_UP":
        out.append(Factor("choch", f"{tf} change of character up (possible reversal)", 12, "structure"))
    elif s.last_break == "CHOCH_DOWN":
        out.append(Factor("choch", f"{tf} change of character down (possible reversal)", -12, "structure"))
    k = cfg.zone_proximity_atr
    bull_fvg = _zone_near([z for z in s.fvgs if z.kind == "bullish"], price, atr or 0, k)
    bear_fvg = _zone_near([z for z in s.fvgs if z.kind == "bearish"], price, atr or 0, k)
    if bull_fvg:
        out.append(Factor("fvg", f"{tf} unmitigated bullish FVG at {bull_fvg.bottom:.1f}-{bull_fvg.top:.1f}", 8, "structure"))
    if bear_fvg:
        out.append(Factor("fvg", f"{tf} unmitigated bearish FVG at {bear_fvg.bottom:.1f}-{bear_fvg.top:.1f}", -8, "structure"))
    bull_ob = _zone_near([z for z in s.order_blocks if z.kind == "bullish"], price, atr or 0, k)
    bear_ob = _zone_near([z for z in s.order_blocks if z.kind == "bearish"], price, atr or 0, k)
    if bull_ob:
        out.append(Factor("order_block", f"{tf} bullish order block at {bull_ob.bottom:.1f}-{bull_ob.top:.1f}", 6, "structure"))
    if bear_ob:
        out.append(Factor("order_block", f"{tf} bearish order block at {bear_ob.bottom:.1f}-{bear_ob.top:.1f}", -6, "structure"))
    if s.liquidity_sweep == "low":
        out.append(Factor("liquidity_sweep", f"{tf} swept lows and reclaimed - bullish stop-run", 7, "structure"))
    elif s.liquidity_sweep == "high":
        out.append(Factor("liquidity_sweep", f"{tf} swept highs and rejected - bearish stop-run", -7, "structure"))
    return out


def _location_factors(intra: Features | None, daily: Features) -> list[Factor]:
    out: list[Factor] = []
    src = intra or daily
    if src.above_vwap is True:
        out.append(Factor("vwap", f"above session VWAP (+{src.vwap_dist_pct:.2f}%)", 6, "location"))
    elif src.above_vwap is False:
        out.append(Factor("vwap", f"below session VWAP ({src.vwap_dist_pct:.2f}%)", -6, "location"))
    if daily.prev_day_high and daily.close > daily.prev_day_high:
        out.append(Factor("pdh_break", "closed above the prior-day high", 7, "location"))
    if daily.prev_day_low and daily.close < daily.prev_day_low:
        out.append(Factor("pdl_break", "closed below the prior-day low", -7, "location"))
    if intra and intra.opening_range_high and intra.close > intra.opening_range_high:
        out.append(Factor("orb", "broke the opening range high", 5, "location"))
    if intra and intra.opening_range_low and intra.close < intra.opening_range_low:
        out.append(Factor("orb", "broke the opening range low", -5, "location"))
    return out


def _volume_factors(intra: Features | None, daily: Features, side_sign: float) -> list[Factor]:
    out: list[Factor] = []
    rv = (intra.rel_volume if intra and intra.rel_volume else None) or daily.rel_volume
    if rv and rv >= 1.5:
        out.append(Factor("rel_volume", f"volume {rv:.1f}x the 20-bar average", side_sign * 6, "volume"))
    elif rv and rv < 0.6:
        out.append(Factor("thin_volume", f"volume only {rv:.1f}x average - weak participation", -side_sign * 4, "volume"))
    return out


def _fundamental_factors(fv: FundamentalView | None, horizon: str) -> list[Factor]:
    if not fv or not fv.available or horizon != "SWING":
        return []
    out: list[Factor] = []
    if fv.bias == "SUPPORTIVE_LONG":
        out.append(Factor("fundamentals", "quality/growth supportive of longs", 6, "fundamental"))
    elif fv.bias == "SUPPORTIVE_SHORT":
        out.append(Factor("fundamentals", "weak quality/growth - supportive of shorts", -6, "fundamental"))
    for flag in fv.flags:
        if flag == "earnings contracting":
            out.append(Factor("fundamental_flag", "earnings contracting YoY", -4, "fundamental"))
        elif flag == "quality at a fair price":
            out.append(Factor("fundamental_flag", "high ROE at a fair valuation", 4, "fundamental"))
        elif flag == "rich valuation":
            out.append(Factor("fundamental_flag", "rich valuation (PE > 60)", -3, "fundamental"))
        elif flag == "high leverage":
            out.append(Factor("fundamental_flag", "high leverage (D/E > 2)", -3, "fundamental"))
    return out


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def trade_style_for(horizon: str, asset_class: str) -> str:
    """What the user actually trades. Indices have no cash-delivery leg, so
    an index directional idea is always intraday (or the option overlay)."""
    if asset_class == "EQUITY":
        return "EQUITY_INTRADAY" if horizon == "INTRADAY" else "EQUITY_DELIVERY"
    return "EQUITY_INTRADAY"  # INDEX / COMMODITY - no delivery


def _round_tick(v: float, tick: float) -> float:
    if tick <= 0:
        return round(v, 2)
    return round(round(v / tick) * tick, 4)


def _pick_horizon(daily: Features, intra: Features | None, asset_class: str,
                  trend_w: float, structure_intra_w: float) -> str:
    if asset_class in ("INDEX", "COMMODITY"):
        # index/commodity: swing only when the daily trend is unambiguous
        return "SWING" if daily.ema_stack in ("BULL", "BEAR") and abs(trend_w) >= 24 else "INTRADAY"
    strong_daily = daily.ema_stack in ("BULL", "BEAR") and abs(trend_w) >= 20
    if strong_daily and abs(trend_w) >= abs(structure_intra_w):
        return "SWING"
    return "INTRADAY"


def _entry_stop_targets(
    direction: str, horizon: str, price: float, atr_d: float | None, atr_i: float | None,
    d_struct: StructureReport, i_struct: StructureReport | None, cfg: SignalConfig, tick: float,
) -> tuple[float, str, float, float, float | None] | None:
    long = direction == "LONG"
    atr = (atr_i if horizon == "INTRADAY" and atr_i else atr_d) or atr_d
    if not atr or atr <= 0:
        return None
    struct = i_struct if (horizon == "INTRADAY" and i_struct) else d_struct

    # --- entry: retest of the nearest aligned zone, else momentum entry at price
    zones = [z for z in (struct.fvgs + struct.order_blocks)
             if z.kind == ("bullish" if long else "bearish")]
    entry, entry_type = price, "MARKET"
    for z in zones:
        edge = z.top if long else z.bottom
        if abs(edge - price) <= cfg.zone_proximity_atr * atr and (
            (long and edge <= price) or (not long and edge >= price)
        ):
            entry, entry_type = edge, "LIMIT"
            break

    # --- stop: beyond structure invalidation, capped at max_sl_atr_mult * ATR
    if long:
        struct_sl = min([v for v in (struct.swing_low, struct.prior_swing_low) if v] or [entry])
        atr_sl = entry - cfg.sl_atr_mult * atr
        sl = min(struct_sl, atr_sl) if struct_sl < entry else atr_sl
        sl = max(sl, entry - cfg.max_sl_atr_mult * atr)
    else:
        struct_sl = max([v for v in (struct.swing_high, struct.prior_swing_high) if v] or [entry])
        atr_sl = entry + cfg.sl_atr_mult * atr
        sl = max(struct_sl, atr_sl) if struct_sl > entry else atr_sl
        sl = min(sl, entry + cfg.max_sl_atr_mult * atr)

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    # --- targets: structure objective, floored at min_rr, T2 further out
    if long:
        struct_obj = d_struct.swing_high if d_struct.swing_high and d_struct.swing_high > entry else None
        t1 = max(entry + cfg.min_rr * risk, struct_obj or 0)
        t2 = entry + cfg.t2_r_multiple * risk
        if horizon == "INTRADAY":
            cap = entry + cfg.intraday_target_atr_cap * (atr_d or atr)
            t1, t2 = min(t1, cap), min(t2, cap + risk)
    else:
        struct_obj = d_struct.swing_low if d_struct.swing_low and d_struct.swing_low < entry else None
        t1 = min(entry - cfg.min_rr * risk, struct_obj or 1e12)
        t2 = entry - cfg.t2_r_multiple * risk
        if horizon == "INTRADAY":
            cap = entry - cfg.intraday_target_atr_cap * (atr_d or atr)
            t1, t2 = max(t1, cap), max(t2, cap - risk)

    return (
        _round_tick(entry, tick), entry_type, _round_tick(sl, tick),
        _round_tick(t1, tick), _round_tick(t2, tick),
    )


_SETUP_LABEL = {
    "choch": "Change-of-character reversal",
    "liquidity_sweep": "Liquidity sweep reversal",
    "golden_cross": "Golden-cross trend",
    "death_cross": "Death-cross downtrend",
    "pdh_break": "Prior-day-high breakout",
    "pdl_break": "Prior-day-low breakdown",
    "orb": "Opening-range breakout",
    "fvg": "Fair-value-gap retest",
    "order_block": "Order-block retest",
    "bos": "Break-of-structure continuation",
    "rsi_oversold": "Oversold bounce",
    "rsi_overbought": "Overbought fade",
    "vwap": "VWAP trend day",
    "ema_stack": "Trend-alignment pullback",
    "macd": "Momentum continuation",
}
# most-specific first - the setup is named after the first of these that fired
_SETUP_PRIORITY = list(_SETUP_LABEL.keys())

_REVERSAL_SETUPS = {
    "Change-of-character reversal", "Liquidity sweep reversal",
    "Oversold bounce", "Overbought fade",
}
# strict quality weights (sum ~= 1.0)
_QW = {
    "alignment": 0.24, "trend": 0.16, "structure": 0.16, "location": 0.14,
    "momentum": 0.12, "rr": 0.08, "volume": 0.06, "risk_fit": 0.04,
}


def _lin(x: float, x0: float, x1: float) -> float:
    if x1 == x0:
        return 0.0
    return max(0.0, min(1.0, (x - x0) / (x1 - x0)))


def _quality_score(
    *, direction: str, horizon: str, setup_type: str,
    aligned: float, against: float, aligned_groups: int,
    d: Features, i: Features | None,
    s_d: StructureReport, s_i: StructureReport | None,
    entry_type: str, rr: float, risk_pct: float, max_risk: float,
    fundamentals: FundamentalView | None,
) -> tuple[float, str, dict[str, Any]]:
    """A strict 0-100 quality read. Most real setups land 40-70; only clean,
    multi-confirmed, well-located, trending setups clear 80."""
    long = direction == "LONG"
    total = aligned + abs(against)

    # 1. alignment: how one-sided the evidence is
    s_align = aligned / total if total else 0.0

    # 2. trend strength (ADX)
    adx = d.adx14 or 0.0
    s_trend = 0.15 + 0.85 * _lin(adx, 16.0, 34.0)

    # 3. structure agreement (daily + intraday), reversal setups judged on the flip
    want = "UP" if long else "DOWN"
    if setup_type in _REVERSAL_SETUPS:
        flip = (s_i or s_d).last_break or ""
        s_struct = 0.9 if (long and flip.endswith("UP")) or (not long and flip.endswith("DOWN")) else 0.35
    else:
        hits = (1 if s_d.trend == want else 0) + (1 if s_i and s_i.trend == want else 0)
        both_possible = s_i is not None
        s_struct = {0: 0.2, 1: 0.55 if both_possible else 0.7, 2: 1.0}[hits]

    # 4. location: entered at a real level vs chased
    s_loc = {"LIMIT": 0.9, "STOP": 0.7}.get(entry_type, 0.35)

    # 5. momentum agreement (RSI zone + MACD), extended = bad
    rsi = d.rsi14
    rsi_ok = rsi is not None and ((long and 45 <= rsi <= 68) or (not long and 32 <= rsi <= 55))
    rsi_extended = rsi is not None and ((long and rsi >= 74) or (not long and rsi <= 26))
    macd_ok = (long and d.macd_state.startswith("RISING")) or (not long and d.macd_state.startswith("FALLING"))
    s_mom = 0.15 if rsi_extended else (1.0 if (rsi_ok and macd_ok) else 0.55 if (rsi_ok or macd_ok) else 0.25)

    # 6. reward:risk asymmetry
    s_rr = _lin(rr, 1.4, 3.2)

    # 7. volume confirmation
    rv = (i.rel_volume if i and i.rel_volume else d.rel_volume) or 0.0
    s_vol = 1.0 if rv >= 2 else 0.75 if rv >= 1.5 else 0.45 if rv >= 1.0 else 0.15 if rv and rv < 0.7 else 0.35

    # 8. stop sits in a sane band of the risk budget
    frac = risk_pct / max_risk if max_risk else 1.0
    s_risk = 1.0 if 0.35 <= frac <= 0.8 else 0.5 if frac < 0.35 else 0.4

    subs = {
        "alignment": s_align, "trend": s_trend, "structure": s_struct, "location": s_loc,
        "momentum": s_mom, "rr": s_rr, "volume": s_vol, "risk_fit": s_risk,
    }
    raw = 100.0 * sum(subs[k] * _QW[k] for k in _QW)

    # penalties
    pen = 0.0
    counter_trend = (d.ema_stack == "BULL" and not long) or (d.ema_stack == "BEAR" and long)
    if counter_trend and setup_type not in _REVERSAL_SETUPS:
        pen += 12
    if adx < 15 and setup_type not in _REVERSAL_SETUPS:
        pen += 10
    if abs(against) > 0.35 * aligned:
        pen += 8
    if rsi_extended:
        pen += 8
    if horizon == "INTRADAY" and i is None:
        pen += 6
    if fundamentals and fundamentals.available and horizon == "SWING" and (
        (long and fundamentals.bias == "SUPPORTIVE_SHORT")
        or (not long and fundamentals.bias == "SUPPORTIVE_LONG")
    ):
        pen += 6

    score = raw - pen

    # hard caps
    caps: list[tuple[str, float]] = []
    if adx < 16 and setup_type not in _REVERSAL_SETUPS:
        caps.append(("chop / no trend", 52.0))
    if s_struct <= 0.2:
        caps.append(("no structural support", 55.0))
    if aligned_groups < 2:
        caps.append(("single-factor setup", 50.0))
    if counter_trend and s_i is None:
        caps.append(("counter-trend, single timeframe", 58.0))
    for _why, cap in caps:
        score = min(score, cap)
    score = max(0.0, min(90.0, score))

    grade = "A" if score >= 74 else "B" if score >= 58 else "C"
    detail = {
        "score": round(score, 1),
        "grade": grade,
        "sub_scores": {k: round(v, 2) for k, v in subs.items()},
        "weights": _QW,
        "penalties": round(pen, 1),
        "caps": [w for w, _ in caps],
        "raw": round(raw, 1),
    }
    return score, grade, detail


def evaluate(inp: SignalInput, cfg: SignalConfig | None = None) -> Setup | None:
    cfg = cfg or SignalConfig()
    d, s_d = inp.daily, inp.daily_structure
    if d.bars < 30 or not d.atr14:
        return None

    trend = _trend_factors(d)
    trend_w = sum(f.weight for f in trend)
    momentum = _momentum_factors(d)
    struct_d = _structure_factors(s_d, inp.ltp, d.atr14, cfg, "daily")
    struct_i: list[Factor] = []
    if inp.intraday and inp.intraday_structure:
        struct_i = _structure_factors(inp.intraday_structure, inp.ltp, inp.intraday.atr14, cfg, "15m")
    struct_i_w = sum(f.weight for f in struct_i)
    location = _location_factors(inp.intraday, d)

    provisional = trend + momentum + struct_d + struct_i + location
    provisional_w = sum(f.weight for f in provisional)
    if abs(provisional_w) < 1:
        return None
    direction = "LONG" if provisional_w > 0 else "SHORT"
    side_sign = 1.0 if direction == "LONG" else -1.0

    horizon = _pick_horizon(d, inp.intraday, inp.asset_class, trend_w, struct_i_w)
    volume = _volume_factors(inp.intraday, d, side_sign)
    fundamental = _fundamental_factors(inp.fundamentals, horizon)

    factors = provisional + volume + fundamental
    bias_score = max(-100.0, min(100.0, sum(f.weight for f in factors)))
    if abs(bias_score) < cfg.min_bias:
        return None
    # a setup must not be a coin toss of opposing factors
    aligned = sum(f.weight for f in factors if (f.weight > 0) == (bias_score > 0))
    against = sum(f.weight for f in factors if (f.weight > 0) != (bias_score > 0))
    if abs(against) > 0.55 * abs(aligned):
        return None

    est = _entry_stop_targets(direction, horizon, inp.ltp, d.atr14,
                              inp.intraday.atr14 if inp.intraday else None,
                              s_d, inp.intraday_structure, cfg, inp.tick_size)
    if est is None:
        return None
    entry, entry_type, sl, t1, t2 = est
    risk = abs(entry - sl)
    reward = abs(t1 - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    risk_pct = 100.0 * risk / entry if entry else 99.0
    max_risk = cfg.max_risk_pct_intraday if horizon == "INTRADAY" else cfg.max_risk_pct_swing
    if rr < cfg.min_rr or risk_pct > max_risk:
        return None

    # name the setup after the most *specific* aligned trigger, not just the
    # heaviest weight (ema_stack would always win otherwise)
    pos = bias_score > 0
    aligned_names = {f.name for f in factors if (f.weight > 0) == pos}
    setup_type = next(
        (_SETUP_LABEL[n] for n in _SETUP_PRIORITY if n in aligned_names),
        "Multi-factor confluence",
    )
    tags = sorted({f.name for f in factors if abs(f.weight) >= 5 and (f.weight > 0) == pos})

    aligned_groups = len({f.group for f in factors if (f.weight > 0) == pos})
    score, grade, detail = _quality_score(
        direction=direction, horizon=horizon, setup_type=setup_type,
        aligned=abs(aligned), against=abs(against), aligned_groups=aligned_groups,
        d=d, i=inp.intraday, s_d=s_d, s_i=inp.intraday_structure,
        entry_type=entry_type, rr=rr, risk_pct=risk_pct, max_risk=max_risk,
        fundamentals=inp.fundamentals,
    )
    if score < cfg.min_confidence:
        return None

    return Setup(
        direction=direction, horizon=horizon, setup_type=setup_type, setup_tags=tags,
        bias_score=round(bias_score, 1), confidence=round(score, 1),
        grade=grade, score_detail=detail,
        entry=entry, entry_type=entry_type, stop_loss=sl, target_1=t1, target_2=t2,
        rr=rr, atr=round(d.atr14, 4), factors=factors,
    )
