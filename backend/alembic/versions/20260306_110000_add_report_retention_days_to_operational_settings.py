"""Add report retention days to operational settings

Revision ID: 20260306_110000
Revises: 20260306_090000
Create Date: 2026-03-06 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_110000"
down_revision = "20260306_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operational_settings",
        sa.Column(
            "report_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("operational_settings", "report_retention_days")
