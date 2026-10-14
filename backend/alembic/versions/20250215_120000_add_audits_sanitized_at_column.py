"""Add audits.sanitized_at column if missing.

Revision ID: 20250215_120000
Revises: 20250214_120000
Create Date: 2025-02-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250215_120000"
down_revision = "20250214_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("audits"):
        existing_columns = {column["name"] for column in inspector.get_columns("audits")}
        if "sanitized_at" not in existing_columns:
            op.add_column(
                "audits",
                sa.Column("sanitized_at", sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    op.drop_column("audits", "sanitized_at", if_exists=True)
