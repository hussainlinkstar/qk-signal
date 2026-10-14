"""Add audit target contract fields for website and brand audits.

Revision ID: 20260306_170000
Revises: 20260306_140000
Create Date: 2026-03-06 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_170000"
down_revision = "20260306_140000"
branch_labels = None
depends_on = None


AUDIT_TARGET_TYPE_ENUM = sa.Enum(
    "website",
    "brand",
    name="audit_target_type",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "audits",
        sa.Column(
            "audit_target_type",
            AUDIT_TARGET_TYPE_ENUM,
            nullable=False,
            server_default="website",
        ),
    )
    op.add_column("audits", sa.Column("target_name", sa.String(), nullable=True))
    op.add_column("audits", sa.Column("target_url", sa.String(), nullable=True))
    op.add_column(
        "audits",
        sa.Column("target_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.add_column(
        "audit_jobs",
        sa.Column(
            "audit_target_type",
            AUDIT_TARGET_TYPE_ENUM,
            nullable=False,
            server_default="website",
        ),
    )
    op.add_column("audit_jobs", sa.Column("target_name", sa.String(), nullable=True))
    op.add_column("audit_jobs", sa.Column("target_url", sa.String(), nullable=True))
    op.add_column(
        "audit_jobs",
        sa.Column("target_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.execute("UPDATE audits SET target_url = url WHERE target_url IS NULL")
    op.execute("UPDATE audits SET target_name = url WHERE target_name IS NULL")
    op.execute("UPDATE audit_jobs SET target_url = url WHERE target_url IS NULL")
    op.execute("UPDATE audit_jobs SET target_name = url WHERE target_name IS NULL")

    op.create_index("ix_audits_audit_target_type", "audits", ["audit_target_type"], unique=False)
    op.create_index(
        "ix_audits_target_type_created_at",
        "audits",
        ["audit_target_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_jobs_audit_target_type", "audit_jobs", ["audit_target_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_jobs_audit_target_type", table_name="audit_jobs")
    op.drop_index("ix_audits_target_type_created_at", table_name="audits")
    op.drop_index("ix_audits_audit_target_type", table_name="audits")

    op.drop_column("audit_jobs", "target_metadata")
    op.drop_column("audit_jobs", "target_url")
    op.drop_column("audit_jobs", "target_name")
    op.drop_column("audit_jobs", "audit_target_type")

    op.drop_column("audits", "target_metadata")
    op.drop_column("audits", "target_url")
    op.drop_column("audits", "target_name")
    op.drop_column("audits", "audit_target_type")
