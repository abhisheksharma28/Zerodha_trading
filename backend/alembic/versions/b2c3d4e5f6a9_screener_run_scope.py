"""screener run: swept scope

Revision ID: b2c3d4e5f6a9
Revises: a1b2c3d4e5f8
Create Date: 2026-09-07 12:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a9"
down_revision: str | None = "a1b2c3d4e5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "screener_runs",
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="broad500"),
    )


def downgrade() -> None:
    op.drop_column("screener_runs", "scope")
