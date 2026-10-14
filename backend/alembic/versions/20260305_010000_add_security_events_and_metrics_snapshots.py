"""Add security_events and metrics_snapshots tables

Revision ID: 20260305_010000
Revises: 20260304_220000
Create Date: 2026-03-05 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_010000"
down_revision = "20260304_220000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── security_events ───────────────────────────────────────────
    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_security_events_id", "security_events", ["id"], unique=False)
    op.create_index(
        "ix_security_events_event_type", "security_events", ["event_type"], unique=False
    )
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"], unique=False)
    op.create_index(
        "ix_security_events_created_at", "security_events", ["created_at"], unique=False
    )

    # ── metrics_snapshots ─────────────────────────────────────────
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requests_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_2xx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_4xx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_5xx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_p50_ms", sa.Float(), nullable=True),
        sa.Column("latency_p95_ms", sa.Float(), nullable=True),
        sa.Column("latency_p99_ms", sa.Float(), nullable=True),
        sa.Column("latency_avg_ms", sa.Float(), nullable=True),
        sa.Column("audit_jobs_completed", sa.Integer(), nullable=True),
        sa.Column("audit_jobs_failed", sa.Integer(), nullable=True),
        sa.Column("audit_avg_duration_seconds", sa.Float(), nullable=True),
        sa.Column("slow_endpoints", sa.JSON(), nullable=True),
    )
    op.create_index("ix_metrics_snapshots_id", "metrics_snapshots", ["id"], unique=False)
    op.create_index(
        "ix_metrics_snapshots_snapshot_at",
        "metrics_snapshots",
        ["snapshot_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_snapshots_snapshot_at", table_name="metrics_snapshots")
    op.drop_index("ix_metrics_snapshots_id", table_name="metrics_snapshots")
    op.drop_table("metrics_snapshots")

    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    op.drop_index("ix_security_events_event_type", table_name="security_events")
    op.drop_index("ix_security_events_id", table_name="security_events")
    op.drop_table("security_events")
