"""Arbitrage Lab — a subsystem separate from the directional Quant Strategy
Leaderboard.

Its own strategy interface, multi-leg backtest engine, net-edge calculator,
data-synchronisation layer, pair discovery, opportunity scanner, risk
engine and (paper) execution. Nothing here feeds the leaderboard or the
normal single-instrument backtest path.

Honesty is enforced by design: every opportunity carries a **net expected
edge** (gross edge minus every per-leg cost, financing, borrow and an
execution-risk buffer) and an **execution-viability score**, and strategies
are classified TRUE_ARBITRAGE / STATISTICAL_ARBITRAGE / RELATIVE_VALUE /
BASIS_ARBITRAGE / LATENCY_DEPENDENT / RESEARCH_ONLY — never "risk-free".
"""

from app.arbitrage.net_edge import NetEdgeBreakdown, net_expected_edge
from app.arbitrage.registry import ARB_STRATEGIES, get_arb_strategy
from app.arbitrage.types import (
    ArbCategory,
    ExecMode,
    Leg,
    Opportunity,
    SyncMode,
    TradeStructure,
)

__all__ = [
    "ARB_STRATEGIES",
    "ArbCategory",
    "ExecMode",
    "Leg",
    "NetEdgeBreakdown",
    "Opportunity",
    "SyncMode",
    "TradeStructure",
    "get_arb_strategy",
    "net_expected_edge",
]
