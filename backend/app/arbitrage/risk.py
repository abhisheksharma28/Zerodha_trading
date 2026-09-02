"""Arbitrage risk engine.

Every opportunity passes through here before it can open. Limits are
expressed against the strategy capital; a breach returns a typed reason so
the scanner / backtest / paper engine all reject for the same, auditable
cause. Also carries the emergency controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.arbitrage.types import TradeStructure


class RejectReason(str, Enum):
    INSUFFICIENT_CAPITAL = "INSUFFICIENT_CAPITAL"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    STALE_DATA = "STALE_DATA"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    NEGATIVE_NET_EDGE = "NEGATIVE_NET_EDGE"
    LATENCY_TOO_HIGH = "LATENCY_TOO_HIGH"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    EXECUTION_NOT_VIABLE = "EXECUTION_NOT_VIABLE"


class EmergencyControl(str, Enum):
    STOP_NEW_TRADES = "STOP_NEW_TRADES"
    CLOSE_ALL_POSITIONS = "CLOSE_ALL_POSITIONS"
    CANCEL_PENDING_ORDERS = "CANCEL_PENDING_ORDERS"
    DISABLE_STRATEGY = "DISABLE_STRATEGY"
    PAPER_MODE_ONLY = "PAPER_MODE_ONLY"


@dataclass
class ArbRiskLimits:
    max_capital_allocation_pct: float = 100.0   # % of strategy capital deployable
    max_gross_exposure_pct: float = 200.0       # Σ|leg notional| as % of capital
    max_net_exposure_pct: float = 40.0          # |Σ signed leg notional| as % of capital
    max_unhedged_exposure_pct: float = 25.0     # worst single-leg imbalance vs capital
    max_margin_usage_pct: float = 80.0
    max_position_per_strategy_pct: float = 60.0 # one structure's notional vs capital
    max_daily_loss_pct: float = 3.0
    max_leg_imbalance: float = 0.10             # fill-fraction spread across legs
    max_correlated_exposure_pct: float = 120.0  # combined notional of correlated open structures

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__}


@dataclass
class RiskState:
    capital: float
    open_gross: float = 0.0
    open_net: float = 0.0
    margin_used: float = 0.0
    day_pnl: float = 0.0
    open_structures: int = 0
    emergency: set[EmergencyControl] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital": self.capital, "open_gross": round(self.open_gross, 2),
            "open_net": round(self.open_net, 2), "margin_used": round(self.margin_used, 2),
            "day_pnl": round(self.day_pnl, 2), "open_structures": self.open_structures,
            "emergency": sorted(e.value for e in self.emergency),
        }


@dataclass
class RiskDecision:
    ok: bool
    reason: RejectReason | None = None
    detail: str = ""
    scale: float = 1.0  # allowed fraction of the requested structure (1.0 = full)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason.value if self.reason else None,
                "detail": self.detail, "scale": round(self.scale, 4)}


class ArbRiskEngine:
    def __init__(self, capital: float, limits: ArbRiskLimits | None = None) -> None:
        self.limits = limits or ArbRiskLimits()
        self.state = RiskState(capital=capital)
        self.rejections: dict[str, int] = {}

    # --- emergency controls ------------------------------------

    def trip(self, control: EmergencyControl) -> None:
        self.state.emergency.add(control)

    def clear(self, control: EmergencyControl) -> None:
        self.state.emergency.discard(control)

    # --- gate -------------------------------------------------

    def check_open(
        self,
        structure: TradeStructure,
        *,
        net_edge_bps: float,
        min_net_edge_bps: float,
        data_quality: float,
        liquidity_score: float,
        viability_score: float,
        latency_sensitivity: str,
        leg_imbalance: float = 0.0,
    ) -> RiskDecision:
        cap = self.state.capital
        if {EmergencyControl.STOP_NEW_TRADES, EmergencyControl.DISABLE_STRATEGY} & self.state.emergency:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED, "emergency control active")

        if net_edge_bps < min_net_edge_bps:
            return self._no(RejectReason.NEGATIVE_NET_EDGE,
                            f"net edge {net_edge_bps:.1f}bps < min {min_net_edge_bps:.1f}bps")
        if data_quality < 50.0:
            return self._no(RejectReason.STALE_DATA, f"data quality {data_quality:.0f}")
        if liquidity_score < 20.0:
            return self._no(RejectReason.LOW_LIQUIDITY, f"liquidity {liquidity_score:.0f}")
        if viability_score < 50.0:
            return self._no(RejectReason.EXECUTION_NOT_VIABLE, f"viability {viability_score:.0f}")
        if latency_sensitivity == "extreme":
            return self._no(RejectReason.LATENCY_TOO_HIGH,
                            "latency-critical strategy — not executable on this infra")
        if leg_imbalance > self.limits.max_leg_imbalance:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED,
                            f"leg imbalance {leg_imbalance:.2f} > {self.limits.max_leg_imbalance}")

        pct = 100.0 / cap if cap else 0.0
        gross = sum(abs(leg.price * leg.quantity) for leg in structure.legs)
        net = abs(sum((1 if leg.side.upper() == "BUY" else -1) * leg.price * leg.quantity
                      for leg in structure.legs))
        if structure.capital_required > cap * self.limits.max_capital_allocation_pct / 100.0:
            return self._no(RejectReason.INSUFFICIENT_CAPITAL,
                            f"needs {structure.capital_required:.0f} > cap allowance")
        if structure.margin_required > cap * self.limits.max_margin_usage_pct / 100.0:
            return self._no(RejectReason.INSUFFICIENT_MARGIN,
                            f"margin {structure.margin_required:.0f} over limit")
        if gross * pct > self.limits.max_position_per_strategy_pct:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED,
                            f"structure gross {gross * pct:.0f}% > "
                            f"{self.limits.max_position_per_strategy_pct}%")
        if (self.state.open_gross + gross) * pct > self.limits.max_gross_exposure_pct:
            return self._scaled(structure, gross, cap)
        if (self.state.open_net + net) * pct > self.limits.max_net_exposure_pct:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED,
                            f"net exposure {(self.state.open_net + net) * pct:.0f}% over limit")
        if self.state.day_pnl < -cap * self.limits.max_daily_loss_pct / 100.0:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED, "daily loss limit hit")
        return RiskDecision(ok=True)

    def _scaled(self, structure: TradeStructure, gross: float, cap: float) -> RiskDecision:
        headroom = cap * self.limits.max_gross_exposure_pct / 100.0 - self.state.open_gross
        if headroom <= 0 or gross <= 0:
            return self._no(RejectReason.RISK_LIMIT_EXCEEDED, "gross exposure limit — no headroom")
        return RiskDecision(ok=True, detail="scaled to gross-exposure headroom",
                            scale=max(0.0, min(1.0, headroom / gross)))

    def _no(self, reason: RejectReason, detail: str) -> RiskDecision:
        self.rejections[reason.value] = self.rejections.get(reason.value, 0) + 1
        return RiskDecision(ok=False, reason=reason, detail=detail)

    # --- state updates --------------------------------------

    def on_open(self, structure: TradeStructure) -> None:
        self.state.open_gross += sum(abs(leg.price * leg.quantity) for leg in structure.legs)
        self.state.open_net += abs(sum((1 if leg.side.upper() == "BUY" else -1)
                                       * leg.price * leg.quantity for leg in structure.legs))
        self.state.margin_used += structure.margin_required
        self.state.open_structures += 1

    def on_close(self, structure: TradeStructure, pnl: float) -> None:
        self.state.open_gross = max(0.0, self.state.open_gross
                                    - sum(abs(leg.price * leg.quantity) for leg in structure.legs))
        self.state.open_net = max(0.0, self.state.open_net
                                  - abs(sum((1 if leg.side.upper() == "BUY" else -1)
                                            * leg.price * leg.quantity for leg in structure.legs)))
        self.state.margin_used = max(0.0, self.state.margin_used - structure.margin_required)
        self.state.open_structures = max(0, self.state.open_structures - 1)
        self.state.day_pnl += pnl

    def new_day(self) -> None:
        self.state.day_pnl = 0.0

    def summary(self) -> dict[str, Any]:
        return {"limits": self.limits.as_dict(), "state": self.state.as_dict(),
                "rejections": self.rejections}
