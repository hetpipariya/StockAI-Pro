"""add_missing_user_auth_columns

Revision ID: c8b1f6e2a9ab
Revises: a1f9c8d7b6e5
Create Date: 2026-04-29 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8b1f6e2a9ab"
down_revision: Union[str, Sequence[str], None] = "a1f9c8d7b6e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(
        column.get("name") == column_name
        for column in inspector.get_columns(table_name)
    )


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(
        index.get("name") == index_name for index in inspector.get_indexes(table_name)
    )


def _backfill_username(bind) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = lower(
                    regexp_replace(split_part(email, '@', 1), '[^a-zA-Z0-9_]+', '_', 'g')
                )
                WHERE username IS NULL;
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = CONCAT(username, '_', id)
                WHERE username IN (
                    SELECT username
                    FROM users
                    GROUP BY username
                    HAVING COUNT(*) > 1
                );
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = CONCAT('user_', id)
                WHERE username IS NULL OR username = '';
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = lower(replace(substr(email, 1, instr(email, '@') - 1), '-', '_'))
                WHERE username IS NULL;
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = username || '_' || id
                WHERE username IN (
                    SELECT username
                    FROM users
                    GROUP BY username
                    HAVING COUNT(*) > 1
                );
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = 'user_' || id
                WHERE username IS NULL OR username = '';
                """
            )
        )


def upgrade() -> None:
    bind = op.get_bind()

    if not _column_exists(bind, "users", "username"):
        op.add_column("users", sa.Column("username", sa.String(length=50), nullable=True))
        _backfill_username(bind)
        op.alter_column("users", "username", nullable=False)

    if not _index_exists(bind, "users", "ix_users_username"):
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    if not _column_exists(bind, "users", "is_active"):
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )

    if not _column_exists(bind, "users", "is_verified"):
        op.add_column(
            "users",
            sa.Column(
                "is_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _column_exists(bind, "users", "starting_capital"):
        op.add_column(
            "users",
            sa.Column(
                "starting_capital",
                sa.Float(),
                nullable=False,
                server_default=sa.text("100000"),
            ),
        )

    if not _column_exists(bind, "users", "trading_mode"):
        op.add_column(
            "users",
            sa.Column(
                "trading_mode",
                sa.String(length=10),
                nullable=False,
                server_default=sa.text("'PAPER'"),
            ),
        )

    if not _column_exists(bind, "users", "refresh_token_hash"):
        op.add_column(
            "users",
            sa.Column("refresh_token_hash", sa.String(length=255), nullable=True),
        )

    if not _column_exists(bind, "users", "created_at"):
        op.add_column(
            "users",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )

    if not _column_exists(bind, "users", "last_login"):
        op.add_column("users", sa.Column("last_login", sa.DateTime(), nullable=True))

    if not _column_exists(bind, "users", "updated_at"):
        op.add_column(
            "users",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _column_exists(bind, "users", "updated_at"):
        op.drop_column("users", "updated_at")
    if _column_exists(bind, "users", "last_login"):
        op.drop_column("users", "last_login")
    if _column_exists(bind, "users", "created_at"):
        op.drop_column("users", "created_at")
    if _column_exists(bind, "users", "refresh_token_hash"):
        op.drop_column("users", "refresh_token_hash")
    if _column_exists(bind, "users", "trading_mode"):
        op.drop_column("users", "trading_mode")
    if _column_exists(bind, "users", "starting_capital"):
        op.drop_column("users", "starting_capital")
    if _column_exists(bind, "users", "is_verified"):
        op.drop_column("users", "is_verified")
    if _column_exists(bind, "users", "is_active"):
        op.drop_column("users", "is_active")
    if _index_exists(bind, "users", "ix_users_username"):
        op.drop_index("ix_users_username", table_name="users")
    if _column_exists(bind, "users", "username"):
        op.drop_column("users", "username")
