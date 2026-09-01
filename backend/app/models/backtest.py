import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BacktestStatus


class Backtest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single backtest run against a specific, immutable strategy version.

    Results (equity curve, trade list summary, metrics) are stored as JSONB
    for fast iteration; large tick-level detail (if ever needed) belongs in
    the shared Order/Trade tables tagged with this backtest_id instead of
    being crammed into this JSON blob.
    """

    __tablename__ = "backtests"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[BacktestStatus] = mapped_column(
        default=BacktestStatus.PENDING, nullable=False
    )
    instrument_universe: Mapped[list] = mapped_column(JSONB, nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False, default="day")

    # Populated once status == COMPLETED
    metrics: Mapped[dict | None] = mapped_column(JSONB)  # CAGR, Sharpe, max DD, win rate, ...
    equity_curve: Mapped[list | None] = mapped_column(JSONB)  # [[ts, equity], ...]
    error_message: Mapped[str | None] = mapped_column(String(2000))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    strategy_version: Mapped["object"] = relationship("StrategyVersion")
