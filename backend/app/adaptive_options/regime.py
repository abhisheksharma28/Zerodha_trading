"""Phase 7 — Market Regime Engine.

Classifies into one of 15 regimes from *multiple* inputs (trend, VWAP,
ADX, structure, ATR, volume, volatility, options positioning, PCR). Never
one indicator. Returns direction, vol class, and confidence / stability /
transition-risk scores plus a human-readable "why".
"""

from __future__ import annotations

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import (
    ConfidenceScore,
    ExpectedMove,
    IntelReport,
    PCRState,
    PositioningReport,
    RegimeState,
    VolReport,
)

_LABELS = {
    "STRONG_BULLISH_TREND", "BULLISH_TREND", "WEAK_BULLISH", "RANGE_BOUND", "NEUTRAL",
    "WEAK_BEARISH", "BEARISH_TREND", "STRONG_BEARISH_TREND", "HIGH_VOLATILITY",
    "LOW_VOLATILITY", "BREAKOUT", "BREAKDOWN", "REVERSAL", "EVENT_RISK", "NO_TRADE",
}


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


_GROUP_CAP = 45.0   # neither price nor options positioning may dominate alone


def _directional_score(
    intel: IntelReport, pcr: PCRState, pos: PositioningReport
) -> tuple[float, float, float, dict[str, str]]:
    """Returns (total, price_score, options_score, why). Each of the two
    groups is capped at +/- _GROUP_CAP so no single side can force a
    strong-trend label on its own."""
    why: dict[str, str] = {}

    # --- price / trend group -------------------------------------
    p = 0.0
    if intel.trend_direction == "UP":
        p += 16 + intel.trend_strength * 0.20
        why["trend"] = f"UP, strength {intel.trend_strength:.0f}"
    elif intel.trend_direction == "DOWN":
        p -= 16 + intel.trend_strength * 0.20
        why["trend"] = f"DOWN, strength {intel.trend_strength:.0f}"
    else:
        why["trend"] = "sideways"
    p += {"BULLISH": 12, "BEARISH": -12, "MIXED": 0}.get(intel.ema_stack, 0)
    why["ema_stack"] = intel.ema_stack
    p += 6 if intel.above_vwap else -6
    why["vwap"] = "above" if intel.above_vwap else "below"
    p += {"RISING": 6, "FALLING": -6, "FLAT": 0}.get(intel.momentum, 0)
    why["momentum"] = intel.momentum
    p += {"HH_HL": 10, "LH_LL": -10, "REVERSAL_UP": 5, "REVERSAL_DOWN": -5}.get(intel.market_structure, 0)
    why["structure"] = intel.market_structure
    price_score = _clamp(p, -_GROUP_CAP, _GROUP_CAP)

    # --- options positioning group ------------------------------
    o = 0.0
    if pcr.state == "EXTREME":
        o += 20 if pcr.weighted_pcr >= 1.0 else -20   # extreme-high = very bullish, extreme-low = very bearish
    else:
        o += {"STRONG_BULLISH": 18, "BULLISH": 11, "NEUTRAL": 0,
              "BEARISH": -11, "STRONG_BEARISH": -18}.get(pcr.state, 0)
    if pcr.transition_confirmed:
        o += 12 if pcr.transition == "TRANSITIONING_UP" else -12 if pcr.transition == "TRANSITIONING_DOWN" else 0
    why["pcr"] = f"{pcr.state} / {pcr.transition}{' (confirmed)' if pcr.transition_confirmed else ''}"
    o += {"LONG_BUILDUP": 14, "SHORT_COVERING": 9, "SHORT_BUILDUP": -14, "LONG_UNWINDING": -9,
          "MIXED": 0}.get(pos.price_oi_state, 0)
    why["positioning"] = pos.price_oi_state
    o += (pos.put_writing_strength - pos.call_writing_strength) * 0.28
    why["writing"] = f"put {pos.put_writing_strength:.0f} vs call {pos.call_writing_strength:.0f}"
    options_score = _clamp(o, -_GROUP_CAP, _GROUP_CAP)

    return _clamp(price_score + options_score), price_score, options_score, why


def _vol_class(vol: VolReport, intel: IntelReport, cfg: AdaptiveConfig) -> str:
    if vol.iv_rank is not None:
        if vol.iv_rank >= cfg.iv_extreme_rank:
            return "EXTREME"
        if vol.iv_rank >= cfg.regime_high_vol_iv_rank:
            return "HIGH"
        if vol.iv_rank <= cfg.regime_low_vol_iv_rank:
            return "LOW"
        return "NORMAL"
    mapping = {"EXTREME_IV": "EXTREME", "HIGH_IV": "HIGH", "LOW_IV": "LOW", "NORMAL_IV": "NORMAL"}
    base = mapping.get(vol.iv_class, "NORMAL")
    if base == "NORMAL" and intel.atr_pct is not None:
        if intel.atr_pct > 1.6:
            return "HIGH"
        if intel.atr_pct < 0.6:
            return "LOW"
    return base


def classify(
    cfg: AdaptiveConfig, *,
    intel: IntelReport,
    pcr: PCRState,
    positioning: PositioningReport,
    vol: VolReport,
    expected_move: ExpectedMove,
    confidence: ConfidenceScore,
    data_ok: bool = True,
) -> RegimeState:
    dscore, price_score, options_score, contributing = _directional_score(intel, pcr, positioning)
    vc = _vol_class(vol, intel, cfg)
    drivers: list[str] = []

    em_expanding = (expected_move.current_vs_expected or 0.0) > 1.0
    groups_oppose = price_score * options_score < 0 and min(abs(price_score), abs(options_score)) >= 18.0
    conflict = groups_oppose or pcr.price_divergence in ("DIVERGING_BULLISH", "DIVERGING_BEARISH")

    # --- special states, in priority order ---------------------------
    label: str | None = None
    if not data_ok:
        label = "NO_TRADE"
        drivers.append("Data-quality gate failed — the engine will not classify on bad data.")
    elif vol.term_structure == "BACKWARDATION" or (vol.iv_change or 0) > 0.02:
        label = "EVENT_RISK"
        drivers.append("Volatility term structure / IV path is pricing a near-dated event.")
    elif confidence.score < cfg.regime_confidence_min and conflict:
        label = "NO_TRADE"
        drivers.append(f"Confidence {confidence.score:.0f} < {cfg.regime_confidence_min:.0f} and signals conflict "
                       "(trend vs positioning / price-PCR divergence).")
    elif intel.market_structure in ("EXPANSION", "REVERSAL_UP") and dscore > 40 and \
            (intel.rel_volume or 0) > 1.3 and intel.resistance and intel.features.get("close", 0) >= intel.resistance:
        label = "BREAKOUT"
        drivers.append("Range expansion through resistance on above-average volume.")
    elif intel.market_structure in ("EXPANSION", "REVERSAL_DOWN") and dscore < -40 and \
            (intel.rel_volume or 0) > 1.3 and intel.support and intel.features.get("close", 0) <= intel.support:
        label = "BREAKDOWN"
        drivers.append("Range expansion through support on above-average volume.")
    elif intel.market_structure in ("REVERSAL_UP", "REVERSAL_DOWN") and pcr.transition_confirmed:
        label = "REVERSAL"
        drivers.append("Market structure has flipped and options positioning has confirmed the turn.")
    elif vc == "EXTREME" and abs(dscore) < 30:
        label = "HIGH_VOLATILITY"
        drivers.append("Volatility is extreme with no clear direction — treat directional bets with caution.")
    elif vc == "LOW" and intel.market_structure in ("COMPRESSION", "RANGE") and abs(dscore) < 20:
        label = "LOW_VOLATILITY"
        drivers.append("Volatility is low and price is coiling in a range.")

    # --- otherwise map the directional score -----------------------
    if label is None:
        if dscore >= 62:
            label = "STRONG_BULLISH_TREND"
        elif dscore >= 34:
            label = "BULLISH_TREND"
        elif dscore >= 15:
            label = "WEAK_BULLISH"
        elif dscore <= -62:
            label = "STRONG_BEARISH_TREND"
        elif dscore <= -34:
            label = "BEARISH_TREND"
        elif dscore <= -15:
            label = "WEAK_BEARISH"
        elif intel.market_structure in ("RANGE", "COMPRESSION"):
            label = "RANGE_BOUND"
        else:
            label = "NEUTRAL"
        drivers.append(f"Directional score {dscore:+.0f} → {label.replace('_', ' ').lower()}.")

    direction = "BULLISH" if dscore > 12 else "BEARISH" if dscore < -12 else "NEUTRAL"
    if label in ("HIGH_VOLATILITY", "LOW_VOLATILITY", "RANGE_BOUND", "NEUTRAL", "NO_TRADE", "EVENT_RISK"):
        direction = direction if label in ("HIGH_VOLATILITY",) else "NEUTRAL"

    # scores
    conf = _clamp(0.55 * confidence.score + 0.45 * min(100.0, abs(dscore) * 1.4), 0.0, 100.0)
    if label in ("NO_TRADE", "EVENT_RISK"):
        conf = min(conf, 55.0)

    stability = 70.0
    stability += {"STABLE": 15.0}.get(pcr.transition, -15.0)
    stability += {"HH_HL": 8, "LH_LL": 8, "RANGE": 6, "COMPRESSION": 2,
                  "REVERSAL_UP": -18, "REVERSAL_DOWN": -18, "EXPANSION": -12}.get(intel.market_structure, 0)
    stability -= 15.0 if vc == "EXTREME" else 0.0
    stability -= 12.0 if em_expanding else 0.0
    stability = _clamp(stability, 0.0, 100.0)

    transition_risk = _clamp(100.0 - stability
                             + (12.0 if pcr.transition != "STABLE" else 0.0)
                             + (10.0 if em_expanding else 0.0)
                             + (10.0 if conflict else 0.0), 0.0, 100.0)

    contributing["confidence"] = f"{confidence.score:.0f} ({confidence.band})"
    contributing["price_score"] = f"{price_score:+.0f}"
    contributing["options_score"] = f"{options_score:+.0f}"
    contributing["vol_class"] = vc
    contributing["expected_move"] = (
        f"{expected_move.points:.0f} pt" if expected_move.points else "n/a"
    ) + (", exceeded" if em_expanding else "")

    return RegimeState(
        label=label, direction=direction, vol_class=vc,
        confidence=conf, stability=stability, transition_risk=transition_risk,
        drivers=drivers, contributing=contributing,
    )
