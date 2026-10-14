"""Add content_briefs table

Revision ID: 20260305_130000
Revises: 20260305_120000
Create Date: 2026-03-05 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_130000"
down_revision = "20260305_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_briefs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "audit_id",
            sa.Integer(),
            sa.ForeignKey("audits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("target_query", sa.String(), nullable=True),
        sa.Column("recommendation_index", sa.Integer(), nullable=True),
        sa.Column("content_structure", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("entity_requirements", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("schema_markup", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("competitive_edge", sa.Text(), nullable=True),
        sa.Column("generation_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("credits_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
        sa.Column("export_format", sa.String(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_content_briefs_id", "content_briefs", ["id"], unique=False)
    op.create_index("ix_content_briefs_project_id", "content_briefs", ["project_id"], unique=False)
    op.create_index("ix_content_briefs_audit_id", "content_briefs", ["audit_id"], unique=False)
    op.create_index("ix_content_briefs_user_id", "content_briefs", ["user_id"], unique=False)
    op.create_index("ix_content_briefs_status", "content_briefs", ["status"], unique=False)
    op.create_index(
        "ix_content_briefs_project_status_created",
        "content_briefs",
        ["project_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_content_briefs_project_audit",
        "content_briefs",
        ["project_id", "audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_briefs_user_created",
        "content_briefs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_briefs_user_created", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_audit", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_status_created", table_name="content_briefs")
    op.drop_index("ix_content_briefs_status", table_name="content_briefs")
    op.drop_index("ix_content_briefs_user_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_audit_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_id", table_name="content_briefs")
    op.drop_table("content_briefs")
