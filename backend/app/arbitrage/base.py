"""Common architecture for Arbitrage Lab strategies.

An arbitrage strategy is driven by the :class:`ArbitrageBacktestEngine`
over *synchronised* multi-leg data points. It declares its data
requirements and honesty classification up front, discovers an opportunity
when flat, and reports exit conditions when in a position. Net-edge, cost
and viability maths live in :mod:`app.arbitrage.net_edge` /
:mod:`app.arbitrage.engine` — a strategy only expresses *intent*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.types import ArbCategory, Leg, Opportunity, TradeStructure
from app.strategies.library.base import ParamError, ParamSpec


@dataclass
class ArbSpec:
    slug: str
    name: str
    category: ArbCategory
    description: str
    logic: str
    legs: str                       # human description, e.g. "2 equities, market-neutral"
    data_requirements: list[str]
    latency_sensitivity: str        # none | low | medium | high | extreme
    min_net_edge_bps_default: float
    infra_note: str                 # e.g. "retail-viable" / "needs colo + TBT feed"
    warning: str
    supported_timeframes: tuple[str, ...] = ("1d", "60m")

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name, "category": self.category.value,
            "description": self.description, "logic": self.logic, "legs": self.legs,
            "data_requirements": self.data_requirements,
            "latency_sensitivity": self.latency_sensitivity,
            "min_net_edge_bps_default": self.min_net_edge_bps_default,
            "infra_note": self.infra_note, "warning": self.warning,
            "supported_timeframes": list(self.supported_timeframes),
        }


_COMMON: dict[str, ParamSpec] = {
    "capital": ParamSpec("number", 1_000_000.0, "Capital the strategy sizes each structure against (INR).",
                         min=10_000.0, group="sizing"),
    "position_fraction": ParamSpec("number", 0.5,
                                   "Fraction of capital deployed as one structure's gross notional.",
                                   min=0.05, max=1.0, group="sizing"),
    "min_net_edge_bps": ParamSpec("number", 15.0,
                                  "Minimum net expected edge (bps of structure notional) to open.",
                                  min=0.0, max=1000.0, group="risk"),
    "max_holding_days": ParamSpec("integer", 30, "Force convergence exit after this many days (0 = off).",
                                  min=0, max=400, group="risk"),
    "spread_bps": ParamSpec("number", 4.0, "Assumed round-trip bid/ask spread per leg (bps).",
                            min=0.0, max=500.0, group="risk"),
    "financing_rate_annual": ParamSpec("number", 0.09, "Annual financing rate for cash legs.",
                                       min=0.0, max=1.0, group="risk"),
    "borrow_rate_annual": ParamSpec("number", 0.04, "Annual stock-borrow rate for short legs.",
                                    min=0.0, max=1.0, group="risk"),
    "exec_risk_buffer_bps": ParamSpec("number", 3.0, "Execution-risk haircut (bps of notional).",
                                      min=0.0, max=200.0, group="risk"),
}


@dataclass
class OpenState:
    structure: TradeStructure
    entry_ts: Any
    entry_index: int
    entry_signal: dict[str, Any]


class ArbitrageStrategy(ABC):
    SPEC: ClassVar[ArbSpec]
    PARAMS: ClassVar[dict[str, ParamSpec]] = {}
    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {}
    N_LEGS: ClassVar[int] = 2

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.p = self.resolve_params(params or {})
        self._i = 0
        self.open: OpenState | None = None

    # --- params ------------------------------------------------

    @classmethod
    def all_params(cls) -> dict[str, ParamSpec]:
        return {**_COMMON, **cls.PARAMS}

    @classmethod
    def resolve_params(cls, supplied: dict[str, Any]) -> dict[str, Any]:
        schema = cls.all_params()
        unknown = set(supplied) - set(schema)
        if unknown:
            raise ParamError(f"Unknown parameter(s): {sorted(unknown)}")
        return {n: s.coerce(n, supplied.get(n)) for n, s in schema.items()}

    @classmethod
    def parameter_schema(cls) -> dict[str, Any]:
        return {n: s.to_dict() for n, s in cls.all_params().items()}

    @classmethod
    def detail(cls) -> dict[str, Any]:
        return {**cls.SPEC.as_dict(), "parameters": cls.parameter_schema(), "presets": cls.PRESETS,
                "n_legs": cls.N_LEGS}

    # --- engine hooks ----------------------------------------

    def ingest(self, point: SyncedPoint) -> None:
        self._i += 1
        self._on_point(point)

    @abstractmethod
    def _on_point(self, point: SyncedPoint) -> None:
        """Update rolling state from a synchronised multi-leg point."""

    @abstractmethod
    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        """Return a signal dict (with at least 'direction', 'gross_edge_bps',
        'hedge_ratio', 'expected_holding_days') when flat and an opportunity
        exists, else None. Cost/viability are applied by the engine."""

    @abstractmethod
    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        """Turn a signal into concrete legs sized against ``self.p['capital']``."""

    @abstractmethod
    def check_exit(self, point: SyncedPoint) -> tuple[bool, str]:
        """(should_exit, reason) for the current open structure."""

    # --- helpers -------------------------------------------

    def _leg(self, instrument: str, side: str, ratio: float, price: float, **kw: Any) -> Leg:
        return Leg(instrument=instrument, side=side, ratio=ratio, price=price, **kw)

    def opportunity_stub(self, signal: dict[str, Any], instruments: list[str]) -> Opportunity:
        from app.arbitrage.types import OpportunityStatus

        return Opportunity(
            strategy=self.SPEC.slug, category=self.SPEC.category, instruments=instruments,
            structure=None, gross_edge=0.0, estimated_costs=0.0, slippage=0.0, market_impact=0.0,
            net_expected_edge=0.0, liquidity_score=0.0, data_quality_score=0.0,
            execution_viability_score=0.0, latency_sensitivity=self.SPEC.latency_sensitivity,
            hedge_ratio=float(signal.get("hedge_ratio", 1.0)),
            expected_holding_days=float(signal.get("expected_holding_days", 0.0)),
            status=OpportunityStatus.WATCHING, metrics=dict(signal),
        )
