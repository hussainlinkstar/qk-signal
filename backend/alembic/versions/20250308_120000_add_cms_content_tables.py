"""Add CMS articles and case studies tables.

Revision ID: 20250308_120000
Revises: 20250307_120000
Create Date: 2025-03-08 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250308_120000"
down_revision = "20250307_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("cms_articles"):
        # Some environments may be left with an orphan serial sequence from a failed
        # prior migration attempt. Drop it defensively before creating the table.
        op.execute(sa.text("DROP SEQUENCE IF EXISTS cms_articles_id_seq CASCADE"))
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
        # Same defensive cleanup for case-studies serial sequence.
        op.execute(sa.text("DROP SEQUENCE IF EXISTS cms_case_studies_id_seq CASCADE"))
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
        op.create_index("ix_cms_case_studies_slug", "cms_case_studies", ["slug"])
        op.create_index("ix_cms_case_studies_industry", "cms_case_studies", ["industry"])
        op.create_index(
            "ix_cms_case_studies_is_published_published_at",
            "cms_case_studies",
            ["is_published", "published_at"],
        )
        op.create_index("ix_cms_case_studies_published_at", "cms_case_studies", ["published_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("cms_case_studies"):
        op.drop_index(
            "ix_cms_case_studies_published_at",
            table_name="cms_case_studies",
            if_exists=True,
        )
        op.drop_index(
            "ix_cms_case_studies_is_published_published_at",
            table_name="cms_case_studies",
            if_exists=True,
        )
        op.drop_index(
            "ix_cms_case_studies_industry",
            table_name="cms_case_studies",
            if_exists=True,
        )
        op.drop_index("ix_cms_case_studies_slug", table_name="cms_case_studies", if_exists=True)
        op.drop_table("cms_case_studies")

    if inspector.has_table("cms_articles"):
        op.drop_index("ix_cms_articles_published_at", table_name="cms_articles", if_exists=True)
        op.drop_index(
            "ix_cms_articles_is_published_published_at",
            table_name="cms_articles",
            if_exists=True,
        )
        op.drop_index("ix_cms_articles_category", table_name="cms_articles", if_exists=True)
        op.drop_index("ix_cms_articles_slug", table_name="cms_articles", if_exists=True)
        op.drop_table("cms_articles")
