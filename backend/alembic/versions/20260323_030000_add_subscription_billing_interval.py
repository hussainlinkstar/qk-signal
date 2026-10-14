"""add billing_interval to subscriptions

Revision ID: 20260323_030000
Revises: 20260323_020000
Create Date: 2026-03-23

"""

from alembic import op
import sqlalchemy as sa

revision = "20260323_030000"
down_revision = "20260323_020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("billing_interval", sa.String(), nullable=False, server_default="month"),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "billing_interval")
