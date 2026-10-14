"""Add embed widget lead capture and sitemap crawl tables

Revision ID: 20260305_150000
Revises: 20260305_140000
Create Date: 2026-03-05 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260305_150000"
down_revision = "20260305_140000"
branch_labels = None
depends_on = None

STRING_ARRAY_TYPE = postgresql.ARRAY(sa.String()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "embed_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(), nullable=False, server_default="stx_embed_"),
        sa.Column("key_last_four", sa.String(), nullable=True),
        sa.Column("allowed_origins", STRING_ARRAY_TYPE, nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index("ix_embed_api_keys_id", "embed_api_keys", ["id"], unique=False)
    op.create_index(
        "ix_embed_api_keys_workspace_id", "embed_api_keys", ["workspace_id"], unique=False
    )
    op.create_index("ix_embed_api_keys_user_id", "embed_api_keys", ["user_id"], unique=False)
    op.create_index("ix_embed_api_keys_key_hash", "embed_api_keys", ["key_hash"], unique=True)
    op.create_index(
        "ix_embed_api_keys_workspace_active",
        "embed_api_keys",
        ["workspace_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "sitemap_crawl_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sitemap_url", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="parsing"),
        sa.Column("total_urls", sa.Integer(), nullable=True),
        sa.Column("completed_urls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_urls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aggregated_scores_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credits_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index("ix_sitemap_crawl_jobs_id", "sitemap_crawl_jobs", ["id"], unique=False)
    op.create_index(
        "ix_sitemap_crawl_jobs_project_id",
        "sitemap_crawl_jobs",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_sitemap_crawl_jobs_user_id",
        "sitemap_crawl_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_sitemap_crawl_jobs_status",
        "sitemap_crawl_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_sitemap_crawl_jobs_project_status_created",
        "sitemap_crawl_jobs",
        ["project_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "embed_key_id",
            sa.Integer(),
            sa.ForeignKey("embed_api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=True),
        sa.Column(
            "audit_job_id",
            sa.String(),
            sa.ForeignKey("audit_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="widget"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index("ix_leads_id", "leads", ["id"], unique=False)
    op.create_index("ix_leads_workspace_id", "leads", ["workspace_id"], unique=False)
    op.create_index("ix_leads_embed_key_id", "leads", ["embed_key_id"], unique=False)
    op.create_index("ix_leads_email", "leads", ["email"], unique=False)
    op.create_index("ix_leads_status", "leads", ["status"], unique=False)
    op.create_index("ix_leads_audit_job_id", "leads", ["audit_job_id"], unique=False)
    op.create_index(
        "ix_leads_workspace_status_created",
        "leads",
        ["workspace_id", "status", "created_at"],
        unique=False,
    )

    op.add_column("audit_jobs", sa.Column("embed_api_key_id", sa.Integer(), nullable=True))
    op.add_column("audit_jobs", sa.Column("sitemap_crawl_job_id", sa.String(), nullable=True))
    op.create_index(
        "ix_audit_jobs_embed_api_key_id", "audit_jobs", ["embed_api_key_id"], unique=False
    )
    op.create_index(
        "ix_audit_jobs_sitemap_crawl_job_id", "audit_jobs", ["sitemap_crawl_job_id"], unique=False
    )
    op.create_foreign_key(
        "fk_audit_jobs_embed_api_key_id",
        "audit_jobs",
        "embed_api_keys",
        ["embed_api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_audit_jobs_sitemap_crawl_job_id",
        "audit_jobs",
        "sitemap_crawl_jobs",
        ["sitemap_crawl_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_audit_jobs_sitemap_crawl_job_id", "audit_jobs", type_="foreignkey")
    op.drop_constraint("fk_audit_jobs_embed_api_key_id", "audit_jobs", type_="foreignkey")
    op.drop_index("ix_audit_jobs_sitemap_crawl_job_id", table_name="audit_jobs")
    op.drop_index("ix_audit_jobs_embed_api_key_id", table_name="audit_jobs")
    op.drop_column("audit_jobs", "sitemap_crawl_job_id")
    op.drop_column("audit_jobs", "embed_api_key_id")

    op.drop_index("ix_leads_workspace_status_created", table_name="leads")
    op.drop_index("ix_leads_audit_job_id", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_email", table_name="leads")
    op.drop_index("ix_leads_embed_key_id", table_name="leads")
    op.drop_index("ix_leads_workspace_id", table_name="leads")
    op.drop_index("ix_leads_id", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_sitemap_crawl_jobs_project_status_created", table_name="sitemap_crawl_jobs")
    op.drop_index("ix_sitemap_crawl_jobs_status", table_name="sitemap_crawl_jobs")
    op.drop_index("ix_sitemap_crawl_jobs_user_id", table_name="sitemap_crawl_jobs")
    op.drop_index("ix_sitemap_crawl_jobs_project_id", table_name="sitemap_crawl_jobs")
    op.drop_index("ix_sitemap_crawl_jobs_id", table_name="sitemap_crawl_jobs")
    op.drop_table("sitemap_crawl_jobs")

    op.drop_index("ix_embed_api_keys_workspace_active", table_name="embed_api_keys")
    op.drop_index("ix_embed_api_keys_key_hash", table_name="embed_api_keys")
    op.drop_index("ix_embed_api_keys_user_id", table_name="embed_api_keys")
    op.drop_index("ix_embed_api_keys_workspace_id", table_name="embed_api_keys")
    op.drop_index("ix_embed_api_keys_id", table_name="embed_api_keys")
    op.drop_table("embed_api_keys")
