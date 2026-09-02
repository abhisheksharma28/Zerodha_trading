"""Value types for the Arbitrage Lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArbCategory(str, Enum):
    TRUE_ARBITRAGE = "TRUE_ARBITRAGE"
    STATISTICAL_ARBITRAGE = "STATISTICAL_ARBITRAGE"
    RELATIVE_VALUE = "RELATIVE_VALUE"
    BASIS_ARBITRAGE = "BASIS_ARBITRAGE"
    LATENCY_DEPENDENT = "LATENCY_DEPENDENT"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class ExecMode(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class SyncMode(str, Enum):
    STRICT_SYNC = "STRICT_SYNC"
    FORWARD_FILL_LIMITED = "FORWARD_FILL_LIMITED"
    LAST_VALID_PRICE_WITH_MAX_AGE = "LAST_VALID_PRICE_WITH_MAX_AGE"
    REJECT_STALE_DATA = "REJECT_STALE_DATA"


class OpportunityStatus(str, Enum):
    WATCHING = "WATCHING"
    CANDIDATE = "CANDIDATE"
    EXECUTABLE = "EXECUTABLE"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class HedgeState(str, Enum):
    FULLY_HEDGED = "FULLY_HEDGED"
    PARTIALLY_HEDGED = "PARTIALLY_HEDGED"
    UNHEDGED = "UNHEDGED"
    LEG_IMBALANCE = "LEG_IMBALANCE"
    EMERGENCY_CLOSE_REQUIRED = "EMERGENCY_CLOSE_REQUIRED"


@dataclass
class Leg:
    """One leg of a multi-leg arbitrage trade."""

    instrument: str
    side: str  # "BUY" | "SELL"
    ratio: float = 1.0          # relative size (hedge ratio), normalised so leg 0 == 1.0
    quantity: int = 0           # filled at trade construction time
    price: float = 0.0          # reference price at signal time
    segment: str = "equity"     # equity | futures | options — drives the cost model
    exchange: str = "NSE"
    product: str = "MIS"
    is_financing_leg: bool = False   # e.g. the cash leg of a cash-and-carry
    borrow_required: bool = False    # short leg that needs stock-borrow

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument, "side": self.side, "ratio": round(self.ratio, 6),
            "quantity": self.quantity, "price": round(self.price, 4), "segment": self.segment,
            "exchange": self.exchange, "product": self.product,
            "borrow_required": self.borrow_required,
        }


@dataclass
class TradeStructure:
    legs: list[Leg]
    direction: str            # human label, e.g. "long_spread" / "cash_and_carry"
    hedge_ratio: float
    notional_per_unit: float  # gross notional of one structure unit (all legs)
    capital_required: float
    margin_required: float
    expected_holding_days: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "legs": [leg.as_dict() for leg in self.legs],
            "direction": self.direction,
            "hedge_ratio": round(self.hedge_ratio, 6),
            "notional_per_unit": round(self.notional_per_unit, 2),
            "capital_required": round(self.capital_required, 2),
            "margin_required": round(self.margin_required, 2),
            "expected_holding_days": round(self.expected_holding_days, 2),
        }


@dataclass
class Opportunity:
    strategy: str
    category: ArbCategory
    instruments: list[str]
    structure: TradeStructure | None
    gross_edge: float           # currency, per structure unit
    estimated_costs: float
    slippage: float
    market_impact: float
    net_expected_edge: float
    liquidity_score: float      # 0-100
    data_quality_score: float   # 0-100
    execution_viability_score: float  # 0-100
    latency_sensitivity: str    # "none" | "low" | "medium" | "high" | "extreme"
    hedge_ratio: float
    expected_holding_days: float
    status: OpportunityStatus
    reject_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    ts: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "category": self.category.value,
            "instruments": self.instruments,
            "structure": self.structure.as_dict() if self.structure else None,
            "gross_edge": round(self.gross_edge, 4),
            "estimated_costs": round(self.estimated_costs, 4),
            "slippage": round(self.slippage, 4),
            "market_impact": round(self.market_impact, 4),
            "net_expected_edge": round(self.net_expected_edge, 4),
            "liquidity_score": round(self.liquidity_score, 1),
            "data_quality_score": round(self.data_quality_score, 1),
            "execution_viability_score": round(self.execution_viability_score, 1),
            "latency_sensitivity": self.latency_sensitivity,
            "hedge_ratio": round(self.hedge_ratio, 6),
            "expected_holding_days": round(self.expected_holding_days, 2),
            "status": self.status.value,
            "reject_reason": self.reject_reason,
            "metrics": self.metrics,
            "ts": self.ts,
        }
