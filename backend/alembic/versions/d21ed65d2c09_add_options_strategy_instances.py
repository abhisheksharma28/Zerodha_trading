"""add options_strategy_instances

Revision ID: d21ed65d2c09
Revises: fbc207bdd7c7
Create Date: 2026-09-01 23:07:37.340777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd21ed65d2c09'
down_revision: Union[str, None] = 'fbc207bdd7c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    trading_mode = postgresql.ENUM(
        'BACKTEST', 'SIMULATION', 'PAPER', 'LIVE', name='tradingmode', create_type=False
    )
    options_status = postgresql.ENUM(
        'CREATED', 'VALIDATING', 'ENTRY_PENDING', 'ENTERED', 'ACTIVE', 'TARGET_HIT', 'STOP_LOSS',
        'SHORT_STRIKE_EXIT', 'TIME_EXIT', 'EXPIRY_EXIT', 'MANUAL_EXIT', 'FAILED', 'CLOSED',
        name='optionsstrategystatus', create_type=False,
    )
    postgresql.ENUM(
        'CREATED', 'VALIDATING', 'ENTRY_PENDING', 'ENTERED', 'ACTIVE', 'TARGET_HIT', 'STOP_LOSS',
        'SHORT_STRIKE_EXIT', 'TIME_EXIT', 'EXPIRY_EXIT', 'MANUAL_EXIT', 'FAILED', 'CLOSED',
        name='optionsstrategystatus',
    ).create(op.get_bind(), checkfirst=True)

    op.create_table('options_strategy_instances',
    sa.Column('slug', sa.String(length=50), nullable=False),
    sa.Column('mode', trading_mode, nullable=False),
    sa.Column('status', options_status, nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('basket_id', sa.String(length=64), nullable=False),
    sa.Column('underlying', sa.String(length=20), nullable=False),
    sa.Column('expiry', sa.Date(), nullable=True),
    sa.Column('entry_date', sa.Date(), nullable=True),
    sa.Column('entry_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dte_at_entry', sa.Integer(), nullable=True),
    sa.Column('spot_at_entry', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('lot_size', sa.Integer(), nullable=True),
    sa.Column('strike_a', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('strike_b', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('strike_c', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('basket', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('net_credit', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('credit_pct', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('deployed_capital', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('deployed_capital_source', sa.String(length=20), nullable=True),
    sa.Column('target_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('stop_loss_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('last_spot', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('last_pnl', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('exit_reason', sa.String(length=40), nullable=True),
    sa.Column('exit_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('exit_prices', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('realized_pnl', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('fees', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('net_pnl', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('not_eligible_reason', sa.String(length=500), nullable=True),
    sa.Column('strategy_version_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['strategy_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_options_strategy_instances_basket_id'), 'options_strategy_instances', ['basket_id'], unique=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f('ix_options_strategy_instances_basket_id'), table_name='options_strategy_instances')
    op.drop_table('options_strategy_instances')
    postgresql.ENUM(name='optionsstrategystatus').drop(op.get_bind(), checkfirst=True)
