"""add recommendation_approvals table and client notification preferences

Revision ID: 20260323_060000
Revises: 20260323_050000
Create Date: 2026-03-23 06:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_060000"
down_revision = "20260323_050000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create recommendation_approvals table
    op.create_table(
        "recommendation_approvals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id", sa.Integer(), sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("section_path", sa.String(), nullable=True),
        sa.Column("source_recommendation_key", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "approved",
                "rejected",
                "deferred",
                name="recommendation_approval_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_recommendation_approvals_audit_id", "recommendation_approvals", ["audit_id"]
    )
    op.create_index(
        "ix_recommendation_approvals_decided_by", "recommendation_approvals", ["decided_by_user_id"]
    )
    op.create_unique_constraint(
        "uq_recommendation_approvals_audit_key",
        "recommendation_approvals",
        ["audit_id", "source_recommendation_key"],
    )

    # 2. Add client notification preference columns to workspace_users
    op.add_column(
        "workspace_users",
        sa.Column(
            "email_digest_frequency",
            sa.Enum(
                "daily",
                "weekly",
                "monthly",
                "none",
                name="client_digest_frequency",
                native_enum=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "workspace_users",
        sa.Column("notify_on_new_audit", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_users", "notify_on_new_audit")
    op.drop_column("workspace_users", "email_digest_frequency")
    op.drop_table("recommendation_approvals")
