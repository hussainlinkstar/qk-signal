"""Add project-level data source assignment table.

Revision ID: 20250311_120000
Revises: add_workspace_project_hierarchy
Create Date: 2026-02-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250311_120000"
down_revision = "add_workspace_project_hierarchy"
branch_labels = None
depends_on = None


PROJECT_DATA_SOURCE_TYPE_ENUM = sa.Enum(
    "google_search_console",
    "google_analytics_4",
    "bing_webmaster",
    name="project_data_source_type",
    native_enum=False,
)
PROJECT_DATA_SOURCE_BINDING_MODE_ENUM = sa.Enum(
    "workspace",
    "client_magic_link",
    "ai_estimate",
    name="project_data_source_binding_mode",
    native_enum=False,
)
OAUTH_PROVIDER_ENUM = sa.Enum(
    "google",
    "bing",
    name="oauth_provider",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_data_sources" not in table_names:
        op.create_table(
            "project_data_sources",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("oauth_connection_id", sa.Integer(), nullable=True),
            sa.Column("provider", OAUTH_PROVIDER_ENUM, nullable=False),
            sa.Column("source_type", PROJECT_DATA_SOURCE_TYPE_ENUM, nullable=False),
            sa.Column(
                "binding_mode",
                PROJECT_DATA_SOURCE_BINDING_MODE_ENUM,
                nullable=False,
                server_default="workspace",
            ),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("source_label", sa.String(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
                onupdate=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["oauth_connection_id"], ["oauth_connections.id"], ondelete="SET NULL"
            ),
            sa.UniqueConstraint(
                "project_id", "source_type", name="uq_project_data_sources_project_type"
            ),
        )
        op.create_index("ix_project_data_sources_id", "project_data_sources", ["id"], unique=False)
        op.create_index(
            "ix_project_data_sources_project_id",
            "project_data_sources",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_data_sources_oauth_connection_id",
            "project_data_sources",
            ["oauth_connection_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_data_sources_source_type",
            "project_data_sources",
            ["source_type"],
            unique=False,
        )
        op.create_index(
            "ix_project_data_sources_project_provider",
            "project_data_sources",
            ["project_id", "provider"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_data_sources" in table_names:
        op.drop_index(
            "ix_project_data_sources_project_provider",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_data_sources_source_type",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_data_sources_oauth_connection_id",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_data_sources_project_id",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_data_sources_id",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_table("project_data_sources")
