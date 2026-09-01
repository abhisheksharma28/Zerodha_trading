from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BrokerSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The single Zerodha session for this (single-user) platform.

    `access_token_encrypted` is never serialized in any API response schema
    (see app.schemas.broker) — only connection status + expiry are exposed.
    In practice there is at most one row per broker; kept as a table (rather
    than a singleton settings blob) so historical sessions are naturally
    audit-visible.
    """

    __tablename__ = "broker_sessions"

    broker: Mapped[str] = mapped_column(String(20), nullable=False, default="zerodha")
    kite_user_id: Mapped[str | None] = mapped_column(String(50))
    access_token_encrypted: Mapped[str | None] = mapped_column(String(1000))
    public_token: Mapped[str | None] = mapped_column(String(200))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
