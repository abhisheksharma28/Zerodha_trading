"""Adaptive Options — an options decision engine, not another strategy.

Pipeline (Phases 0-7 built here):

    AdaptiveContext (underlying bars + option-chain snapshot + config)
      -> data_quality.assess()      -> ChainQualityReport
      -> market_intelligence()      -> IntelReport
      -> pcr_engine.analyse()       -> PCRState
      -> positioning.analyse()      -> PositioningReport
      -> volatility.analyse()       -> VolReport
      -> greeks_engine.chain()      -> GreeksReport
      -> expected_move()            -> ExpectedMove
      -> confidence.score()         -> ConfidenceScore
      -> regime.classify()          -> RegimeState

Strategy selection, strike selection, sizing, risk, leg management,
backtesting and paper trading are later phases and are not in this package
yet. Everything is data-driven from ``AdaptiveConfig``; nothing about
thresholds or weights is hard-coded.
"""

from app.adaptive_options.config import PRESETS, AdaptiveConfig
from app.adaptive_options.types import (
    ChainRow,
    ChainSnapshot,
    ConfidenceScore,
    ExpectedMove,
    GreeksReport,
    IntelReport,
    PCRState,
    PositioningReport,
    RegimeState,
    VolReport,
)

__all__ = [
    "AdaptiveConfig",
    "PRESETS",
    "ChainRow",
    "ChainSnapshot",
    "ConfidenceScore",
    "ExpectedMove",
    "GreeksReport",
    "IntelReport",
    "PCRState",
    "PositioningReport",
    "RegimeState",
    "VolReport",
]
