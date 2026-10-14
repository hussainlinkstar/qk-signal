"""add user avatar_url column

Revision ID: 20260321_070000
Revises: 20260321_060000
Create Date: 2026-03-21 07:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260321_070000"
down_revision = "20260321_060000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
