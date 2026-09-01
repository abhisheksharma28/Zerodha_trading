"""Import every model module here so Base.metadata is complete for Alembic
autogenerate and for `Base.metadata.create_all` in tests."""

from app.models.audit import AuditLog, ChangeLogEntry
from app.models.backtest import Backtest
from app.models.broker_session import BrokerSession
from app.models.deployment import Deployment
from app.models.instrument import Instrument
from app.models.options_strategy import OptionsStrategyInstance
from app.models.order import Order, Trade
from app.models.strategy import Strategy, StrategyVersion

__all__ = [
    "AuditLog",
    "ChangeLogEntry",
    "Backtest",
    "BrokerSession",
    "Deployment",
    "Instrument",
    "OptionsStrategyInstance",
    "Order",
    "Trade",
    "Strategy",
    "StrategyVersion",
]
