"""add user unsubscribe_token column

Revision ID: 20260303_010000
Revises: 20260303_000000
Create Date: 2026-03-03 01:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_010000"
down_revision = "20260303_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("unsubscribe_token", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_users_unsubscribe_token",
        "users",
        ["unsubscribe_token"],
        unique=True,
    )

    # Backfill existing rows with a unique token per user.
    # Use gen_random_uuid() (PG 13+) and fall back to uuid_generate_v4().
    op.execute(
        "UPDATE users SET unsubscribe_token = gen_random_uuid()::text "
        "WHERE unsubscribe_token IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_users_unsubscribe_token", table_name="users")
    op.drop_column("users", "unsubscribe_token")
