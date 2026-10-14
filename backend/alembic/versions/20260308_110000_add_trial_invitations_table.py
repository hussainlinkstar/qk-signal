"""Add trial_invitations table for admin-managed trial invites.

Revision ID: 20260308_110000
Revises: 20260308_100000
Create Date: 2026-03-08 11:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_110000"
down_revision = "20260308_100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trial_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(), nullable=False, index=True),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("token", sa.String(), nullable=False, unique=True, index=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "redeemed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # email, token, and redeemed_by_user_id indexes are already created
    # by index=True in the column definitions above.
    op.create_index("ix_trial_invitations_status", "trial_invitations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_trial_invitations_status", table_name="trial_invitations")
    op.drop_index("ix_trial_invitations_email", table_name="trial_invitations")
    op.drop_table("trial_invitations")
