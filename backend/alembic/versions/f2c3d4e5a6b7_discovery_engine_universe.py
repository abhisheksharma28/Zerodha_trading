"""discovery engine universe + price store

Revision ID: f2c3d4e5a6b7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-04 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f2c3d4e5a6b7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("asset_class", sa.String(length=16), nullable=False),
        sa.Column("sub_class", sa.String(length=48), nullable=False),
        sa.Column("region", sa.String(length=12), nullable=False, server_default="US"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="twelvedata"),
        sa.Column("provider_symbol", sa.String(length=48), nullable=False),
        sa.Column("return_kind", sa.String(length=12), nullable=False, server_default="price"),
        sa.Column("expense_ratio", sa.Numeric(6, 4), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("data_start", sa.Date(), nullable=True),
        sa.Column("data_end", sa.Date(), nullable=True),
        sa.Column("n_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bar_interval", sa.String(length=8), nullable=False, server_default="1month"),
        sa.Column("tier", sa.String(length=1), nullable=True),
        sa.Column("quality_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_discovery_instruments_symbol", "discovery_instruments", ["symbol"])
    op.create_index("ix_discovery_instruments_asset_class", "discovery_instruments", ["asset_class"])
    op.create_index("ix_discovery_instruments_tier", "discovery_instruments", ["tier"])
    op.create_index("ix_discovery_instruments_active", "discovery_instruments", ["active"])

    op.create_table(
        "discovery_bars",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("d", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["discovery_instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "d", name="uq_discovery_bar"),
    )
    op.create_index("ix_discovery_bar_instr_d", "discovery_bars", ["instrument_id", "d"])

    op.create_table(
        "discovery_fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair", sa.String(length=8), nullable=False),
        sa.Column("d", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair", "d", name="uq_discovery_fx"),
    )
    op.create_index("ix_discovery_fx_rates_pair", "discovery_fx_rates", ["pair"])

    op.create_table(
        "discovery_ingest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="twelvedata"),
        sa.Column("bar_interval", sa.String(length=8), nullable=False, server_default="1month"),
        sa.Column("n_instruments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("discovery_ingest_runs")
    op.drop_index("ix_discovery_fx_rates_pair", table_name="discovery_fx_rates")
    op.drop_table("discovery_fx_rates")
    op.drop_index("ix_discovery_bar_instr_d", table_name="discovery_bars")
    op.drop_table("discovery_bars")
    for ix in ("active", "tier", "asset_class", "symbol"):
        op.drop_index(f"ix_discovery_instruments_{ix}", table_name="discovery_instruments")
    op.drop_table("discovery_instruments")
