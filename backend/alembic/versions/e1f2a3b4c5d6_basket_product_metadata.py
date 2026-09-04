"""basket product metadata

Revision ID: e1f2a3b4c5d6
Revises: d8b3f1a05c67
Create Date: 2026-09-04 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d8b3f1a05c67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("baskets", sa.Column("risk_level", sa.SmallInteger(), nullable=True))
    op.add_column("baskets", sa.Column("objective", sa.String(length=400), nullable=True))
    op.add_column("baskets", sa.Column("horizon", sa.String(length=40), nullable=True))
    op.add_column("baskets", sa.Column("investment_style", sa.String(length=60), nullable=True))
    op.add_column("baskets", sa.Column("how_it_works", postgresql.JSONB(), nullable=True))
    op.add_column(
        "baskets",
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("baskets", "internal")
    op.drop_column("baskets", "how_it_works")
    op.drop_column("baskets", "investment_style")
    op.drop_column("baskets", "horizon")
    op.drop_column("baskets", "objective")
    op.drop_column("baskets", "risk_level")
