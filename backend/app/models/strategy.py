import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import StrategyStatus


class Strategy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A named trading idea. All executable content lives on
    StrategyVersion — a Strategy row is just the stable identity + pointer to
    whichever version is "current" for new backtests/deployments."""

    __tablename__ = "strategies"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StrategyStatus] = mapped_column(
        default=StrategyStatus.DRAFT, nullable=False
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id", use_alter=True)
    )

    versions: Mapped[list["StrategyVersion"]] = relationship(
        back_populates="strategy",
        foreign_keys="StrategyVersion.strategy_id",
        cascade="all, delete-orphan",
        order_by="StrategyVersion.version_number",
    )


class StrategyVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An immutable snapshot of a strategy's logic + parameters.

    Immutability is deliberate: once created, a version's `source_code` and
    `parameters` never change (enforced at the service layer, not just by
    convention) so that a Backtest or Deployment referencing a version_id
    always reproduces exactly the logic that ran. Editing a strategy always
    creates a new version instead — that is also what makes version
    comparison (requirement #11) meaningful.
    """

    __tablename__ = "strategy_versions"
    __table_args__ = (
        Index("ix_strategy_versions_strategy_id_version", "strategy_id", "version_number", unique=True),
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    entry_point: Mapped[str] = mapped_column(
        String(200), nullable=False, default="Strategy"
    )  # class name inside source_code implementing app.strategies.base.BaseStrategy
    change_summary: Mapped[str | None] = mapped_column(Text)
    cloned_from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id")
    )

    strategy: Mapped["Strategy"] = relationship(
        back_populates="versions", foreign_keys=[strategy_id]
    )
