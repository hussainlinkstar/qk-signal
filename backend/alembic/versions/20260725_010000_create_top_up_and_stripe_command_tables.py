"""create top-up and Stripe command tables

Revision ID: 20260725_010000
Revises: 20260722_150000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_010000"
down_revision = "20260722_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_top_up_orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("intent_key_hash", sa.String(64), nullable=False),
        sa.Column("expected_credits", sa.Integer(), nullable=False),
        sa.Column("expected_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="usd", nullable=False),
        sa.Column("stripe_mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_session_id", sa.String(255), nullable=True),
        sa.Column("credit_adjustment_id", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "expected_credits >= 100 AND expected_credits <= 10000",
            name="ck_credit_top_up_orders_expected_credits",
        ),
        sa.CheckConstraint(
            "expected_amount_cents > 0", name="ck_credit_top_up_orders_expected_amount_positive"
        ),
        sa.CheckConstraint("currency = 'usd'", name="ck_credit_top_up_orders_currency_usd"),
        sa.CheckConstraint(
            "stripe_mode IN ('test', 'live')", name="ck_credit_top_up_orders_stripe_mode"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'checkout_created', 'validation_failed', 'fulfilled', 'canceled')",
            name="ck_credit_top_up_orders_status",
        ),
        sa.CheckConstraint(
            "(status = 'fulfilled' AND stripe_customer_id IS NOT NULL AND stripe_session_id IS NOT NULL AND fulfilled_at IS NOT NULL AND credit_adjustment_id IS NOT NULL) OR (status != 'fulfilled' AND fulfilled_at IS NULL AND credit_adjustment_id IS NULL)",
            name="ck_credit_top_up_orders_fulfilled_fields",
        ),
        sa.CheckConstraint(
            "status != 'pending' OR stripe_session_id IS NULL",
            name="ck_credit_top_up_orders_pending_fields",
        ),
        sa.CheckConstraint(
            "status != 'checkout_created' OR (stripe_customer_id IS NOT NULL AND stripe_session_id IS NOT NULL)",
            name="ck_credit_top_up_orders_checkout_fields",
        ),
        sa.ForeignKeyConstraint(
            ["credit_adjustment_id"],
            ["user_credit_adjustments.id"],
            name="fk_credit_top_up_orders_credit_adjustment_id",
        ),
        sa.UniqueConstraint("stripe_session_id", name="uq_credit_top_up_orders_stripe_session_id"),
        sa.UniqueConstraint(
            "user_id", "intent_key_hash", name="uq_credit_top_up_orders_user_intent_key_hash"
        ),
        sa.UniqueConstraint(
            "credit_adjustment_id", name="uq_credit_top_up_orders_credit_adjustment_id"
        ),
    )
    for name, columns in (
        ("ix_credit_top_up_orders_user_id", ["user_id"]),
        ("ix_credit_top_up_orders_status", ["status"]),
        ("ix_credit_top_up_orders_stripe_customer_id", ["stripe_customer_id"]),
        ("ix_credit_top_up_orders_stripe_session_id", ["stripe_session_id"]),
        ("ix_credit_top_up_orders_user_status", ["user_id", "status"]),
    ):
        op.create_index(name, "credit_top_up_orders", columns)

    op.create_table(
        "stripe_command_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("stripe_mode", sa.String(8), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claim_token", sa.String(64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'failed', 'succeeded', 'dead_letter')",
            name="ck_stripe_command_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_stripe_command_outbox_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "stripe_mode IN ('test', 'live')", name="ck_stripe_command_outbox_stripe_mode"
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (status = 'processing' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (status = 'failed' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NOT NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR (status = 'succeeded' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NOT NULL AND dead_lettered_at IS NULL) OR (status = 'dead_letter' AND claim_token IS NULL AND claimed_at IS NULL AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NOT NULL)",
            name="ck_stripe_command_outbox_state_consistency",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_stripe_command_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_stripe_command_outbox_status_next_attempt",
        "stripe_command_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: financial and Stripe command records must be preserved."
    )
