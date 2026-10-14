"""Add PDF job retry fields (attempt_count, max_attempts).

Revision ID: 20260404_130000
Revises: 20260404_120000
Create Date: 2026-04-04 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260404_130000"
down_revision = "20260404_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complex_report_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "complex_report_jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("complex_report_jobs", "max_attempts")
    op.drop_column("complex_report_jobs", "attempt_count")
