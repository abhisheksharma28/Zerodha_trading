"""adaptive options paper trading tables

Revision ID: b8e4d1a06c33
Revises: a7f3c9d15b20
Create Date: 2026-09-03 01:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8e4d1a06c33"
down_revision: str | None = "a7f3c9d15b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = dict(server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "adaptive_paper_runs",
        sa.Column("underlying", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("preset", sa.String(length=20), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("capital", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "adaptive_paper_positions",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("legs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("entry_spot", sa.Numeric(18, 4), nullable=True),
        sa.Column("entry_net_premium", sa.Numeric(18, 2), nullable=True),
        sa.Column("entry_costs", sa.Numeric(18, 2), nullable=True),
        sa.Column("margin", sa.Numeric(18, 2), nullable=True),
        sa.Column("target_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("stop_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("entry_regime", sa.String(length=30), nullable=True),
        sa.Column("entry_iv", sa.Numeric(12, 6), nullable=True),
        sa.Column("entry_confidence", sa.Numeric(6, 2), nullable=True),
        sa.Column("adjustments", sa.Integer(), nullable=False),
        sa.Column("mae", sa.Numeric(18, 2), nullable=False),
        sa.Column("mfe", sa.Numeric(18, 2), nullable=False),
        sa.Column("last_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("exit_reason", sa.String(length=120), nullable=True),
        sa.Column("gross_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("costs", sa.Numeric(18, 2), nullable=True),
        sa.Column("net_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["adaptive_paper_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_adaptive_paper_positions_run_id", "adaptive_paper_positions", ["run_id"])
    op.create_table(
        "adaptive_decisions",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase", sa.String(length=12), nullable=False),
        sa.Column("regime", sa.String(length=30), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 2), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("position_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["adaptive_paper_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_adaptive_decisions_run_id", "adaptive_decisions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_adaptive_decisions_run_id", table_name="adaptive_decisions")
    op.drop_table("adaptive_decisions")
    op.drop_index("ix_adaptive_paper_positions_run_id", table_name="adaptive_paper_positions")
    op.drop_table("adaptive_paper_positions")
    op.drop_table("adaptive_paper_runs")
