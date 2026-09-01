import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OptionsStrategyStatus, TradingMode


class OptionsStrategyInstance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One run of a scheduled options-basket strategy (currently the NIFTY
    Monthly HNI 1:3:2 ratio). The three option legs are recorded as normal
    Order rows tagged with ``basket_id`` in ``raw_request``; this row holds
    the basket-level economics and lifecycle so target / stop / short-strike
    monitoring and restart recovery have a single source of truth.
    """

    __tablename__ = "options_strategy_instances"

    slug: Mapped[str] = mapped_column(String(50), nullable=False, default="nifty-monthly-hni")
    mode: Mapped[TradingMode] = mapped_column(nullable=False, default=TradingMode.PAPER)
    status: Mapped[OptionsStrategyStatus] = mapped_column(
        default=OptionsStrategyStatus.CREATED, nullable=False
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # idempotency: at most one non-terminal instance per (slug, expiry, mode)
    basket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    underlying: Mapped[str] = mapped_column(String(20), nullable=False, default="NIFTY")
    expiry: Mapped[date | None] = mapped_column(Date)
    entry_date: Mapped[date | None] = mapped_column(Date)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dte_at_entry: Mapped[int | None] = mapped_column()

    spot_at_entry: Mapped[float | None] = mapped_column(Numeric(18, 4))
    lot_size: Mapped[int | None] = mapped_column()
    strike_a: Mapped[float | None] = mapped_column(Numeric(18, 2))
    strike_b: Mapped[float | None] = mapped_column(Numeric(18, 2))  # short strike
    strike_c: Mapped[float | None] = mapped_column(Numeric(18, 2))

    # full basket + per-leg detail (strikes theoretical/actual/diff, tokens,
    # entry prices, order ids) — see app.strategies.options.base.BasketSpec
    basket: Mapped[dict | None] = mapped_column(JSONB)

    net_credit: Mapped[float | None] = mapped_column(Numeric(18, 2))
    credit_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    deployed_capital: Mapped[float | None] = mapped_column(Numeric(18, 2))
    deployed_capital_source: Mapped[str | None] = mapped_column(String(20))
    target_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    stop_loss_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))

    # monitoring state
    last_spot: Mapped[float | None] = mapped_column(Numeric(18, 4))
    last_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # exit
    exit_reason: Mapped[str | None] = mapped_column(String(40))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_prices: Mapped[dict | None] = mapped_column(JSONB)
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    fees: Mapped[float | None] = mapped_column(Numeric(18, 2))
    net_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))

    not_eligible_reason: Mapped[str | None] = mapped_column(String(500))

    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id")
    )
