"""Add project visibility monitoring tables and batch scoping

Revision ID: 20260304_100000
Revises: 20260304_090000
Create Date: 2026-03-04 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260304_100000"
down_revision = "20260304_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_visibility_queries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.String(), nullable=False),
        sa.Column("query_type", sa.String(), nullable=False, server_default="aeo"),
        sa.Column("providers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id",
            "query_text",
            name="uq_project_visibility_queries_project_query",
        ),
    )
    op.create_index(
        "ix_project_visibility_queries_project_id",
        "project_visibility_queries",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_visibility_queries_project_active",
        "project_visibility_queries",
        ["project_id", "is_active"],
        unique=False,
    )

    op.add_column(
        "visibility_run_batches",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_visibility_run_batches_project_id",
        "visibility_run_batches",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_visibility_run_batches_project_topic_provider_created",
        "visibility_run_batches",
        ["project_id", "topic", "provider", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_visibility_run_batches_project_topic_provider_created",
        table_name="visibility_run_batches",
    )
    op.drop_index(
        "ix_visibility_run_batches_project_id",
        table_name="visibility_run_batches",
    )
    op.drop_column("visibility_run_batches", "project_id")

    op.drop_index(
        "ix_project_visibility_queries_project_active",
        table_name="project_visibility_queries",
    )
    op.drop_index(
        "ix_project_visibility_queries_project_id",
        table_name="project_visibility_queries",
    )
    op.drop_table("project_visibility_queries")
