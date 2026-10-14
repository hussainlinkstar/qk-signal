"""Add addon_results column to audits table

Revision ID: 20260318_010000
Revises: 20260317_150000
Create Date: 2026-03-18 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260318_010000"
down_revision = "20260317_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audits",
        sa.Column("addon_results", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audits", "addon_results")
