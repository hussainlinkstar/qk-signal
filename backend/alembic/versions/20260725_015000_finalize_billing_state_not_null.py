"""finalize validated billing state not-null columns

Revision ID: 20260725_015000
Revises: 20260725_014000
"""

from alembic import op

revision = "20260725_015000"
down_revision = "20260725_014000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.alter_column("stripe_event_log", "attempt_count", nullable=False)
    op.alter_column("plan_credit_grants", "entitlement_key", nullable=False)
    op.alter_column("plan_credit_grants", "stripe_mode", nullable=False)
    op.alter_column("plan_credit_grants", "stripe_price_id", nullable=False)
    op.alter_column("plan_credit_grants", "period_start", nullable=False)
    op.alter_column("plan_credit_grants", "period_end", nullable=False)


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: finalized billing state must be preserved.")
