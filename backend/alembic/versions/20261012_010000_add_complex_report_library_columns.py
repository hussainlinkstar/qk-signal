"""Add the report library columns to complex_report_jobs (SIGV2-1130).

The approved Report library row shows NAME, PERIOD and SIZE. None of the three
was stored: the name did not exist, the requested interval reached the generate
endpoint and was then discarded, and the size could only be found by reading
the stored object back. This adds the four columns that make the row servable
from storage instead of recomputed on every read.

Additive and nullable only: four new columns, no backfill, no NOT NULL, no
rename and nothing dropped. Rows that predate it keep NULL and are served with
a name derived at read time (services/report_library.resolve_stored_report_name),
which is the one place the format applies on read and is deliberately confined
to historical rows.

Revision ID: 20261012_010000
Revises: 20261011_010000
Create Date: 2026-10-12 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261012_010000"
down_revision = "20261011_010000"
branch_labels = None
depends_on = None

TABLE_NAME = "complex_report_jobs"
NEW_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("name", sa.String()),
    ("period_start", sa.DateTime(timezone=True)),
    ("period_end", sa.DateTime(timezone=True)),
    ("file_size_bytes", sa.Integer()),
)


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    existing = _columns(inspector, TABLE_NAME)
    for column_name, column_type in NEW_COLUMNS:
        if column_name not in existing:
            op.add_column(TABLE_NAME, sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    existing = _columns(inspector, TABLE_NAME)
    for column_name, _column_type in reversed(NEW_COLUMNS):
        if column_name in existing:
            op.drop_column(TABLE_NAME, column_name)
