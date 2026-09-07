"""notifications outbox + config

Revision ID: c5d0e9a71f42
Revises: b4c9d2e5f6a8
Create Date: 2026-09-07 08:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c5d0e9a71f42"
down_revision: str | None = "b4c9d2e5f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_config",
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=True),
        sa.Column("notify_new_ideas", sa.Boolean(), nullable=False),
        sa.Column("notify_idea_outcomes", sa.Boolean(), nullable=False),
        sa.Column("notify_paper_fills", sa.Boolean(), nullable=False),
        sa.Column("notify_daily_summary", sa.Boolean(), nullable=False),
        sa.Column("idea_min_grade", sa.String(length=1), nullable=False),
        sa.Column("last_summary_day", sa.String(length=10), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notifications",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=400), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_status_created", "notifications", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_status_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_config")
