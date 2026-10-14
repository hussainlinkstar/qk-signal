"""Add notifications_enabled to users.

Revision ID: 20250210_120000
Revises: 20250209_120000
Create Date: 2025-02-10 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250210_120000"
down_revision = "20250209_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "notifications_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "notifications_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "notifications_enabled" in columns:
        op.drop_column("users", "notifications_enabled")
