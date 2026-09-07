"""stock screener ratings + runs

Revision ID: e8f2a1b3c4d6
Revises: d7e1f2a3b4c5
Create Date: 2026-09-07 10:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e8f2a1b3c4d6"
down_revision: str | None = "d7e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "screener_ratings",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("verdict", sa.String(length=8), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("composite", sa.Float(), nullable=False),
        sa.Column("value_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("growth_score", sa.Float(), nullable=True),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("data_completeness", sa.Float(), nullable=False),
        sa.Column("ltp", sa.Float(), nullable=True),
        sa.Column("pct_from_52w_high", sa.Float(), nullable=True),
        sa.Column("pct_from_52w_low", sa.Float(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_screener_ratings_symbol", "screener_ratings", ["symbol"])
    op.create_index("ix_screener_ratings_sector", "screener_ratings", ["sector"])
    op.create_index("ix_screener_ratings_verdict", "screener_ratings", ["verdict"])
    op.create_index("ix_screener_ratings_composite", "screener_ratings", ["composite"])
    op.create_index("ix_screener_verdict_score", "screener_ratings", ["verdict", "composite"])

    op.create_table(
        "screener_runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("scored", sa.Integer(), nullable=False),
        sa.Column("buy", sa.Integer(), nullable=False),
        sa.Column("hold", sa.Integer(), nullable=False),
        sa.Column("avoid", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("screener_runs")
    op.drop_index("ix_screener_verdict_score", table_name="screener_ratings")
    op.drop_index("ix_screener_ratings_composite", table_name="screener_ratings")
    op.drop_index("ix_screener_ratings_verdict", table_name="screener_ratings")
    op.drop_index("ix_screener_ratings_sector", table_name="screener_ratings")
    op.drop_index("ix_screener_ratings_symbol", table_name="screener_ratings")
    op.drop_table("screener_ratings")
