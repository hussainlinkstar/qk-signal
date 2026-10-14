"""add external api product fields

Revision ID: 20260303_070000
Revises: 20260303_060000
Create Date: 2026-03-03 07:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_070000"
down_revision = "20260303_060000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    api_key_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    audit_job_columns = {column["name"] for column in inspector.get_columns("audit_jobs")}
    audit_job_indexes = {index["name"] for index in inspector.get_indexes("audit_jobs")}

    with op.batch_alter_table("api_keys") as batch_op:
        if "key_prefix" not in api_key_columns:
            batch_op.add_column(sa.Column("key_prefix", sa.String(), nullable=True))
        if "key_last_four" not in api_key_columns:
            batch_op.add_column(sa.Column("key_last_four", sa.String(), nullable=True))
        if "scopes" not in api_key_columns:
            batch_op.add_column(
                sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
            )
        if "is_active" not in api_key_columns:
            batch_op.add_column(
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
            )
        if "revoked_at" not in api_key_columns:
            batch_op.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("audit_jobs") as batch_op:
        if "api_key_id" not in audit_job_columns:
            batch_op.add_column(sa.Column("api_key_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_audit_jobs_api_key_id",
                "api_keys",
                ["api_key_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "project_id" not in audit_job_columns:
            batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_audit_jobs_project_id",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "source" not in audit_job_columns:
            batch_op.add_column(
                sa.Column(
                    "source",
                    sa.String(),
                    nullable=False,
                    server_default=sa.text("'internal'"),
                )
            )
        if "provider" not in audit_job_columns:
            batch_op.add_column(sa.Column("provider", sa.String(), nullable=True))
        if "tier" not in audit_job_columns:
            batch_op.add_column(sa.Column("tier", sa.String(), nullable=True))
        if "estimated_credit_cost" not in audit_job_columns:
            batch_op.add_column(sa.Column("estimated_credit_cost", sa.Integer(), nullable=True))
        if "consumed_credit_cost" not in audit_job_columns:
            batch_op.add_column(sa.Column("consumed_credit_cost", sa.Integer(), nullable=True))
        if "idempotency_key_hash" not in audit_job_columns:
            batch_op.add_column(sa.Column("idempotency_key_hash", sa.String(), nullable=True))
        if "webhook_url" not in audit_job_columns:
            batch_op.add_column(sa.Column("webhook_url", sa.String(), nullable=True))
        if "webhook_secret" not in audit_job_columns:
            batch_op.add_column(sa.Column("webhook_secret", sa.Text(), nullable=True))
        if "webhook_status" not in audit_job_columns:
            batch_op.add_column(sa.Column("webhook_status", sa.String(), nullable=True))
        if "webhook_attempts" not in audit_job_columns:
            batch_op.add_column(
                sa.Column(
                    "webhook_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "webhook_last_error" not in audit_job_columns:
            batch_op.add_column(sa.Column("webhook_last_error", sa.Text(), nullable=True))
        if "webhook_delivered_at" not in audit_job_columns:
            batch_op.add_column(
                sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True)
            )

    if "ix_audit_jobs_api_key_id" not in audit_job_indexes:
        op.create_index("ix_audit_jobs_api_key_id", "audit_jobs", ["api_key_id"], unique=False)
    if "ix_audit_jobs_project_id" not in audit_job_indexes:
        op.create_index("ix_audit_jobs_project_id", "audit_jobs", ["project_id"], unique=False)
    if "ix_audit_jobs_source" not in audit_job_indexes:
        op.create_index("ix_audit_jobs_source", "audit_jobs", ["source"], unique=False)
    if "ix_audit_jobs_idempotency_key_hash" not in audit_job_indexes:
        op.create_index(
            "ix_audit_jobs_idempotency_key_hash",
            "audit_jobs",
            ["idempotency_key_hash"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    api_key_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    audit_job_columns = {column["name"] for column in inspector.get_columns("audit_jobs")}
    audit_job_indexes = {index["name"] for index in inspector.get_indexes("audit_jobs")}

    for index_name in (
        "ix_audit_jobs_idempotency_key_hash",
        "ix_audit_jobs_source",
        "ix_audit_jobs_project_id",
        "ix_audit_jobs_api_key_id",
    ):
        if index_name in audit_job_indexes:
            op.drop_index(index_name, table_name="audit_jobs")

    with op.batch_alter_table("audit_jobs") as batch_op:
        for column_name in (
            "webhook_delivered_at",
            "webhook_last_error",
            "webhook_attempts",
            "webhook_status",
            "webhook_secret",
            "webhook_url",
            "idempotency_key_hash",
            "consumed_credit_cost",
            "estimated_credit_cost",
            "tier",
            "provider",
            "source",
            "project_id",
            "api_key_id",
        ):
            if column_name in audit_job_columns:
                batch_op.drop_column(column_name)

    with op.batch_alter_table("api_keys") as batch_op:
        for column_name in (
            "revoked_at",
            "is_active",
            "scopes",
            "key_last_four",
            "key_prefix",
        ):
            if column_name in api_key_columns:
                batch_op.drop_column(column_name)
