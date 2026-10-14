"""Add nullable audit_job_id link on visibility_run_batches (SIGV2-1010).

Lets a batch record the audit job (scan) that triggered it, so the AIO
prompts table can return the snapshot belonging to a specific scan instead
of the freshest scheduled measurement. Fully additive: existing scheduled
and queued batches keep a NULL link.

Revision ID: 20261004_010000
Revises: 20261003_010000
Create Date: 2026-10-04 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261004_010000"
down_revision = "20261003_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("visibility_run_batches")}
    if "audit_job_id" not in columns:
        op.add_column(
            "visibility_run_batches",
            sa.Column(
                "audit_job_id",
                sa.String(),
                sa.ForeignKey("audit_jobs.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    indexes = {index["name"] for index in inspector.get_indexes("visibility_run_batches")}
    if "ix_visibility_run_batches_audit_job_id" not in indexes:
        op.create_index(
            "ix_visibility_run_batches_audit_job_id",
            "visibility_run_batches",
            ["audit_job_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("visibility_run_batches")}
    if "ix_visibility_run_batches_audit_job_id" in indexes:
        op.drop_index(
            "ix_visibility_run_batches_audit_job_id",
            table_name="visibility_run_batches",
        )
    columns = {column["name"] for column in inspector.get_columns("visibility_run_batches")}
    if "audit_job_id" in columns:
        # Plain drop_column: Postgres (the deployed engine) handles this
        # directly; sqlite's dialect lacks column-drop support.
        op.drop_column("visibility_run_batches", "audit_job_id")
