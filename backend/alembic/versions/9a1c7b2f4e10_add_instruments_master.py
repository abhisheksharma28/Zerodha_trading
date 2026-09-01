"""canonical instrument master

Revision ID: 9a1c7b2f4e10
Revises: 32586352cbfa
Create Date: 2026-09-02 01:20:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9a1c7b2f4e10"
down_revision: str | None = "32586352cbfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("instrument_token", sa.String(length=24), nullable=False),
        sa.Column("exchange_token", sa.String(length=24), nullable=True),
        sa.Column("tradingsymbol", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("exchange", sa.String(length=12), nullable=False),
        sa.Column("segment", sa.String(length=24), nullable=False),
        sa.Column("instrument_type", sa.String(length=12), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("strike", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("tick_size", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=True),
        sa.Column("underlying", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_symbol"),
    )
    op.create_index(op.f("ix_instruments_instrument_token"), "instruments", ["instrument_token"])
    op.create_index(op.f("ix_instruments_tradingsymbol"), "instruments", ["tradingsymbol"])
    op.create_index(op.f("ix_instruments_name"), "instruments", ["name"])
    op.create_index(op.f("ix_instruments_exchange"), "instruments", ["exchange"])
    op.create_index(op.f("ix_instruments_segment"), "instruments", ["segment"])
    op.create_index(op.f("ix_instruments_instrument_type"), "instruments", ["instrument_type"])
    op.create_index(op.f("ix_instruments_expiry"), "instruments", ["expiry"])
    op.create_index(op.f("ix_instruments_underlying"), "instruments", ["underlying"])
    op.create_index(op.f("ix_instruments_active"), "instruments", ["active"])


def downgrade() -> None:
    op.drop_table("instruments")
