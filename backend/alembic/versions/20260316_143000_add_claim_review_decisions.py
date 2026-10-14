"""Add claim review decisions table for agency manual disposition workflows.

Revision ID: 20260316_143000
Revises: 20260316_120000
Create Date: 2026-03-16 14:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_143000"
down_revision = "20260316_120000"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("claim_review_decisions"):
        op.create_table(
            "claim_review_decisions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("claim_id", sa.String(length=64), nullable=False),
            sa.Column("claim_domain", sa.String(length=16), nullable=False),
            sa.Column("claim_text", sa.Text(), nullable=False),
            sa.Column("original_disposition", sa.String(length=32), nullable=False),
            sa.Column("review_disposition", sa.String(length=32), nullable=False),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
            sa.Column(
                "reviewed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audit_id", "claim_id", name="uq_claim_review_audit_claim"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("claim_review_decisions"):
        indexes = _index_names(inspector, "claim_review_decisions")
        if "ix_claim_review_project_audit" not in indexes:
            op.create_index(
                "ix_claim_review_project_audit",
                "claim_review_decisions",
                ["project_id", "audit_id"],
                unique=False,
            )
        if "ix_claim_review_reviewer_id" not in indexes:
            op.create_index(
                "ix_claim_review_reviewer_id",
                "claim_review_decisions",
                ["reviewed_by_id"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("claim_review_decisions"):
        op.drop_index(
            "ix_claim_review_reviewer_id", table_name="claim_review_decisions", if_exists=True
        )
        op.drop_index(
            "ix_claim_review_project_audit", table_name="claim_review_decisions", if_exists=True
        )
        op.drop_table("claim_review_decisions", if_exists=True)
