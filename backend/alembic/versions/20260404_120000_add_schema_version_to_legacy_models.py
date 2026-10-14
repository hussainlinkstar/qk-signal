"""add schema_version to legacy models

Revision ID: 20260404_120000
Revises: 20260322_080000
Create Date: 2026-04-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260404_120000"
down_revision = "20260322_080000"
branch_labels = None
depends_on = None

# Tables that predate the schema_version convention and need the column added.
_TABLES = [
    "users",
    "workspaces",
    "auth_audit_logs",
    "security_events",
    "user_sessions",
    "metrics_snapshots",
    "user_credit_adjustments",
    "audits",
    "sites",
    "subscriptions",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "schema_version")
