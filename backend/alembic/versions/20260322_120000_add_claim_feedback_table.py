"""add claim feedback table

Revision ID: 20260322_120000
Revises: 20260322_090000
Create Date: 2026-03-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260322_120000"
down_revision = "20260322_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id", sa.Integer(), sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("claim_key", sa.String(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_category", sa.String(), nullable=True),
        sa.Column(
            "feedback_type",
            sa.Enum("agree", "disagree", "fixed", name="claim_feedback_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_claim_feedback_audit_id", "claim_feedback", ["audit_id"])
    op.create_index("ix_claim_feedback_claim_key", "claim_feedback", ["claim_key"])
    op.create_index("ix_claim_feedback_user_id", "claim_feedback", ["user_id"])
    op.create_unique_constraint(
        "uq_claim_feedback_per_user", "claim_feedback", ["audit_id", "claim_key", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_claim_feedback_per_user", "claim_feedback", type_="unique")
    op.drop_index("ix_claim_feedback_user_id", table_name="claim_feedback")
    op.drop_index("ix_claim_feedback_claim_key", table_name="claim_feedback")
    op.drop_index("ix_claim_feedback_audit_id", table_name="claim_feedback")
    op.drop_table("claim_feedback")
