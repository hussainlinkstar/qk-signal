"""add advisor_plan_snapshots (one persisted Advisor plan per completed audit)

Revision ID: 20260501_090000
Revises: 20260430_090000
Create Date: 2026-05-01 09:00:00

Creates the ``advisor_plan_snapshots`` table that persists exactly one snapshot
of the deterministic Advisor plan per completed audit (R12 progress/trend
foundation). Each row stores the full ``advisor_plan`` (the response-time
``metadata.advisor`` shape, reused verbatim) plus a small denormalized
``plan_summary`` (total/high/medium/low action counts) for cheap trend queries.

The plan itself is still computed at response-time and never replaces the
canonical contract; this table only records a point-in-time copy so progress
can later be shown over time. No auto-execution, no UI — persistence only.

Nullable-safe / additive only: a new table is created (no DROP, no SET NOT NULL
on an existing populated column, no column rename). Guarded by an inspector
check so re-running is idempotent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_090000"
down_revision = "20260430_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisor_plan_snapshots" in set(inspector.get_table_names()):
        return

    op.create_table(
        "advisor_plan_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("advisor_plan", sa.JSON(), nullable=False),
        sa.Column("plan_summary", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("audit_id", name="uq_advisor_plan_snapshots_audit"),
    )
    op.create_index("ix_advisor_plan_snapshots_id", "advisor_plan_snapshots", ["id"], unique=False)
    op.create_index(
        "ix_advisor_plan_snapshots_audit_id",
        "advisor_plan_snapshots",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_advisor_plan_snapshots_project_id",
        "advisor_plan_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_advisor_plan_snapshots_project_created",
        "advisor_plan_snapshots",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisor_plan_snapshots" not in set(inspector.get_table_names()):
        return
    op.drop_index(
        "ix_advisor_plan_snapshots_project_created",
        table_name="advisor_plan_snapshots",
    )
    op.drop_index("ix_advisor_plan_snapshots_project_id", table_name="advisor_plan_snapshots")
    op.drop_index("ix_advisor_plan_snapshots_audit_id", table_name="advisor_plan_snapshots")
    op.drop_index("ix_advisor_plan_snapshots_id", table_name="advisor_plan_snapshots")
    op.drop_table("advisor_plan_snapshots")
