"""Add admin settings payload to operational settings.

Revision ID: 20250217_120000
Revises: 20250216_120000
Create Date: 2025-02-17 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250217_120000"
down_revision = "20250216_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operational_settings",
        sa.Column("admin_settings_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operational_settings", "admin_settings_payload")
