"""add subscriptions user unique index concurrently

Revision ID: 20260725_022000
Revises: 20260725_021000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_022000"
down_revision = "20260725_021000"
branch_labels = None
depends_on = None


DUPLICATE_DIAGNOSTIC = (
    "SUBSCRIPTIONS_USER_ID_DUPLICATES_DETECTED: resolve duplicate "
    "subscriptions.user_id rows before retrying migration."
)
INDEX_NAME = "uq_subscriptions_user_id"


def _duplicate_user_exists() -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM subscriptions WHERE user_id IS NOT NULL "
                "GROUP BY user_id HAVING count(*) > 1 LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )


def _invalid_index_exists() -> bool:
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
            {"index_name": INDEX_NAME},
        )
        .scalar_one_or_none()
    )


def upgrade() -> None:
    if _duplicate_user_exists():
        raise RuntimeError(DUPLICATE_DIAGNOSTIC)

    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '30min'")
        try:
            if _invalid_index_exists():
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{INDEX_NAME}"')
            op.execute(
                f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "{INDEX_NAME}" '
                "ON subscriptions (user_id)"
            )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: subscription user uniqueness must be preserved.")
