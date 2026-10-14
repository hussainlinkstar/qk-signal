"""add credit commitments and usage cycles

Revision ID: 20260303_050000
Revises: 20260303_040000
Create Date: 2026-03-03 05:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_050000"
down_revision = "20260303_040000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_commitments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("committed_credits", sa.Integer(), nullable=False),
        sa.Column("rate_per_credit", sa.Numeric(10, 4), nullable=False),
        sa.Column("monthly_fee_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("overage_rate", sa.Numeric(10, 4), nullable=False, server_default="0.0100"),
        sa.Column("stripe_subscription_id", sa.String(), nullable=False),
        sa.Column("stripe_commitment_subscription_item_id", sa.String(), nullable=True),
        sa.Column("stripe_overage_subscription_item_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_cycle_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_cycle_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_tier", sa.String(), nullable=True),
        sa.Column("pending_committed_credits", sa.Integer(), nullable=True),
        sa.Column("pending_rate_per_credit", sa.Numeric(10, 4), nullable=True),
        sa.Column("pending_monthly_fee_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("pending_change_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_credit_commitments_user_id", "credit_commitments", ["user_id"])
    op.create_index("ix_credit_commitments_tier", "credit_commitments", ["tier"])
    op.create_index("ix_credit_commitments_status", "credit_commitments", ["status"])
    op.create_index(
        "ix_credit_commitments_user_status",
        "credit_commitments",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_credit_commitments_stripe_subscription_id",
        "credit_commitments",
        ["stripe_subscription_id"],
        unique=True,
    )

    op.create_table(
        "commitment_usage_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("commitment_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cycle_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cycle_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_credits", sa.Integer(), nullable=False),
        sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overage_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overage_reported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warning_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["commitment_id"], ["credit_commitments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("commitment_id", "cycle_start", name="uq_commitment_cycle_start"),
    )
    op.create_index(
        "ix_commitment_usage_cycles_commitment_id", "commitment_usage_cycles", ["commitment_id"]
    )
    op.create_index("ix_commitment_usage_cycles_user_id", "commitment_usage_cycles", ["user_id"])
    op.create_index(
        "ix_commitment_cycles_active",
        "commitment_usage_cycles",
        ["commitment_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_commitment_cycles_active", table_name="commitment_usage_cycles")
    op.drop_index("ix_commitment_usage_cycles_user_id", table_name="commitment_usage_cycles")
    op.drop_index("ix_commitment_usage_cycles_commitment_id", table_name="commitment_usage_cycles")
    op.drop_table("commitment_usage_cycles")

    op.drop_index("ix_credit_commitments_stripe_subscription_id", table_name="credit_commitments")
    op.drop_index("ix_credit_commitments_user_status", table_name="credit_commitments")
    op.drop_index("ix_credit_commitments_status", table_name="credit_commitments")
    op.drop_index("ix_credit_commitments_tier", table_name="credit_commitments")
    op.drop_index("ix_credit_commitments_user_id", table_name="credit_commitments")
    op.drop_table("credit_commitments")
