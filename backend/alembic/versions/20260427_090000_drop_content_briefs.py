"""Drop content_briefs table

Removes the content briefs / content-hub feature (de-scoped in Phase 10). Drops
the ``content_briefs`` table together with its indexes. This is a destructive
migration approved as part of the feature removal (no client data exists for
this feature). The first-party workspace endpoints, the public external API
surface, the generation service, and the ``ContentBrief`` ORM model were removed
in the same change.

Revision ID: 20260427_090000
Revises: 20260426_090000
Create Date: 2026-04-27 09:00:00.000000
"""

from alembic import op


revision = "20260427_090000"
down_revision = "20260426_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_content_briefs_user_created", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_audit", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_status_created", table_name="content_briefs")
    op.drop_index("ix_content_briefs_status", table_name="content_briefs")
    op.drop_index("ix_content_briefs_user_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_audit_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_project_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_id", table_name="content_briefs")
    op.drop_table("content_briefs")


def downgrade() -> None:
    # The content briefs feature has been removed entirely; recreating the table
    # is not supported. Restore from a backup taken before the upgrade if the
    # data is ever required.
    raise NotImplementedError(
        "Downgrade not supported: the content briefs feature was removed in Phase 10."
    )
