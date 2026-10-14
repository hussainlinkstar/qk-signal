"""Add project-level OAuth connections and magic-link audit trail.

Revision ID: 20250312_120000
Revises: 20250311_120000
Create Date: 2026-02-24 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250312_120000"
down_revision = "20250311_120000"
branch_labels = None
depends_on = None


OAUTH_PROVIDER_ENUM = sa.Enum(
    "google",
    "bing",
    name="oauth_provider",
    native_enum=False,
)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_oauth_connections" not in table_names:
        op.create_table(
            "project_oauth_connections",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("magic_link_id", sa.Integer(), nullable=True),
            sa.Column("provider", OAUTH_PROVIDER_ENUM, nullable=False),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("refresh_token", sa.Text(), nullable=True),
            sa.Column("token_type", sa.String(), nullable=True),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("connected_by_email", sa.String(), nullable=True),
            sa.Column("external_subject", sa.String(), nullable=True),
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
            sa.ForeignKeyConstraint(["magic_link_id"], ["magic_links.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "project_id",
                "provider",
                name="uq_project_oauth_connections_project_provider",
            ),
        )
        op.create_index(
            "ix_project_oauth_connections_id", "project_oauth_connections", ["id"], unique=False
        )
        op.create_index(
            "ix_project_oauth_connections_project_id",
            "project_oauth_connections",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_oauth_connections_magic_link_id",
            "project_oauth_connections",
            ["magic_link_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_oauth_connections_provider",
            "project_oauth_connections",
            ["provider"],
            unique=False,
        )
        op.create_index(
            "ix_project_oauth_connections_project_provider",
            "project_oauth_connections",
            ["project_id", "provider"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "project_connection_audit_logs" not in table_names:
        op.create_table(
            "project_connection_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("magic_link_id", sa.Integer(), nullable=True),
            sa.Column("provider", OAUTH_PROVIDER_ENUM, nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["magic_link_id"], ["magic_links.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_project_connection_audit_logs_id",
            "project_connection_audit_logs",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_project_connection_audit_logs_project_id",
            "project_connection_audit_logs",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_connection_audit_logs_magic_link_id",
            "project_connection_audit_logs",
            ["magic_link_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_connection_audit_logs_event_type",
            "project_connection_audit_logs",
            ["event_type"],
            unique=False,
        )
        op.create_index(
            "ix_project_connection_audit_logs_project_created",
            "project_connection_audit_logs",
            ["project_id", "created_at"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if "project_data_sources" in set(inspector.get_table_names()) and not _has_column(
        inspector, "project_data_sources", "project_oauth_connection_id"
    ):
        op.add_column(
            "project_data_sources",
            sa.Column("project_oauth_connection_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_project_data_sources_project_oauth_connection_id",
            "project_data_sources",
            ["project_oauth_connection_id"],
            unique=False,
        )
        op.create_foreign_key(
            "fk_project_data_sources_project_oauth_connection_id",
            "project_data_sources",
            "project_oauth_connections",
            ["project_oauth_connection_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "project_data_sources" in set(inspector.get_table_names()) and _has_column(
        inspector, "project_data_sources", "project_oauth_connection_id"
    ):
        op.drop_constraint(
            "fk_project_data_sources_project_oauth_connection_id",
            "project_data_sources",
            type_="foreignkey",
        )
        op.drop_index(
            "ix_project_data_sources_project_oauth_connection_id",
            table_name="project_data_sources",
            if_exists=True,
        )
        op.drop_column("project_data_sources", "project_oauth_connection_id")

    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "project_connection_audit_logs" in table_names:
        op.drop_index(
            "ix_project_connection_audit_logs_project_created",
            table_name="project_connection_audit_logs",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_connection_audit_logs_event_type",
            table_name="project_connection_audit_logs",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_connection_audit_logs_magic_link_id",
            table_name="project_connection_audit_logs",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_connection_audit_logs_project_id",
            table_name="project_connection_audit_logs",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_connection_audit_logs_id",
            table_name="project_connection_audit_logs",
            if_exists=True,
        )
        op.drop_table("project_connection_audit_logs")

    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "project_oauth_connections" in table_names:
        op.drop_index(
            "ix_project_oauth_connections_project_provider",
            table_name="project_oauth_connections",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_oauth_connections_provider",
            table_name="project_oauth_connections",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_oauth_connections_magic_link_id",
            table_name="project_oauth_connections",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_oauth_connections_project_id",
            table_name="project_oauth_connections",
            if_exists=True,
        )
        op.drop_index(
            "ix_project_oauth_connections_id",
            table_name="project_oauth_connections",
            if_exists=True,
        )
        op.drop_table("project_oauth_connections")
