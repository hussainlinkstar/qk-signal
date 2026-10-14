"""Add operational settings.

Revision ID: 20241008_090000
Revises: 20240924_120000
Create Date: 2024-10-08 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20241008_090000"
down_revision = "20240924_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS operational_settings (
                id SERIAL NOT NULL,
                fallback_model_enabled BOOLEAN DEFAULT false NOT NULL,
                cache_refresh_requested_at TIMESTAMP WITH TIME ZONE,
                PRIMARY KEY (id)
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS operational_settings"))
