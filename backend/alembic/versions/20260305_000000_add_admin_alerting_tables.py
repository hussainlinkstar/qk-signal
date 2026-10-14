"""Add admin alerting tables

Revision ID: 20260305_000000
Revises: 20260305_010000
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_000000"
down_revision = "20260305_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_notification_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("channel_type", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_admin_notification_channels_id",
        "admin_notification_channels",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_notification_channels_channel_type",
        "admin_notification_channels",
        ["channel_type"],
        unique=False,
    )
    op.create_index(
        "ix_admin_notification_channels_is_active",
        "admin_notification_channels",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_admin_notification_channels_type_active",
        "admin_notification_channels",
        ["channel_type", "is_active"],
        unique=False,
    )

    op.create_table(
        "admin_alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metric_key", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("time_window_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("severity", sa.String(), nullable=False, server_default="warning"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_slack", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
    )
    op.create_index("ix_admin_alert_rules_id", "admin_alert_rules", ["id"], unique=False)
    op.create_index(
        "ix_admin_alert_rules_metric_key",
        "admin_alert_rules",
        ["metric_key"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_rules_metric_active",
        "admin_alert_rules",
        ["metric_key", "is_active"],
        unique=False,
    )

    op.create_table(
        "admin_alert_rule_channels",
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["admin_alert_rules.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["admin_notification_channels.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "rule_id",
            "channel_id",
            name="uq_admin_alert_rule_channels_rule_channel",
        ),
    )
    op.create_index(
        "ix_admin_alert_rule_channels_rule_id",
        "admin_alert_rule_channels",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_rule_channels_channel_id",
        "admin_alert_rule_channels",
        ["channel_id"],
        unique=False,
    )

    op.create_table(
        "admin_alert_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("metric_key", sa.String(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("context_info", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "notifications_sent", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["admin_alert_rules.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_admin_alert_events_id", "admin_alert_events", ["id"], unique=False)
    op.create_index(
        "ix_admin_alert_events_rule_id",
        "admin_alert_events",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_events_metric_key",
        "admin_alert_events",
        ["metric_key"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_events_status",
        "admin_alert_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_events_triggered_at",
        "admin_alert_events",
        ["triggered_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_events_status_triggered",
        "admin_alert_events",
        ["status", "triggered_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_alert_events_rule_triggered",
        "admin_alert_events",
        ["rule_id", "triggered_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_alert_events_rule_triggered", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_status_triggered", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_triggered_at", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_status", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_metric_key", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_rule_id", table_name="admin_alert_events")
    op.drop_index("ix_admin_alert_events_id", table_name="admin_alert_events")
    op.drop_table("admin_alert_events")

    op.drop_index(
        "ix_admin_alert_rule_channels_channel_id",
        table_name="admin_alert_rule_channels",
    )
    op.drop_index(
        "ix_admin_alert_rule_channels_rule_id",
        table_name="admin_alert_rule_channels",
    )
    op.drop_table("admin_alert_rule_channels")

    op.drop_index("ix_admin_alert_rules_metric_active", table_name="admin_alert_rules")
    op.drop_index("ix_admin_alert_rules_metric_key", table_name="admin_alert_rules")
    op.drop_index("ix_admin_alert_rules_id", table_name="admin_alert_rules")
    op.drop_table("admin_alert_rules")

    op.drop_index(
        "ix_admin_notification_channels_type_active",
        table_name="admin_notification_channels",
    )
    op.drop_index(
        "ix_admin_notification_channels_is_active",
        table_name="admin_notification_channels",
    )
    op.drop_index(
        "ix_admin_notification_channels_channel_type",
        table_name="admin_notification_channels",
    )
    op.drop_index("ix_admin_notification_channels_id", table_name="admin_notification_channels")
    op.drop_table("admin_notification_channels")
