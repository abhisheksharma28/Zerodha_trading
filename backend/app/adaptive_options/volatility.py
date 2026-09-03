"""Phase 5 — Volatility engine.

ATM IV, IV rank / percentile (vs stored history), IV skew, term structure
(when a second expiry's ATM IV is supplied), realized vol from the
underlying, IV-minus-RV, an IV class, and a VOLATILITY_SELLING_SCORE that
weighs whether conditions actually favour premium selling — high IV alone
is not enough.
"""

from __future__ import annotations

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, VolReport

# absolute ATM-IV bands used only when there is no IV history yet (NIFTY-ish)
_ABS_BANDS = (0.10, 0.15, 0.22)


def _atm_ivs(snap: ChainSnapshot) -> tuple[float | None, float | None]:
    atm = snap.atm_strike()
    if atm is None:
        return None, None
    row = next((r for r in snap.rows if r.strike == atm), None)
    if row is None:
        return None, None
    return row.call_iv, row.put_iv


def _wing_skew(snap: ChainSnapshot, steps: int = 3) -> float | None:
    atm = snap.atm_strike()
    if atm is None:
        return None
    step = snap.strike_step()
    put_row = next((r for r in snap.rows if abs(r.strike - (atm - steps * step)) < 1e-6), None)
    call_row = next((r for r in snap.rows if abs(r.strike - (atm + steps * step)) < 1e-6), None)
    if put_row and call_row and put_row.put_iv and call_row.call_iv:
        return put_row.put_iv - call_row.call_iv
    return None


def analyse(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *,
    iv_history: list[float] | None = None,
    realized_vol: float | None = None,
    adx: float | None = None,
    trend_strength: float | None = None,
    far_atm_iv: float | None = None,
) -> VolReport:
    iv_history = [v for v in (iv_history or []) if v and v > 0]
    call_iv, put_iv = _atm_ivs(snap)
    parts = [v for v in (call_iv, put_iv) if v and v > 0]
    atm_iv = sum(parts) / len(parts) if parts else None
    skew = _wing_skew(snap)

    iv_rank = iv_pctile = iv_change = None
    if atm_iv is not None and len(iv_history) >= 8:
        lo, hi = min(iv_history), max(iv_history)
        iv_rank = 100.0 * (atm_iv - lo) / (hi - lo) if hi > lo else 50.0
        iv_rank = max(0.0, min(100.0, iv_rank))
        iv_pctile = 100.0 * sum(1 for v in iv_history if v <= atm_iv) / len(iv_history)
        iv_change = atm_iv - iv_history[-1]

    # classification
    if iv_rank is not None:
        iv_class = ("EXTREME_IV" if iv_rank >= cfg.iv_extreme_rank
                    else "HIGH_IV" if iv_rank >= cfg.iv_high_rank
                    else "LOW_IV" if iv_rank <= cfg.iv_low_rank
                    else "NORMAL_IV")
    elif atm_iv is not None:
        lo, mid, hi = _ABS_BANDS
        iv_class = ("LOW_IV" if atm_iv < lo else "NORMAL_IV" if atm_iv < mid
                    else "HIGH_IV" if atm_iv < hi else "EXTREME_IV")
    else:
        iv_class = "UNKNOWN"

    iv_minus_rv = (atm_iv - realized_vol) if (atm_iv is not None and realized_vol is not None) else None

    term = "NA"
    if atm_iv is not None and far_atm_iv is not None and far_atm_iv > 0:
        if far_atm_iv > atm_iv * 1.02:
            term = "CONTANGO"
        elif far_atm_iv < atm_iv * 0.98:
            term = "BACKWARDATION"
        else:
            term = "FLAT"

    # ---- VOLATILITY_SELLING_SCORE -------------------------------------
    score = 0.0
    notes: list[str] = []
    if atm_iv is None:
        notes.append("ATM IV unavailable — volatility read is incomplete.")
    # rich vs realised (max +25)
    if iv_minus_rv is not None:
        score += max(-20.0, min(25.0, iv_minus_rv * 400.0))   # +25 at ~+6 vol pts
    # IV rank / level (max +35)
    if iv_rank is not None:
        score += (iv_rank - 40.0) * 0.6            # -24 at rank 0, +36 at rank 100
    elif iv_class in ("HIGH_IV", "EXTREME_IV"):
        score += 18.0
    elif iv_class == "LOW_IV":
        score -= 18.0
    # trend weakness — selling premium into a strong trend is punished (max +20 / -20)
    if trend_strength is not None:
        score += (55.0 - trend_strength) * 0.35
    elif adx is not None:
        score += (cfg.adx_trend_min - adx) * 1.2
    # DTE — very short DTE = gamma risk for sellers (max +10 / heavy negative near expiry)
    if snap.dte >= 7:
        score += 10.0
    elif snap.dte >= 3:
        score += 2.0
    else:
        score -= 20.0
        notes.append("Under 3 DTE: gamma risk makes premium selling hazardous regardless of IV.")
    # IV expanding fast = do not sell into it
    if iv_change is not None and iv_change > 0.015:
        score -= 18.0
        notes.append("IV is expanding quickly — mean-reversion is not yet in your favour for selling.")
    # term backwardation warns of an event
    if term == "BACKWARDATION":
        score -= 10.0
        notes.append("Term structure in backwardation — the market is pricing a near-dated event.")

    score = max(0.0, min(100.0, 50.0 + score))
    verdict = ("FAVOURABLE" if score >= cfg.vol_selling_favourable_min
               else "UNFAVOURABLE" if score <= cfg.vol_selling_unfavourable_max
               else "NEUTRAL")

    if len(iv_history) < 8:
        notes.append(f"IV rank / percentile need ~8 stored snapshots (have {len(iv_history)}); "
                     "class is from absolute IV bands for now.")

    return VolReport(
        atm_iv=atm_iv, call_iv=call_iv, put_iv=put_iv, iv_skew=skew,
        iv_rank=iv_rank, iv_percentile=iv_pctile, iv_change=iv_change,
        realized_vol=realized_vol, iv_minus_rv=iv_minus_rv,
        iv_class=iv_class, term_structure=term,
        vol_selling_score=score, vol_selling_verdict=verdict,
        history_len=len(iv_history), notes=notes,
    )
