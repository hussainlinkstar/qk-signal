"""add project_brand_facts (guardrails input)

Revision ID: 20260422_090000
Revises: 20260421_090000
Create Date: 2026-04-22 09:00:00

Creates the per-project ``project_brand_facts`` table that stores brand facts
and allowed/forbidden claims. These structured statements feed the audit's
evidence/grounding context (gated by ``has_brand_integrity_guardrails``).

Nullable-safe / additive only: a new table is created (no DROP, no SET NOT NULL
on an existing populated column, no column rename). Guarded by an inspector
check so re-running is idempotent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_090000"
down_revision = "20260421_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_brand_facts" in set(inspector.get_table_names()):
        return

    op.create_table(
        "project_brand_facts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="fact"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "is_forbidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_project_brand_facts_id", "project_brand_facts", ["id"], unique=False)
    op.create_index(
        "ix_project_brand_facts_project_id",
        "project_brand_facts",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_brand_facts_project_created",
        "project_brand_facts",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_brand_facts" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_project_brand_facts_project_created", table_name="project_brand_facts")
    op.drop_index("ix_project_brand_facts_project_id", table_name="project_brand_facts")
    op.drop_index("ix_project_brand_facts_id", table_name="project_brand_facts")
    op.drop_table("project_brand_facts")
