"""Add granular notification preference columns.

Revision ID: 20260317_150000
Revises: 20260316_180000
Create Date: 2026-03-17

"""

from alembic import op
import sqlalchemy as sa

revision = "20260317_150000"
down_revision = "20260316_180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_product_updates", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column("notify_audit_alerts", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users", sa.Column("notify_billing", sa.Boolean(), nullable=False, server_default="true")
    )


def downgrade() -> None:
    op.drop_column("users", "notify_billing")
    op.drop_column("users", "notify_audit_alerts")
    op.drop_column("users", "notify_product_updates")
