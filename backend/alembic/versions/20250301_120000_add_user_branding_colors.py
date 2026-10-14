"""Add persistent user branding fields for report generation.

Revision ID: 20250301_120000
Revises: 20250228_120000
Create Date: 2025-03-01 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250301_120000"
down_revision = "20250228_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("company_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("primary_color", sa.String(), nullable=True))
    op.add_column("users", sa.Column("secondary_color", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "secondary_color")
    op.drop_column("users", "primary_color")
    op.drop_column("users", "company_name")
