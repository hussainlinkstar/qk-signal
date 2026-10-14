"""add audit report archive columns

Revision ID: 20260322_080000
Revises: 20260321_070000
Create Date: 2026-03-22 08:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260322_080000"
down_revision = "20260321_070000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("report_archive_uri", sa.String(), nullable=True))
    op.add_column(
        "audits", sa.Column("report_archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "audits", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false")
    )
    op.alter_column("audits", "full_report", existing_type=sa.JSON(), nullable=True)
    op.create_index("ix_audits_report_archived_at", "audits", ["report_archived_at"])


def downgrade() -> None:
    op.drop_index("ix_audits_report_archived_at", table_name="audits")
    op.drop_column("audits", "is_pinned")
    op.drop_column("audits", "report_archived_at")
    op.drop_column("audits", "report_archive_uri")
    op.alter_column("audits", "full_report", existing_type=sa.JSON(), nullable=False)
