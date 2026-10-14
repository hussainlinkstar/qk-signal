"""Add alert rules and logs tables.

Revision ID: 20250318_120000
Revises: 20250317_120000
Create Date: 2025-03-18 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250318_120000"
down_revision = "20250317_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # alert_rules table
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("email_to", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_alert_rules_id", "alert_rules", ["id"], unique=False)
    op.create_index("ix_alert_rules_project_id", "alert_rules", ["project_id"], unique=False)

    # alert_logs table
    op.create_table(
        "alert_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_alert_logs_id", "alert_logs", ["id"], unique=False)
    op.create_index("ix_alert_logs_rule_id", "alert_logs", ["rule_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_logs_rule_id", table_name="alert_logs")
    op.drop_index("ix_alert_logs_id", table_name="alert_logs")
    op.drop_table("alert_logs")

    op.drop_index("ix_alert_rules_project_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_id", table_name="alert_rules")
    op.drop_table("alert_rules")
