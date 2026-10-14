"""Add mfa_secret column to users.

Revision ID: 20250307_120000
Revises: 20250306_120000
Create Date: 2025-03-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250307_120000"
down_revision = "20250306_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "mfa_secret" not in columns:
        op.add_column("users", sa.Column("mfa_secret", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "mfa_secret" in columns:
        op.drop_column("users", "mfa_secret")
