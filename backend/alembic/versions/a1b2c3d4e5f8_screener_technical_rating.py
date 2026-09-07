"""screener rating: technical rating columns

Revision ID: a1b2c3d4e5f8
Revises: f9a3b2c1d4e7
Create Date: 2026-09-07 11:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f8"
down_revision: str | None = "f9a3b2c1d4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("screener_ratings", sa.Column("ta_verdict", sa.String(length=12), nullable=True))
    op.add_column("screener_ratings", sa.Column("ta_score", sa.Float(), nullable=True))
    op.add_column(
        "screener_ratings",
        sa.Column(
            "ta_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_screener_ratings_ta_verdict", "screener_ratings", ["ta_verdict"])


def downgrade() -> None:
    op.drop_index("ix_screener_ratings_ta_verdict", table_name="screener_ratings")
    op.drop_column("screener_ratings", "ta_detail")
    op.drop_column("screener_ratings", "ta_score")
    op.drop_column("screener_ratings", "ta_verdict")
