"""add slack teams integrations and workflows

Revision ID: 20260303_030000
Revises: 20260303_020000
Create Date: 2026-03-03 03:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_030000"
down_revision = "20260303_020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "slack_connections" not in table_names:
        op.create_table(
            "slack_connections",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("incoming_webhook_url", sa.Text(), nullable=True),
            sa.Column("team_id", sa.String(), nullable=False),
            sa.Column("team_name", sa.String(), nullable=True),
            sa.Column("bot_user_id", sa.String(), nullable=True),
            sa.Column("default_channel_id", sa.String(), nullable=True),
            sa.Column("default_channel_name", sa.String(), nullable=True),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
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
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("workspace_id", name="uq_slack_connections_workspace"),
        )
        op.create_index("ix_slack_connections_id", "slack_connections", ["id"], unique=False)
        op.create_index(
            "ix_slack_connections_workspace_id", "slack_connections", ["workspace_id"], unique=False
        )

    if "teams_connections" not in table_names:
        op.create_table(
            "teams_connections",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("webhook_url", sa.Text(), nullable=False),
            sa.Column("channel_name", sa.String(), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
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
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("workspace_id", name="uq_teams_connections_workspace"),
        )
        op.create_index("ix_teams_connections_id", "teams_connections", ["id"], unique=False)
        op.create_index(
            "ix_teams_connections_workspace_id", "teams_connections", ["workspace_id"], unique=False
        )

    if "workflows" not in table_names:
        op.create_table(
            "workflows",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("trigger_config", sa.JSON(), nullable=False),
            sa.Column("actions_config", sa.JSON(), nullable=False),
            sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="1440"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
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
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_workflows_id", "workflows", ["id"], unique=False)
        op.create_index(
            "ix_workflows_workspace_project_active",
            "workflows",
            ["workspace_id", "project_id", "is_active"],
            unique=False,
        )

    if "workflow_runs" not in table_names:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column(
                "triggered_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("trigger_event", sa.String(), nullable=False),
            sa.Column("trigger_context", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("action_results", sa.JSON(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_workflow_runs_id", "workflow_runs", ["id"], unique=False)
        op.create_index(
            "ix_workflow_runs_workflow_triggered_at",
            "workflow_runs",
            ["workflow_id", "triggered_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "workflow_runs" in table_names:
        op.drop_index("ix_workflow_runs_workflow_triggered_at", table_name="workflow_runs")
        op.drop_index("ix_workflow_runs_id", table_name="workflow_runs")
        op.drop_table("workflow_runs")

    if "workflows" in table_names:
        op.drop_index("ix_workflows_workspace_project_active", table_name="workflows")
        op.drop_index("ix_workflows_id", table_name="workflows")
        op.drop_table("workflows")

    if "teams_connections" in table_names:
        op.drop_index("ix_teams_connections_workspace_id", table_name="teams_connections")
        op.drop_index("ix_teams_connections_id", table_name="teams_connections")
        op.drop_table("teams_connections")

    if "slack_connections" in table_names:
        op.drop_index("ix_slack_connections_workspace_id", table_name="slack_connections")
        op.drop_index("ix_slack_connections_id", table_name="slack_connections")
        op.drop_table("slack_connections")
