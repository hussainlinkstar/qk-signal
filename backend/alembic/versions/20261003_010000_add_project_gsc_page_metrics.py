"""Add project_gsc_page_metrics table (SIGV2-1025).

Revision ID: 20261003_010000
Revises: 20261002_010000
Create Date: 2026-10-03 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261003_010000"
down_revision = "20261002_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_gsc_page_metrics" in inspector.get_table_names():
        return
    op.create_table(
        "project_gsc_page_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("property", sa.String(), nullable=False),
        sa.Column("page", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("is_incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "project_id",
            "property",
            "page",
            "date",
            name="uq_project_gsc_page_metrics_grain",
        ),
        sa.Index("ix_project_gsc_page_metrics_project_date", "project_id", "date"),
    )
    op.create_index(
        "ix_project_gsc_page_metrics_project_id",
        "project_gsc_page_metrics",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_table("project_gsc_page_metrics")
