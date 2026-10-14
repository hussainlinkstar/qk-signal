"""Add credit_holds table for audit credit reservations.

Revision ID: 20260307_110000
Revises: 20260307_090000
Create Date: 2026-03-07 11:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_110000"
down_revision = "20260307_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_holds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("hold_amount", sa.Integer(), nullable=False),
        sa.Column("final_amount", sa.Integer(), nullable=True),
        sa.Column("refunded_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("feature_key", sa.String(length=100), nullable=False),
        sa.Column("tier_class", sa.String(length=20), nullable=False, server_default="fast"),
        sa.Column("policy_version", sa.String(length=10), nullable=False, server_default="v1"),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_credit_holds_expires_at"), "credit_holds", ["expires_at"], unique=False
    )
    op.create_index(op.f("ix_credit_holds_id"), "credit_holds", ["id"], unique=False)
    op.create_index(
        op.f("ix_credit_holds_project_id"), "credit_holds", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_credit_holds_request_id"), "credit_holds", ["request_id"], unique=True)
    op.create_index(op.f("ix_credit_holds_status"), "credit_holds", ["status"], unique=False)
    op.create_index(
        "ix_credit_holds_status_expires",
        "credit_holds",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_credit_holds_user_status",
        "credit_holds",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(op.f("ix_credit_holds_user_id"), "credit_holds", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_credit_holds_workspace_id"), "credit_holds", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_holds_workspace_id"), table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_user_id"), table_name="credit_holds")
    op.drop_index("ix_credit_holds_user_status", table_name="credit_holds")
    op.drop_index("ix_credit_holds_status_expires", table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_status"), table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_request_id"), table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_project_id"), table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_id"), table_name="credit_holds")
    op.drop_index(op.f("ix_credit_holds_expires_at"), table_name="credit_holds")
    op.drop_table("credit_holds")
