"""Add marketplace addon tables

Revision ID: 20260306_090000
Revises: 20260305_190000, 7b61608e95c4
Create Date: 2026-03-06 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_090000"
down_revision = ("20260305_190000", "7b61608e95c4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "addons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="general"),
        sa.Column("version", sa.String(), nullable=False, server_default="1.0.0"),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pricing_type",
            sa.Enum("free", "per_use", "monthly", name="addon_pricing_type", native_enum=False),
            nullable=False,
            server_default="free",
        ),
        sa.Column("credit_cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_fee_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "execution_mode",
            sa.Enum("webhook", name="addon_execution_mode", native_enum=False),
            nullable=False,
            server_default="webhook",
        ),
        sa.Column("webhook_url", sa.String(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("manifest_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_first_party", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("install_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating_average", sa.Float(), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint("slug", name="uq_addons_slug"),
    )
    op.create_index("ix_addons_id", "addons", ["id"], unique=False)
    op.create_index("ix_addons_slug", "addons", ["slug"], unique=True)
    op.create_index("ix_addons_author_id", "addons", ["author_id"], unique=False)
    op.create_index(
        "ix_addons_published_category",
        "addons",
        ["is_published", "category"],
        unique=False,
    )
    op.create_index(
        "ix_addons_first_party_verified",
        "addons",
        ["is_first_party", "is_verified"],
        unique=False,
    )

    op.create_table(
        "addon_installations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "addon_id",
            sa.Integer(),
            sa.ForeignKey("addons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "installed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("granted_scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "workspace_id", "addon_id", name="uq_addon_installations_workspace_addon"
        ),
    )
    op.create_index("ix_addon_installations_id", "addon_installations", ["id"], unique=False)
    op.create_index(
        "ix_addon_installations_workspace_id",
        "addon_installations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_installations_addon_id",
        "addon_installations",
        ["addon_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_installations_installed_by_user_id",
        "addon_installations",
        ["installed_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_installations_workspace_active",
        "addon_installations",
        ["workspace_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_addon_installations_addon_active",
        "addon_installations",
        ["addon_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "addon_usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "installation_id",
            sa.Integer(),
            sa.ForeignKey("addon_installations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "addon_id",
            sa.Integer(),
            sa.ForeignKey("addons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triggered_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="succeeded"),
        sa.Column("credits_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("input_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index("ix_addon_usage_logs_id", "addon_usage_logs", ["id"], unique=False)
    op.create_index(
        "ix_addon_usage_logs_installation_id",
        "addon_usage_logs",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_usage_logs_workspace_id",
        "addon_usage_logs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_usage_logs_addon_id",
        "addon_usage_logs",
        ["addon_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_usage_logs_triggered_by_user_id",
        "addon_usage_logs",
        ["triggered_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_addon_usage_logs_installation_triggered_at",
        "addon_usage_logs",
        ["installation_id", "triggered_at"],
        unique=False,
    )
    op.create_index(
        "ix_addon_usage_logs_workspace_addon_triggered_at",
        "addon_usage_logs",
        ["workspace_id", "addon_id", "triggered_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_addon_usage_logs_workspace_addon_triggered_at",
        table_name="addon_usage_logs",
    )
    op.drop_index(
        "ix_addon_usage_logs_installation_triggered_at",
        table_name="addon_usage_logs",
    )
    op.drop_index("ix_addon_usage_logs_triggered_by_user_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_addon_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_workspace_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_installation_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_id", table_name="addon_usage_logs")
    op.drop_table("addon_usage_logs")

    op.drop_index("ix_addon_installations_addon_active", table_name="addon_installations")
    op.drop_index("ix_addon_installations_workspace_active", table_name="addon_installations")
    op.drop_index("ix_addon_installations_installed_by_user_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_addon_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_workspace_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_id", table_name="addon_installations")
    op.drop_table("addon_installations")

    op.drop_index("ix_addons_first_party_verified", table_name="addons")
    op.drop_index("ix_addons_published_category", table_name="addons")
    op.drop_index("ix_addons_author_id", table_name="addons")
    op.drop_index("ix_addons_slug", table_name="addons")
    op.drop_index("ix_addons_id", table_name="addons")
    op.drop_table("addons")
