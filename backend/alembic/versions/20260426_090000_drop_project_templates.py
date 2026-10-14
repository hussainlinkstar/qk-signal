"""Drop project_templates table and projects.template_id column

Removes the project templates feature (de-scoped in Phase 10). Drops the
``projects.template_id`` foreign-key column (its FK constraint first, then the
column) and the ``project_templates`` table with its index. This is a
destructive migration approved as part of the feature removal (no client data
exists for this feature). The project clone feature (``cloned_from_id``) is
unrelated and intentionally left intact.

Revision ID: 20260426_090000
Revises: 20260425_090000
Create Date: 2026-04-26 09:00:00.000000
"""

from alembic import op


revision = "20260426_090000"
down_revision = "20260425_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the FK constraint on projects.template_id before the column.
    op.drop_constraint("fk_projects_template_id", "projects", type_="foreignkey")
    # 2. Drop the now-unreferenced column.
    op.drop_column("projects", "template_id")
    # 3. Drop the project_templates table (and its index).
    op.drop_index("ix_project_templates_workspace_id", table_name="project_templates")
    op.drop_table("project_templates")


def downgrade() -> None:
    # The project templates feature has been removed entirely; recreating the
    # table and column is not supported. Restore from a backup taken before the
    # upgrade if the data is ever required.
    raise NotImplementedError(
        "Downgrade not supported: the project templates feature was removed in Phase 10."
    )
