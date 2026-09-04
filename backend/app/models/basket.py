"""Baskets — a smallcase-style portfolio the platform holds and rebalances.

A basket is a set of *sleeves*, each with a fixed target weight of the
whole (e.g. 60% equity core, 25% gold, 15% silver). A sleeve can carry a
*rule* that re-ranks its member list on a schedule (momentum top-k with a
trend filter), so the basket drifts with the market while the sleeve
weights stay put. Rebalanced weekly / monthly / quarterly, only trading a
sleeve once it drifts past a band.

v1 deploys to the standalone paper account only (``paper_account_id``);
its orders route through ``app/paper_account/engine.py`` like any other
paper fill.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_MONEY = Numeric(18, 4)


class Basket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "baskets"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(40))  # new taxonomy, e.g. "Smart Alpha"

    # product-layer presentation metadata (carried from the flagship catalog
    # when a user clones a product; free-form for hand-built baskets)
    risk_level: Mapped[int | None] = mapped_column(SmallInteger)  # 1..5
    objective: Mapped[str | None] = mapped_column(String(400))
    horizon: Mapped[str | None] = mapped_column(String(40))
    investment_style: Mapped[str | None] = mapped_column(String(60))
    how_it_works: Mapped[list | None] = mapped_column(JSONB)  # list[str]
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    benchmark: Mapped[str] = mapped_column(String(32), nullable=False, default="NIFTY 50")
    rebalance_frequency: Mapped[str] = mapped_column(
        String(12), nullable=False, default="monthly"
    )  # weekly | monthly | quarterly
    drift_band_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=3.0)
    capital: Mapped[float] = mapped_column(_MONEY, nullable=False, default=500_000)

    spec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {"sleeves": [...]}

    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", index=True
    )  # draft | deployed | archived -> index ix_baskets_status
    paper_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_rebalanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_backtest: Mapped[dict | None] = mapped_column(JSONB)  # cached summary + curve


class BasketRebalanceEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One rebalance decision — a preview, a backtest step, or an applied
    paper rebalance. ``orders`` is the diff that was (or would be) sent."""

    __tablename__ = "basket_rebalance_events"

    basket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("baskets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="preview")
    # preview | paper | backtest
    target_weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {sym: w}
    orders: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # [{symbol, side, qty, est_value, from_weight, to_weight}]
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(300))
    attribution: Mapped[dict | None] = mapped_column(JSONB)
    # {regime, sleeves: [{sleeve_id, name, holdings: [{symbol, weight_pct, score,
    #  factor_ranks, status}]}], dropped, risk_contribution, notes}

    __table_args__ = (Index("ix_basket_reb_basket_time", "basket_id", "as_of"),)
