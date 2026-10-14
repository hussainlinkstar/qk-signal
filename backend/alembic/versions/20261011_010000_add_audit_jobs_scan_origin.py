"""Add audit_jobs.scan_origin and classify existing rows (SIGV2-1129).

The customer-facing scan allowance is counted over ``audit_jobs`` at
acceptance, before the ``audits`` row the worker will later write exists, so
``audits.project_scope`` (SIGV2-1117) is not reachable from the row being
counted. The job therefore needs its own explicit declaration, and the
allowance counts only the jobs positively declared as the customer's own scan.

This migration is additive only. It adds one nullable column and backfills it;
nothing is dropped, renamed, or made NOT NULL.

The backfill classifies a historical job as Signal's own competitor refresh on
positive evidence, which on a job row is its server-written ``request_id``
prefix:

  * ``competitive-benchmark:`` (project competitor benchmark, fanned out by a
    scheduled audit or by the workspace refresh endpoint)
  * ``lite-refresh:`` (site competitor lite refresh)

Both prefixes are written by internal competitor writers only, and SIGV2-1126
made every client-supplied request id reject them, so a customer cannot have
forged one onto their own job.

Every remaining existing row is backfilled as the customer's own scan. Those
rows were all billed under the previous rule, so marking them that way leaves
the customer's current 30-day window as they already see it, instead of
silently handing back a month of scans on deploy. The positive-declaration rule
applies from here on: rows written after this migration are classified by the
write path, and a row that declares nothing stays NULL and is not billed.

Revision ID: 20261011_010000
Revises: 20261010_010000
Create Date: 2026-10-11 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261011_010000"
down_revision = "20261010_010000"
branch_labels = None
depends_on = None

AUDIT_JOBS_TABLE = "audit_jobs"
COLUMN_NAME = "scan_origin"
ORIGIN_CUSTOMER = "customer"
ORIGIN_COMPETITOR_REFRESH = "competitor_refresh"
COMPETITOR_REQUEST_ID_PREFIXES = ("competitive-benchmark:", "lite-refresh:")


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if AUDIT_JOBS_TABLE not in set(inspector.get_table_names()):
        return

    if COLUMN_NAME not in _columns(inspector, AUDIT_JOBS_TABLE):
        op.add_column(AUDIT_JOBS_TABLE, sa.Column(COLUMN_NAME, sa.String(), nullable=True))

    competitor_predicates = " OR ".join(
        f"request_id LIKE '{prefix}%'" for prefix in COMPETITOR_REQUEST_ID_PREFIXES
    )
    op.execute(
        sa.text(
            f"UPDATE {AUDIT_JOBS_TABLE} SET {COLUMN_NAME} = '{ORIGIN_COMPETITOR_REFRESH}' "
            f"WHERE {COLUMN_NAME} IS NULL AND ({competitor_predicates})"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {AUDIT_JOBS_TABLE} SET {COLUMN_NAME} = '{ORIGIN_CUSTOMER}' "
            f"WHERE {COLUMN_NAME} IS NULL"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if AUDIT_JOBS_TABLE not in set(inspector.get_table_names()):
        return
    if COLUMN_NAME in _columns(inspector, AUDIT_JOBS_TABLE):
        op.drop_column(AUDIT_JOBS_TABLE, COLUMN_NAME)
