"""add project budget guardrails

Revision ID: 20260302_190000
Revises: 20260302_160000
Create Date: 2026-03-02 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260302_190000"
down_revision = "20260302_160000"
branch_labels = None
depends_on = None


OLD_SCHEDULED_AUDIT_PAUSE_REASON_ENUM = sa.Enum(
    "insufficient_credits",
    "plan_restricted",
    "manual",
    name="scheduled_audit_pause_reason",
    native_enum=False,
)
NEW_SCHEDULED_AUDIT_PAUSE_REASON_ENUM = sa.Enum(
    "insufficient_credits",
    "budget_exceeded",
    "plan_restricted",
    "manual",
    name="scheduled_audit_pause_reason",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "scheduled_audits" in table_names:
        with op.batch_alter_table("scheduled_audits") as batch_op:
            batch_op.alter_column(
                "paused_reason",
                existing_type=OLD_SCHEDULED_AUDIT_PAUSE_REASON_ENUM,
                type_=NEW_SCHEDULED_AUDIT_PAUSE_REASON_ENUM,
                existing_nullable=True,
            )

    if "project_budgets" not in table_names:
        op.create_table(
            "project_budgets",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("monthly_limit_credits", sa.Integer(), nullable=False),
            sa.Column("cycle_anchor_day", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "monthly_limit_credits >= 0", name="ck_project_budgets_monthly_limit_non_negative"
            ),
            sa.CheckConstraint(
                "cycle_anchor_day >= 1 AND cycle_anchor_day <= 28",
                name="ck_project_budgets_cycle_anchor_day",
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("project_id", name="uq_project_budgets_project_id"),
        )
        op.create_index("ix_project_budgets_id", "project_budgets", ["id"], unique=False)
        op.create_index(
            "ix_project_budgets_project_id", "project_budgets", ["project_id"], unique=False
        )

    if "project_budget_usage_periods" not in table_names:
        op.create_table(
            "project_budget_usage_periods",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("cycle_anchor_day", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("budget_limit_credits", sa.Integer(), nullable=True),
            sa.Column("consumed_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_threshold_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("limit_reached_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "consumed_credits >= 0", name="ck_project_budget_usage_consumed_non_negative"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "project_id", "period_start", name="uq_project_budget_usage_project_period"
            ),
        )
        op.create_index(
            "ix_project_budget_usage_periods_id",
            "project_budget_usage_periods",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_project_budget_usage_project_period",
            "project_budget_usage_periods",
            ["project_id", "period_start"],
            unique=False,
        )
        op.create_index(
            "ix_project_budget_usage_period_start",
            "project_budget_usage_periods",
            ["period_start"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "project_budget_usage_periods" in table_names:
        op.drop_index(
            "ix_project_budget_usage_period_start", table_name="project_budget_usage_periods"
        )
        op.drop_index(
            "ix_project_budget_usage_project_period", table_name="project_budget_usage_periods"
        )
        op.drop_index(
            "ix_project_budget_usage_periods_id", table_name="project_budget_usage_periods"
        )
        op.drop_table("project_budget_usage_periods")

    if "project_budgets" in table_names:
        op.drop_index("ix_project_budgets_project_id", table_name="project_budgets")
        op.drop_index("ix_project_budgets_id", table_name="project_budgets")
        op.drop_table("project_budgets")

    if "scheduled_audits" in table_names:
        with op.batch_alter_table("scheduled_audits") as batch_op:
            batch_op.alter_column(
                "paused_reason",
                existing_type=NEW_SCHEDULED_AUDIT_PAUSE_REASON_ENUM,
                type_=OLD_SCHEDULED_AUDIT_PAUSE_REASON_ENUM,
                existing_nullable=True,
            )
