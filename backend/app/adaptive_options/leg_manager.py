"""Phase 12 — Dynamic leg management.

Given an open position and a fresh market read, return one action with its
trigger, reason, expected effect and risk impact. Priority order:

    stop hit  >  expiry close  >  regime flip against a directional book
    >  short strike threatened  >  greek breach  >  target hit  >  HOLD
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, IntelReport, PCRState, RegimeState, VolReport

ACTIONS = (
    "HOLD", "FULL_EXIT", "PARTIAL_EXIT", "REDUCE_QTY", "ROLL_UP", "ROLL_DOWN",
    "ROLL_OUT", "MOVE_HEDGE", "ADD_HEDGE", "CONVERT_TO_SPREAD",
)


@dataclass
class OpenPosition:
    slug: str
    direction: str                 # BULLISH | BEARISH | NEUTRAL
    lots: int
    lot_size: int
    entry_spot: float
    entry_net_premium: float        # +credit / -debit for the whole position
    short_call: float | None
    short_put: float | None
    long_call: float | None
    long_put: float | None
    entry_regime: str
    entry_pcr_state: str
    target_pnl: float               # absolute INR, >0
    stop_pnl: float                 # absolute INR, <0
    adjustments_done: int = 0
    undefined_risk: bool = False


@dataclass
class ManagementAction:
    action: str
    trigger: str
    reason: str
    expected_effect: str
    risk_impact: str
    urgency: str = "normal"         # normal | high | critical

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action, "trigger": self.trigger, "reason": self.reason,
            "expected_effect": self.expected_effect, "risk_impact": self.risk_impact,
            "urgency": self.urgency,
        }


def _hold(reason: str = "No trigger met; the thesis is intact.") -> ManagementAction:
    return ManagementAction("HOLD", "none", reason,
                            "Position left unchanged.", "Unchanged.")


def evaluate(
    pos: OpenPosition,
    cfg: AdaptiveConfig,
    *,
    snap: ChainSnapshot,
    regime: RegimeState,
    pcr: PCRState,
    intel: IntelReport,
    vol: VolReport,
    current_pnl: float,
    dte: float,
    portfolio_delta_units: float | None = None,
) -> ManagementAction:
    spot = snap.spot
    step = snap.strike_step()

    # 1. stop
    if current_pnl <= pos.stop_pnl:
        return ManagementAction(
            "FULL_EXIT", f"P&L {current_pnl:,.0f} ≤ stop {pos.stop_pnl:,.0f}",
            "Structure stop-loss hit.",
            "Realises the loss and frees margin.",
            "Removes all further risk from this position.", "critical")

    # 2. expiry close
    if dte <= max(0.5, cfg.expiry_reduce_dte - 1):
        return ManagementAction(
            "FULL_EXIT", f"{dte:.0f} DTE",
            "Too close to expiry to manage gamma safely.",
            "Closes the position before pin / assignment risk peaks.",
            "Eliminates expiry-day gamma and assignment risk.", "high")

    # 3. regime flip against a directional book
    now_dir = regime.direction
    if pos.direction in ("BULLISH", "BEARISH") and now_dir != "NEUTRAL" and now_dir != pos.direction:
        confirmed = pcr.transition_confirmed and (
            (pos.direction == "BULLISH" and pcr.transition == "TRANSITIONING_DOWN")
            or (pos.direction == "BEARISH" and pcr.transition == "TRANSITIONING_UP"))
        if confirmed:
            return ManagementAction(
                "FULL_EXIT", f"regime flipped {pos.direction} → {now_dir}, PCR reversal confirmed",
                "The directional thesis is broken.",
                "Exits before the adverse move extends.",
                "Cuts directional exposure to zero.", "high")
        return ManagementAction(
            "REDUCE_QTY", f"regime softened from {pos.direction} to {now_dir}",
            "Directional edge is weakening but not confirmed broken.",
            "Halves the position; keeps a runner if the thesis recovers.",
            "Roughly halves directional and vega exposure.")

    # 4. short strike threatened
    threat = _threatened_side(pos, spot, step)
    losing = current_pnl < 0
    if threat and losing:
        if threat == "call":
            act = "ROLL_UP" if not pos.undefined_risk else "MOVE_HEDGE"
            return ManagementAction(
                act, f"spot {spot:.0f} within {step:.0f} of short call {pos.short_call:.0f}",
                "Upside short strike is under pressure with the position red.",
                "Rolls the call side further out (or moves the hedge in) for a debit, buying room.",
                "Reduces upside gamma; caps or shifts the loss.", "high")
        act = "ROLL_DOWN" if not pos.undefined_risk else "MOVE_HEDGE"
        return ManagementAction(
            act, f"spot {spot:.0f} within {step:.0f} of short put {pos.short_put:.0f}",
            "Downside short strike is under pressure with the position red.",
            "Rolls the put side lower (or moves the hedge in) for a debit, buying room.",
            "Reduces downside gamma; caps or shifts the loss.", "high")

    # 5. greek breach (needs a portfolio delta context)
    if portfolio_delta_units is not None:
        dl_notional = abs(portfolio_delta_units) * spot
        if dl_notional > cfg.max_portfolio_delta_pct * cfg.account_capital / 100.0:
            return ManagementAction(
                "ADD_HEDGE", f"portfolio delta ₹{dl_notional:,.0f} over the limit",
                "Net directional exposure has drifted past the risk limit.",
                "Adds a small offsetting option leg to bring delta back toward neutral.",
                "Cuts directional risk; adds a little theta / cost.")

    # 6. IV spike against a short-vega book
    if not pos.undefined_risk and pos.direction == "NEUTRAL" and vol.iv_change and vol.iv_change > 0.02:
        return ManagementAction(
            "PARTIAL_EXIT", f"ATM IV +{vol.iv_change*100:.1f} pts",
            "A vega-negative structure is marking against a fast IV expansion.",
            "Closes ~half the lots to cut vega before it compounds.",
            "Halves vega and gamma exposure.")

    # 7. target
    if current_pnl >= pos.target_pnl:
        return ManagementAction(
            "FULL_EXIT", f"P&L {current_pnl:,.0f} ≥ target {pos.target_pnl:,.0f}",
            "Profit target reached.",
            "Books the gain and releases capital for the next setup.",
            "Removes all remaining risk from this position.")

    return _hold()


def _threatened_side(pos: OpenPosition, spot: float, step: float) -> str | None:
    near = step * 1.0
    if pos.short_call is not None and spot >= pos.short_call - near:
        return "call"
    if pos.short_put is not None and spot <= pos.short_put + near:
        return "put"
    return None
