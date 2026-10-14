"""Add trial fields to users table.

Revision ID: 20260308_100000
Revises: 20260307_220000
Create Date: 2026-03-08 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_100000"
down_revision = "20260307_220000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("trial_plan", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "trial_audits_used",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "trial_max_audits",
                sa.Integer(),
                nullable=False,
                server_default="5",
            )
        )
        batch_op.add_column(
            sa.Column(
                "trial_initial_credits",
                sa.Integer(),
                nullable=False,
                server_default="100",
            )
        )
        batch_op.add_column(
            sa.Column(
                "trial_concierge_completed",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("trial_concierge_completed")
        batch_op.drop_column("trial_initial_credits")
        batch_op.drop_column("trial_max_audits")
        batch_op.drop_column("trial_audits_used")
        batch_op.drop_column("trial_plan")
        batch_op.drop_column("trial_ends_at")
        batch_op.drop_column("trial_started_at")
