import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DeploymentStatus, TradingMode


class Deployment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A running (or previously running) instance of a strategy version in
    SIMULATION, PAPER, or LIVE mode. Never BACKTEST — see
    app.models.enums.DEPLOYABLE_MODES.

    `live_trading_confirmed_at` / `live_trading_confirmation_phrase` exist
    specifically to satisfy requirement #14: LIVE deployments require an
    explicit, separately-recorded confirmation step at creation time, and
    app.execution.guard re-checks this row (not any cached/in-memory belief)
    before every single live order.
    """

    __tablename__ = "deployments"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mode: Mapped[TradingMode] = mapped_column(nullable=False)
    status: Mapped[DeploymentStatus] = mapped_column(
        default=DeploymentStatus.PENDING, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    instrument_universe: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Explicit, auditable proof of intent for LIVE deployments (requirement #14).
    live_trading_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_trading_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cloned_from_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id")
    )

    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(2000))

    strategy_version: Mapped["object"] = relationship("StrategyVersion")
