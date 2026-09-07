"""Persistence for the outbound notifications subsystem (``app/notifications/``).

Two tables:

* ``notification_config`` - one row, the runtime settings: the master
  on/off, the Telegram chat id, per-category toggles, the minimum idea
  grade to push, and a marker so the daily summary is sent once per day.
  The bot *token* is deliberately not here - it is a secret and lives in
  the environment (``settings.telegram_bot_token``).
* ``notifications`` - the delivery outbox / log. Event sites (the scanner,
  the tracker, the paper-account fill path) write a row here on their own
  transaction; a background loop in ``app/notifications/scheduler.py``
  picks up ``pending`` rows and delivers them, so a slow or failing
  Telegram call never blocks or breaks the trading loops.

Nothing here sends anything on import. See ``app/notifications/``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# outbox kinds
KIND_IDEA_NEW = "IDEA_NEW"
KIND_IDEA_OUTCOME = "IDEA_OUTCOME"
KIND_PAPER_FILL = "PAPER_FILL"
KIND_DAILY_SUMMARY = "DAILY_SUMMARY"
KIND_TEST = "TEST"

# outbox status
STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


class NotificationConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single row. Runtime notification settings, edited from
    Settings ▸ Notifications."""

    __tablename__ = "notification_config"

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))

    notify_new_ideas: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_idea_outcomes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_paper_fills: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_daily_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # only push a new idea whose grade is this letter or better (A|B|C).
    idea_min_grade: Mapped[str] = mapped_column(String(1), nullable=False, default="A")

    # YYYY-MM-DD IST of the last day a daily-summary row was enqueued.
    last_summary_day: Mapped[str | None] = mapped_column(String(10))


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One outbound message: a queued/sent/failed/skipped delivery record."""

    __tablename__ = "notifications"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="telegram")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(400))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_notifications_status_created", "status", "created_at"),)
