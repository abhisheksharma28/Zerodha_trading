"""IMIE phase 1: signals, transitions, scans, config

Revision ID: c3d4e5f6a7ba
Revises: b2c3d4e5f6a9
Create Date: 2026-09-07 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d4e5f6a7ba"
down_revision: str | None = "b2c3d4e5f6a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TS = sa.DateTime(timezone=True)


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "imie_signals",
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("at", _TS, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=8), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("opportunity_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("move_probability", sa.Float(), nullable=True),
        sa.Column("bullish_probability", sa.Float(), nullable=True),
        sa.Column("bearish_probability", sa.Float(), nullable=True),
        sa.Column("expected_move_pct_p50", sa.Float(), nullable=True),
        sa.Column("expected_move_pct_p75", sa.Float(), nullable=True),
        sa.Column("expected_move_pct_p90", sa.Float(), nullable=True),
        sa.Column("ltp", sa.Float(), nullable=True),
        sa.Column("trigger_level", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("factor_scores", _JSONB, nullable=False),
        sa.Column("features", _JSONB, nullable=False),
        sa.Column("signals_detected", _JSONB, nullable=False),
        sa.Column("trade_setup", _JSONB, nullable=False),
        sa.Column("historical", _JSONB, nullable=False),
        sa.Column("explain", _JSONB, nullable=False),
        sa.Column("engine_version", sa.String(length=16), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("data_note", sa.Text(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imie_signals_scan_id", "imie_signals", ["scan_id"])
    op.create_index("ix_imie_signals_at", "imie_signals", ["at"])
    op.create_index("ix_imie_signals_symbol", "imie_signals", ["symbol"])
    op.create_index("ix_imie_signals_sector", "imie_signals", ["sector"])
    op.create_index("ix_imie_signals_state", "imie_signals", ["state"])
    op.create_index("ix_imie_signals_opportunity_score", "imie_signals", ["opportunity_score"])
    op.create_index("ix_imie_signal_symbol_at", "imie_signals", ["symbol", "at"])

    op.create_table(
        "imie_state_transitions",
        sa.Column("at", _TS, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=False),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("opportunity_score", sa.Float(), nullable=False),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imie_state_transitions_at", "imie_state_transitions", ["at"])
    op.create_index("ix_imie_state_transitions_symbol", "imie_state_transitions", ["symbol"])

    op.create_table(
        "imie_scans",
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("evaluated", sa.Integer(), nullable=False),
        sa.Column("emitted", sa.Integer(), nullable=False),
        sa.Column("market_phase", sa.String(length=16), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "imie_config",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("universe", sa.String(length=16), nullable=False),
        sa.Column("weights", _JSONB, nullable=False),
        sa.Column("thresholds", _JSONB, nullable=False),
        sa.Column("opening_range_minutes", _JSONB, nullable=False),
        sa.Column("move_thresholds_pct", _JSONB, nullable=False),
        sa.Column("min_volume", sa.Integer(), nullable=False),
        sa.Column("watch_score", sa.Float(), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("imie_config")
    op.drop_table("imie_scans")
    op.drop_table("imie_state_transitions")
    op.drop_table("imie_signals")
