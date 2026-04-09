"""add_query_performance_indexes

Revision ID: e6b9f2c4a1d0
Revises: d3f90f4c2b18
Create Date: 2026-03-29 00:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b9f2c4a1d0"
down_revision: Union[str, Sequence[str], None] = "d3f90f4c2b18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(ix.get("name") == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _index_exists("orders", "ix_orders_user_timestamp"):
        op.create_index(
            "ix_orders_user_timestamp", "orders", ["user_id", "timestamp"], unique=False
        )

    if not _index_exists("predictions", "ix_predictions_symbol_timestamp"):
        op.create_index(
            "ix_predictions_symbol_timestamp",
            "predictions",
            ["symbol", "timestamp"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_predictions_symbol_timestamp", table_name="predictions")
    op.drop_index("ix_orders_user_timestamp", table_name="orders")
