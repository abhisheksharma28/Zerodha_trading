"""basket rebalance event — factor attribution store

Revision ID: b4c9d2e5f6a8
Revises: a3b8c1d2e4f5
Create Date: 2026-09-04 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4c9d2e5f6a8"
down_revision: str | None = "a3b8c1d2e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "basket_rebalance_events",
        sa.Column("attribution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("basket_rebalance_events", "attribution")
