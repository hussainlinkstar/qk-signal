"""Add template_key column to email_outbox.

Revision ID: 20260308_170000
Revises: 20260308_110000
Create Date: 2026-03-08 17:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_170000"
down_revision = "20260308_110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_outbox",
        sa.Column("template_key", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_email_outbox_template_key",
        "email_outbox",
        ["template_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_outbox_template_key", table_name="email_outbox")
    op.drop_column("email_outbox", "template_key")
