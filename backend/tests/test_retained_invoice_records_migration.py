"""Contracts for the migration that lets invoice records outlive an account (SIGV2-1144).

Two layers, mirroring tests/test_narrowed_subscription_plan_constraint_migration.py:

1. Source contracts, always run. They pin the revision chain, the additive
   shape (seven nullable columns, one new table, NOT NULL relaxed and never
   imposed), the absence of any row rewrite or drop in `upgrade()`, and the
   documented refusal in `downgrade()`.
2. The executable PostgreSQL gate, which runs upgrade() and downgrade() for
   real against an isolated local database:

RETAINED_INVOICE_MIGRATION_TEST_DATABASE_URL=<isolated-url> python -m pytest \
    tests/test_retained_invoice_records_migration.py -q
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20261015_010000_retain_invoice_records_after_account_deletion.py"
)
REVISION = "20261015_010000"
DOWN_REVISION = "20261014_010000"
PAYMENTS_TABLE = "billing_payments"
RECEIPTS_TABLE = "account_deletion_receipts"
EXPECTED_NEW_PAYMENT_COLUMNS = {
    "former_user_id",
    "invoice_customer_name",
    "invoice_customer_email",
    "retention_until",
    "retention_hold",
    "retention_hold_reason",
    "anonymized_at",
}
LIBPQ_TARGET_ENVIRONMENT_VARIABLES = frozenset(
    {
        "PGDATABASE",
        "PGHOST",
        "PGHOSTADDR",
        "PGPASSFILE",
        "PGPORT",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGSYSCONFDIR",
    }
)


def _migration_source() -> str:
    assert MIGRATION_PATH.exists(), f"Missing retention migration: {MIGRATION_PATH.name}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "retained_invoice_records_migration", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script_directory() -> ScriptDirectory:
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(alembic_config)


def _validated_local_test_database_url(raw_url: str) -> URL:
    ambient_overrides = sorted(
        variable_name
        for variable_name in LIBPQ_TARGET_ENVIRONMENT_VARIABLES
        if variable_name in os.environ
    )
    if ambient_overrides:
        raise ValueError(
            "Migration acceptance must not inherit libpq target overrides: "
            + ", ".join(ambient_overrides)
        )

    database_url = make_url(raw_url)
    if database_url.get_backend_name() != "postgresql":
        raise ValueError("Migration acceptance requires PostgreSQL.")

    connection_target_query_keys = {
        "database",
        "dbname",
        "host",
        "hostaddr",
        "passfile",
        "password",
        "port",
        "service",
        "servicefile",
        "user",
    }
    supplied_target_overrides = connection_target_query_keys.intersection(
        key.lower() for key in database_url.query
    )
    if supplied_target_overrides:
        raise ValueError("Migration acceptance URL must not override its connection target.")

    if database_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Migration acceptance database must be hosted on loopback.")

    database_name = (database_url.database or "").lower()
    clearly_test_specific = (
        database_name == "test"
        or database_name.startswith("test_")
        or database_name.endswith("_test")
        or "_test_" in database_name
    )
    if not clearly_test_specific:
        raise ValueError("Migration acceptance database name must be clearly test-specific.")
    return database_url


# ---------------------------------------------------------------------------
# 1. Source contracts
# ---------------------------------------------------------------------------


def test_migration_chains_onto_the_current_head_without_branching() -> None:
    source = _migration_source()

    assert re.search(rf'^revision\s*=\s*["\']{REVISION}["\']', source, flags=re.MULTILINE)
    assert re.search(rf'^down_revision\s*=\s*["\']{DOWN_REVISION}["\']', source, flags=re.MULTILINE)
    # This migration is no longer the head; later ones chain on top of it. It
    # must still be an ancestor of whatever the single head is, and there must
    # be exactly one head. Reading the head instead of naming it keeps this
    # test about branching rather than about whichever migration landed last.
    script_directory = _script_directory()
    heads = script_directory.get_heads()
    assert len(heads) == 1, heads
    ancestors = {
        script_revision.revision
        for script_revision in script_directory.iterate_revisions(heads[0], None, inclusive=True)
    }
    assert REVISION in ancestors


def test_upgrade_is_additive_and_rewrites_no_rows() -> None:
    source = _migration_source()
    upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0].lower()

    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    for forbidden in ("update ", "delete from", "truncate", "rename"):
        assert forbidden not in upgrade_body

    # Every column added to the existing table is nullable, and the single
    # alter_column relaxes NOT NULL rather than imposing it. NOT NULL on the
    # brand-new receipts table is fine: it has no rows to violate it.
    compact_upgrade = upgrade_body.replace(" ", "").replace("\n", "")
    assert "sa.column(column_name,column_type,nullable=true" in compact_upgrade
    assert compact_upgrade.count("op.alter_column") == 1
    assert "nullable=true,)" in compact_upgrade

    compact_source = " ".join(source.lower().split())
    assert "update billing_payments" not in compact_source
    assert "delete from" not in compact_source
    assert "truncate" not in compact_source


def test_upgrade_adds_exactly_the_retention_columns_as_nullable() -> None:
    migration = _load_migration_module()

    assert {name for name, _type, _extra in migration.NEW_PAYMENT_COLUMNS} == (
        EXPECTED_NEW_PAYMENT_COLUMNS
    )
    assert migration.PAYMENTS_TABLE == PAYMENTS_TABLE
    assert migration.RECEIPTS_TABLE == RECEIPTS_TABLE


def test_downgrade_refuses_while_an_anonymised_invoice_exists() -> None:
    downgrade_body = _migration_source().split("def downgrade()", 1)[1].lower()

    # The refusal is the documented limit: restoring NOT NULL would require
    # deleting a statutory record.
    assert "user_id is null" in downgrade_body
    assert "raise runtimeerror" in downgrade_body
    assert "74/2023" in downgrade_body


# ---------------------------------------------------------------------------
# 2. Executable PostgreSQL gate
# ---------------------------------------------------------------------------


def _create_pre_migration_tables(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE billing_payments (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users (id),
                stripe_invoice_id TEXT NOT NULL UNIQUE,
                stripe_customer_id TEXT NOT NULL,
                stripe_subscription_id TEXT,
                amount_paid INTEGER,
                amount_due INTEGER,
                currency TEXT,
                status TEXT,
                hosted_invoice_url TEXT,
                invoice_pdf TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    )
    connection.execute(text("INSERT INTO users (id, email) VALUES (1, 'payer@example.invalid')"))
    connection.execute(
        text(
            """
            INSERT INTO billing_payments (
                id, user_id, stripe_invoice_id, stripe_customer_id, amount_paid,
                amount_due, currency, status, created_at
            )
            VALUES (
                1, 1, 'inv_migration_1', 'cus_migration_1', 39900, 39900, 'usd', 'paid',
                TIMESTAMPTZ '2026-02-14 09:30:00+00'
            )
            """
        )
    )


def test_migration_executes_and_reverts_on_isolated_postgresql() -> None:
    raw_database_url = os.environ.get("RETAINED_INVOICE_MIGRATION_TEST_DATABASE_URL")
    if not raw_database_url:
        pytest.skip(
            "Set RETAINED_INVOICE_MIGRATION_TEST_DATABASE_URL to an isolated PostgreSQL "
            "database and run this test explicitly for final migration acceptance."
        )
    database_url = _validated_local_test_database_url(raw_database_url)

    migration = _load_migration_module()
    engine = create_engine(database_url)
    schema = f"retained_invoices_{uuid4().hex}"
    schema_created = False

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                schema_created = True
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                _create_pre_migration_tables(connection)

                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()

                inspector = inspect(connection)
                payment_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(PAYMENTS_TABLE, schema=schema)
                }
                assert EXPECTED_NEW_PAYMENT_COLUMNS.issubset(payment_columns)
                assert all(
                    payment_columns[name]["nullable"] for name in EXPECTED_NEW_PAYMENT_COLUMNS
                )
                assert payment_columns["user_id"]["nullable"] is True
                assert RECEIPTS_TABLE in set(inspector.get_table_names(schema=schema))

                # The pre-existing row is untouched and still readable.
                assert (
                    connection.execute(
                        text("SELECT amount_paid FROM billing_payments WHERE id = 1")
                    ).scalar_one()
                    == 39900
                )

                # An invoice can now be severed from its account and kept.
                connection.execute(
                    text(
                        "UPDATE billing_payments SET user_id = NULL, former_user_id = 1, "
                        "anonymized_at = now() WHERE id = 1"
                    )
                )
                connection.execute(text("DELETE FROM users WHERE id = 1"))
                assert (
                    connection.execute(
                        text("SELECT stripe_invoice_id FROM billing_payments WHERE id = 1")
                    ).scalar_one()
                    == "inv_migration_1"
                )

                # Downgrade refuses while that row exists.
                with pytest.raises(RuntimeError) as refusal:
                    migration.downgrade()
                assert "74/2023" in str(refusal.value)

                # Re-link it, and the downgrade is clean and complete.
                connection.execute(text("INSERT INTO users (id, email) VALUES (2, 'b@x.invalid')"))
                connection.execute(
                    text(
                        "UPDATE billing_payments SET user_id = 2, former_user_id = NULL, "
                        "anonymized_at = NULL WHERE id = 1"
                    )
                )
                migration.downgrade()

                inspector = inspect(connection)
                reverted_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(PAYMENTS_TABLE, schema=schema)
                }
                assert not EXPECTED_NEW_PAYMENT_COLUMNS.intersection(reverted_columns)
                assert reverted_columns["user_id"]["nullable"] is False
                assert RECEIPTS_TABLE not in set(inspector.get_table_names(schema=schema))
                assert (
                    connection.execute(
                        text("SELECT amount_paid FROM billing_payments WHERE id = 1")
                    ).scalar_one()
                    == 39900
                )
            finally:
                transaction.rollback()
    finally:
        try:
            if schema_created:
                with engine.begin() as cleanup_connection:
                    cleanup_connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            engine.dispose()
