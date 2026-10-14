"""Canonicalize and constrain subscription plan types.

Revision ID: 20260730_010000
Revises: 20260727_010000
Create Date: 2026-07-30 01:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_010000"
down_revision = "20260727_010000"
branch_labels = None
depends_on = None


CANONICAL_PLAN_TYPES = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
    "plan_global_enterprise",
)
CONSTRAINT_NAME = "ck_subscriptions_plan_type_canonical"
CANONICAL_PLAN_CHECK = (
    "plan_type IN (" + ", ".join(repr(plan_type) for plan_type in CANONICAL_PLAN_TYPES) + ")"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")

    op.execute(
        """
        UPDATE subscriptions
        SET plan_type = 'plan_global_enterprise'
        WHERE plan_type = 'global_enterprise';
        """
    )

    bind = op.get_bind()
    invalid_rows = bind.execute(
        sa.text(
            """
            SELECT plan_type, count(*) AS row_count
            FROM subscriptions
            WHERE plan_type NOT IN (
                'plan_starter',
                'plan_agency_trial',
                'plan_standard',
                'plan_specialist',
                'plan_executive',
                'plan_global_enterprise'
            )
            GROUP BY plan_type
            ORDER BY plan_type
            """
        )
    ).all()
    if invalid_rows:
        diagnostics = {row.plan_type: row.row_count for row in invalid_rows}
        raise RuntimeError(
            "Cannot enforce canonical subscription plan types; "
            f"noncanonical value counts: {diagnostics}"
        )

    existing_constraint = bind.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = :constraint_name
                  AND conrelid = to_regclass('subscriptions')
            )
            """
        ),
        {"constraint_name": CONSTRAINT_NAME},
    ).scalar_one()
    if not existing_constraint:
        op.execute(
            f"ALTER TABLE subscriptions ADD CONSTRAINT {CONSTRAINT_NAME} "
            f"CHECK ({CANONICAL_PLAN_CHECK}) NOT VALID"
        )

    op.execute(
        """ALTER TABLE subscriptions
        VALIDATE CONSTRAINT ck_subscriptions_plan_type_canonical"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: canonical subscription plan IDs and their "
        "validated data-integrity constraint must be preserved."
    )
