"""Add missing indexes on frequently filtered columns.

Revision ID: 20250313_120000
Revises: 20250312_120000
"""

from alembic import op

revision = "20250313_120000"
down_revision = "20250312_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"], if_not_exists=True)
    op.create_index(
        "ix_subscriptions_plan_type", "subscriptions", ["plan_type"], if_not_exists=True
    )
    op.create_index(
        "ix_billing_payments_status", "billing_payments", ["status"], if_not_exists=True
    )
    op.create_index("ix_audits_audit_type", "audits", ["type"], if_not_exists=True)
    op.create_index(
        "ix_stripe_event_log_processing_status",
        "stripe_event_log",
        ["processing_status"],
        if_not_exists=True,
    )
    op.create_index("ix_magic_links_is_used", "magic_links", ["is_used"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_magic_links_is_used", table_name="magic_links", if_exists=True)
    op.drop_index(
        "ix_stripe_event_log_processing_status", table_name="stripe_event_log", if_exists=True
    )
    op.drop_index("ix_audits_audit_type", table_name="audits", if_exists=True)
    op.drop_index("ix_billing_payments_status", table_name="billing_payments", if_exists=True)
    op.drop_index("ix_subscriptions_plan_type", table_name="subscriptions", if_exists=True)
    op.drop_index("ix_subscriptions_status", table_name="subscriptions", if_exists=True)
