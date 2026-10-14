"""Add external_id column to users.

Revision ID: 20250314_120000
Revises: 20250313_120000
Create Date: 2025-03-14 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250314_120000"
down_revision = "20250313_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "external_id" not in columns:
        op.add_column("users", sa.Column("external_id", sa.String(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_external_id" not in indexes:
        op.create_index("ix_users_external_id", "users", ["external_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        return

    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_external_id" in indexes:
        op.drop_index("ix_users_external_id", table_name="users")

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "external_id" in columns:
        op.drop_column("users", "external_id")
