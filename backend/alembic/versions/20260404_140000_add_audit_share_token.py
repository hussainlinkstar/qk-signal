"""Add share_token column to audits table.

Revision ID: 20260404_140000
Revises: 20260404_130000
Create Date: 2026-04-04 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260404_140000"
down_revision = "20260404_130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audits",
        sa.Column("share_token", sa.String(), nullable=True),
    )
    op.create_index("ix_audits_share_token", "audits", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_audits_share_token", table_name="audits")
    op.drop_column("audits", "share_token")
