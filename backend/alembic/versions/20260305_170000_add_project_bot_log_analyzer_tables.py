"""Add project bot log analyzer tables

Revision ID: 20260305_170000
Revises: 20260305_160000
Create Date: 2026-03-05 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_170000"
down_revision = "20260305_160000"
branch_labels = None
depends_on = None


bot_log_ingestion_source_type = sa.Enum(
    "MANUAL_UPLOAD",
    "CLOUDFLARE_LOGPUSH",
    "AWS_S3",
    "GCP_CLOUD_STORAGE",
    name="bot_log_ingestion_source_type",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "project_bot_log_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", bot_log_ingestion_source_type, nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id", "source_type", name="uq_project_bot_log_sources_project_source"
        ),
    )
    op.create_index(
        "ix_project_bot_log_sources_id", "project_bot_log_sources", ["id"], unique=False
    )
    op.create_index(
        "ix_project_bot_log_sources_project_id",
        "project_bot_log_sources",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_sources_project_active",
        "project_bot_log_sources",
        ["project_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "project_bot_log_uploads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("project_bot_log_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_type",
            bot_log_ingestion_source_type,
            nullable=False,
            server_default="MANUAL_UPLOAD",
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="processing"),
        sa.Column("bytes_processed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lines_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bot_hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_project_bot_log_uploads_id", "project_bot_log_uploads", ["id"], unique=False
    )
    op.create_index(
        "ix_project_bot_log_uploads_project_id",
        "project_bot_log_uploads",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_uploads_source_id",
        "project_bot_log_uploads",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_uploads_project_uploaded",
        "project_bot_log_uploads",
        ["project_id", "uploaded_at"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_uploads_project_status",
        "project_bot_log_uploads",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "project_bot_log_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "upload_id",
            sa.Integer(),
            sa.ForeignKey("project_bot_log_uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            bot_log_ingestion_source_type,
            nullable=False,
            server_default="MANUAL_UPLOAD",
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("bot_name", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("status_class", sa.String(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_ips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "upload_id",
            "snapshot_date",
            "bot_name",
            "section",
            "status_class",
            "is_verified",
            name="uq_project_bot_log_aggregates_upload_dimension",
        ),
    )
    op.create_index(
        "ix_project_bot_log_aggregates_id", "project_bot_log_aggregates", ["id"], unique=False
    )
    op.create_index(
        "ix_project_bot_log_aggregates_project_id",
        "project_bot_log_aggregates",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_aggregates_upload_id",
        "project_bot_log_aggregates",
        ["upload_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_aggregates_project_date",
        "project_bot_log_aggregates",
        ["project_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_aggregates_project_bot",
        "project_bot_log_aggregates",
        ["project_id", "bot_name"],
        unique=False,
    )

    op.create_table(
        "project_bot_log_daily_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            bot_log_ingestion_source_type,
            nullable=False,
            server_default="MANUAL_UPLOAD",
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("bot_name", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("status_class", sa.String(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_ips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id",
            "source_type",
            "snapshot_date",
            "bot_name",
            "section",
            "status_class",
            "is_verified",
            name="uq_project_bot_log_daily_summaries_dimension",
        ),
    )
    op.create_index(
        "ix_project_bot_log_daily_summaries_id",
        "project_bot_log_daily_summaries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_daily_summaries_project_id",
        "project_bot_log_daily_summaries",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_daily_summaries_project_date",
        "project_bot_log_daily_summaries",
        ["project_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_project_bot_log_daily_summaries_project_bot",
        "project_bot_log_daily_summaries",
        ["project_id", "bot_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_bot_log_daily_summaries_project_bot",
        table_name="project_bot_log_daily_summaries",
    )
    op.drop_index(
        "ix_project_bot_log_daily_summaries_project_date",
        table_name="project_bot_log_daily_summaries",
    )
    op.drop_index(
        "ix_project_bot_log_daily_summaries_project_id",
        table_name="project_bot_log_daily_summaries",
    )
    op.drop_index(
        "ix_project_bot_log_daily_summaries_id", table_name="project_bot_log_daily_summaries"
    )
    op.drop_table("project_bot_log_daily_summaries")

    op.drop_index(
        "ix_project_bot_log_aggregates_project_bot", table_name="project_bot_log_aggregates"
    )
    op.drop_index(
        "ix_project_bot_log_aggregates_project_date", table_name="project_bot_log_aggregates"
    )
    op.drop_index(
        "ix_project_bot_log_aggregates_upload_id", table_name="project_bot_log_aggregates"
    )
    op.drop_index(
        "ix_project_bot_log_aggregates_project_id", table_name="project_bot_log_aggregates"
    )
    op.drop_index("ix_project_bot_log_aggregates_id", table_name="project_bot_log_aggregates")
    op.drop_table("project_bot_log_aggregates")

    op.drop_index("ix_project_bot_log_uploads_project_status", table_name="project_bot_log_uploads")
    op.drop_index(
        "ix_project_bot_log_uploads_project_uploaded", table_name="project_bot_log_uploads"
    )
    op.drop_index("ix_project_bot_log_uploads_source_id", table_name="project_bot_log_uploads")
    op.drop_index("ix_project_bot_log_uploads_project_id", table_name="project_bot_log_uploads")
    op.drop_index("ix_project_bot_log_uploads_id", table_name="project_bot_log_uploads")
    op.drop_table("project_bot_log_uploads")

    op.drop_index("ix_project_bot_log_sources_project_active", table_name="project_bot_log_sources")
    op.drop_index("ix_project_bot_log_sources_project_id", table_name="project_bot_log_sources")
    op.drop_index("ix_project_bot_log_sources_id", table_name="project_bot_log_sources")
    op.drop_table("project_bot_log_sources")
