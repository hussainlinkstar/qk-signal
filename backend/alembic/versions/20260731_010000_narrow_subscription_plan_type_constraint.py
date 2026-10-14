"""Narrow the canonical subscription plan constraint to the supported plans.

Revision ID: 20260731_010000
Revises: 20260730_010000
Create Date: 2026-07-31 01:00:00

The Global Enterprise plan was removed from the product. Its plan ID,
'plan_global_enterprise', survives only inside the allowed-value list of the
already-applied ck_subscriptions_plan_type_canonical check constraint, created
by revision 20260730_010000. That revision is applied in production and is not
edited here: rewriting applied migration history would make freshly created
databases diverge from production. This revision rebuilds the constraint
forward instead, so the database matches app.config.plans.CANONICAL_PLAN_TYPES
and the Subscription ORM model, which already dropped the retired plan.

That constraint is the only one that listed the retired plan ID. The other
plan-bearing columns were checked and need no change:
  * subscriptions.pending_plan_type is guarded by
    ck_subscriptions_pending_plan_type, which lists only the four self-service
    plans (20260727_010000).
  * base_checkout_attempts.target_plan is guarded by
    ck_base_checkout_attempts_target_plan, the same four plans
    (20260725_021000).
  * plan_credit_grants.plan_type (20260722_150000) and users.trial_plan
    (20260308_100000) carry no check constraint at all.
There is no PostgreSQL enum type for plan values, so there is nothing else to
alter.

Production carried zero rows with the retired plan ID in every one of those
five columns when this revision was written. The upgrade still refuses to run
against a database that does contain such rows: it counts them first, grouped
by value, and raises naming the table, the column and the counts. It never
rewrites or deletes billing rows to make the constraint apply.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_010000"
down_revision = "20260730_010000"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_subscriptions_plan_type_canonical"
RETIRED_PLAN_TYPE = "plan_global_enterprise"
SUPPORTED_PLAN_TYPES = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)
PREVIOUS_PLAN_TYPES = (*SUPPORTED_PLAN_TYPES, RETIRED_PLAN_TYPE)


def _plan_type_list(plan_types: tuple[str, ...]) -> str:
    return ", ".join(repr(plan_type) for plan_type in plan_types)


def _plan_check(plan_types: tuple[str, ...]) -> str:
    return f"plan_type IN ({_plan_type_list(plan_types)})"


def _reject_unsupported_rows(plan_types: tuple[str, ...]) -> None:
    """Fail loudly, and readably, rather than touch anybody's billing rows."""
    bind = op.get_bind()
    unsupported_rows = bind.execute(
        sa.text(
            "SELECT plan_type, count(*) AS row_count "
            "FROM subscriptions "
            f"WHERE plan_type NOT IN ({_plan_type_list(plan_types)}) "
            "GROUP BY plan_type "
            "ORDER BY plan_type"
        )
    ).all()
    if unsupported_rows:
        diagnostics = {row.plan_type: row.row_count for row in unsupported_rows}
        raise RuntimeError(
            "Cannot rebuild the canonical subscription plan constraint; "
            f"subscriptions.plan_type holds unsupported value counts: {diagnostics}. "
            "Move those subscriptions onto a supported plan first; this migration "
            "never rewrites or deletes subscription rows."
        )


def _rebuild_constraint(plan_types: tuple[str, ...]) -> None:
    op.execute(f"ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE subscriptions ADD CONSTRAINT {CONSTRAINT_NAME} "
        f"CHECK ({_plan_check(plan_types)}) NOT VALID"
    )
    op.execute(f"ALTER TABLE subscriptions VALIDATE CONSTRAINT {CONSTRAINT_NAME}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")

    _reject_unsupported_rows(SUPPORTED_PLAN_TYPES)
    _rebuild_constraint(SUPPORTED_PLAN_TYPES)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")

    _reject_unsupported_rows(PREVIOUS_PLAN_TYPES)
    _rebuild_constraint(PREVIOUS_PLAN_TYPES)
