"""Add complex_report_jobs table.

Revision ID: 20250303_120000
Revises: 20250302_120000
Create Date: 2025-03-03 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250303_120000"
down_revision = "20250302_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("complex_report_jobs"):
        op.create_table(
            "complex_report_jobs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("file_path", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("complex_report_jobs")}
    if "ix_complex_report_jobs_id" not in existing_indexes:
        op.create_index("ix_complex_report_jobs_id", "complex_report_jobs", ["id"], unique=False)
    if "ix_complex_report_jobs_status" not in existing_indexes:
        op.create_index(
            "ix_complex_report_jobs_status", "complex_report_jobs", ["status"], unique=False
        )
    if "ix_complex_report_jobs_user_id" not in existing_indexes:
        op.create_index(
            "ix_complex_report_jobs_user_id", "complex_report_jobs", ["user_id"], unique=False
        )


def downgrade() -> None:
    op.drop_index(
        "ix_complex_report_jobs_user_id", table_name="complex_report_jobs", if_exists=True
    )
    op.drop_index("ix_complex_report_jobs_status", table_name="complex_report_jobs", if_exists=True)
    op.drop_index("ix_complex_report_jobs_id", table_name="complex_report_jobs", if_exists=True)
    op.drop_table("complex_report_jobs", if_exists=True)
