"""Add nullable export_manifest column to complex_report_jobs.

Revision ID: 20260930_010000
Revises: 20260922_010000
Create Date: 2026-09-30 01:00:00.000000

The resolved export manifest is persisted at enqueue time so the PDF worker
and the download endpoint can re-check report export entitlements against the
same manifest the renderer uses, instead of re-deriving one from job options.

Additive and nullable only: no NOT NULL constraint and no backfill. Rows that
predate this column keep a NULL manifest and fall back to the base
has_pdf_audit_reports entitlement check at download time.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260930_010000"
down_revision = "20260922_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complex_report_jobs",
        sa.Column("export_manifest", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("complex_report_jobs", "export_manifest")
