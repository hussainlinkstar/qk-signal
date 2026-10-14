"""Add EmailOutbox sender override columns

Revision ID: 20260304_110000
Revises: 20260304_100000
Create Date: 2026-03-04 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260304_110000"
down_revision = "20260304_100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_outbox",
        sa.Column("from_name", sa.String(), nullable=True),
    )
    op.add_column(
        "email_outbox",
        sa.Column("reply_to", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_outbox", "reply_to")
    op.drop_column("email_outbox", "from_name")
