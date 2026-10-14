"""add subscription pending plan changes

Revision ID: 20260727_010000
Revises: 20260725_023000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260727_010000"
down_revision = "20260725_023000"
branch_labels = None
depends_on = None


COMPLETE_SET_CHECK = (
    "(stripe_schedule_id IS NULL AND pending_plan_type IS NULL "
    "AND pending_billing_interval IS NULL "
    "AND pending_change_effective_at IS NULL) OR "
    "(stripe_schedule_id IS NOT NULL AND pending_plan_type IS NOT NULL "
    "AND pending_billing_interval IS NOT NULL "
    "AND pending_change_effective_at IS NOT NULL)"
)
PENDING_PLAN_CHECK = (
    "pending_plan_type IS NULL OR pending_plan_type IN "
    "('plan_starter', 'plan_standard', 'plan_specialist', 'plan_executive')"
)
PENDING_INTERVAL_CHECK = (
    "pending_billing_interval IS NULL OR " "pending_billing_interval IN ('month', 'year')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "subscriptions",
        sa.Column("stripe_schedule_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("managed_plan_change_schedule_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("pending_plan_type", sa.String(), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("pending_billing_interval", sa.String(8), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "pending_change_effective_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "plan_state_event_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_subscriptions_pending_change_complete_set",
        "subscriptions",
        COMPLETE_SET_CHECK,
    )
    op.create_check_constraint(
        "ck_subscriptions_pending_plan_type",
        "subscriptions",
        PENDING_PLAN_CHECK,
    )
    op.create_check_constraint(
        "ck_subscriptions_pending_billing_interval",
        "subscriptions",
        PENDING_INTERVAL_CHECK,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: subscription pending plan changes must be preserved."
    )
