"""Add entity authority snapshots

Revision ID: 20260304_120000
Revises: 20260304_110000
Create Date: 2026-03-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260304_120000"
down_revision = "20260304_110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_authority_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("authority_score", sa.Float(), nullable=False),
        sa.Column("coverage_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("depth_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("consistency_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uniqueness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detected_entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computation_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_entity_authority_snapshots_project_id",
        "entity_authority_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_authority_snapshots_project_computed_at",
        "entity_authority_snapshots",
        ["project_id", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_authority_snapshots_project_computed_at",
        table_name="entity_authority_snapshots",
    )
    op.drop_index(
        "ix_entity_authority_snapshots_project_id",
        table_name="entity_authority_snapshots",
    )
    op.drop_table("entity_authority_snapshots")
