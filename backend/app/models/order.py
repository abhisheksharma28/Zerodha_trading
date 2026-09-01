import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    OrderStatus,
    OrderTransactionType,
    OrderType,
    ProductType,
    TradingMode,
)


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single order, in ANY mode.

    Exactly one of (deployment_id, backtest_id) is set — this is what gives
    the platform one unified trade-log table (requirement #8) spanning
    backtest/simulation/paper/live instead of four separate schemas that
    would drift apart. `broker_order_id` / `raw_response` are only populated
    for orders that actually touched Zerodha (mode == LIVE, and PAPER once it
    starts mirroring order acks without routing to the exchange).
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "(deployment_id IS NOT NULL) OR (backtest_id IS NOT NULL)",
            name="ck_orders_has_deployment_or_backtest",
        ),
    )

    mode: Mapped[TradingMode] = mapped_column(nullable=False)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id", ondelete="CASCADE")
    )
    backtest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtests.id", ondelete="CASCADE")
    )

    broker_order_id: Mapped[str | None] = mapped_column(String(50), index=True)

    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    transaction_type: Mapped[OrderTransactionType] = mapped_column(nullable=False)
    order_type: Mapped[OrderType] = mapped_column(nullable=False)
    product: Mapped[ProductType] = mapped_column(nullable=False)
    variety: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    quantity: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    trigger_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    market_protection: Mapped[float | None] = mapped_column(Numeric(6, 4))

    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.PENDING, nullable=False)
    status_message: Mapped[str | None] = mapped_column(String(1000))

    raw_request: Mapped[dict | None] = mapped_column(JSONB)
    raw_response: Mapped[dict | None] = mapped_column(JSONB)

    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    trades: Mapped[list["Trade"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class Trade(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A fill against an Order. An order can have multiple partial fills."""

    __tablename__ = "trades"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[TradingMode] = mapped_column(nullable=False)
    broker_trade_id: Mapped[str | None] = mapped_column(String(50))
    fill_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    fill_quantity: Mapped[int] = mapped_column(nullable=False)
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="trades")
