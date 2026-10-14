"""attach subscriptions user unique constraint

Revision ID: 20260725_023000
Revises: 20260725_022000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_023000"
down_revision = "20260725_022000"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "uq_subscriptions_user_id"


def _constraint_exists() -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = :constraint_name AND conrelid = 'subscriptions'::regclass"
            ),
            {"constraint_name": CONSTRAINT_NAME},
        )
        .scalar_one_or_none()
    )


def upgrade() -> None:
    if _constraint_exists():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        'ALTER TABLE subscriptions ADD CONSTRAINT "uq_subscriptions_user_id" '
        'UNIQUE USING INDEX "uq_subscriptions_user_id"'
    )


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: subscription user uniqueness must be preserved.")
