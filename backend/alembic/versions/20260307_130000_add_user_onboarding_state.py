"""Add onboarding_state JSON column to users.

Revision ID: 20260307_130000
Revises: 20260307_110000
Create Date: 2026-03-07 13:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_130000"
down_revision = "20260307_110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("onboarding_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("onboarding_state")
