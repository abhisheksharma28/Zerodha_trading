"""paper strategy run: universe label

Revision ID: d7e1f2a3b4c5
Revises: c5d0e9a71f42
Create Date: 2026-09-07 09:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e1f2a3b4c5"
down_revision: str | None = "c5d0e9a71f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_strategy_runs",
        sa.Column("universe", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_strategy_runs", "universe")
