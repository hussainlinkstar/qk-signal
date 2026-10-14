"""add project progress reports

Revision ID: 20260302_210000
Revises: 20260302_190000
Create Date: 2026-03-02 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260302_210000"
down_revision = "20260302_190000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_progress_reports" in table_names:
        return

    op.create_table(
        "project_progress_reports",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("report_month", sa.Date(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("generated_by", sa.String(), nullable=False, server_default="manual"),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id", "report_month", name="uq_project_progress_reports_project_month"
        ),
    )
    op.create_index(
        "ix_project_progress_reports_id", "project_progress_reports", ["id"], unique=False
    )
    op.create_index(
        "ix_project_progress_reports_project_month",
        "project_progress_reports",
        ["project_id", "report_month"],
        unique=False,
    )
    op.create_index(
        "ix_project_progress_reports_workspace_month",
        "project_progress_reports",
        ["workspace_id", "report_month"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_progress_reports" not in table_names:
        return

    op.drop_index(
        "ix_project_progress_reports_workspace_month", table_name="project_progress_reports"
    )
    op.drop_index(
        "ix_project_progress_reports_project_month", table_name="project_progress_reports"
    )
    op.drop_index("ix_project_progress_reports_id", table_name="project_progress_reports")
    op.drop_table("project_progress_reports")
