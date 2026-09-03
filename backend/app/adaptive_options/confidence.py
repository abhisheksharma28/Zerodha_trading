"""Phase 6 — Signal Confidence.

A weighted 0-100 score of how *coherent and readable* the current picture
is. It is deliberately not a "trade / don't trade" verdict — high
confidence still has to clear regime and (later) risk filters.
"""

from __future__ import annotations

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import (
    ChainSnapshot,
    ConfidenceScore,
    IntelReport,
    PCRState,
    PositioningReport,
    VolReport,
)

_STRUCT = {
    "HH_HL": 82, "LH_LL": 82, "REVERSAL_UP": 66, "REVERSAL_DOWN": 66,
    "EXPANSION": 60, "COMPRESSION": 55, "RANGE": 42,
}


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def score(
    cfg: AdaptiveConfig, *,
    intel: IntelReport,
    pcr: PCRState,
    positioning: PositioningReport,
    vol: VolReport,
    snap: ChainSnapshot,
    futures_state: str | None = None,
) -> ConfidenceScore:
    notes: list[str] = []

    # trend
    c_trend = intel.trend_strength if intel.trend_direction != "SIDEWAYS" \
        else 30.0 + intel.trend_strength * 0.3

    # positioning conviction
    spread = abs(positioning.call_writing_strength - 50.0) + abs(positioning.put_writing_strength - 50.0)
    c_pos = _clamp(45.0 + spread - (20.0 if positioning.price_oi_state == "MIXED" else 0.0))

    # pcr context
    z = abs(pcr.weighted_stat.zscore or 0.0)
    c_pcr = _clamp(40.0 + min(40.0, z * 20.0)
                   + (15.0 if pcr.transition_confirmed else 0.0)
                   + (5.0 if pcr.state != "NEUTRAL" else 0.0))

    # price action / structure
    c_pa = float(_STRUCT.get(intel.market_structure, 45))
    if (intel.trend_direction == "UP" and intel.above_vwap) or \
       (intel.trend_direction == "DOWN" and not intel.above_vwap):
        c_pa = _clamp(c_pa + 8.0)
    elif intel.trend_direction != "SIDEWAYS":
        c_pa = _clamp(c_pa - 10.0)

    # volatility readability — an IV rank far from the middle is "clear"
    c_vol = _clamp(40.0 + abs(vol.iv_rank - 50.0)) if vol.iv_rank is not None else 35.0

    # volume
    c_volm = 45.0
    if intel.rel_volume is not None:
        c_volm = _clamp(45.0 + (intel.rel_volume - 1.0) * 30.0)
    c_volm += 10.0 if intel.price_volume == "CONFIRMING" else -10.0 if intel.price_volume == "DIVERGING" else 0.0
    c_volm = _clamp(c_volm)

    # futures (optional)
    weights = cfg.confidence_weights()
    if futures_state:
        aligned = ((intel.trend_direction == "UP" and futures_state in ("LONG_BUILDUP", "SHORT_COVERING"))
                   or (intel.trend_direction == "DOWN" and futures_state in ("SHORT_BUILDUP", "LONG_UNWINDING")))
        c_fut = 75.0 if aligned else 25.0 if futures_state != "NA" else 50.0
    else:
        c_fut = 50.0
        # fold the futures weight back into trend + positioning
        w_fut = weights.pop("futures")
        weights["trend"] += w_fut * 0.5
        weights["positioning"] += w_fut * 0.5
        weights["futures"] = 0.0
        notes.append("No futures positioning input — its weight was folded into trend / positioning.")

    # liquidity — NIFTY/BANKNIFTY chains are deep; penalise only a thin snapshot
    with_oi = sum(1 for r in snap.rows if r.call_oi > 0 or r.put_oi > 0)
    c_liq = 90.0 if with_oi >= 15 else 62.0 if with_oi >= 8 else 38.0

    comp_raw = {
        "trend": c_trend, "positioning": c_pos, "pcr": c_pcr,
        "price_action": c_pa, "volatility": c_vol, "volume": c_volm,
        "futures": c_fut, "liquidity": c_liq,
    }
    contributions = {k: comp_raw[k] * weights.get(k, 0.0) for k in comp_raw}
    total = _clamp(sum(contributions.values()))

    band = ("VERY_HIGH" if total >= 85 else "HIGH" if total >= 70
            else "MODERATE" if total >= 50 else "WEAK" if total >= 30 else "LOW")

    return ConfidenceScore(score=total, band=band, components=contributions, notes=notes)
