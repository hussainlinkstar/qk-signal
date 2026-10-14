"""Add pricing_v3_shadow_mode to operational settings.

Revision ID: 20260307_090000
Revises: 20260306_190000
Create Date: 2026-03-07 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_090000"
down_revision = "20260306_190000"
branch_labels = None
depends_on = None


def _backfill_legacy_pricing_flags() -> None:
    # Promote legacy all-false rows to the v2-live baseline without touching
    # mixed/explicit operator overrides.
    op.execute(
        sa.text(
            """
            UPDATE operational_settings
            SET pricing_v2_enabled = true,
                credit_engine_v2_enabled = true
            WHERE pricing_v2_enabled = false
              AND credit_engine_v2_enabled = false
            """
        )
    )


def upgrade() -> None:
    with op.batch_alter_table("operational_settings") as batch_op:
        batch_op.alter_column("pricing_v2_enabled", server_default=sa.text("true"))
        batch_op.alter_column("credit_engine_v2_enabled", server_default=sa.text("true"))
        batch_op.add_column(
            sa.Column(
                "pricing_v3_shadow_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    _backfill_legacy_pricing_flags()


def downgrade() -> None:
    with op.batch_alter_table("operational_settings") as batch_op:
        batch_op.drop_column("pricing_v3_shadow_mode")
        batch_op.alter_column("pricing_v2_enabled", server_default=sa.text("false"))
        batch_op.alter_column("credit_engine_v2_enabled", server_default=sa.text("false"))
