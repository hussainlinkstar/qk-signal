"""Add pricing v2 operational flags and AI economics ledger

Revision ID: 20260306_140000
Revises: 20260306_110000
Create Date: 2026-03-06 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_140000"
down_revision = "20260306_110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operational_settings",
        sa.Column(
            "pricing_v2_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "operational_settings",
        sa.Column(
            "credit_engine_v2_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "operational_settings",
        sa.Column(
            "pricing_v2_shadow_mode",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    op.create_table(
        "ai_economics_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("policy_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column("feature_key", sa.String(), nullable=False),
        sa.Column("tier_class", sa.String(), nullable=False, server_default="fast"),
        sa.Column("routing_profile", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("fallback_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_cost_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("infra_alloc_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("orchestration_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("retry_risk_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("real_cost_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credit_unit_value_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("implied_revenue_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("margin_eur", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("margin_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shadow_policy_version", sa.String(), nullable=True),
        sa.Column("shadow_credits_charged", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_id",
        "ai_economics_ledger_entries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_feature_key",
        "ai_economics_ledger_entries",
        ["feature_key"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_provider",
        "ai_economics_ledger_entries",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_request_id",
        "ai_economics_ledger_entries",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_workspace_id",
        "ai_economics_ledger_entries",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_project_id",
        "ai_economics_ledger_entries",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_user_id",
        "ai_economics_ledger_entries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_economics_ledger_entries_created_at",
        "ai_economics_ledger_entries",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_econ_ledger_feature_created",
        "ai_economics_ledger_entries",
        ["feature_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_econ_ledger_workspace_created",
        "ai_economics_ledger_entries",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_econ_ledger_project_created",
        "ai_economics_ledger_entries",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_econ_ledger_project_created", table_name="ai_economics_ledger_entries")
    op.drop_index("ix_ai_econ_ledger_workspace_created", table_name="ai_economics_ledger_entries")
    op.drop_index("ix_ai_econ_ledger_feature_created", table_name="ai_economics_ledger_entries")
    op.drop_index(
        "ix_ai_economics_ledger_entries_created_at", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_user_id", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_project_id", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_workspace_id", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_request_id", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_provider", table_name="ai_economics_ledger_entries"
    )
    op.drop_index(
        "ix_ai_economics_ledger_entries_feature_key", table_name="ai_economics_ledger_entries"
    )
    op.drop_index("ix_ai_economics_ledger_entries_id", table_name="ai_economics_ledger_entries")
    op.drop_table("ai_economics_ledger_entries")

    op.drop_column("operational_settings", "pricing_v2_shadow_mode")
    op.drop_column("operational_settings", "credit_engine_v2_enabled")
    op.drop_column("operational_settings", "pricing_v2_enabled")
