"""orders.options_instance_id + widen the has-parent check constraint

Revision ID: 32586352cbfa
Revises: d21ed65d2c09
Create Date: 2026-09-01 23:16:06.162942
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "32586352cbfa"
down_revision: str | None = "d21ed65d2c09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_orders_has_deployment_or_backtest"


def upgrade() -> None:
    op.add_column("orders", sa.Column("options_instance_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_orders_options_instance_id", "orders", "options_strategy_instances",
        ["options_instance_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint(_CK, "orders", type_="check")
    op.create_check_constraint(
        _CK, "orders",
        "(deployment_id IS NOT NULL) OR (backtest_id IS NOT NULL) "
        "OR (options_instance_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(_CK, "orders", type_="check")
    op.create_check_constraint(
        _CK, "orders",
        "(deployment_id IS NOT NULL) OR (backtest_id IS NOT NULL)",
    )
    op.drop_constraint("fk_orders_options_instance_id", "orders", type_="foreignkey")
    op.drop_column("orders", "options_instance_id")
