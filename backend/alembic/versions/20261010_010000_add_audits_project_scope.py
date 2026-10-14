"""Add audits.project_scope and classify existing rows (SIGV2-1117).

A competitor benchmark is stored with ``audits.project_id`` set to the customer's
own project. Nothing on the audit row recorded that it measured a competitor, so
project score history, trend, 30-day change and rank could read a competitor's
scores back as the project's own.

This migration is additive only. It adds one nullable column and backfills it;
nothing is dropped, renamed, or made NOT NULL.

The backfill classifies a row as a competitor benchmark on positive evidence,
which for historical rows is one of:

  * the row is referenced by ``project_competitor_snapshots.competitor_audit_id``
  * ``request_id`` starts with ``competitive-benchmark:`` (project competitor
    benchmark, scheduled or manually refreshed)
  * ``request_id`` starts with ``lite-refresh:`` (site competitor lite refresh,
    the path that never wrote a snapshot at all)

Each of those writers stamps its own request-id prefix, so the classification
does not depend on the snapshot rows that the contamination could outlive. Every
remaining row is marked as the project's own, so existing history keeps reading
back in full.

Known limit of the backfill: an audit requested through ``POST /api/v1/audit``
with ``category="competitor lite audit"`` and a ``project_id`` carries no durable
marker on the audit row (the category is not persisted there), so a historical
row of that kind is classified as the project's own. New rows from that path are
classified correctly at write time.


Revision ID: 20261010_010000
Revises: 20261009_010000
Create Date: 2026-10-10 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261010_010000"
down_revision = "20261009_010000"
branch_labels = None
depends_on = None

AUDITS_TABLE = "audits"
SNAPSHOTS_TABLE = "project_competitor_snapshots"
COLUMN_NAME = "project_scope"
SCOPE_OWN = "project"
SCOPE_COMPETITOR = "competitor"


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if AUDITS_TABLE not in tables:
        return

    if COLUMN_NAME not in _columns(inspector, AUDITS_TABLE):
        op.add_column(AUDITS_TABLE, sa.Column(COLUMN_NAME, sa.String(), nullable=True))

    competitor_predicates = [
        "request_id LIKE 'competitive-benchmark:%'",
        "request_id LIKE 'lite-refresh:%'",
    ]
    if SNAPSHOTS_TABLE in tables:
        competitor_predicates.append(
            f"id IN (SELECT competitor_audit_id FROM {SNAPSHOTS_TABLE} "
            "WHERE competitor_audit_id IS NOT NULL)"
        )

    op.execute(
        sa.text(
            f"UPDATE {AUDITS_TABLE} SET {COLUMN_NAME} = '{SCOPE_COMPETITOR}' "
            f"WHERE {COLUMN_NAME} IS NULL AND ({' OR '.join(competitor_predicates)})"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {AUDITS_TABLE} SET {COLUMN_NAME} = '{SCOPE_OWN}' "
            f"WHERE {COLUMN_NAME} IS NULL"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if AUDITS_TABLE not in tables:
        return
    if COLUMN_NAME in _columns(inspector, AUDITS_TABLE):
        op.drop_column(AUDITS_TABLE, COLUMN_NAME)
