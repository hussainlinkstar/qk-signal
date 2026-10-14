"""Add audits.query_category column if missing.

Revision ID: 20250302_120000
Revises: 20250301_120000
Create Date: 2025-03-02 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250302_120000"
down_revision = "20250301_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("audits"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("audits")}
    if "query_category" not in existing_columns:
        op.add_column("audits", sa.Column("query_category", sa.String(), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("audits")}
    if "ix_audits_query_category" not in existing_indexes:
        op.create_index("ix_audits_query_category", "audits", ["query_category"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audits_query_category", table_name="audits", if_exists=True)
    op.drop_column("audits", "query_category", if_exists=True)
