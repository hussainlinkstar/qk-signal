"""Add scan-denominated columns to project budget tables (SIGV2-1102).

The project budget guardrail is re-denominated in scans. The legacy credit
columns stay in place, unused; ``monthly_limit_credits`` relaxes to nullable
so new rows do not have to write it. Nothing is dropped or renamed and no
value is converted from credits into scans.

Revision ID: 20261009_010000
Revises: 20261008_010000
Create Date: 2026-10-09 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261009_010000"
down_revision = "20261008_010000"
branch_labels = None
depends_on = None

BUDGETS_TABLE = "project_budgets"
USAGE_TABLE = "project_budget_usage_periods"
BUDGETS_SCAN_CHECK = "ck_project_budgets_monthly_limit_scans_non_negative"
USAGE_SCAN_CHECK = "ck_project_budget_usage_consumed_scans_non_negative"


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _check_constraints(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table)
            if constraint.get("name")
        }
    except NotImplementedError:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if BUDGETS_TABLE in tables:
        budget_columns = _columns(inspector, BUDGETS_TABLE)
        if "monthly_limit_scans" not in budget_columns:
            op.add_column(
                BUDGETS_TABLE,
                sa.Column("monthly_limit_scans", sa.Integer(), nullable=True),
            )
        op.alter_column(
            BUDGETS_TABLE,
            "monthly_limit_credits",
            existing_type=sa.Integer(),
            nullable=True,
        )
        if BUDGETS_SCAN_CHECK not in _check_constraints(inspector, BUDGETS_TABLE):
            op.create_check_constraint(
                BUDGETS_SCAN_CHECK,
                BUDGETS_TABLE,
                "monthly_limit_scans >= 0",
            )

    if USAGE_TABLE in tables:
        usage_columns = _columns(inspector, USAGE_TABLE)
        if "budget_limit_scans" not in usage_columns:
            op.add_column(
                USAGE_TABLE,
                sa.Column("budget_limit_scans", sa.Integer(), nullable=True),
            )
        if "consumed_scans" not in usage_columns:
            op.add_column(
                USAGE_TABLE,
                sa.Column(
                    "consumed_scans",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        if USAGE_SCAN_CHECK not in _check_constraints(inspector, USAGE_TABLE):
            op.create_check_constraint(
                USAGE_SCAN_CHECK,
                USAGE_TABLE,
                "consumed_scans >= 0",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if USAGE_TABLE in tables:
        if USAGE_SCAN_CHECK in _check_constraints(inspector, USAGE_TABLE):
            op.drop_constraint(USAGE_SCAN_CHECK, USAGE_TABLE, type_="check")
        usage_columns = _columns(inspector, USAGE_TABLE)
        if "consumed_scans" in usage_columns:
            op.drop_column(USAGE_TABLE, "consumed_scans")
        if "budget_limit_scans" in usage_columns:
            op.drop_column(USAGE_TABLE, "budget_limit_scans")

    if BUDGETS_TABLE in tables:
        if BUDGETS_SCAN_CHECK in _check_constraints(inspector, BUDGETS_TABLE):
            op.drop_constraint(BUDGETS_SCAN_CHECK, BUDGETS_TABLE, type_="check")
        budget_columns = _columns(inspector, BUDGETS_TABLE)
        if "monthly_limit_scans" in budget_columns:
            op.drop_column(BUDGETS_TABLE, "monthly_limit_scans")
        # Rows written while the guardrail was scan-denominated carry no
        # credit limit. Restoring the pre-migration NOT NULL needs a value,
        # and 0 is the only one that invents nothing.
        op.execute(
            sa.text(
                f"UPDATE {BUDGETS_TABLE} SET monthly_limit_credits = 0 "
                "WHERE monthly_limit_credits IS NULL"
            )
        )
        op.alter_column(
            BUDGETS_TABLE,
            "monthly_limit_credits",
            existing_type=sa.Integer(),
            nullable=False,
        )
