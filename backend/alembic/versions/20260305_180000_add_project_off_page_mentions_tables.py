"""Add project off-page mentions tables

Revision ID: 20260305_180000
Revises: 20260305_170000
Create Date: 2026-03-05 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_180000"
down_revision = "20260305_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_off_page_mentions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(), nullable=False, server_default="manual_import"),
        sa.Column("source_domain", sa.String(), nullable=True),
        sa.Column("mention_url", sa.String(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sentiment_label", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("linked_keywords", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("entities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("authority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("action_recommendation", sa.Text(), nullable=True),
        sa.Column("analysis_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("analysis_error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id",
            "fingerprint_hash",
            name="uq_project_off_page_mentions_project_fingerprint",
        ),
    )
    op.create_index(
        "ix_project_off_page_mentions_id", "project_off_page_mentions", ["id"], unique=False
    )
    op.create_index(
        "ix_project_off_page_mentions_project_id",
        "project_off_page_mentions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mentions_external_id",
        "project_off_page_mentions",
        ["external_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mentions_project_published",
        "project_off_page_mentions",
        ["project_id", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mentions_project_sentiment",
        "project_off_page_mentions",
        ["project_id", "sentiment_label"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mentions_project_domain",
        "project_off_page_mentions",
        ["project_id", "source_domain"],
        unique=False,
    )

    op.create_table(
        "project_off_page_mention_daily_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positive_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_domains", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_authority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("off_page_aeo_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("degraded_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id",
            "snapshot_date",
            name="uq_project_off_page_mention_daily_summaries_project_date",
        ),
    )
    op.create_index(
        "ix_project_off_page_mention_daily_summaries_id",
        "project_off_page_mention_daily_summaries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mention_daily_summaries_project_id",
        "project_off_page_mention_daily_summaries",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_off_page_mention_daily_summaries_project_date",
        "project_off_page_mention_daily_summaries",
        ["project_id", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_off_page_mention_daily_summaries_project_date",
        table_name="project_off_page_mention_daily_summaries",
    )
    op.drop_index(
        "ix_project_off_page_mention_daily_summaries_project_id",
        table_name="project_off_page_mention_daily_summaries",
    )
    op.drop_index(
        "ix_project_off_page_mention_daily_summaries_id",
        table_name="project_off_page_mention_daily_summaries",
    )
    op.drop_table("project_off_page_mention_daily_summaries")

    op.drop_index(
        "ix_project_off_page_mentions_project_domain", table_name="project_off_page_mentions"
    )
    op.drop_index(
        "ix_project_off_page_mentions_project_sentiment", table_name="project_off_page_mentions"
    )
    op.drop_index(
        "ix_project_off_page_mentions_project_published", table_name="project_off_page_mentions"
    )
    op.drop_index(
        "ix_project_off_page_mentions_external_id", table_name="project_off_page_mentions"
    )
    op.drop_index("ix_project_off_page_mentions_project_id", table_name="project_off_page_mentions")
    op.drop_index("ix_project_off_page_mentions_id", table_name="project_off_page_mentions")
    op.drop_table("project_off_page_mentions")
