"""Add verified outbound-link state on project_off_page_mentions (SIGV2-1008).

Additive only: ``link_state`` defaults to "unknown" (never checked, fetch
failed or restricted pages are NOT reclaimable), plus ``link_checked_at``
and a ``link_evidence`` JSON payload carrying fetch outcome, brand-match and
matched target URLs for provenance.

Revision ID: 20261006_010000
Revises: 20261004_010000
Create Date: 2026-10-06 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261006_010000"
down_revision = "20261005_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("project_off_page_mentions")}
    if "link_state" not in columns:
        op.add_column(
            "project_off_page_mentions",
            sa.Column(
                "link_state",
                sa.String(),
                nullable=False,
                server_default="unknown",
            ),
        )
    if "link_checked_at" not in columns:
        op.add_column(
            "project_off_page_mentions",
            sa.Column("link_checked_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "link_evidence" not in columns:
        op.add_column(
            "project_off_page_mentions",
            sa.Column("link_evidence", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("project_off_page_mentions")}
    if "link_evidence" in columns:
        op.drop_column("project_off_page_mentions", "link_evidence")
    if "link_checked_at" in columns:
        op.drop_column("project_off_page_mentions", "link_checked_at")
    if "link_state" in columns:
        op.drop_column("project_off_page_mentions", "link_state")
