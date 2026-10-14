"""add billing state constraints without validation

Revision ID: 20260725_013000
Revises: 20260725_012000
"""

from alembic import op

revision = "20260725_013000"
down_revision = "20260725_012000"
branch_labels = None
depends_on = None

STATE_CHECK = "(processing_status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (processing_status = 'failed' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NOT NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (processing_status = 'processing' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (processing_status = 'processed' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NOT NULL AND dead_lettered_at IS NULL) OR (processing_status = 'dead_letter' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NOT NULL)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.alter_column("stripe_event_log", "attempt_count", server_default="0")
    op.execute(
        "ALTER TABLE credit_commitments ADD CONSTRAINT ck_credit_commitments_stripe_mode CHECK (stripe_mode IS NULL OR stripe_mode IN ('test', 'live')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE subscriptions ADD CONSTRAINT ck_subscriptions_stripe_mode CHECK (stripe_mode IS NULL OR stripe_mode IN ('test', 'live')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE plan_credit_grants ADD CONSTRAINT ck_plan_credit_grants_entitlement_key_not_null CHECK (entitlement_key IS NOT NULL AND stripe_mode IS NOT NULL AND stripe_price_id IS NOT NULL AND period_start IS NOT NULL AND period_end IS NOT NULL) NOT VALID"
    )
    op.execute(
        "ALTER TABLE plan_credit_grants ADD CONSTRAINT ck_plan_credit_grants_stripe_mode CHECK (stripe_mode IN ('legacy', 'test', 'live')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE plan_credit_grants ADD CONSTRAINT ck_plan_credit_grants_period CHECK (period_start >= 0 AND period_end >= period_start) NOT VALID"
    )
    op.execute(
        "ALTER TABLE stripe_event_log ADD CONSTRAINT ck_stripe_event_log_attempt_count_not_null CHECK (attempt_count IS NOT NULL) NOT VALID"
    )
    op.execute(
        "ALTER TABLE stripe_event_log ADD CONSTRAINT ck_stripe_event_log_attempt_count_nonnegative CHECK (attempt_count >= 0) NOT VALID"
    )
    op.execute(
        "ALTER TABLE stripe_event_log ADD CONSTRAINT ck_stripe_event_log_processing_status CHECK (processing_status IN ('pending', 'processing', 'failed', 'processed', 'dead_letter')) NOT VALID"
    )
    op.execute(
        f"ALTER TABLE stripe_event_log ADD CONSTRAINT ck_stripe_event_log_state_consistency CHECK ({STATE_CHECK}) NOT VALID"
    )


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: billing state constraints must be preserved.")
