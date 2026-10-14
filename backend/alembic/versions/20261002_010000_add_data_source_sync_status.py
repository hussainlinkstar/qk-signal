"""Add sync status columns to project_data_sources.

Revision ID: 20261002_010000
Revises: 20260930_010000
Create Date: 2026-10-02 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261002_010000"
down_revision = "20260930_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_data_sources" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("project_data_sources")}
    if "last_sync_at" not in existing:
        op.add_column(
            "project_data_sources",
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "last_status" not in existing:
        op.add_column(
            "project_data_sources",
            sa.Column("last_status", sa.String(), nullable=True),
        )
    if "last_error" not in existing:
        op.add_column(
            "project_data_sources",
            sa.Column("last_error", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("project_data_sources", "last_error")
    op.drop_column("project_data_sources", "last_status")
    op.drop_column("project_data_sources", "last_sync_at")
