"""add client portal rbac tables

Revision ID: 20260302_160000
Revises: 20260301_120000
Create Date: 2026-03-02 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260302_160000"
down_revision = "20260301_120000"
branch_labels = None
depends_on = None


OLD_WORKSPACE_ROLE_ENUM = sa.Enum(
    "ADMIN",
    "EDITOR",
    "VIEWER",
    name="workspace_user_role",
    native_enum=False,
)
NEW_WORKSPACE_ROLE_ENUM = sa.Enum(
    "ADMIN",
    "EDITOR",
    "VIEWER",
    "CLIENT_READONLY",
    name="workspace_user_role",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    with op.batch_alter_table("workspace_users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=OLD_WORKSPACE_ROLE_ENUM,
            type_=NEW_WORKSPACE_ROLE_ENUM,
            existing_nullable=False,
            existing_server_default="ADMIN",
        )

    if "workspace_user_project_access" not in table_names:
        op.create_table(
            "workspace_user_project_access",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_user_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["workspace_user_id"], ["workspace_users.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "workspace_user_id",
                "project_id",
                name="uq_workspace_user_project_access_member_project",
            ),
        )
        op.create_index(
            "ix_workspace_user_project_access_id",
            "workspace_user_project_access",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_workspace_user_project_access_member",
            "workspace_user_project_access",
            ["workspace_user_id"],
            unique=False,
        )
        op.create_index(
            "ix_workspace_user_project_access_project",
            "workspace_user_project_access",
            ["project_id"],
            unique=False,
        )

    if "project_jira_exports" not in table_names:
        op.create_table(
            "project_jira_exports",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("jira_project_key", sa.String(), nullable=True),
            sa.Column("issue_id", sa.String(), nullable=False),
            sa.Column("issue_key", sa.String(), nullable=False),
            sa.Column("issue_url", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("issue_type", sa.String(), nullable=False, server_default="Task"),
            sa.Column("status_name", sa.String(), nullable=False, server_default="Exported"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_project_jira_exports_id", "project_jira_exports", ["id"], unique=False)
        op.create_index(
            "ix_project_jira_exports_project_id",
            "project_jira_exports",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_jira_exports_audit_id",
            "project_jira_exports",
            ["audit_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_jira_exports_created_by_user_id",
            "project_jira_exports",
            ["created_by_user_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_jira_exports_project_created",
            "project_jira_exports",
            ["project_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_project_jira_exports_issue_key",
            "project_jira_exports",
            ["issue_key"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_jira_exports" in table_names:
        op.drop_index("ix_project_jira_exports_issue_key", table_name="project_jira_exports")
        op.drop_index("ix_project_jira_exports_project_created", table_name="project_jira_exports")
        op.drop_index(
            "ix_project_jira_exports_created_by_user_id", table_name="project_jira_exports"
        )
        op.drop_index("ix_project_jira_exports_audit_id", table_name="project_jira_exports")
        op.drop_index("ix_project_jira_exports_project_id", table_name="project_jira_exports")
        op.drop_index("ix_project_jira_exports_id", table_name="project_jira_exports")
        op.drop_table("project_jira_exports")

    if "workspace_user_project_access" in table_names:
        op.drop_index(
            "ix_workspace_user_project_access_project", table_name="workspace_user_project_access"
        )
        op.drop_index(
            "ix_workspace_user_project_access_member", table_name="workspace_user_project_access"
        )
        op.drop_index(
            "ix_workspace_user_project_access_id", table_name="workspace_user_project_access"
        )
        op.drop_table("workspace_user_project_access")

    with op.batch_alter_table("workspace_users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=NEW_WORKSPACE_ROLE_ENUM,
            type_=OLD_WORKSPACE_ROLE_ENUM,
            existing_nullable=False,
            existing_server_default="ADMIN",
        )
