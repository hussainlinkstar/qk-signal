"""add recommendation_decisions.action_label (readable learnings label)

Revision ID: 20260429_090000
Revises: 20260428_090000
Create Date: 2026-04-29 09:00:00

Adds a nullable ``action_label`` column to ``recommendation_decisions`` so the
Learnings view can show a human-readable summary of the dismissed/accepted
Advisor action instead of the raw sha256 ``action_fingerprint``. The label is a
RAW-sanitized (control chars stripped, length-capped) copy of the action text —
never HTML-escaped (React escapes at render).

Nullable-safe / additive only: a new nullable column is added (no DROP, no SET
NOT NULL on existing rows, no column rename). Old rows keep a NULL label and the
frontend falls back to a shortened fingerprint. Guarded by an inspector check so
re-running is idempotent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_090000"
down_revision = "20260428_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("recommendation_decisions")}
    if "action_label" in columns:
        return
    op.add_column(
        "recommendation_decisions",
        sa.Column("action_label", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("recommendation_decisions")}
    if "action_label" not in columns:
        return
    op.drop_column("recommendation_decisions", "action_label")
