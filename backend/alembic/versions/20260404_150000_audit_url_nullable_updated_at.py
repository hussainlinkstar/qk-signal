"""Make Audit.url nullable and add updated_at column.

Revision ID: 20260404_150000
Revises: 20260404_140000
Create Date: 2026-04-04 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260404_150000"
down_revision = "20260404_140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audits",
        "url",
        existing_type=sa.String(),
        nullable=True,
    )
    op.add_column(
        "audits",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audits", "updated_at")
    op.execute("UPDATE audits SET url = '' WHERE url IS NULL")
    op.alter_column(
        "audits",
        "url",
        existing_type=sa.String(),
        nullable=False,
    )
