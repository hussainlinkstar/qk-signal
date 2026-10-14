"""add durable plan invoice credit grants

Revision ID: 20260722_150000
Revises: 20260501_090000
Create Date: 2026-07-22 15:00:00

This additive migration creates the Stripe-invoice idempotency boundary for
base-plan credit grants. The downgrade intentionally preserves the table and
its financial audit records; removing it would permit historical invoices to
be granted again after a redeploy.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_150000"
down_revision = "20260501_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "plan_credit_grants" in set(inspector.get_table_names()):
        return

    op.create_table(
        "plan_credit_grants",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("stripe_invoice_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_type", sa.String(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "stripe_invoice_id",
            name="uq_plan_credit_grants_stripe_invoice_id",
        ),
    )
    op.create_index(
        "ix_plan_credit_grants_id",
        "plan_credit_grants",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_plan_credit_grants_user_id",
        "plan_credit_grants",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # Financial idempotency and audit records are intentionally retained.
    pass
