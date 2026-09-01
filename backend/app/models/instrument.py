"""Canonical instrument master, synced from Zerodha's instrument dumps.

Kite publishes the full tradable universe as unauthenticated CSVs at
``https://api.kite.trade/instruments/<exchange>``. ``instrument_service``
pulls those, upserts every row here keyed by ``(exchange, tradingsymbol)``,
and flips anything missing from the latest dump to ``active = False`` — so
the app always has a searchable, point-in-time-ish view of what is tradable
without anyone maintaining a hand-written list.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Instrument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_symbol"),
    )

    instrument_token: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    exchange_token: Mapped[str | None] = mapped_column(String(24))
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), index=True)

    exchange: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # EQ | FUT | CE | PE  (indices come through as EQ on segment INDICES)
    instrument_type: Mapped[str] = mapped_column(String(12), nullable=False, index=True)

    expiry: Mapped[date | None] = mapped_column(Date, index=True)
    strike: Mapped[float | None] = mapped_column(Numeric(18, 4))
    tick_size: Mapped[float | None] = mapped_column(Numeric(12, 4))
    lot_size: Mapped[int | None] = mapped_column(Integer)

    # Underlying tradingsymbol for derivatives (Kite puts it in the `name`
    # column of F&O rows); NULL for cash equities and indices.
    underlying: Mapped[str | None] = mapped_column(String(64), index=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
