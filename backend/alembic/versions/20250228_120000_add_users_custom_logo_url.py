"""Add custom logo URL column for user white-label reports.

Revision ID: 20250228_120000
Revises: 20250227_120000
Create Date: 2025-02-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250228_120000"
down_revision = "20250227_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("custom_logo_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "custom_logo_url")
