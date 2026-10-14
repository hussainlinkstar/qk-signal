"""add nullable billing state columns

Revision ID: 20260725_011000
Revises: 20260725_010000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_011000"
down_revision = "20260725_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column("credit_commitments", sa.Column("stripe_mode", sa.String(8), nullable=True))
    op.add_column("subscriptions", sa.Column("stripe_mode", sa.String(8), nullable=True))
    op.add_column("plan_credit_grants", sa.Column("entitlement_key", sa.String(512), nullable=True))
    op.add_column("plan_credit_grants", sa.Column("stripe_mode", sa.String(8), nullable=True))
    op.add_column("plan_credit_grants", sa.Column("stripe_price_id", sa.String(255), nullable=True))
    op.add_column("plan_credit_grants", sa.Column("period_start", sa.Integer(), nullable=True))
    op.add_column("plan_credit_grants", sa.Column("period_end", sa.Integer(), nullable=True))
    op.add_column("stripe_event_log", sa.Column("claim_token", sa.String(64), nullable=True))
    op.add_column(
        "stripe_event_log", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "stripe_event_log", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("stripe_event_log", sa.Column("attempt_count", sa.Integer(), nullable=True))
    op.add_column(
        "stripe_event_log", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: billing state columns must be preserved.")
