"""add users anonymized_at column for GDPR compliance

Revision ID: 20260303_060000
Revises: 20260303_050000
Create Date: 2026-03-03 06:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_060000"
down_revision = "20260303_050000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "anonymized_at")
