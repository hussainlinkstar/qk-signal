"""Let invoice records outlive the account, and add the deletion receipt (SIGV2-1144).

`DELETE /api/v1/users/me` deleted `billing_payments`, which is the invoice
record. The UAE retention duty (Cabinet Decision 74/2023 Article 3, five years
following the Tax Period, extendable for audit, dispute and Voluntary
Disclosure; VAT Decree-Law Article 78; MD 243/2025 Article 11) means those rows
must stay retrievable and reproducible in complete and readable form. They are
now anonymised instead of deleted, which needs `billing_payments.user_id` to
accept NULL.

Additive only:

* seven new nullable columns on `billing_payments`;
* `ALTER COLUMN user_id DROP NOT NULL`, which relaxes a constraint and cannot
  lose data (the reverse, SET NOT NULL, is the dangerous direction and is only
  re-applied on downgrade when no anonymised row exists);
* one new table, `account_deletion_receipts`.

No DROP, no rename, no backfill and no row rewrite. Rows that predate this
carry NULL in `retention_until`; their retention date is derived from the
invoice date on read by
app/services/billing_retention.effective_retention_until, so the migration
never has to touch existing data.

`downgrade()` restores the NOT NULL only if every row still has a `user_id`.
If an anonymised invoice exists it refuses, because making the downgrade
succeed would mean deleting a statutory record to fit an older schema. That is
the documented limit required by AGENTS.md section 10 rule 2.

Revision ID: 20261015_010000
Revises: 20261014_010000
Create Date: 2026-10-13 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261015_010000"
down_revision = "20261014_010000"
branch_labels = None
depends_on = None

PAYMENTS_TABLE = "billing_payments"
RECEIPTS_TABLE = "account_deletion_receipts"

NEW_PAYMENT_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, dict[str, object]], ...] = (
    ("former_user_id", sa.Integer(), {}),
    ("invoice_customer_name", sa.String(), {}),
    ("invoice_customer_email", sa.String(), {}),
    ("retention_until", sa.DateTime(timezone=True), {}),
    ("retention_hold", sa.Boolean(), {"server_default": sa.text("false")}),
    ("retention_hold_reason", sa.String(), {}),
    ("anonymized_at", sa.DateTime(timezone=True), {}),
)

NEW_PAYMENT_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_billing_payments_former_user_id", "former_user_id"),
    ("ix_billing_payments_retention_until", "retention_until"),
)


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(inspector: sa.Inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _user_id_is_nullable(inspector: sa.Inspector) -> bool:
    for column in inspector.get_columns(PAYMENTS_TABLE):
        if column["name"] == "user_id":
            return bool(column["nullable"])
    return True


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if PAYMENTS_TABLE in tables:
        existing_columns = _columns(inspector, PAYMENTS_TABLE)
        for column_name, column_type, extra in NEW_PAYMENT_COLUMNS:
            if column_name not in existing_columns:
                op.add_column(
                    PAYMENTS_TABLE,
                    sa.Column(column_name, column_type, nullable=True, **extra),
                )

        existing_indexes = _indexes(inspector, PAYMENTS_TABLE)
        for index_name, column_name in NEW_PAYMENT_INDEXES:
            if index_name not in existing_indexes:
                op.create_index(index_name, PAYMENTS_TABLE, [column_name])

        if not _user_id_is_nullable(inspector):
            op.alter_column(
                PAYMENTS_TABLE,
                "user_id",
                existing_type=sa.Integer(),
                nullable=True,
            )

    if RECEIPTS_TABLE not in tables:
        op.create_table(
            RECEIPTS_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reference", sa.String(length=64), nullable=False),
            # No foreign key on purpose: the receipt exists because the user
            # row is gone, so it must not depend on one.
            sa.Column("former_user_id", sa.Integer(), nullable=False),
            sa.Column("subject_email_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("initiated_by", sa.String(length=32), nullable=False),
            sa.Column("initiated_by_admin_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "erased_record_counts",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "retained_billing_payment_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("retained_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retention_basis", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("reference", name="uq_account_deletion_receipts_reference"),
            sa.CheckConstraint(
                "initiated_by IN ('self_service', 'admin')",
                name="ck_account_deletion_receipts_initiated_by",
            ),
        )
        op.create_index(
            "ix_account_deletion_receipts_former_user_id",
            RECEIPTS_TABLE,
            ["former_user_id"],
        )
        op.create_index(
            "ix_account_deletion_receipts_fingerprint",
            RECEIPTS_TABLE,
            ["subject_email_fingerprint"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if RECEIPTS_TABLE in tables:
        op.drop_index("ix_account_deletion_receipts_fingerprint", table_name=RECEIPTS_TABLE)
        op.drop_index("ix_account_deletion_receipts_former_user_id", table_name=RECEIPTS_TABLE)
        op.drop_table(RECEIPTS_TABLE)

    if PAYMENTS_TABLE not in tables:
        return

    anonymized_invoices = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {PAYMENTS_TABLE} WHERE user_id IS NULL")
    ).scalar()
    if anonymized_invoices:
        raise RuntimeError(
            f"Refusing to downgrade: {anonymized_invoices} invoice record(s) have been "
            "anonymised and no longer reference a user. Restoring "
            f"{PAYMENTS_TABLE}.user_id NOT NULL would require deleting statutory tax "
            "records (UAE Cabinet Decision 74/2023 Article 3). Re-link or export those "
            "rows deliberately before downgrading."
        )

    op.alter_column(
        PAYMENTS_TABLE,
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    existing_indexes = _indexes(inspector, PAYMENTS_TABLE)
    for index_name, _column_name in NEW_PAYMENT_INDEXES:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=PAYMENTS_TABLE)

    existing_columns = _columns(inspector, PAYMENTS_TABLE)
    for column_name, _column_type, _extra in reversed(NEW_PAYMENT_COLUMNS):
        if column_name in existing_columns:
            op.drop_column(PAYMENTS_TABLE, column_name)
