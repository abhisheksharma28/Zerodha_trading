"""Import every model module here so Base.metadata is complete for Alembic
autogenerate and for `Base.metadata.create_all` in tests."""

from app.models.adaptive_options import (
    AdaptiveChainSnapshot,
    AdaptiveDecision,
    AdaptivePaperPosition,
    AdaptivePaperRun,
)
from app.models.audit import AuditLog, ChangeLogEntry
from app.models.backtest import Backtest
from app.models.broker_session import BrokerSession
from app.models.deployment import Deployment
from app.models.instrument import Instrument
from app.models.market_scanner import ScannerAlert, ScanRecommendation, ScanRun
from app.models.options_strategy import OptionsStrategyInstance
from app.models.order import Order, Trade
from app.models.paper_account import (
    PaperAccount,
    PaperHolding,
    PaperLedger,
    PaperOrder,
    PaperPosition,
    PaperStrategyRun,
    PaperTrade,
)
from app.models.strategy import Strategy, StrategyVersion

__all__ = [
    "AdaptiveChainSnapshot",
    "AdaptiveDecision",
    "AdaptivePaperPosition",
    "AdaptivePaperRun",
    "AuditLog",
    "ChangeLogEntry",
    "Backtest",
    "BrokerSession",
    "Deployment",
    "Instrument",
    "ScanRecommendation",
    "ScanRun",
    "ScannerAlert",
    "OptionsStrategyInstance",
    "Order",
    "Trade",
    "PaperAccount",
    "PaperOrder",
    "PaperTrade",
    "PaperPosition",
    "PaperHolding",
    "PaperLedger",
    "PaperStrategyRun",
    "Strategy",
    "StrategyVersion",
]
