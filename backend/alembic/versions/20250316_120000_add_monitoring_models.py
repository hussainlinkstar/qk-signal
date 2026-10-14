"""Add continuous monitoring models.

Creates tables for GEO LLM referral traffic detection (GA4) and
AEO Featured Snippet / PAA tracking (DataForSEO).

Revision ID: 20250316_120000
Revises: 20250315_120000
Create Date: 2025-03-16 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250316_120000"
down_revision = "20250315_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ----------------------------------------------------------------
    # project_ga4_configs
    # ----------------------------------------------------------------
    if not inspector.has_table("project_ga4_configs"):
        op.create_table(
            "project_ga4_configs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("ga4_property_id", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", name="uq_project_ga4_configs_project"),
        )
        op.create_index("ix_project_ga4_configs_id", "project_ga4_configs", ["id"], unique=False)
        op.create_index(
            "ix_project_ga4_configs_project_id", "project_ga4_configs", ["project_id"], unique=True
        )

    # Refresh inspector after table creation
    inspector = sa.inspect(bind)

    # ----------------------------------------------------------------
    # llm_traffic_snapshots
    # ----------------------------------------------------------------
    if not inspector.has_table("llm_traffic_snapshots"):
        op.create_table(
            "llm_traffic_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("users", sa.Integer(), nullable=True),
            sa.Column("page_views", sa.Integer(), nullable=True),
            sa.Column("avg_session_duration_seconds", sa.Float(), nullable=True),
            sa.Column("bounce_rate", sa.Float(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "source",
                "snapshot_date",
                name="uq_llm_traffic_snapshots_project_source_date",
            ),
        )
        op.create_index(
            "ix_llm_traffic_snapshots_id", "llm_traffic_snapshots", ["id"], unique=False
        )
        op.create_index(
            "ix_llm_traffic_snapshots_project_id",
            "llm_traffic_snapshots",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_llm_traffic_snapshots_project_date",
            "llm_traffic_snapshots",
            ["project_id", "snapshot_date"],
            unique=False,
        )

    inspector = sa.inspect(bind)

    # ----------------------------------------------------------------
    # target_keywords
    # ----------------------------------------------------------------
    if not inspector.has_table("target_keywords"):
        op.create_table(
            "target_keywords",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("keyword", sa.String(), nullable=False),
            sa.Column("search_engine", sa.String(), nullable=False, server_default="google"),
            sa.Column("language_code", sa.String(), nullable=False, server_default="en"),
            sa.Column("location_code", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "keyword", name="uq_target_keywords_project_keyword"),
        )
        op.create_index("ix_target_keywords_id", "target_keywords", ["id"], unique=False)
        op.create_index(
            "ix_target_keywords_project_id", "target_keywords", ["project_id"], unique=False
        )
        op.create_index(
            "ix_target_keywords_project_active",
            "target_keywords",
            ["project_id", "is_active"],
            unique=False,
        )

    inspector = sa.inspect(bind)

    # ----------------------------------------------------------------
    # serp_tracking_snapshots
    # ----------------------------------------------------------------
    if not inspector.has_table("serp_tracking_snapshots"):
        op.create_table(
            "serp_tracking_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("keyword_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column(
                "owns_featured_snippet", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column("featured_snippet_url", sa.String(), nullable=True),
            sa.Column("featured_snippet_content", sa.Text(), nullable=True),
            sa.Column("paa_appearances", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("organic_position", sa.Integer(), nullable=True),
            sa.Column("serp_features_present", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("raw_response_hash", sa.String(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["keyword_id"], ["target_keywords.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "keyword_id", "snapshot_date", name="uq_serp_tracking_snapshots_keyword_date"
            ),
        )
        op.create_index(
            "ix_serp_tracking_snapshots_id", "serp_tracking_snapshots", ["id"], unique=False
        )
        op.create_index(
            "ix_serp_tracking_snapshots_keyword_id",
            "serp_tracking_snapshots",
            ["keyword_id"],
            unique=False,
        )
        op.create_index(
            "ix_serp_tracking_snapshots_project_id",
            "serp_tracking_snapshots",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_serp_tracking_snapshots_keyword_date",
            "serp_tracking_snapshots",
            ["keyword_id", "snapshot_date"],
            unique=False,
        )
        op.create_index(
            "ix_serp_tracking_snapshots_project_date",
            "serp_tracking_snapshots",
            ["project_id", "snapshot_date"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("serp_tracking_snapshots"):
        op.drop_table("serp_tracking_snapshots")

    if inspector.has_table("target_keywords"):
        op.drop_table("target_keywords")

    if inspector.has_table("llm_traffic_snapshots"):
        op.drop_table("llm_traffic_snapshots")

    if inspector.has_table("project_ga4_configs"):
        op.drop_table("project_ga4_configs")
