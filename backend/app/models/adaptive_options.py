"""Persistence for the Adaptive Options engine.

Phase 0-7 needs one table: a rolling store of option-chain snapshots. IV
rank / percentile, PCR percentile / z-score / transitions and OI-wall
migration are all computed *against this history*, so simply using the
Market Intelligence screen builds the dataset over time. It is also the
seed for the intraday backtest once enough history accumulates.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AdaptiveChainSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "adaptive_chain_snapshots"

    underlying: Mapped[str] = mapped_column(String(20), nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="live")

    spot: Mapped[float | None] = mapped_column(Numeric(18, 4))
    dte: Mapped[float | None] = mapped_column(Numeric(10, 4))

    # denormalised series columns — cheap to query for the history the engines need
    oi_pcr: Mapped[float | None] = mapped_column(Numeric(12, 5))
    weighted_pcr: Mapped[float | None] = mapped_column(Numeric(12, 5))
    atm_iv: Mapped[float | None] = mapped_column(Numeric(12, 6))
    put_support: Mapped[float | None] = mapped_column(Numeric(18, 2))
    call_resistance: Mapped[float | None] = mapped_column(Numeric(18, 2))

    # full per-strike rows for exact replay (compact ChainSnapshot.as_dict())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_adaptive_snap_lookup", "underlying", "expiry", "captured_at"),
    )


class AdaptivePaperRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A live paper-trading session driven by the adaptive decision engine."""

    __tablename__ = "adaptive_paper_runs"

    underlying: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")  # ACTIVE | STOPPED
    preset: Mapped[str] = mapped_column(String(20), nullable=False, default="balanced")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capital: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=1_000_000)
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(400))


class AdaptivePaperPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "adaptive_paper_positions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("adaptive_paper_runs.id", ondelete="CASCADE"),
        nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")  # OPEN | CLOSED
    expiry: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lots: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False)
    legs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    entry_spot: Mapped[float | None] = mapped_column(Numeric(18, 4))
    entry_net_premium: Mapped[float | None] = mapped_column(Numeric(18, 2))
    entry_costs: Mapped[float | None] = mapped_column(Numeric(18, 2))
    margin: Mapped[float | None] = mapped_column(Numeric(18, 2))
    target_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    stop_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    entry_regime: Mapped[str | None] = mapped_column(String(30))
    entry_iv: Mapped[float | None] = mapped_column(Numeric(12, 6))
    entry_confidence: Mapped[float | None] = mapped_column(Numeric(6, 2))
    adjustments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mae: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    mfe: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    last_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    exit_reason: Mapped[str | None] = mapped_column(String(120))
    gross_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    costs: Mapped[float | None] = mapped_column(Numeric(18, 2))
    net_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))


class AdaptiveDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "adaptive_decisions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("adaptive_paper_runs.id", ondelete="CASCADE"),
        nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    phase: Mapped[str] = mapped_column(String(12), nullable=False)  # select | manage
    regime: Mapped[str | None] = mapped_column(String(30))
    direction: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 2))
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    position_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
