"""add recommendation_decisions (learnings loop)

Revision ID: 20260423_090000
Revises: 20260422_090000
Create Date: 2026-04-23 09:00:00

Creates the per-project ``recommendation_decisions`` table that records a user's
accept/dismiss decision for an Advisor recommendation, keyed by a stable
``action_fingerprint`` (sha256 of the action text). Dismissed fingerprints are
suppressed from the Advisor plan on future audits; the history feeds a
user-facing Learnings view and the data moat.

Nullable-safe / additive only: a new table is created (no DROP, no SET NOT NULL
on an existing populated column, no column rename). Guarded by an inspector
check so re-running is idempotent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_090000"
down_revision = "20260422_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "recommendation_decisions" in set(inspector.get_table_names()):
        return

    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("action_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "project_id",
            "action_fingerprint",
            name="uq_recommendation_decisions_project_fingerprint",
        ),
    )
    op.create_index(
        "ix_recommendation_decisions_id",
        "recommendation_decisions",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_decisions_project_id",
        "recommendation_decisions",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "recommendation_decisions" not in set(inspector.get_table_names()):
        return
    op.drop_index(
        "ix_recommendation_decisions_project_id",
        table_name="recommendation_decisions",
    )
    op.drop_index(
        "ix_recommendation_decisions_id",
        table_name="recommendation_decisions",
    )
    op.drop_table("recommendation_decisions")
