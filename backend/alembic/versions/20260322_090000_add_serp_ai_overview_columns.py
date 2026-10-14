"""add SERP AI overview tracking columns

Revision ID: 20260322_090000
Revises: 20260322_080000
Create Date: 2026-03-22 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260322_090000"
down_revision = "20260322_080000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "serp_tracking_snapshots",
        sa.Column("ai_overview_detected", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "serp_tracking_snapshots",
        sa.Column("ai_overview_cites_target", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "serp_tracking_snapshots",
        sa.Column("ai_overview_source_urls", sa.JSON(), nullable=True),
    )
    op.add_column(
        "serp_tracking_snapshots",
        sa.Column("ai_overview_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("serp_tracking_snapshots", "ai_overview_text")
    op.drop_column("serp_tracking_snapshots", "ai_overview_source_urls")
    op.drop_column("serp_tracking_snapshots", "ai_overview_cites_target")
    op.drop_column("serp_tracking_snapshots", "ai_overview_detected")
