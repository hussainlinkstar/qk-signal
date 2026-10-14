"""Add trial feedback requests table and schema version to invitations.

Revision ID: 20260308_190000
Revises: 20260308_170000
Create Date: 2026-03-08 19:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_190000"
down_revision = "20260308_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trial_invitations",
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )

    op.create_table(
        "trial_feedback_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("trial_invitation_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "trigger_reason",
            sa.String(),
            nullable=False,
            server_default="trial_expired",
        ),
        sa.Column("trial_started_at_snapshot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ended_at_snapshot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overall_rating", sa.Integer(), nullable=True),
        sa.Column("would_recommend", sa.String(), nullable=True),
        sa.Column("what_worked_well", sa.Text(), nullable=True),
        sa.Column("what_was_missing", sa.Text(), nullable=True),
        sa.Column("improvement_suggestions", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["trial_invitation_id"], ["trial_invitations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token", name="uq_trial_feedback_requests_token"),
        sa.UniqueConstraint(
            "user_id",
            "trial_started_at_snapshot",
            name="uq_trial_feedback_requests_user_trial_start",
        ),
    )
    op.create_index(
        "ix_trial_feedback_requests_id",
        "trial_feedback_requests",
        ["id"],
    )
    op.create_index(
        "ix_trial_feedback_requests_user_id",
        "trial_feedback_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_trial_feedback_requests_trial_invitation_id",
        "trial_feedback_requests",
        ["trial_invitation_id"],
    )
    op.create_index(
        "ix_trial_feedback_requests_requested_by_user_id",
        "trial_feedback_requests",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_trial_feedback_requests_token",
        "trial_feedback_requests",
        ["token"],
    )
    op.create_index(
        "ix_trial_feedback_requests_status",
        "trial_feedback_requests",
        ["status"],
    )
    op.create_index(
        "ix_trial_feedback_requests_requested_at",
        "trial_feedback_requests",
        ["requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trial_feedback_requests_requested_at",
        table_name="trial_feedback_requests",
    )
    op.drop_index(
        "ix_trial_feedback_requests_status",
        table_name="trial_feedback_requests",
    )
    op.drop_index(
        "ix_trial_feedback_requests_token",
        table_name="trial_feedback_requests",
    )
    op.drop_index(
        "ix_trial_feedback_requests_requested_by_user_id",
        table_name="trial_feedback_requests",
    )
    op.drop_index(
        "ix_trial_feedback_requests_trial_invitation_id",
        table_name="trial_feedback_requests",
    )
    op.drop_index(
        "ix_trial_feedback_requests_user_id",
        table_name="trial_feedback_requests",
    )
    op.drop_index("ix_trial_feedback_requests_id", table_name="trial_feedback_requests")
    op.drop_table("trial_feedback_requests")

    op.drop_column("trial_invitations", "schema_version")
