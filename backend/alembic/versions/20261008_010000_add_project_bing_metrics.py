"""Add project_bing_metrics table (SIGV2-1082).

Revision ID: 20261008_010000
Revises: 20261007_010000
Create Date: 2026-10-08 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261008_010000"
down_revision = "20261007_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_bing_metrics" in inspector.get_table_names():
        return
    op.create_table(
        "project_bing_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("site_url", sa.String(), nullable=False),
        sa.Column("dimension_type", sa.String(), nullable=False),
        sa.Column("dimension", sa.String(), nullable=False, server_default=""),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_click_position_raw", sa.Integer(), nullable=True),
        sa.Column("avg_impression_position_raw", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "project_id",
            "site_url",
            "dimension_type",
            "dimension",
            "date",
            name="uq_project_bing_metrics_grain",
        ),
        sa.Index("ix_project_bing_metrics_project_date", "project_id", "date"),
    )
    op.create_index(
        "ix_project_bing_metrics_project_id",
        "project_bing_metrics",
        ["project_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_bing_metrics" not in inspector.get_table_names():
        return
    op.drop_index("ix_project_bing_metrics_project_id", table_name="project_bing_metrics")
    op.drop_table("project_bing_metrics")
