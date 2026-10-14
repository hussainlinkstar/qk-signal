"""Add stripe event log table.

Revision ID: 20241010_120000
Revises: 20241008_090000
Create Date: 2024-10-10 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20241010_120000"
down_revision = "20241008_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS stripe_event_log (
                id SERIAL NOT NULL,
                event_id VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                event_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                payload JSON NOT NULL,
                processed_at TIMESTAMP WITH TIME ZONE,
                processing_status VARCHAR DEFAULT 'pending' NOT NULL,
                last_error TEXT,
                PRIMARY KEY (id),
                CONSTRAINT uq_stripe_event_log_event_id UNIQUE (event_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_stripe_event_log_event_id
            ON stripe_event_log (event_id)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_stripe_event_log_event_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS stripe_event_log"))
