"""validate billing state constraints

Revision ID: 20260725_014000
Revises: 20260725_013000
"""

from alembic import op

revision = "20260725_014000"
down_revision = "20260725_013000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL statement_timeout = '5min'")
    op.execute(
        "ALTER TABLE credit_commitments VALIDATE CONSTRAINT ck_credit_commitments_stripe_mode"
    )
    op.execute("ALTER TABLE subscriptions VALIDATE CONSTRAINT ck_subscriptions_stripe_mode")
    op.execute(
        "ALTER TABLE plan_credit_grants VALIDATE CONSTRAINT ck_plan_credit_grants_entitlement_key_not_null"
    )
    op.execute(
        "ALTER TABLE plan_credit_grants VALIDATE CONSTRAINT ck_plan_credit_grants_stripe_mode"
    )
    op.execute("ALTER TABLE plan_credit_grants VALIDATE CONSTRAINT ck_plan_credit_grants_period")
    op.execute(
        "ALTER TABLE stripe_event_log VALIDATE CONSTRAINT ck_stripe_event_log_attempt_count_not_null"
    )
    for name in (
        "ck_stripe_event_log_attempt_count_nonnegative",
        "ck_stripe_event_log_processing_status",
        "ck_stripe_event_log_state_consistency",
    ):
        op.execute(f"ALTER TABLE stripe_event_log VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: validated billing constraints must be preserved.")
