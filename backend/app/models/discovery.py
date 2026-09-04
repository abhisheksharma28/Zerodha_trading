"""Portfolio Alpha Discovery Engine — instrument universe + price store.

A point-in-time, versioned multi-asset dataset the discovery engine runs
against offline. Prices are ingested once (from Twelve Data for global
ETFs, from the Kite candle store for Indian ETFs) into ``discovery_bars``;
nothing in the search / validation path makes a live external call, so
every discovered portfolio is reproducible.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DiscoveryInstrument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "discovery_instruments"

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # EQUITY | BOND | COMMODITY | REIT | CASH | MIXED
    sub_class: Mapped[str] = mapped_column(String(48), nullable=False)  # "US Large Cap", ...
    region: Mapped[str] = mapped_column(String(12), nullable=False, default="US")  # US|INTL|EM|IN|GLOBAL
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="twelvedata")
    provider_symbol: Mapped[str] = mapped_column(String(48), nullable=False)
    return_kind: Mapped[str] = mapped_column(String(12), nullable=False, default="price")
    # price | total  (dividends reinvested)

    expense_ratio: Mapped[float | None] = mapped_column(Numeric(6, 4))
    inception_date: Mapped[date | None] = mapped_column(Date)

    data_start: Mapped[date | None] = mapped_column(Date)
    data_end: Mapped[date | None] = mapped_column(Date)
    n_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bar_interval: Mapped[str] = mapped_column(String(8), nullable=False, default="1month")
    tier: Mapped[str | None] = mapped_column(String(1), index=True)  # A|B|C|D
    quality_score: Mapped[float | None] = mapped_column(Numeric(6, 2))

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(String(300))


class DiscoveryBar(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "discovery_bars"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovery_instruments.id", ondelete="CASCADE"),
        nullable=False,
    )
    d: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)

    __table_args__ = (
        UniqueConstraint("instrument_id", "d", name="uq_discovery_bar"),
        Index("ix_discovery_bar_instr_d", "instrument_id", "d"),
    )


class DiscoveryFxRate(Base, UUIDPrimaryKeyMixin):
    """Daily / monthly FX close for currency normalisation (e.g. USD/INR)."""

    __tablename__ = "discovery_fx_rates"

    pair: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # "USD/INR"
    d: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)

    __table_args__ = (UniqueConstraint("pair", "d", name="uq_discovery_fx"),)


class DiscoveryIngestRun(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "discovery_ingest_runs"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="twelvedata")
    bar_interval: Mapped[str] = mapped_column(String(8), nullable=False, default="1month")
    n_instruments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_bars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(400))
