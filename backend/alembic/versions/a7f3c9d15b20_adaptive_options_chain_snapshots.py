"""adaptive options chain snapshots

Revision ID: a7f3c9d15b20
Revises: 9a1c7b2f4e10
Create Date: 2026-09-03 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7f3c9d15b20"
down_revision: str | None = "9a1c7b2f4e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adaptive_chain_snapshots",
        sa.Column("underlying", sa.String(length=20), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("spot", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("dte", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("oi_pcr", sa.Numeric(precision=12, scale=5), nullable=True),
        sa.Column("weighted_pcr", sa.Numeric(precision=12, scale=5), nullable=True),
        sa.Column("atm_iv", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("put_support", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("call_resistance", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adaptive_snap_lookup",
        "adaptive_chain_snapshots",
        ["underlying", "expiry", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_adaptive_snap_lookup", table_name="adaptive_chain_snapshots")
    op.drop_table("adaptive_chain_snapshots")
