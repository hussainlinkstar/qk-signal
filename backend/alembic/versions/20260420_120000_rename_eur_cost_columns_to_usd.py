"""rename EUR cost columns to USD (currency unified to USD)

Revision ID: 20260420_120000
Revises: 20260417_235800
Create Date: 2026-04-20 12:00:00

The billing/cost subsystem no longer converts AI provider costs (USD) into an
EUR billing reference; everything is denominated in USD.  This migration renames
the legacy ``*_eur`` financial columns to ``*_usd``.  Stored numeric values are
preserved unchanged.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_120000"
down_revision = "20260417_235800"
branch_labels = None
depends_on = None


# table -> list of (old_suffix_eur, new_suffix_usd) base names
_RENAMES: dict[str, list[str]] = {
    "ai_economics_ledger_entries": [
        "token_cost",
        "infra_alloc",
        "orchestration",
        "retry_risk",
        "real_cost",
        "credit_unit_value",
        "implied_revenue",
        "margin",
    ],
    "debate_traces": ["cost"],
    "credit_commitments": ["monthly_fee"],
    "signal_audit_snapshots": ["total_debate_cost"],
    "signal_debate_agent_facts": ["cost"],
    "addons": ["monthly_fee"],
}


def _existing_columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _rename(table: str, frm: str, to: str) -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind, table)
    if frm in cols and to not in cols:
        op.alter_column(table, frm, new_column_name=to)


def upgrade() -> None:
    for table, bases in _RENAMES.items():
        for base in bases:
            _rename(table, f"{base}_eur", f"{base}_usd")


def downgrade() -> None:
    for table, bases in _RENAMES.items():
        for base in bases:
            _rename(table, f"{base}_usd", f"{base}_eur")
