"""Add B2B billing profile fields to users.

Revision ID: 20250309_120000
Revises: 20250308_120000
Create Date: 2025-03-09 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250309_120000"
down_revision = "20250308_120000"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column_name in columns:
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_column_if_missing("users", sa.Column("company_legal_name", sa.String(), nullable=True))
    _add_column_if_missing(
        "users",
        sa.Column("company_registration_number", sa.String(), nullable=True),
    )
    _add_column_if_missing("users", sa.Column("company_vat_number", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_email", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_phone", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_address_line1", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_address_line2", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_city", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_state", sa.String(), nullable=True))
    _add_column_if_missing("users", sa.Column("billing_postal_code", sa.String(), nullable=True))
    _add_column_if_missing(
        "users", sa.Column("billing_country", sa.String(length=2), nullable=True)
    )
    _add_column_if_missing("users", sa.Column("billing_website_url", sa.String(), nullable=True))
    _add_column_if_missing(
        "users",
        sa.Column(
            "billing_tax_exempt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    _drop_column_if_exists("users", "billing_tax_exempt")
    _drop_column_if_exists("users", "billing_website_url")
    _drop_column_if_exists("users", "billing_country")
    _drop_column_if_exists("users", "billing_postal_code")
    _drop_column_if_exists("users", "billing_state")
    _drop_column_if_exists("users", "billing_city")
    _drop_column_if_exists("users", "billing_address_line2")
    _drop_column_if_exists("users", "billing_address_line1")
    _drop_column_if_exists("users", "billing_phone")
    _drop_column_if_exists("users", "billing_email")
    _drop_column_if_exists("users", "company_vat_number")
    _drop_column_if_exists("users", "company_registration_number")
    _drop_column_if_exists("users", "company_legal_name")
