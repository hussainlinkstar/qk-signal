"""add project task management tables

Revision ID: 20260303_000000
Revises: 20260302_230000
Create Date: 2026-03-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_000000"
down_revision = "20260302_230000"
branch_labels = None
depends_on = None


PROJECT_TASK_STATUS_ENUM = sa.Enum(
    "todo",
    "in_progress",
    "done",
    name="project_task_status",
    native_enum=False,
)

PROJECT_TASK_PRIORITY_ENUM = sa.Enum(
    "low",
    "medium",
    "high",
    "critical",
    name="project_task_priority",
    native_enum=False,
)

PROJECT_TASK_ORIGIN_ENUM = sa.Enum(
    "manual",
    "audit_recommendation",
    name="project_task_origin",
    native_enum=False,
)

PROJECT_TASK_RESOLUTION_SOURCE_ENUM = sa.Enum(
    "manual",
    "audit_validated",
    name="project_task_resolution_source",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_tasks" not in table_names:
        op.create_table(
            "project_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_audit_id", sa.Integer(), nullable=True),
            sa.Column("verification_audit_id", sa.Integer(), nullable=True),
            sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                PROJECT_TASK_STATUS_ENUM,
                nullable=False,
                server_default="todo",
            ),
            sa.Column(
                "priority",
                PROJECT_TASK_PRIORITY_ENUM,
                nullable=False,
                server_default="medium",
            ),
            sa.Column(
                "origin",
                PROJECT_TASK_ORIGIN_ENUM,
                nullable=False,
                server_default="manual",
            ),
            sa.Column(
                "resolution_source",
                PROJECT_TASK_RESOLUTION_SOURCE_ENUM,
                nullable=True,
            ),
            sa.Column("category", sa.String(), nullable=False, server_default="General"),
            sa.Column("source_recommendation_key", sa.String(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_audit_id"], ["audits.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["verification_audit_id"], ["audits.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_project_tasks_id", "project_tasks", ["id"], unique=False)
        op.create_index(
            "ix_project_tasks_project_status_sort",
            "project_tasks",
            ["project_id", "status", "sort_order"],
            unique=False,
        )
        op.create_index(
            "ix_project_tasks_project_created",
            "project_tasks",
            ["project_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_project_tasks_source_key",
            "project_tasks",
            ["project_id", "source_recommendation_key"],
            unique=False,
        )
        op.create_index(
            "ix_project_tasks_assigned_to",
            "project_tasks",
            ["assigned_to_user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_tasks" in table_names:
        op.drop_index("ix_project_tasks_assigned_to", table_name="project_tasks")
        op.drop_index("ix_project_tasks_source_key", table_name="project_tasks")
        op.drop_index("ix_project_tasks_project_created", table_name="project_tasks")
        op.drop_index("ix_project_tasks_project_status_sort", table_name="project_tasks")
        op.drop_index("ix_project_tasks_id", table_name="project_tasks")
        op.drop_table("project_tasks")
