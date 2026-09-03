"""Sector Seasonality — model freeze / version control and point-in-time
signal snapshots.

Stage 3 of the pipeline: before anything can be paper-traded the model is
*frozen* (methodology + parameters + the report it was built from), given
a version, and never mutated by live results. Stage 4 writes one immutable
signal snapshot per month, reproducible six months later.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SeasonalityModelVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "seasonality_model_versions"

    version: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # "v1.0"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="frozen", index=True)
    # frozen | retired
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    methodology_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # frozen knobs: edge measure, min_years, horizons, cost bps, strategy, universe
    report_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    backtest_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    verdict: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(1000))


class SeasonalitySignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "seasonality_signals"

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seasonality_model_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    signal_ref: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # e.g. "SEASONAL-2026-04-v1.0"
    for_month: Mapped[str] = mapped_column(String(7), nullable=False)   # "2026-04"
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff: Mapped[str] = mapped_column(String(10), nullable=False)  # last completed month-end

    rankings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    long_candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    short_candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    market_regime: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(12), nullable=False, default="generated", index=True)
    # generated | reviewed
    review: Mapped[dict | None] = mapped_column(JSONB)  # predicted vs actual, rank IC, spread
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_seasonality_signal_month", "model_version_id", "for_month"),)
