"""Make scheduled_audits.url nullable for brand audit support

Revision ID: 20260306_180000
Revises: 20260306_170000
Create Date: 2026-03-06 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_180000"
down_revision = "20260306_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scheduled_audits"):
        return

    op.alter_column(
        "scheduled_audits",
        "url",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scheduled_audits"):
        return

    op.execute("UPDATE scheduled_audits SET url = '' WHERE url IS NULL")
    op.alter_column(
        "scheduled_audits",
        "url",
        existing_type=sa.String(),
        nullable=False,
    )
