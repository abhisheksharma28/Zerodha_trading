"""Shared enums.

TradingMode is the single most important type in this codebase: almost every
safety rule in app/execution/guard.py exists to make sure a value here is
never LIVE by accident.
"""

import enum


class TradingMode(str, enum.Enum):
    BACKTEST = "backtest"
    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE = "live"


# Modes a Deployment row is allowed to hold. Backtests are their own entity
# (app.models.backtest.Backtest), never a Deployment — this makes it
# structurally impossible for a backtest run to be mistaken for a live
# deployment anywhere that switches on Deployment.mode.
DEPLOYABLE_MODES = (TradingMode.SIMULATION, TradingMode.PAPER, TradingMode.LIVE)


class StrategyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class BacktestStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentStatus(str, enum.Enum):
    PENDING = "pending"       # created, not yet started
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"       # terminal, deliberate
    ERROR = "error"           # terminal-ish, needs operator attention


class OrderTransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class ProductType(str, enum.Enum):
    CNC = "CNC"
    MIS = "MIS"
    NRML = "NRML"
    MTF = "MTF"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class ChangeEntityType(str, enum.Enum):
    STRATEGY = "strategy"
    STRATEGY_VERSION = "strategy_version"
    DEPLOYMENT = "deployment"
    RISK_CONFIG = "risk_config"
    BROKER_SESSION = "broker_session"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    DEPLOY = "deploy"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    CLONE = "clone"
    ORDER_PLACED = "order_placed"
    ORDER_REJECTED = "order_rejected"
    LOGIN = "login"
    LOGOUT = "logout"
    RISK_BREACH = "risk_breach"


class OptionsStrategyStatus(str, enum.Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTERED = "ENTERED"
    ACTIVE = "ACTIVE"
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS = "STOP_LOSS"
    SHORT_STRIKE_EXIT = "SHORT_STRIKE_EXIT"
    TIME_EXIT = "TIME_EXIT"
    EXPIRY_EXIT = "EXPIRY_EXIT"
    MANUAL_EXIT = "MANUAL_EXIT"
    FAILED = "FAILED"
    CLOSED = "CLOSED"
