"""Persistence for the Stock Screener.

Once a day :mod:`app.screener.engine` sweeps the liquid NSE universe,
pulls fundamentals (configured provider) + technicals (Kite daily
candles), cross-sectionally ranks every name and writes one
:class:`ScreenerRating` per stock. The rating is a transparent composite
of four 0-100 pillars (value / quality / growth / technical) plus the raw
inputs that fed them, bucketed BUY / HOLD / AVOID by score. A name whose
data is too thin is forced to HOLD and flagged low-confidence.

Nothing here is advice. It is a screen with its full working shown.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScreenerRating(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "screener_ratings"

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(64), index=True)

    verdict: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # BUY | HOLD | AVOID
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # HIGH | MEDIUM | LOW

    composite: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    value_score: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    growth_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    data_completeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    ltp: Mapped[float | None] = mapped_column(Float)
    pct_from_52w_high: Mapped[float | None] = mapped_column(Float)
    pct_from_52w_low: Mapped[float | None] = mapped_column(Float)

    # TradingView-style technical rating from the same daily candles
    # (STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL); ta_score is the
    # net buy-minus-sell ratio in [-1, 1]; ta_detail holds the 3 gauges +
    # the 9 raw signals. Null when there were too few candles.
    ta_verdict: Mapped[str | None] = mapped_column(String(12), index=True)
    ta_score: Mapped[float | None] = mapped_column(Float)
    ta_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # every raw metric + per-pillar sub-factor breakdown, as pulled
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_screener_verdict_score", "verdict", "composite"),)


class ScreenerDeepDive(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generated, on-demand narrative deep-dive for one stock. The
    sections are written by the configured assistant LLM strictly from the
    numbers the screener already pulled — anything unsupported is left as
    "Not enough data." Cached per symbol; regenerated on request or when
    stale."""

    __tablename__ = "screener_deep_dives"

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    verdict: Mapped[str | None] = mapped_column(String(8))
    model: Mapped[str | None] = mapped_column(String(120))
    sections: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScreenerRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "screener_runs"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avoid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
