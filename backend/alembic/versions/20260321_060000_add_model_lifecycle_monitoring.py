"""Add model lifecycle monitoring tables

Revision ID: 20260321_060000
Revises: 20260318_010000
Create Date: 2026-03-21 06:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "20260321_060000"
down_revision = "20260318_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_lifecycle_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("page_type", sa.String(), nullable=False, server_default="deprecations"),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("extracted_models", sa.JSON(), nullable=True),
        sa.Column("raw_text_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_lifecycle_snapshots_id"), "model_lifecycle_snapshots", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_model_lifecycle_snapshots_provider"),
        "model_lifecycle_snapshots",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_model_lifecycle_snapshots_provider_source",
        "model_lifecycle_snapshots",
        ["provider", "source_url"],
        unique=False,
    )
    op.create_index(
        "ix_model_lifecycle_snapshots_fetched",
        "model_lifecycle_snapshots",
        ["fetched_at"],
        unique=False,
    )

    op.create_table(
        "model_lifecycle_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="warning"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("affected_models", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "acknowledged_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_lifecycle_alerts_id"), "model_lifecycle_alerts", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_model_lifecycle_alerts_status"), "model_lifecycle_alerts", ["status"], unique=False
    )
    op.create_index(
        "ix_model_lifecycle_alerts_status_created",
        "model_lifecycle_alerts",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_model_lifecycle_alerts_provider", "model_lifecycle_alerts", ["provider"], unique=False
    )
    op.create_index(
        op.f("ix_model_lifecycle_alerts_created_at"),
        "model_lifecycle_alerts",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_lifecycle_alerts_created_at"), table_name="model_lifecycle_alerts")
    op.drop_index("ix_model_lifecycle_alerts_provider", table_name="model_lifecycle_alerts")
    op.drop_index("ix_model_lifecycle_alerts_status_created", table_name="model_lifecycle_alerts")
    op.drop_index(op.f("ix_model_lifecycle_alerts_status"), table_name="model_lifecycle_alerts")
    op.drop_index(op.f("ix_model_lifecycle_alerts_id"), table_name="model_lifecycle_alerts")
    op.drop_table("model_lifecycle_alerts")

    op.drop_index("ix_model_lifecycle_snapshots_fetched", table_name="model_lifecycle_snapshots")
    op.drop_index(
        "ix_model_lifecycle_snapshots_provider_source", table_name="model_lifecycle_snapshots"
    )
    op.drop_index(
        op.f("ix_model_lifecycle_snapshots_provider"), table_name="model_lifecycle_snapshots"
    )
    op.drop_index(op.f("ix_model_lifecycle_snapshots_id"), table_name="model_lifecycle_snapshots")
    op.drop_table("model_lifecycle_snapshots")
