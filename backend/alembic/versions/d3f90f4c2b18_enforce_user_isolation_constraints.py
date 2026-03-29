"""enforce_user_isolation_constraints

Revision ID: d3f90f4c2b18
Revises: b770c489ddcd
Create Date: 2026-03-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3f90f4c2b18"
down_revision: Union[str, Sequence[str], None] = "b770c489ddcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(ix.get("name") == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    null_user_rows_exist = False
    for table in ("orders", "positions", "trade_logs"):
        if table in existing_tables:
            has_null = bind.execute(
                sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE user_id IS NULL)")
            ).scalar()
            if has_null:
                null_user_rows_exist = True
                break

    if null_user_rows_exist:
        # Enforcing NOT NULL requires cleanup for legacy rows.
        first_user_id = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
        if first_user_id is None:
            raise RuntimeError(
                "Cannot enforce user_id NOT NULL because users table is empty. "
                "Create at least one user before running this migration."
            )

        for table in ("orders", "positions", "trade_logs"):
            if table in existing_tables:
                bind.execute(
                    sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": int(first_user_id)},
                )

    if "orders" in existing_tables:
        bind.execute(sa.text("UPDATE orders SET price = 0 WHERE price IS NULL"))

    op.alter_column("orders", "user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("positions", "user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("trade_logs", "user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("orders", "price", existing_type=sa.Float(), nullable=False)

    op.alter_column(
        "orders",
        "status",
        existing_type=sa.String(length=25),
        type_=sa.String(length=20),
        existing_nullable=True,
        server_default=sa.text("'PENDING'"),
    )
    op.alter_column(
        "orders",
        "mode",
        existing_type=sa.String(length=10),
        existing_nullable=True,
        server_default=sa.text("'paper'"),
    )
    op.alter_column(
        "positions",
        "mode",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default=sa.text("'paper'"),
    )

    if not _index_exists("orders", "ix_orders_user_symbol"):
        op.create_index("ix_orders_user_symbol", "orders", ["user_id", "symbol"], unique=False)
    if not _index_exists("orders", "ix_orders_user_status"):
        op.create_index("ix_orders_user_status", "orders", ["user_id", "status"], unique=False)
    if not _index_exists("positions", "ix_positions_user_id"):
        op.create_index("ix_positions_user_id", "positions", ["user_id"], unique=False)
    if not _index_exists("trade_logs", "ix_trade_logs_user_id"):
        op.create_index("ix_trade_logs_user_id", "trade_logs", ["user_id"], unique=False)
    if not _index_exists("trade_logs", "ix_trade_logs_user_symbol"):
        op.create_index("ix_trade_logs_user_symbol", "trade_logs", ["user_id", "symbol"], unique=False)
    if not _index_exists("trade_logs", "ix_trade_logs_user_timestamp"):
        op.create_index("ix_trade_logs_user_timestamp", "trade_logs", ["user_id", "timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("orders", "price", existing_type=sa.Float(), nullable=True)
    op.alter_column("trade_logs", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("positions", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("orders", "user_id", existing_type=sa.Integer(), nullable=True)

    op.alter_column(
        "orders",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=25),
        existing_nullable=True,
        server_default=None,
    )
    op.alter_column(
        "orders",
        "mode",
        existing_type=sa.String(length=10),
        existing_nullable=True,
        server_default=None,
    )
    op.alter_column(
        "positions",
        "mode",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default=None,
    )
