"""Add audit_jobs table.

Revision ID: 20250306_120000
Revises: 20250305_120000
Create Date: 2025-03-06 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250306_120000"
down_revision = "20250305_120000"
branch_labels = None
depends_on = None


def _drop_orphan_audit_jobs_type(bind) -> None:
    """Drop stale composite type left behind by a failed table creation."""
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE t.typname = 'audit_jobs'
                      AND n.nspname = current_schema()
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = 'audit_jobs'
                      AND n.nspname = current_schema()
                ) THEN
                    EXECUTE format('DROP TYPE IF EXISTS %I.audit_jobs', current_schema());
                END IF;
            END
            $$;
            """
        )
    )


def _create_audit_jobs_table() -> None:
    op.create_table(
        "audit_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("audit_jobs"):
        try:
            _create_audit_jobs_table()
        except sa.exc.IntegrityError as exc:
            if "pg_type_typname_nsp_index" not in str(getattr(exc, "orig", exc)):
                raise
            _drop_orphan_audit_jobs_type(bind)
            _create_audit_jobs_table()

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("audit_jobs")}
    if "ix_audit_jobs_id" not in existing_indexes:
        op.create_index("ix_audit_jobs_id", "audit_jobs", ["id"], unique=False)
    if "ix_audit_jobs_user_id" not in existing_indexes:
        op.create_index("ix_audit_jobs_user_id", "audit_jobs", ["user_id"], unique=False)
    if "ix_audit_jobs_status" not in existing_indexes:
        op.create_index("ix_audit_jobs_status", "audit_jobs", ["status"], unique=False)
    if "ix_audit_jobs_request_id" not in existing_indexes:
        op.create_index("ix_audit_jobs_request_id", "audit_jobs", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_jobs_request_id", table_name="audit_jobs", if_exists=True)
    op.drop_index("ix_audit_jobs_status", table_name="audit_jobs", if_exists=True)
    op.drop_index("ix_audit_jobs_user_id", table_name="audit_jobs", if_exists=True)
    op.drop_index("ix_audit_jobs_id", table_name="audit_jobs", if_exists=True)
    op.drop_table("audit_jobs", if_exists=True)
