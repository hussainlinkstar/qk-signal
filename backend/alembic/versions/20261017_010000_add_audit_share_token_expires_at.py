"""Add audits.share_token_expires_at (SIGV2-1250).

A public audit share token was minted once and then lived forever: there was
no deadline on the row and no rotation or revocation path, so a link that
leaked stayed valid indefinitely. ``share_token_expires_at`` records the
deadline for each token, and ``services.audit_share_token_service`` is the one
place that reads it.

This migration is additive only: one nullable timestamp column, no index, no
backfill, nothing dropped, renamed or retyped.

**The column is deliberately NOT backfilled.** NULL means "no expiry
recorded", which is exactly the state of every token minted before this
change, and the service treats it as "valid until rotated". Writing a deadline
into existing rows would retroactively break share links that customers have
already handed out. Those tokens pick up a deadline the first time they are
rotated.

Revision ID: 20261017_010000
Revises: 20261016_010000
Create Date: 2026-10-17 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261017_010000"
down_revision = "20261016_010000"
branch_labels = None
depends_on = None

TABLE_NAME = "audits"
COLUMN_NAME = "share_token_expires_at"


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    if COLUMN_NAME not in _columns(inspector, TABLE_NAME):
        op.add_column(
            "audits",
            sa.Column("share_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove the column.

    Reversible in shape, lossy in content: the deadlines are stored nowhere
    else, so every remaining token returns to never expiring. Never run
    against a live database (AGENTS.md 4.2).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    if COLUMN_NAME in _columns(inspector, TABLE_NAME):
        op.drop_column("audits", "share_token_expires_at")
