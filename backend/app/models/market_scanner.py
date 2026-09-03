"""Persistence for the Market Scanner recommendation engine.

Every 5 minutes the scanner sweeps the tradable universe, scores each
instrument from technical + price-action + fundamental checks, and writes
the setups that clear the bar as :class:`ScanRecommendation` rows with
``status = "LIVE"``. A separate tracker loop marks each live row against
the real-time price and, when the target / stop / end-of-day is reached,
flips it to ``status = "EXPIRED"`` with a concrete ``outcome`` and result.

Nothing here is advice or a claim of profitability - it is screener output
with a transparent factor breakdown. See ``app/market_scanner/``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScanRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One sweep of the universe. Kept so the Log Book and /status can show
    coverage, data availability and why a cycle produced nothing."""

    __tablename__ = "scan_runs"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(12), nullable=False, default="schedule")  # schedule | manual

    data_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(400))  # why data_available is False

    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    produced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)

    # {"NSE:XYZ": "only 40 daily bars", ...} - instruments skipped and why
    skipped: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (Index("ix_scan_runs_started", "started_at"),)


class ScanRecommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "scan_recommendations"

    scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_runs.id", ondelete="SET NULL")
    )

    # --- instrument ------------------------------------------------------
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_token: Mapped[str] = mapped_column(String(24), nullable=False)
    segment: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    underlying: Mapped[str | None] = mapped_column(String(64))  # F&O root, for the option overlay
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False, default="EQUITY")  # EQUITY | INDEX | COMMODITY

    # --- the call -------------------------------------------------------
    horizon: Mapped[str] = mapped_column(String(10), nullable=False)  # INTRADAY | SWING  (view timeframe)
    # what to actually trade:
    #   EQUITY_DELIVERY  - buy/sell the stock, CNC, hold across days
    #   EQUITY_INTRADAY  - buy/sell the stock, MIS, square off same day
    #   OPTION           - a defined-risk option spread expressing the view
    trade_style: Mapped[str] = mapped_column(String(20), nullable=False, default="EQUITY_DELIVERY", index=True)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)  # LONG | SHORT
    setup_type: Mapped[str] = mapped_column(String(48), nullable=False)  # human label of the primary setup
    setup_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # ["golden_cross", "fvg_15m", ...]

    ref_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)  # LTP at scan time
    entry: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False, default="MARKET")  # MARKET | LIMIT | STOP
    stop_loss: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    target_1: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    target_2: Mapped[float | None] = mapped_column(Numeric(18, 4))
    rr: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)  # reward:risk to target_1
    atr: Mapped[float | None] = mapped_column(Numeric(18, 4))

    confidence: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)  # 0-100 strict quality score
    bias_score: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)  # -100..100 directional lean
    pop: Mapped[float | None] = mapped_column(Numeric(6, 4))  # option-overlay probability of profit only
    factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{name, detail, weight, side}]
    # the weighted sub-scores + penalties + caps behind ``confidence``
    score_detail: Mapped[dict | None] = mapped_column(JSONB)

    # optional attached defined-risk option structure
    option_overlay: Mapped[dict | None] = mapped_column(JSONB)
    # optional protective-option leg to run *alongside* an equity delivery
    # position (buy both together): {leg, strike, est_premium, cost_pct, floor}
    hedge: Mapped[dict | None] = mapped_column(JSONB)
    # links the equity card and the OPTION card that came from the same view
    pair_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    fundamentals: Mapped[dict | None] = mapped_column(JSONB)

    # --- lifecycle ----------------------------------------------------
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="LIVE", index=True)  # LIVE | EXPIRED
    outcome: Mapped[str | None] = mapped_column(String(12))  # TARGET | SL | NEUTRAL | INVALIDATED
    trading_day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD IST

    entered_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    exit_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    result_r: Mapped[float | None] = mapped_column(Numeric(8, 3))
    result_points: Mapped[float | None] = mapped_column(Numeric(18, 4))
    mfe_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))  # max favourable excursion
    mae_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))  # max adverse excursion

    last_ltp: Mapped[float | None] = mapped_column(Numeric(18, 4))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_state: Mapped[str] = mapped_column(String(8), nullable=False, default="OK")  # OK | STALE

    disclaimer: Mapped[str] = mapped_column(
        Text, nullable=False,
        default="Screener output, not advice. No guarantee of profit. Validate before trading.",
    )

    __table_args__ = (
        Index("ix_scan_reco_status_day", "status", "trading_day"),
        Index("ix_scan_reco_symbol_day", "tradingsymbol", "trading_day"),
    )


class ScannerAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A fired notification. Delivery channel (push / email / webhook) is
    wired later - for now the row is the alert and the UI reads it."""

    __tablename__ = "scanner_alerts"

    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_recommendations.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="NEW_TRADE")  # NEW_TRADE | TARGET | SL
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    channel: Mapped[str | None] = mapped_column(String(24))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_scanner_alerts_created", "created_at"),)
