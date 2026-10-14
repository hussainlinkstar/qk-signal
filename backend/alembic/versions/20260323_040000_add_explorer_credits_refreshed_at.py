"""add explorer_credits_refreshed_at to users

Revision ID: 20260323_040000
Revises: 20260323_030000
Create Date: 2026-03-23 04:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_040000"
down_revision = "20260323_030000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("explorer_credits_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "explorer_credits_refreshed_at")
