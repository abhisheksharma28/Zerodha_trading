"""screener deep dives

Revision ID: f9a3b2c1d4e7
Revises: e8f2a1b3c4d6
Create Date: 2026-09-07 11:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f9a3b2c1d4e7"
down_revision: str | None = "e8f2a1b3c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "screener_deep_dives",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=8), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_screener_deep_dives_symbol", "screener_deep_dives", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_screener_deep_dives_symbol", table_name="screener_deep_dives")
    op.drop_table("screener_deep_dives")
