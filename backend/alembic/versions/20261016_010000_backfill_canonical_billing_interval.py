"""Backfill canonical values into subscriptions.billing_interval (SIGV2-1238).

GET /api/v1/billing/plans was logging
"Unsupported subscription billing interval: ... code=billing_interval_normalized"
on every request against preprod, because SIGV2-1198's read-side normaliser
(`billing.router.normalized_billing_interval`) was correcting a stored row in
flight rather than fixing the row itself.

`subscriptions.billing_interval` (see `models.py`) has no CHECK constraint, so
a manually created, seeded or legacy row can hold any string. The normaliser
treats exactly two values as supported, `"month"` and `"year"`
(`billing.router.SUPPORTED_BILLING_INTERVALS`); anything else, including the
known offender `"monthly"`, is degraded to the default,
`billing.router.DEFAULT_BILLING_INTERVAL` ("month"). This migration reuses
that exact mapping as a one-time data backfill: every row whose
`billing_interval` is not already `"month"` or `"year"` is rewritten to
`"month"`.

This is a DATA-ONLY migration:

* no column added, dropped, renamed or retyped;
* no constraint added or removed;
* a single `UPDATE ... WHERE billing_interval NOT IN ('month', 'year')`.

The read-side normaliser from SIGV2-1198 STAYS. It is what makes running this
migration safe (a row written with a bad value between the audit and the
deploy is still served correctly), and it keeps protecting against anything
that writes a non-canonical spelling again. If the warning starts firing
again after this migration ships, something is writing `"monthly"` (or any
other unsupported value) today, which is a distinct, more interesting bug
that this now-quiet log will surface.

`downgrade()` cannot be a true inverse: once a row's original spelling has
been overwritten with `"month"`, there is no stored information distinguishing
"was already `month`" from "was `monthly`/`weekly`/anything else before the
backfill". Restoring the literal string `"monthly"` for every affected row
would not be an inverse, it would be a second guess, and could re-introduce
exactly the bug this migration fixes. `downgrade()` is therefore a documented
no-op; reverting the underlying data (if ever required) is a manual,
case-by-case decision, not an automated rewrite.

Revision ID: 20261016_010000
Revises: 20261015_010000
Create Date: 2026-10-16 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261016_010000"
down_revision = "20261015_010000"
branch_labels = None
depends_on = None

SUBSCRIPTIONS_TABLE = "subscriptions"
BILLING_INTERVAL_COLUMN = "billing_interval"

# Mirrors billing.router.SUPPORTED_BILLING_INTERVALS /
# billing.router.DEFAULT_BILLING_INTERVAL exactly. Do not let this drift from
# that module; test_billing_interval_backfill_migration.py pins the two
# together.
SUPPORTED_BILLING_INTERVALS = ("month", "year")
CANONICAL_BILLING_INTERVAL = "month"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if SUBSCRIPTIONS_TABLE not in inspector.get_table_names():
        return

    bind.execute(
        sa.text(
            f"UPDATE {SUBSCRIPTIONS_TABLE} "
            f"SET {BILLING_INTERVAL_COLUMN} = :canonical "
            f"WHERE {BILLING_INTERVAL_COLUMN} NOT IN :supported"
        ).bindparams(
            sa.bindparam("canonical", value=CANONICAL_BILLING_INTERVAL),
            sa.bindparam("supported", value=SUPPORTED_BILLING_INTERVALS, expanding=True),
        )
    )


def downgrade() -> None:
    # Data-only backfill with no recoverable inverse: once a non-canonical
    # spelling has been overwritten with the canonical value, the original
    # string is gone, so there is nothing truthful to restore. See the
    # module docstring.
    pass
