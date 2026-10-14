"""add workspaces.role_mode (nullable)

Revision ID: 20260421_090000
Revises: 20260420_120000
Create Date: 2026-04-21 09:00:00

Adds a nullable ``role_mode`` column to the ``workspaces`` table to capture the
persona role mode (marketer | specialist | agency | enterprise | explorer)
selected at onboarding. Nullable with no backfill required.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_090000"
down_revision = "20260420_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("role_mode", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "role_mode")
