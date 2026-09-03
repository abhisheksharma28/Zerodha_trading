"""A standalone discretionary paper-trading account - a demo demat/trading
account that behaves like Kite: virtual funds, manual buy/sell of equities
and F&O, positions that mark to the live price, delivered stock in
holdings, an order book, a trade book and a funds ledger.

Fully isolated from the strategy / deployment / OMS machinery
(``app/paper_account/``). One account per platform (single-user).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_MONEY = Numeric(18, 4)


class PaperAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "paper_accounts"

    name: Mapped[str] = mapped_column(String(80), nullable=False, default="Paper account")
    opening_balance: Mapped[float] = mapped_column(_MONEY, nullable=False, default=1_000_000)
    cash: Mapped[float] = mapped_column(_MONEY, nullable=False, default=1_000_000)   # free cash
    realized_pnl: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)   # cumulative booked
    charges_paid: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    auto_squareoff_mis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_eod_day: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD IST of the last EOD roll


class PaperOrder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "paper_orders"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_token: Mapped[str | None] = mapped_column(String(24))
    segment: Mapped[str | None] = mapped_column(String(24))
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False, default="EQUITY")  # EQUITY|FUT|OPT

    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY | SELL
    order_type: Mapped[str] = mapped_column(String(6), nullable=False, default="MARKET")  # MARKET|LIMIT|SL|SL-M
    product: Mapped[str] = mapped_column(String(4), nullable=False, default="CNC")  # CNC|MIS|NRML
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float | None] = mapped_column(_MONEY)
    trigger_price: Mapped[float | None] = mapped_column(_MONEY)

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN", index=True)
    # OPEN | COMPLETE | CANCELLED | REJECTED
    status_message: Mapped[str | None] = mapped_column(String(300))
    filled_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(_MONEY)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_squareoff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tag: Mapped[str | None] = mapped_column(String(64))  # e.g. "strat:<uuid>", "exit", "mis-squareoff"

    __table_args__ = (Index("ix_paper_orders_acct_status", "account_id", "status"),)


class PaperTrade(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "paper_trades"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False, default="EQUITY")
    product: Mapped[str] = mapped_column(String(4), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(_MONEY, nullable=False)
    value: Mapped[float] = mapped_column(_MONEY, nullable=False)
    charges: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    charges_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    realized_pnl: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)  # booked on this fill
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_paper_trades_acct_time", "account_id", "traded_at"),)


class PaperPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A net position for one (instrument, product). MIS positions are
    intraday (``day=True``); CNC/NRML carry overnight. Net qty 0 => CLOSED."""

    __tablename__ = "paper_positions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_token: Mapped[str | None] = mapped_column(String(24))
    segment: Mapped[str | None] = mapped_column(String(24))
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False, default="EQUITY")
    product: Mapped[str] = mapped_column(String(4), nullable=False)

    net_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buy_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sell_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buy_value: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    sell_value: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    avg_price: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)  # of the open leg
    realized_pnl: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    charges: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    margin_blocked: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)

    last_price: Mapped[float | None] = mapped_column(_MONEY)
    prev_close: Mapped[float | None] = mapped_column(_MONEY)
    day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # MIS
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="OPEN", index=True)  # OPEN|CLOSED
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trading_day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD IST

    __table_args__ = (
        Index("ix_paper_pos_key", "account_id", "tradingsymbol", "product", "status"),
    )


class PaperHolding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Delivered equity (CNC). Buys accumulate, sells reduce. ``t1_qty`` is
    the bit still settling (bought today, not yet deliverable)."""

    __tablename__ = "paper_holdings"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_token: Mapped[str | None] = mapped_column(String(24))

    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    t1_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_price: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    realized_pnl: Mapped[float] = mapped_column(_MONEY, nullable=False, default=0)
    last_price: Mapped[float | None] = mapped_column(_MONEY)
    prev_close: Mapped[float | None] = mapped_column(_MONEY)

    __table_args__ = (
        Index("ix_paper_hold_key", "account_id", "tradingsymbol"),
    )


class PaperAlgoConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row: the auto-trade ('Algo') settings for the paper account. When
    ``enabled``, LIVE Market-Scanner recommendations that pass the filters
    are auto-placed into this account and managed to the idea's stop/target."""

    __tablename__ = "paper_algo_config"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_grade: Mapped[str] = mapped_column(String(1), nullable=False, default="B")   # A | B | C
    pct_per_trade: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=2.0)
    max_open_auto: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    daily_loss_stop_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=5.0)
    cutoff_ist: Mapped[str] = mapped_column(String(5), nullable=False, default="14:45")
    allow_delivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_intraday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_options: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    equity_product: Mapped[str] = mapped_column(String(4), nullable=False, default="MIS")  # CNC | MIS
    halted_reason: Mapped[str | None] = mapped_column(String(200))  # set when the daily loss stop trips
    halted_day: Mapped[str | None] = mapped_column(String(10))


class PaperStrategyRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A strategy from the library, deployed to trade *inside* the paper
    account. Its fills flow through the same engine as manual orders and
    show up in the same positions / holdings / P&L; orders it places are
    tagged ``strat:<id>`` for per-strategy attribution."""

    __tablename__ = "paper_strategy_runs"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)  # template slug
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    instruments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # ["NSE:INFY", ...]
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False, default="day")
    product: Mapped[str] = mapped_column(String(4), nullable=False, default="CNC")

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", index=True)
    # ACTIVE | PAUSED | STOPPED
    flatten_on_stop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_bar_ts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {symbol: iso}
    signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_placed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (Index("ix_paper_strat_acct_status", "account_id", "status"),)


class PaperLedger(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "paper_ledger"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # FUNDS_ADD | BUY | SELL | CHARGES | MTM_SETTLE | RESET | SQUAREOFF
    amount: Mapped[float] = mapped_column(_MONEY, nullable=False)  # signed
    balance_after: Mapped[float] = mapped_column(_MONEY, nullable=False)
    ref: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (Index("ix_paper_ledger_acct_time", "account_id", "at"),)
