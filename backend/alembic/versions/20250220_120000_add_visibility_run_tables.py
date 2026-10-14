"""Add visibility run batch and run artifact tables.

Revision ID: 20250220_120000
Revises: 20250219_120000
Create Date: 2025-02-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20250220_120000"
down_revision = "20250219_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visibility_run_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("schedule_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_visibility_run_batches_topic", "visibility_run_batches", ["topic"])
    op.create_index("ix_visibility_run_batches_provider", "visibility_run_batches", ["provider"])
    op.create_index(
        "ix_visibility_run_batches_schedule_key", "visibility_run_batches", ["schedule_key"]
    )
    op.create_index("ix_visibility_run_batches_status", "visibility_run_batches", ["status"])
    op.create_index(
        "ix_visibility_run_batches_topic_provider_created",
        "visibility_run_batches",
        ["topic", "provider", "created_at"],
    )

    op.create_table(
        "visibility_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("visibility_run_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("prompt_template", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("parsed_citations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("valid_citations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_visibility_runs_batch_id", "visibility_runs", ["batch_id"])
    op.create_index("ix_visibility_runs_topic", "visibility_runs", ["topic"])
    op.create_index("ix_visibility_runs_provider", "visibility_runs", ["provider"])
    op.create_index("ix_visibility_runs_status", "visibility_runs", ["status"])
    op.create_index(
        "ix_visibility_runs_batch_created", "visibility_runs", ["batch_id", "created_at"]
    )
    op.create_index(
        "ix_visibility_runs_topic_provider_created",
        "visibility_runs",
        ["topic", "provider", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_visibility_runs_topic_provider_created", table_name="visibility_runs")
    op.drop_index("ix_visibility_runs_batch_created", table_name="visibility_runs")
    op.drop_index("ix_visibility_runs_status", table_name="visibility_runs")
    op.drop_index("ix_visibility_runs_provider", table_name="visibility_runs")
    op.drop_index("ix_visibility_runs_topic", table_name="visibility_runs")
    op.drop_index("ix_visibility_runs_batch_id", table_name="visibility_runs")
    op.drop_table("visibility_runs")

    op.drop_index(
        "ix_visibility_run_batches_topic_provider_created", table_name="visibility_run_batches"
    )
    op.drop_index("ix_visibility_run_batches_status", table_name="visibility_run_batches")
    op.drop_index("ix_visibility_run_batches_schedule_key", table_name="visibility_run_batches")
    op.drop_index("ix_visibility_run_batches_provider", table_name="visibility_run_batches")
    op.drop_index("ix_visibility_run_batches_topic", table_name="visibility_run_batches")
    op.drop_table("visibility_run_batches")
