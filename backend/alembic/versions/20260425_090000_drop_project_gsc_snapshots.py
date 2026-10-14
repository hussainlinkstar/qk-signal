"""Drop project GSC snapshots table

Removes the ``project_gsc_snapshots`` table that backed the Predictive Traffic &
ROI Simulator feature (de-scoped in Phase 10). The table and its indexes are
dropped together. This is a destructive migration approved as part of the
feature removal (no client data exists for this table).

Revision ID: 20260425_090000
Revises: 20260424_090000
Create Date: 2026-04-25 09:00:00.000000
"""

from alembic import op


revision = "20260425_090000"
down_revision = "20260424_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_project_gsc_snapshots_project_date", table_name="project_gsc_snapshots")
    op.drop_index("ix_project_gsc_snapshots_project_id", table_name="project_gsc_snapshots")
    op.drop_index("ix_project_gsc_snapshots_id", table_name="project_gsc_snapshots")
    op.drop_table("project_gsc_snapshots")


def downgrade() -> None:
    # The ROI simulator feature has been removed entirely; recreating this table
    # is not supported. Restore from a backup taken before the upgrade if the
    # data is ever required.
    raise NotImplementedError(
        "Downgrade not supported: the ROI simulator feature was removed in Phase 10."
    )
