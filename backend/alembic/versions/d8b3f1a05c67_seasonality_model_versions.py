"""seasonality model versions + signals

Revision ID: d8b3f1a05c67
Revises: c7a1e2f4b8d3
Create Date: 2026-09-04 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd8b3f1a05c67'
down_revision: Union[str, None] = 'c7a1e2f4b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'seasonality_model_versions',
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('methodology_hash', sa.String(length=64), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('report_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('backtest_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('verdict', sa.String(length=200), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version'),
    )
    op.create_index(
        op.f('ix_seasonality_model_versions_status'),
        'seasonality_model_versions', ['status'], unique=False,
    )

    op.create_table(
        'seasonality_signals',
        sa.Column('model_version_id', sa.UUID(), nullable=False),
        sa.Column('signal_ref', sa.String(length=40), nullable=False),
        sa.Column('for_month', sa.String(length=7), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('data_cutoff', sa.String(length=10), nullable=False),
        sa.Column('rankings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('long_candidates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('short_candidates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('market_regime', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('review', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('frozen', sa.Boolean(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['model_version_id'], ['seasonality_model_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_ref'),
    )
    op.create_index(
        op.f('ix_seasonality_signals_model_version_id'),
        'seasonality_signals', ['model_version_id'], unique=False,
    )
    op.create_index(
        op.f('ix_seasonality_signals_status'),
        'seasonality_signals', ['status'], unique=False,
    )
    op.create_index(
        'ix_seasonality_signal_month',
        'seasonality_signals', ['model_version_id', 'for_month'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_seasonality_signal_month', table_name='seasonality_signals')
    op.drop_index(op.f('ix_seasonality_signals_status'), table_name='seasonality_signals')
    op.drop_index(op.f('ix_seasonality_signals_model_version_id'), table_name='seasonality_signals')
    op.drop_table('seasonality_signals')
    op.drop_index(op.f('ix_seasonality_model_versions_status'), table_name='seasonality_model_versions')
    op.drop_table('seasonality_model_versions')
