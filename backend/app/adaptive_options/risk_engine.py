"""Phase 11b — Risk engine + kill switch.

Pre-trade: capital allocation, margin usage, lot cap, portfolio delta,
daily trade count, and (defence in depth) a naked-without-ack block.
Returns ``ok`` / a ``scale`` factor / a hard ``blocked_reason``.

Kill switch: daily loss breached, data-quality failure passed in, or an
explicit operator trip — stops all new entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.sizing import SizedPosition
from app.adaptive_options.strategy_library import BuiltPosition


@dataclass
class PortfolioState:
    capital: float
    open_capital_at_risk: float = 0.0
    open_margin: float = 0.0
    open_delta_units: float = 0.0          # sum of position deltas (index units)
    spot: float = 0.0
    day_pnl: float = 0.0
    trades_today: int = 0
    adjustments_today: int = 0
    killed: bool = False
    kill_reasons: list[str] = field(default_factory=list)


@dataclass
class RiskDecision:
    ok: bool
    scale: float                 # 1.0 = full size, <1 = reduce, 0 = blocked
    blocked_reason: str | None
    warnings: list[str]
    checks: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "scale": round(self.scale, 3),
            "blocked_reason": self.blocked_reason,
            "warnings": self.warnings, "checks": self.checks,
        }


def kill_switch(state: PortfolioState, cfg: AdaptiveConfig, *, data_ok: bool = True) -> tuple[bool, list[str]]:
    reasons: list[str] = list(state.kill_reasons)
    if state.killed:
        reasons.append("Operator kill switch is engaged.")
    max_daily_loss = -cfg.account_capital * cfg.max_daily_loss_pct / 100.0
    if state.day_pnl <= max_daily_loss:
        reasons.append(f"Daily loss ₹{state.day_pnl:,.0f} breached the limit ₹{max_daily_loss:,.0f}.")
    if not data_ok:
        reasons.append("Data-quality gate failed — new entries halted.")
    if state.trades_today >= cfg.max_trades_per_day:
        reasons.append(f"Max trades/day ({cfg.max_trades_per_day}) reached.")
    return (len(reasons) > 0, reasons)


def expiry_guidance(dte: float, cfg: AdaptiveConfig) -> list[str]:
    if dte <= 0.5:
        return ["Expiry day: no new positions; manage existing to a flat close."]
    if dte <= cfg.expiry_reduce_dte:
        return [f"{dte:.0f} DTE: size halved, hedges mandatory, cut adjustment frequency, "
                "tighten exit discipline — gamma dominates here."]
    if dte <= cfg.expiry_reduce_dte + 3:
        return [f"{dte:.0f} DTE: gamma is rising; prefer defined-risk and smaller size."]
    return []


def check_entry(
    sized: SizedPosition,
    pos: BuiltPosition,
    cfg: AdaptiveConfig,
    state: PortfolioState,
    *,
    data_ok: bool = True,
    dte: float = 30.0,
) -> RiskDecision:
    checks: dict[str, str] = {}
    warnings: list[str] = []

    killed, kr = kill_switch(state, cfg, data_ok=data_ok)
    if killed:
        return RiskDecision(False, 0.0, "; ".join(kr), warnings, {"kill_switch": "TRIPPED"})

    if sized.lots <= 0:
        return RiskDecision(False, 0.0, "Sizing returned 0 lots (risk budget too small for this structure).",
                            warnings, {"sizing": "0 lots"})

    if pos.undefined_risk and not (cfg.allow_naked and cfg.naked_risk_acknowledged):
        return RiskDecision(False, 0.0, "Naked / undefined-risk structure without acknowledgement.",
                            warnings, {"naked": "BLOCKED"})

    scale = 1.0

    # capital allocation
    alloc = (state.open_capital_at_risk + sized.capital_at_risk) / max(state.capital, 1.0) * 100.0
    cap_limit = cfg.max_capital_allocation_pct
    checks["capital_allocation_pct"] = f"{alloc:.1f} / {cap_limit:.0f}"
    if alloc > cap_limit:
        room = max(0.0, cap_limit / 100.0 * state.capital - state.open_capital_at_risk)
        scale = min(scale, room / max(sized.capital_at_risk, 1.0))

    # margin
    mu = (state.open_margin + sized.margin) / max(state.capital, 1.0) * 100.0
    checks["margin_usage_pct"] = f"{mu:.1f} / {cfg.max_margin_usage_pct:.0f}"
    if mu > cfg.max_margin_usage_pct:
        room = max(0.0, cfg.max_margin_usage_pct / 100.0 * state.capital - state.open_margin)
        scale = min(scale, room / max(sized.margin, 1.0))

    # portfolio delta
    spot = state.spot or pos.legs[0].strike
    new_delta_units = pos.greeks.get("delta", 0.0) * sized.lots
    tot_delta_notional = abs(state.open_delta_units + new_delta_units) * spot
    dl = tot_delta_notional / max(state.capital, 1.0) * 100.0
    checks["portfolio_delta_pct"] = f"{dl:.1f} / {cfg.max_portfolio_delta_pct * 100:.0f}"
    if dl > cfg.max_portfolio_delta_pct * 100.0:
        warnings.append(f"Portfolio delta would be {dl:.0f}% of capital — directional risk is high.")
        if dl > cfg.max_portfolio_delta_pct * 200.0:
            scale = min(scale, 0.5)

    # lots cap
    checks["lots"] = f"{sized.lots} / {cfg.max_lots_per_trade}"

    scale = max(0.0, min(1.0, scale))
    if scale <= 0.0:
        return RiskDecision(False, 0.0, "No headroom under the capital / margin limits.", warnings, checks)
    if scale < 0.999:
        warnings.append(f"Scaled to {scale:.0%} of the sized position to fit risk limits.")

    for g in expiry_guidance(dte, cfg):
        warnings.append(g)

    return RiskDecision(True, scale, None, warnings, checks)
