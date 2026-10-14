"""Drop the CMS articles and case studies tables.

Revision ID: 20260922_010000
Revises: 20260731_010000
Create Date: 2026-09-22 01:00:00.000000

The blog (cms_articles) and case studies (cms_case_studies) marketing pages were
retired from qiko-signal in favour of qiko-website-v2 owning that content going
forward, once a business decision on what replaces them is made (see WEB-1008).
Their routers, admin CRUD endpoints, admin UI and ORM models are already removed
from the codebase; this migration removes the now-unused tables themselves.

This is a destructive migration: any stored articles or case studies are
permanently lost, and downgrade() only restores the empty table structure, not
the data. Per qiko-signal/AGENTS.md's danger zone rule, DROP TABLE requires
explicit human approval before this is ever run against a real database, and
that has not happened yet as of this revision being written. Do not run
`alembic upgrade head` against any shared database until that approval is
given and a backup is confirmed.

Unrelated to services/cms_fix_delivery_service.py, services/cms_adapters/, or
the cms_connections / cms_deployment_logs tables, which are the WordPress/
Shopify fix-delivery feature and are not touched by this migration.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260922_010000"
down_revision = "20260731_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("cms_case_studies"):
        op.drop_table("cms_case_studies")

    if inspector.has_table("cms_articles"):
        op.drop_table("cms_articles")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("cms_articles"):
        op.create_table(
            "cms_articles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("excerpt", sa.Text(), nullable=False),
            sa.Column("body_markdown", sa.Text(), nullable=False),
            sa.Column("featured_image_url", sa.Text(), nullable=True),
            sa.Column("featured_image_alt", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=False, server_default="Insights"),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("seo_title", sa.String(), nullable=True),
            sa.Column("seo_description", sa.Text(), nullable=True),
            sa.Column("canonical_url", sa.String(), nullable=True),
            sa.Column(
                "author_name",
                sa.String(),
                nullable=False,
                server_default="Qiko Signal Research",
            ),
            sa.Column("reading_time_minutes", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_cms_articles_slug", "cms_articles", ["slug"])
        op.create_index("ix_cms_articles_category", "cms_articles", ["category"])
        op.create_index(
            "ix_cms_articles_is_published_published_at",
            "cms_articles",
            ["is_published", "published_at"],
        )
        op.create_index("ix_cms_articles_published_at", "cms_articles", ["published_at"])

    if not inspector.has_table("cms_case_studies"):
        op.create_table(
            "cms_case_studies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("industry", sa.String(), nullable=True),
            sa.Column("client_name", sa.String(), nullable=True),
            sa.Column("challenge_markdown", sa.Text(), nullable=False, server_default=""),
            sa.Column("solution_markdown", sa.Text(), nullable=False, server_default=""),
            sa.Column("results_markdown", sa.Text(), nullable=False, server_default=""),
            sa.Column("featured_image_url", sa.Text(), nullable=True),
            sa.Column("featured_image_alt", sa.String(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("seo_title", sa.String(), nullable=True),
            sa.Column("seo_description", sa.Text(), nullable=True),
            sa.Column("canonical_url", sa.String(), nullable=True),
            sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_project_id", sa.Integer(), nullable=True),
            sa.Column("anonymization_level", sa.String(), nullable=True, server_default="full"),
            sa.Column(
                "ai_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("generation_prompt_hash", sa.String(), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["source_project_id"],
                ["projects.id"],
                ondelete="SET NULL",
                name="fk_cms_case_studies_source_project",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_cms_case_studies_slug", "cms_case_studies", ["slug"])
        op.create_index("ix_cms_case_studies_industry", "cms_case_studies", ["industry"])
        op.create_index(
            "ix_cms_case_studies_is_published_published_at",
            "cms_case_studies",
            ["is_published", "published_at"],
        )
        op.create_index("ix_cms_case_studies_published_at", "cms_case_studies", ["published_at"])
        op.create_index(
            "ix_cms_case_studies_source_project_id", "cms_case_studies", ["source_project_id"]
        )
