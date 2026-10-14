"""Add CMS fix delivery tables

Revision ID: 20260305_140000
Revises: 20260305_130000
Create Date: 2026-03-05 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_140000"
down_revision = "20260305_130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cms_type", sa.String(), nullable=False),
        sa.Column("site_url", sa.String(), nullable=False),
        sa.Column("credentials_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "cms_type", name="uq_cms_connections_project_type"),
    )
    op.create_index("ix_cms_connections_id", "cms_connections", ["id"], unique=False)
    op.create_index(
        "ix_cms_connections_project_id", "cms_connections", ["project_id"], unique=False
    )
    op.create_index(
        "ix_cms_connections_workspace_id", "cms_connections", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_cms_connections_project_type",
        "cms_connections",
        ["project_id", "cms_type"],
        unique=False,
    )

    op.create_table(
        "cms_deployment_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_task_id",
            sa.Integer(),
            sa.ForeignKey("project_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cms_connection_id",
            sa.Integer(),
            sa.ForeignKey("cms_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "initiated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("page_url", sa.String(), nullable=False),
        sa.Column("field_changed", sa.String(), nullable=False),
        sa.Column("value_before", sa.Text(), nullable=True),
        sa.Column("value_after", sa.Text(), nullable=False),
        sa.Column("cms_revision_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cms_deployment_logs_id", "cms_deployment_logs", ["id"], unique=False)
    op.create_index(
        "ix_cms_deployment_logs_project_task_id",
        "cms_deployment_logs",
        ["project_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_cms_deployment_logs_cms_connection_id",
        "cms_deployment_logs",
        ["cms_connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_cms_deployment_logs_initiated_by", "cms_deployment_logs", ["initiated_by"], unique=False
    )
    op.create_index(
        "ix_cms_deployment_logs_task_created",
        "cms_deployment_logs",
        ["project_task_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_cms_deployment_logs_connection_created",
        "cms_deployment_logs",
        ["cms_connection_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cms_deployment_logs_connection_created", table_name="cms_deployment_logs")
    op.drop_index("ix_cms_deployment_logs_task_created", table_name="cms_deployment_logs")
    op.drop_index("ix_cms_deployment_logs_initiated_by", table_name="cms_deployment_logs")
    op.drop_index("ix_cms_deployment_logs_cms_connection_id", table_name="cms_deployment_logs")
    op.drop_index("ix_cms_deployment_logs_project_task_id", table_name="cms_deployment_logs")
    op.drop_index("ix_cms_deployment_logs_id", table_name="cms_deployment_logs")
    op.drop_table("cms_deployment_logs")

    op.drop_index("ix_cms_connections_project_type", table_name="cms_connections")
    op.drop_index("ix_cms_connections_workspace_id", table_name="cms_connections")
    op.drop_index("ix_cms_connections_project_id", table_name="cms_connections")
    op.drop_index("ix_cms_connections_id", table_name="cms_connections")
    op.drop_table("cms_connections")
