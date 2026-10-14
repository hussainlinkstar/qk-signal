"""add Stripe event due indexes concurrently

Revision ID: 20260725_020000
Revises: 20260725_015000
Create Date: 2026-07-25 02:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260725_020000"
down_revision = "20260725_015000"
branch_labels = None
depends_on = None


INDEX_DEFINITIONS = {
    "ix_stripe_event_log_status_next_attempt": (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stripe_event_log_status_next_attempt "
        "ON stripe_event_log (processing_status, next_attempt_at)"
    ),
    "ix_stripe_event_log_status_claimed_at": (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stripe_event_log_status_claimed_at "
        "ON stripe_event_log (processing_status, claimed_at)"
    ),
}


def _invalid_index_exists(index_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_class c "
                "JOIN pg_index i ON i.indexrelid = c.oid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :index_name "
                "AND n.nspname = current_schema() AND i.indisvalid = false"
            ),
            {"index_name": index_name},
        )
        .scalar_one_or_none()
    )


def _constraint_exists(name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        )
        .scalar_one_or_none()
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '30min'")
        try:
            for index_name, create_sql in INDEX_DEFINITIONS.items():
                if _invalid_index_exists(index_name):
                    op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')
                op.execute(create_sql)
            if _invalid_index_exists("uq_plan_credit_grants_entitlement_key"):
                op.execute(
                    'DROP INDEX CONCURRENTLY IF EXISTS "uq_plan_credit_grants_entitlement_key"'
                )
            op.execute(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_plan_credit_grants_entitlement_key ON plan_credit_grants (entitlement_key)"
            )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")
    if not _constraint_exists("uq_plan_credit_grants_entitlement_key"):
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute(
            "ALTER TABLE plan_credit_grants ADD CONSTRAINT uq_plan_credit_grants_entitlement_key UNIQUE USING INDEX uq_plan_credit_grants_entitlement_key"
        )


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: durable Stripe event indexes must be preserved.")
