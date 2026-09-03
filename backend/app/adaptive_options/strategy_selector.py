"""Phase 9 — Adaptive Strategy Selection.

Scores every eligible template with a configurable Suitability Score
(regime / positioning / volatility / PCR / price-action / risk-reward /
liquidity / DTE), builds the best few into concrete positions, and ranks
them. NO_TRADE is returned whenever the data-quality gate fails, the
regime is NO_TRADE / EVENT_RISK without an expansion template fitting, or
engine confidence is below the floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adaptive_options import strike_selector
from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.strategy_library import (
    BuiltPosition,
    StrategyTemplate,
    available_templates,
    build_position,
)
from app.adaptive_options.types import (
    ChainSnapshot,
    ConfidenceScore,
    ExpectedMove,
    IntelReport,
    PCRState,
    PositioningReport,
    RegimeState,
    VolReport,
)


@dataclass
class RankedStrategy:
    slug: str
    name: str
    suitability: float
    risk_level: str
    reasons: list[str]
    components: dict[str, float]
    position: dict[str, Any]
    strikes: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name,
            "suitability": round(self.suitability, 1), "risk_level": self.risk_level,
            "reasons": self.reasons,
            "components": {k: round(v, 1) for k, v in self.components.items()},
            "position": self.position, "strikes": self.strikes,
        }


@dataclass
class SelectionResult:
    action: str                 # ENTER | NO_TRADE | WAIT
    no_trade_reason: str | None
    ranked: list[RankedStrategy]
    avoid: list[dict[str, Any]]
    top: RankedStrategy | None
    decision_matrix: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "no_trade_reason": self.no_trade_reason,
            "top": self.top.as_dict() if self.top else None,
            "ranked": [r.as_dict() for r in self.ranked],
            "avoid": self.avoid,
            "decision_matrix": self.decision_matrix,
        }


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _regime_match(t: StrategyTemplate, reg: RegimeState) -> tuple[float, str]:
    s = 45.0
    if reg.label in t.fit_regimes:
        s += 35.0
    if t.direction != "NEUTRAL" and reg.direction != "NEUTRAL":
        s += 20.0 if t.direction == reg.direction else -30.0
    elif t.direction == "NEUTRAL" and reg.direction == "NEUTRAL":
        s += 15.0
    s += (reg.confidence - 50.0) * 0.2
    why = f"regime {reg.label} ({reg.direction})" + (" — listed fit" if reg.label in t.fit_regimes else "")
    return _clamp(s), why


def _positioning_match(t: StrategyTemplate, pos: PositioningReport) -> tuple[float, str]:
    s = 50.0
    sells_puts = any(lg.right == "PE" and lg.side == "SELL" for lg in t.legs)
    sells_calls = any(lg.right == "CE" and lg.side == "SELL" for lg in t.legs)
    if sells_puts:
        s += (pos.put_writing_strength - 50.0) * 0.6
    if sells_calls:
        s += (pos.call_writing_strength - 50.0) * 0.6
    if sells_puts and sells_calls and pos.oi_concentration > 0.4:
        s += 8.0     # both-side writing into a pinned chain
    if t.direction == "BULLISH" and pos.price_oi_state in ("LONG_BUILDUP", "SHORT_COVERING"):
        s += 8.0
    if t.direction == "BEARISH" and pos.price_oi_state in ("SHORT_BUILDUP", "LONG_UNWINDING"):
        s += 8.0
    return _clamp(s), f"writing put {pos.put_writing_strength:.0f} / call {pos.call_writing_strength:.0f}"


def _vol_match(t: StrategyTemplate, vol: VolReport) -> tuple[float, str]:
    s = 45.0
    if vol.iv_class in t.fit_iv:
        s += 25.0
    is_seller = t.category in ("VOL_CONTRACTION", "NEUTRAL") or any(
        lg.side == "SELL" for lg in t.legs) and not any(lg.side == "BUY" and lg.ratio > 1 for lg in t.legs)
    is_buyer = t.category == "VOL_EXPANSION"
    if is_buyer:
        s += {"FAVOURABLE": -20.0, "NEUTRAL": 5.0, "UNFAVOURABLE": 22.0}[vol.vol_selling_verdict]
    elif is_seller:
        s += {"FAVOURABLE": 22.0, "NEUTRAL": 0.0, "UNFAVOURABLE": -22.0}[vol.vol_selling_verdict]
    return _clamp(s), f"IV {vol.iv_class}, selling {vol.vol_selling_verdict.lower()}"


def _pcr_confirm(t: StrategyTemplate, pcr: PCRState) -> tuple[float, str]:
    s = 50.0
    bull_states = ("BULLISH", "STRONG_BULLISH")
    bear_states = ("BEARISH", "STRONG_BEARISH")
    if t.direction == "BULLISH":
        s += 22.0 if pcr.state in bull_states else -18.0 if pcr.state in bear_states else 0.0
        if pcr.transition_confirmed and pcr.transition == "TRANSITIONING_UP":
            s += 12.0
    elif t.direction == "BEARISH":
        s += 22.0 if pcr.state in bear_states else -18.0 if pcr.state in bull_states else 0.0
        if pcr.transition_confirmed and pcr.transition == "TRANSITIONING_DOWN":
            s += 12.0
    else:
        s += 15.0 if pcr.state == "NEUTRAL" else -5.0
    if pcr.price_divergence in ("DIVERGING_BULLISH", "DIVERGING_BEARISH"):
        s -= 10.0
    return _clamp(s), f"PCR {pcr.state} / {pcr.transition.lower()}"


def _price_action(t: StrategyTemplate, intel: IntelReport) -> tuple[float, str]:
    s = 50.0
    trend_ok = {
        "BULLISH": intel.trend_direction == "UP",
        "BEARISH": intel.trend_direction == "DOWN",
        "NEUTRAL": intel.trend_direction == "SIDEWAYS",
    }[t.direction]
    s += 20.0 if trend_ok else -15.0
    if t.direction == "NEUTRAL" and intel.market_structure in ("RANGE", "COMPRESSION"):
        s += 12.0
    if t.category == "VOL_EXPANSION" and intel.market_structure in ("COMPRESSION", "REVERSAL_UP", "REVERSAL_DOWN"):
        s += 15.0
    return _clamp(s), f"trend {intel.trend_direction}, structure {intel.market_structure}"


def _risk_reward(pos: BuiltPosition) -> tuple[float, str]:
    rr = pos.risk_reward
    s = 40.0 + pos.pop * 45.0
    if rr is not None:
        s += min(15.0, rr * 12.0)
    elif pos.undefined_risk:
        s -= 15.0
    return _clamp(s), (f"POP {pos.pop:.0%}, R:R "
                       + ("n/a (undefined risk)" if rr is None else f"{rr:.2f}"))


def _liquidity(pos: BuiltPosition, snap: ChainSnapshot) -> tuple[float, str]:
    ois = []
    for lg in pos.legs:
        row = min(snap.rows, key=lambda r: abs(r.strike - lg.strike))
        ois.append(row.call_oi if lg.right == "CE" else row.put_oi)
    m = min(ois) if ois else 0.0
    s = 40.0 if m <= 0 else 60.0 if m < 20_000 else 82.0 if m < 100_000 else 92.0
    return s, f"thinnest leg OI ~ {m:,.0f}"


def _dte_match(t: StrategyTemplate, dte: float) -> tuple[float, str]:
    if t.min_dte <= dte <= t.max_dte:
        centre = (t.min_dte + t.max_dte) / 2
        span = max(t.max_dte - t.min_dte, 1)
        return _clamp(90.0 - abs(dte - centre) / span * 40.0), f"{dte:.0f} DTE in [{t.min_dte},{t.max_dte}]"
    return 15.0, f"{dte:.0f} DTE outside [{t.min_dte},{t.max_dte}]"


def _risk_level(pos: BuiltPosition, cfg: AdaptiveConfig) -> str:
    if pos.undefined_risk:
        return "UNDEFINED"
    frac = pos.max_loss / max(cfg.account_capital, 1.0)
    return "HIGH" if frac > 0.04 else "MEDIUM" if frac > 0.015 else "LOW"


def decision_matrix(cfg: AdaptiveConfig) -> list[dict[str, Any]]:
    rows = []
    for t in available_templates(cfg, far_expiry_ok=True):
        rows.append({
            "strategy": t.name, "slug": t.slug, "direction": t.direction,
            "category": t.category, "defined_risk": t.defined_risk,
            "regimes": list(t.fit_regimes), "pcr": list(t.fit_pcr) or ["any"],
            "iv": list(t.fit_iv) or ["any"], "thesis": t.thesis,
        })
    return rows


def rank(
    cfg: AdaptiveConfig,
    *,
    snap: ChainSnapshot,
    regime: RegimeState,
    pcr: PCRState,
    positioning: PositioningReport,
    vol: VolReport,
    expected_move: ExpectedMove,
    confidence: ConfidenceScore,
    intel: IntelReport,
    data_ok: bool = True,
    far_expiry_ok: bool = False,
    top_n: int = 6,
) -> SelectionResult:
    matrix = decision_matrix(cfg)

    if not data_ok:
        return SelectionResult("NO_TRADE", "Data-quality gate failed — no decision.", [], [], None, matrix)
    if regime.label == "NO_TRADE":
        return SelectionResult("NO_TRADE",
                               "Regime is NO_TRADE: " + (regime.drivers[0] if regime.drivers else "conflicting signals."),
                               [], [], None, matrix)
    if confidence.score < cfg.no_trade_confidence_min:
        return SelectionResult("NO_TRADE",
                               f"Engine confidence {confidence.score:.0f} < floor {cfg.no_trade_confidence_min:.0f}.",
                               [], [], None, matrix)

    plan = strike_selector.select(
        snap, cfg,
        expected_move_points=expected_move.points,
        support=intel.support, resistance=intel.resistance,
        call_wall=positioning.call_resistance, put_wall=positioning.put_support,
    )
    fb_iv = vol.atm_iv or 0.13

    weights_raw = {
        "regime": cfg.w_regime_match, "positioning": cfg.w_positioning_match,
        "volatility": cfg.w_volatility_match, "pcr": cfg.w_pcr_confirm,
        "price_action": cfg.w_price_action_confirm, "risk_reward": cfg.w_risk_reward,
        "liquidity": cfg.w_liquidity_match, "dte": cfg.w_dte_match,
    }
    wsum = sum(weights_raw.values()) or 1.0
    weights = {k: v / wsum for k, v in weights_raw.items()}

    ranked: list[RankedStrategy] = []
    avoid: list[dict[str, Any]] = []

    for t in available_templates(cfg, far_expiry_ok=far_expiry_ok):
        try:
            pos = build_position(t, plan.levels, snap, lots=1,
                                 lot_size=_lot_size(snap), fallback_iv=fb_iv)
        except (ValueError, KeyError) as exc:
            avoid.append({"slug": t.slug, "suitability": 0.0, "reason": f"cannot build: {exc}"})
            continue

        comps: dict[str, float] = {}
        why: list[str] = []
        for name, fn, arg in (
            ("regime", _regime_match, (t, regime)),
            ("positioning", _positioning_match, (t, positioning)),
            ("volatility", _vol_match, (t, vol)),
            ("pcr", _pcr_confirm, (t, pcr)),
            ("price_action", _price_action, (t, intel)),
            ("risk_reward", _risk_reward, (pos,)),
            ("liquidity", _liquidity, (pos, snap)),
            ("dte", _dte_match, (t, snap.dte)),
        ):
            val, txt = fn(*arg)
            comps[name] = val
            why.append(f"{name.replace('_', ' ')}: {txt}")

        suit = _clamp(sum(comps[k] * weights[k] for k in comps))
        rec = RankedStrategy(
            slug=t.slug, name=t.name, suitability=suit,
            risk_level=_risk_level(pos, cfg),
            reasons=why, components=comps,
            position=pos.as_dict(), strikes=plan.as_dict(),
        )
        if suit < cfg.suitability_min:
            avoid.append({"slug": t.slug, "suitability": round(suit, 1),
                          "reason": _weakest(comps)})
        else:
            ranked.append(rec)

    ranked.sort(key=lambda r: -r.suitability)
    ranked = ranked[:top_n]
    top = ranked[0] if ranked else None
    action = "ENTER" if top and top.suitability >= cfg.suitability_min else "WAIT"
    reason = None if action == "ENTER" else "No strategy cleared the suitability floor for this market."
    return SelectionResult(action, reason, ranked, avoid, top, matrix)


def compare(cfg: AdaptiveConfig, slugs: list[str], **ctx: Any) -> list[dict[str, Any]]:
    res = rank(cfg, top_n=99, **ctx)
    by = {r.slug: r for r in res.ranked}
    by_avoid = {a["slug"]: a for a in res.avoid}
    out: list[dict[str, Any]] = []
    for s in slugs:
        if s in by:
            out.append(by[s].as_dict())
        elif s in by_avoid:
            out.append({**by_avoid[s], "avoided": True})
        else:
            out.append({"slug": s, "error": "not eligible (naked without ack, or unknown slug)"})
    return out


def _weakest(comps: dict[str, float]) -> str:
    k = min(comps, key=lambda x: comps[x])
    return f"weak {k.replace('_', ' ')} ({comps[k]:.0f}/100)"


def _lot_size(snap: ChainSnapshot) -> int:
    try:
        from app.options.instruments_nfo import lot_size_for
        return lot_size_for(snap.underlying)
    except Exception:  # noqa: BLE001
        return {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 140}.get(snap.underlying, 50)
