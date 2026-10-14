"""add user credit adjustments

Revision ID: 20250212_120000
Revises: 20250209_120000
Create Date: 2025-02-12 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250212_120000"
down_revision = "20250209_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_credit_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("admin_user_id", sa.Integer(), nullable=True, index=True),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("user_credit_adjustments")
