"""Drop audits.addon_results column

Removes the orphaned ``audits.addon_results`` JSON column. The addon marketplace
feature was removed in Phase 10 (its tables were dropped in revision
20260424_090000), which left this column on the kept ``audits`` table with no
remaining reader or writer. This is a destructive DROP COLUMN on a live table,
approved as part of the feature removal (no client data depends on it). Only the
orphaned column is dropped; all other ``audits`` columns are untouched.

Revision ID: 20260428_090000
Revises: 20260427_090000
Create Date: 2026-04-28 09:00:00.000000
"""

from alembic import op


revision = "20260428_090000"
down_revision = "20260427_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("audits", "addon_results")


def downgrade() -> None:
    # The addon marketplace feature (the only writer of this column) has been
    # removed entirely; recreating the column is not supported. Restore from a
    # backup taken before the upgrade if the data is ever required.
    raise NotImplementedError(
        "Downgrade not supported: the addon marketplace feature was removed in Phase 10."
    )
