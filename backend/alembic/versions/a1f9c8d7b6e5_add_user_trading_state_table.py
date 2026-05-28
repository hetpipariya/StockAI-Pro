"""add_user_trading_state_table

Revision ID: a1f9c8d7b6e5
Revises: f4a2b7d1e9c3
Create Date: 2026-04-16 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f9c8d7b6e5"
down_revision: Union[str, Sequence[str], None] = "f4a2b7d1e9c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(ix.get("name") == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("user_trading_state"):
        op.create_table(
            "user_trading_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("balance", sa.Float(), nullable=False),
            sa.Column("positions", sa.JSON(), nullable=False),
            sa.Column("orders", sa.JSON(), nullable=False),
            sa.Column(
                "last_updated",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_user_trading_state_user_id"),
        )

    if not _index_exists("user_trading_state", "ix_user_trading_state_user_id"):
        op.create_index(
            "ix_user_trading_state_user_id",
            "user_trading_state",
            ["user_id"],
            unique=True,
        )

    if not _index_exists(
        "user_trading_state",
        "ix_user_trading_state_last_updated",
    ):
        op.create_index(
            "ix_user_trading_state_last_updated",
            "user_trading_state",
            ["last_updated"],
            unique=False,
        )


def downgrade() -> None:
    if _table_exists("user_trading_state"):
        if _index_exists("user_trading_state", "ix_user_trading_state_last_updated"):
            op.drop_index("ix_user_trading_state_last_updated", table_name="user_trading_state")
        if _index_exists("user_trading_state", "ix_user_trading_state_user_id"):
            op.drop_index("ix_user_trading_state_user_id", table_name="user_trading_state")
        op.drop_table("user_trading_state")
