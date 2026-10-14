"""Normalize audit_target_type enum defaults to enum names.

Revision ID: 20260306_190000
Revises: 20260306_180000
Create Date: 2026-03-06 19:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_190000"
down_revision = "20260306_180000"
branch_labels = None
depends_on = None

TARGET_TABLES = ("audits", "audit_jobs")


def _normalize_values(table_name: str, *, to_upper: bool) -> None:
    website_value = "WEBSITE" if to_upper else "website"
    brand_value = "BRAND" if to_upper else "brand"
    op.execute(
        sa.text(
            f"""
            UPDATE "{table_name}"
            SET "audit_target_type" = CASE
                WHEN LOWER("audit_target_type") = 'website' THEN :website_value
                WHEN LOWER("audit_target_type") = 'brand' THEN :brand_value
                ELSE "audit_target_type"
            END
            WHERE "audit_target_type" IS NOT NULL
            """
        ).bindparams(website_value=website_value, brand_value=brand_value)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name in TARGET_TABLES:
        if table_name not in existing_tables:
            continue
        _normalize_values(table_name, to_upper=True)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("audit_target_type", server_default="WEBSITE")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name in TARGET_TABLES:
        if table_name not in existing_tables:
            continue
        _normalize_values(table_name, to_upper=False)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("audit_target_type", server_default="website")
