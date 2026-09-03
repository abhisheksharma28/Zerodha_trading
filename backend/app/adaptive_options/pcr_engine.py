"""Phase 3 — PCR Intelligence.

Not a fixed "PCR<1 sell CE" rule. Computes every PCR variant, then reads
LEVEL + TREND + MOMENTUM + SPEED + HISTORICAL CONTEXT + PRICE DIVERGENCE
together, and detects TRANSITIONING_UP / TRANSITIONING_DOWN with a slope
threshold and a confirmation count (hysteresis) so it does not flip the
moment PCR crosses 1.

``history`` is a list of prior readings, oldest first, each a dict with at
least ``oi_pcr``, ``weighted_pcr`` and ``spot``. The current snapshot is
appended internally for the slope / momentum maths.
"""

from __future__ import annotations

import math
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, PCRSeriesStat, PCRState


def _ratio(put: float, call: float) -> float | None:
    if call <= 0:
        return None
    return put / call


def _safe_ratio(put: float, call: float, fallback: float = 1.0) -> float:
    r = _ratio(put, call)
    return fallback if r is None else r


def _lin_slope(ys: list[float]) -> float | None:
    n = len(ys)
    if n < 3:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def _series_stat(hist_vals: list[float], current: float, lookback: int) -> PCRSeriesStat:
    full = hist_vals + [current]
    pctile = z = slope = momentum = accel = None
    if len(hist_vals) >= 5:
        le = sum(1 for v in hist_vals if v <= current)
        pctile = le / len(hist_vals)
        mean = sum(hist_vals) / len(hist_vals)
        var = sum((v - mean) ** 2 for v in hist_vals) / len(hist_vals)
        sd = math.sqrt(var)
        z = (current - mean) / sd if sd > 1e-9 else 0.0
    window = full[-lookback:] if len(full) >= 3 else full
    if len(window) >= 3:
        slope = _lin_slope(window)
        momentum = window[-1] - window[0]
        half = max(2, len(window) // 2)
        s_recent = _lin_slope(window[-half:])
        s_older = _lin_slope(window[:half])
        if s_recent is not None and s_older is not None:
            accel = s_recent - s_older
    return PCRSeriesStat(current, z, pctile, slope, momentum, accel)


def _level_state(pcr: float, cfg: AdaptiveConfig) -> str:
    if pcr >= cfg.pcr_extreme_bull or pcr <= cfg.pcr_extreme_bear:
        return "EXTREME"
    if pcr >= cfg.pcr_strong_bull:
        return "STRONG_BULLISH"
    if pcr >= cfg.pcr_bull_threshold:
        return "BULLISH"
    if pcr <= cfg.pcr_strong_bear:
        return "STRONG_BEARISH"
    if pcr <= cfg.pcr_bear_threshold:
        return "BEARISH"
    return "NEUTRAL"


def _transition(series: list[float], cfg: AdaptiveConfig) -> tuple[str, bool]:
    """series oldest..current of the weighted PCR."""
    need = cfg.pcr_transition_confirm + 1
    if len(series) < need:
        return "STABLE", False
    tail = series[-need:]
    diffs = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]
    up = all(d > 0 for d in diffs) and (sum(diffs) / len(diffs)) >= cfg.pcr_transition_min_slope
    dn = all(d < 0 for d in diffs) and (-sum(diffs) / len(diffs)) >= cfg.pcr_transition_min_slope
    if up:
        return "TRANSITIONING_UP", True
    if dn:
        return "TRANSITIONING_DOWN", True
    # unconfirmed lean from the recent slope
    sl = _lin_slope(series[-cfg.pcr_transition_lookback:])
    if sl is not None and sl >= cfg.pcr_transition_min_slope * 0.6:
        return "TRANSITIONING_UP", False
    if sl is not None and sl <= -cfg.pcr_transition_min_slope * 0.6:
        return "TRANSITIONING_DOWN", False
    return "STABLE", False


def _divergence(pcr_series: list[float], spot_series: list[float]) -> str:
    if len(pcr_series) < 4 or len(spot_series) < 4:
        return "NA"
    n = min(len(pcr_series), len(spot_series), 6)
    ps, ss = pcr_series[-n:], spot_series[-n:]
    pcr_up = ps[-1] > ps[0] * 1.01
    pcr_dn = ps[-1] < ps[0] * 0.99
    px_up = ss[-1] > ss[0] * 1.002
    px_dn = ss[-1] < ss[0] * 0.998
    if pcr_up and px_dn:
        return "DIVERGING_BULLISH"
    if pcr_dn and px_up:
        return "DIVERGING_BEARISH"
    if (pcr_up and px_up) or (pcr_dn and px_dn):
        return "ALIGNED"
    return "NA"


def analyse(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *, history: list[dict[str, Any]] | None = None
) -> PCRState:
    history = history or []
    rows = snap.rows
    tot_call_oi = sum(r.call_oi for r in rows)
    tot_put_oi = sum(r.put_oi for r in rows)
    tot_call_vol = sum(r.call_volume for r in rows)
    tot_put_vol = sum(r.put_volume for r in rows)
    tot_call_dchg = sum(r.call_chg_oi for r in rows)
    tot_put_dchg = sum(r.put_chg_oi for r in rows)

    oi_pcr = _safe_ratio(tot_put_oi, tot_call_oi)
    volume_pcr = _safe_ratio(tot_put_vol, tot_call_vol)
    chg_oi_pcr = None
    if abs(tot_call_dchg) > 1e-6 and abs(tot_put_dchg) > 1e-6 and \
            tot_call_dchg > 0 and tot_put_dchg > 0:
        chg_oi_pcr = tot_put_dchg / tot_call_dchg

    atm = snap.atm_strike()
    atm_row = next((r for r in rows if r.strike == atm), None)
    atm_pcr = _safe_ratio(atm_row.put_oi, atm_row.call_oi) if atm_row else oi_pcr

    near = snap.window(cfg.pcr_near_atm_strikes)
    near_atm_pcr = _safe_ratio(sum(r.put_oi for r in near), sum(r.call_oi for r in near))

    # weighted PCR — OI weighted by proximity to ATM (exponential falloff)
    step = snap.strike_step()
    hl = max(cfg.pcr_weighted_halflife_strikes, 0.5)
    w_put = w_call = 0.0
    if atm is not None:
        for r in rows:
            dist = abs(r.strike - atm) / step
            w = 0.5 ** (dist / hl)
            w_put += w * r.put_oi
            w_call += w * r.call_oi
    weighted_pcr = _safe_ratio(w_put, w_call, oi_pcr)

    hist_oi = [float(h.get("oi_pcr", 0.0)) for h in history if h.get("oi_pcr")]
    hist_w = [float(h.get("weighted_pcr", 0.0)) for h in history if h.get("weighted_pcr")]
    hist_spot = [float(h.get("spot", 0.0)) for h in history if h.get("spot")]

    oi_stat = _series_stat(hist_oi, oi_pcr, cfg.pcr_transition_lookback)
    w_stat = _series_stat(hist_w, weighted_pcr, cfg.pcr_transition_lookback)

    state = _level_state(weighted_pcr, cfg)
    transition, confirmed = _transition(hist_w + [weighted_pcr], cfg)
    divergence = _divergence(hist_w + [weighted_pcr], hist_spot + [snap.spot])

    notes: list[str] = []
    if not history:
        notes.append("No PCR history yet — trend / percentile / transition need a few stored snapshots.")
    if chg_oi_pcr is None and (tot_call_dchg or tot_put_dchg):
        notes.append("Change-in-OI PCR skipped: one side had non-positive net ΔOI (unwinding dominates).")
    if state in ("BULLISH", "STRONG_BULLISH") and transition == "TRANSITIONING_DOWN":
        notes.append("Level is bullish but positioning is rolling over — treat the bullish read as fading.")

    return PCRState(
        oi_pcr=oi_pcr, volume_pcr=volume_pcr, chg_oi_pcr=chg_oi_pcr,
        atm_pcr=atm_pcr, weighted_pcr=weighted_pcr, near_atm_pcr=near_atm_pcr,
        state=state, transition=transition, transition_confirmed=confirmed,
        price_divergence=divergence,
        oi_pcr_stat=oi_stat, weighted_stat=w_stat,
        history_len=len(history), notes=notes,
    )
