"""add project_templates table and project tags/status columns

Revision ID: 20260323_070000
Revises: 20260323_060000
Create Date: 2026-03-23 07:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_070000"
down_revision = "20260323_060000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create project_templates table
    op.create_table(
        "project_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_target_country", sa.String(), nullable=True),
        sa.Column("default_language", sa.String(), nullable=False, server_default="en"),
        sa.Column("default_icp_roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("default_pain_points", sa.Text(), nullable=True),
        sa.Column("default_usp", sa.Text(), nullable=True),
        sa.Column(
            "default_competitors_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("auto_schedule_audit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_project_templates_workspace_id", "project_templates", ["workspace_id"])

    # 2. Add new columns to projects table
    op.add_column(
        "projects",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "projects",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.add_column(
        "projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("template_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("cloned_from_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_template_id",
        "projects",
        "project_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_projects_cloned_from_id",
        "projects",
        "projects",
        ["cloned_from_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_cloned_from_id", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_template_id", "projects", type_="foreignkey")
    op.drop_column("projects", "cloned_from_id")
    op.drop_column("projects", "template_id")
    op.drop_column("projects", "archived_at")
    op.drop_column("projects", "status")
    op.drop_column("projects", "tags")
    op.drop_table("project_templates")
