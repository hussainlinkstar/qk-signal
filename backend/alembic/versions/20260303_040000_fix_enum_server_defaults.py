"""fix enum server_defaults lowercase to uppercase

Revision ID: 20260303_040000
Revises: 20260303_030000
Create Date: 2026-03-03 04:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_040000"
down_revision = "20260303_030000"
branch_labels = None
depends_on = None

# SQLAlchemy Enum(PythonEnum, native_enum=False) stores enum .name (uppercase),
# but several migrations used lowercase .value as server_default, causing
# LookupError on read for rows populated by the DB default.
FIXES = [
    ("projects", "competitive_digest_frequency"),
    ("project_data_sources", "binding_mode"),
    ("report_annotations", "visibility"),
    ("project_tasks", "status"),
    ("project_tasks", "priority"),
    ("project_tasks", "origin"),
    ("scheduled_audits", "frequency"),
]

# Mapping of column default corrections (table, column, old_default, new_default)
DEFAULT_FIXES = [
    ("projects", "competitive_digest_frequency", "WEEKLY"),
    ("project_data_sources", "binding_mode", "WORKSPACE"),
    ("report_annotations", "visibility", "INTERNAL"),
    ("project_tasks", "status", "TODO"),
    ("project_tasks", "priority", "MEDIUM"),
    ("project_tasks", "origin", "MANUAL"),
    ("scheduled_audits", "frequency", "WEEKLY"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1) Fix existing data: convert lowercase values to uppercase names
    for table, column in FIXES:
        if table not in existing_tables:
            continue
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET "{column}" = UPPER("{column}") '
                f'WHERE "{column}" != UPPER("{column}")'
            )
        )

    # 2) Fix column server_defaults to uppercase
    for table, column, new_default in DEFAULT_FIXES:
        if table not in existing_tables:
            continue
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, server_default=new_default)


def downgrade() -> None:
    # Lowercase defaults are the original (broken) state, restore them
    DOWNGRADE_DEFAULTS = [
        ("projects", "competitive_digest_frequency", "weekly"),
        ("project_data_sources", "binding_mode", "workspace"),
        ("report_annotations", "visibility", "internal"),
        ("project_tasks", "status", "todo"),
        ("project_tasks", "priority", "medium"),
        ("project_tasks", "origin", "manual"),
        ("scheduled_audits", "frequency", "weekly"),
    ]
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, column, old_default in DOWNGRADE_DEFAULTS:
        if table not in existing_tables:
            continue
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, server_default=old_default)
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET "{column}" = LOWER("{column}") '
                f'WHERE "{column}" != LOWER("{column}")'
            )
        )
