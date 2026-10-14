"""Drop marketplace addon tables

Removes the addon marketplace feature (de-scoped in Phase 10). Drops the
``addons``, ``addon_installations`` and ``addon_usage_logs`` tables together
with their indexes. This is a destructive migration approved as part of the
feature removal (no client data exists for these tables).

The ``audits.addon_results`` column is intentionally retained: it lives on a
kept table and dropping a column on a live table is out of scope for this
table-drop migration.

Revision ID: 20260424_090000
Revises: 20260423_090000
Create Date: 2026-04-24 09:00:00.000000
"""

from alembic import op


revision = "20260424_090000"
down_revision = "20260423_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop in FK-dependency order: usage logs → installations → addons.
    op.drop_index("ix_addon_usage_logs_workspace_addon_triggered_at", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_installation_triggered_at", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_triggered_by_user_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_addon_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_workspace_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_installation_id", table_name="addon_usage_logs")
    op.drop_index("ix_addon_usage_logs_id", table_name="addon_usage_logs")
    op.drop_table("addon_usage_logs")

    op.drop_index("ix_addon_installations_addon_active", table_name="addon_installations")
    op.drop_index("ix_addon_installations_workspace_active", table_name="addon_installations")
    op.drop_index("ix_addon_installations_installed_by_user_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_addon_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_workspace_id", table_name="addon_installations")
    op.drop_index("ix_addon_installations_id", table_name="addon_installations")
    op.drop_table("addon_installations")

    op.drop_index("ix_addons_first_party_verified", table_name="addons")
    op.drop_index("ix_addons_published_category", table_name="addons")
    op.drop_index("ix_addons_author_id", table_name="addons")
    op.drop_index("ix_addons_slug", table_name="addons")
    op.drop_index("ix_addons_id", table_name="addons")
    op.drop_table("addons")
    # Note: pricing_type / execution_mode were declared with native_enum=False
    # (stored as VARCHAR, no PostgreSQL ENUM type), so no type cleanup is needed.


def downgrade() -> None:
    # The addon marketplace feature has been removed entirely; recreating these
    # tables is not supported. Restore from a backup taken before the upgrade
    # if the data is ever required.
    raise NotImplementedError(
        "Downgrade not supported: the addon marketplace feature was removed in Phase 10."
    )
