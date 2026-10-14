"""Add workspace intelligence models (invitations, activity log, credit tracking).

Revision ID: 20260323_080000
Revises: 20260323_070000
Create Date: 2026-03-23 08:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260323_080000"
down_revision = "20260323_070000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- workspace_invitations ---
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_email", sa.String(), nullable=False),
        sa.Column("invited_name", sa.String(), nullable=True),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(), nullable=False, server_default="viewer"),
        sa.Column("project_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"]
    )
    op.create_index(
        "ix_workspace_invitations_token", "workspace_invitations", ["token"], unique=True
    )

    # --- workspace_activity_log ---
    op.create_table(
        "workspace_activity_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_workspace_activity_log_workspace_id_created_at",
        "workspace_activity_log",
        ["workspace_id", "created_at"],
    )

    # --- Workspace credit tracking columns ---
    op.add_column("workspaces", sa.Column("credit_budget", sa.Integer(), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("credit_usage_current_cycle", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "workspaces", sa.Column("credit_cycle_start", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workspaces", "credit_cycle_start")
    op.drop_column("workspaces", "credit_usage_current_cycle")
    op.drop_column("workspaces", "credit_budget")

    op.drop_index("ix_workspace_activity_log_workspace_id_created_at", "workspace_activity_log")
    op.drop_table("workspace_activity_log")

    op.drop_index("ix_workspace_invitations_token", "workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_id", "workspace_invitations")
    op.drop_table("workspace_invitations")
