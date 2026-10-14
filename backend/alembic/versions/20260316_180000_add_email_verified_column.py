"""Add email_verified column to users table.

Revision ID: 20260316_180000
Revises: 20260316_170000
Create Date: 2026-03-16 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_180000"
down_revision = "20260316_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Existing users have been active without verification enforcement;
    # mark them as verified so they are not disrupted.
    op.execute("UPDATE users SET email_verified = true")


def downgrade() -> None:
    op.drop_column("users", "email_verified")
