"""basket category

Revision ID: c7a1e2f4b8d3
Revises: b45e70c1a9d2
Create Date: 2026-09-04 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7a1e2f4b8d3'
down_revision: Union[str, None] = 'b45e70c1a9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('baskets', sa.Column('category', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('baskets', 'category')
