"""Persistence for the Intraday Move Intelligence Engine.

Every scan cycle writes one :class:`ImieSignal` per instrument that clears
the watch threshold — a fully reproducible snapshot (the feature vector,
scores, state, suggested levels and the engine/config version that
produced it). A :class:`ImieStateTransition` is written whenever an
instrument's state changes. :class:`ImieConfig` is a single editable row
holding the weights / thresholds so nothing predictive is hard-coded as
its only source.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

STATES = (
    "NORMAL",
    "COMPRESSION",
    "PRESSURE_BUILDING",
    "BREAKOUT_IMMINENT",
    "MOVE_CONFIRMED",
    "TRENDING_EXPANSION",
    "EXHAUSTION",
    "REVERSAL_RISK",
)


class ImieSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "imie_signals"

    scan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False, default="NSE")
    sector: Mapped[str | None] = mapped_column(String(64), index=True)

    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # HIGH | MEDIUM | LOW

    move_probability: Mapped[float | None] = mapped_column(Float)   # 0..1, P(|move| > threshold)
    bullish_probability: Mapped[float | None] = mapped_column(Float)
    bearish_probability: Mapped[float | None] = mapped_column(Float)
    expected_move_pct_p50: Mapped[float | None] = mapped_column(Float)
    expected_move_pct_p75: Mapped[float | None] = mapped_column(Float)
    expected_move_pct_p90: Mapped[float | None] = mapped_column(Float)

    ltp: Mapped[float | None] = mapped_column(Float)
    trigger_level: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)

    # per-factor 0..100 scores and the raw feature vector (reproducible)
    factor_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    signals_detected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    trade_setup: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    historical: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    explain: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_imie_signal_symbol_at", "symbol", "at"),)


class ImieStateTransition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "imie_state_transitions"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    from_state: Mapped[str] = mapped_column(String(20), nullable=False)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ImieScan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "imie_scans"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    market_phase: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ImieConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "imie_config"

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    universe: Mapped[str] = mapped_column(String(16), nullable=False, default="fno")
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    opening_range_minutes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    move_thresholds_pct: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    min_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watch_score: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
