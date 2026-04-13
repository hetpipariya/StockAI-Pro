"""add_instruments_table

Revision ID: f4a2b7d1e9c3
Revises: e6b9f2c4a1d0
Create Date: 2026-04-13 19:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a2b7d1e9c3"
down_revision: Union[str, Sequence[str], None] = "e6b9f2c4a1d0"
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
    if not _table_exists("instruments"):
        op.create_table(
            "instruments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("token", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=12), nullable=False),
            sa.Column("tradingsymbol", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("instrument_type", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("expiry", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("strike", sa.Float(), nullable=True),
            sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("tick_size", sa.Float(), nullable=True),
            sa.Column("isin", sa.String(length=40), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "exchange", "symbol", name="uq_instruments_exchange_symbol"
            ),
            sa.UniqueConstraint(
                "exchange", "token", name="uq_instruments_exchange_token"
            ),
        )

    if not _index_exists("instruments", "ix_instruments_exchange_symbol"):
        op.create_index(
            "ix_instruments_exchange_symbol",
            "instruments",
            ["exchange", "symbol"],
            unique=False,
        )

    if not _index_exists("instruments", "ix_instruments_exchange_token"):
        op.create_index(
            "ix_instruments_exchange_token",
            "instruments",
            ["exchange", "token"],
            unique=False,
        )


def downgrade() -> None:
    if _table_exists("instruments"):
        op.drop_index("ix_instruments_exchange_token", table_name="instruments")
        op.drop_index("ix_instruments_exchange_symbol", table_name="instruments")
        op.drop_table("instruments")
