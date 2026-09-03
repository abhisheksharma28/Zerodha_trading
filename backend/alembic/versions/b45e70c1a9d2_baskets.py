"""baskets

Revision ID: b45e70c1a9d2
Revises: 0c7269141e7d
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b45e70c1a9d2'
down_revision: Union[str, None] = '0c7269141e7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'baskets',
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('benchmark', sa.String(length=32), nullable=False),
        sa.Column('rebalance_frequency', sa.String(length=12), nullable=False),
        sa.Column('drift_band_pct', sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column('capital', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('paper_account_id', sa.UUID(), nullable=True),
        sa.Column('last_rebalanced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_backtest', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_baskets_status', 'baskets', ['status'], unique=False)

    op.create_table(
        'basket_rebalance_events',
        sa.Column('basket_id', sa.UUID(), nullable=False),
        sa.Column('as_of', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('target_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('orders', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('applied', sa.Boolean(), nullable=False),
        sa.Column('note', sa.String(length=300), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['basket_id'], ['baskets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_basket_rebalance_events_basket_id'),
        'basket_rebalance_events', ['basket_id'], unique=False,
    )
    op.create_index(
        'ix_basket_reb_basket_time',
        'basket_rebalance_events', ['basket_id', 'as_of'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_basket_reb_basket_time', table_name='basket_rebalance_events')
    op.drop_index(
        op.f('ix_basket_rebalance_events_basket_id'), table_name='basket_rebalance_events'
    )
    op.drop_table('basket_rebalance_events')
    op.drop_index('ix_baskets_status', table_name='baskets')
    op.drop_table('baskets')
