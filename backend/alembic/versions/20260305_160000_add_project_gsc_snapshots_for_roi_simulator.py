"""Add project GSC snapshots for ROI simulator

Revision ID: 20260305_160000
Revises: 20260305_150000
Create Date: 2026-03-05 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_160000"
down_revision = "20260305_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_gsc_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("average_position", sa.Float(), nullable=True),
        sa.Column("conversions", sa.Float(), nullable=True),
        sa.Column("conversion_value", sa.Float(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
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
            "project_id",
            "snapshot_date",
            name="uq_project_gsc_snapshots_project_date",
        ),
    )
    op.create_index("ix_project_gsc_snapshots_id", "project_gsc_snapshots", ["id"], unique=False)
    op.create_index(
        "ix_project_gsc_snapshots_project_id",
        "project_gsc_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_gsc_snapshots_project_date",
        "project_gsc_snapshots",
        ["project_id", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_gsc_snapshots_project_date", table_name="project_gsc_snapshots")
    op.drop_index("ix_project_gsc_snapshots_project_id", table_name="project_gsc_snapshots")
    op.drop_index("ix_project_gsc_snapshots_id", table_name="project_gsc_snapshots")
    op.drop_table("project_gsc_snapshots")
