"""add durable base subscription checkout attempts

Revision ID: 20260725_021000
Revises: 20260725_020000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_021000"
down_revision = "20260725_020000"
branch_labels = None
depends_on = None


ACTIVE_STATUS_PREDICATE = "status IN ('pending', 'customer_created', 'session_created')"


def upgrade() -> None:
    op.create_table(
        "base_checkout_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_mode", sa.String(8), nullable=False),
        sa.Column("target_plan", sa.String(), nullable=False),
        sa.Column("billing_interval", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_session_id", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_base_checkout_attempts_stripe_mode",
        ),
        sa.CheckConstraint(
            "target_plan IN ('plan_starter', 'plan_standard', 'plan_specialist', "
            "'plan_executive')",
            name="ck_base_checkout_attempts_target_plan",
        ),
        sa.CheckConstraint(
            "billing_interval IN ('month', 'year')",
            name="ck_base_checkout_attempts_billing_interval",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'customer_created', 'session_created', "
            "'completed', 'expired', 'failed', 'canceled')",
            name="ck_base_checkout_attempts_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND stripe_customer_id IS NULL "
            "AND stripe_session_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'customer_created' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'session_created' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status IN ('expired', 'failed', 'canceled') AND completed_at IS NULL)",
            name="ck_base_checkout_attempts_state_consistency",
        ),
        sa.UniqueConstraint(
            "stripe_session_id",
            name="uq_base_checkout_attempts_stripe_session_id",
        ),
    )
    op.create_index(
        "ix_base_checkout_attempts_user_id",
        "base_checkout_attempts",
        ["user_id"],
    )
    op.create_index(
        "ix_base_checkout_attempts_user_mode_status",
        "base_checkout_attempts",
        ["user_id", "stripe_mode", "status"],
    )
    op.create_index(
        "ix_base_checkout_attempts_status_expires_at",
        "base_checkout_attempts",
        ["status", "expires_at"],
    )
    op.create_index(
        "uq_base_checkout_attempts_active_user_mode",
        "base_checkout_attempts",
        ["user_id", "stripe_mode"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUS_PREDICATE),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: durable base checkout attempt records must be preserved."
    )
