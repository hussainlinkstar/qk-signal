"""Contracts for the billing_interval canonical-value backfill (SIGV2-1238).

Two layers, mirroring tests/test_retained_invoice_records_migration.py:

1. Source contracts, always run. They pin the revision chain, pin the
   backfill mapping to the exact one used by the SIGV2-1198 read-side
   normaliser (billing.router.normalized_billing_interval), and confirm the
   migration performs a data-only UPDATE with no schema change.
2. The executable PostgreSQL gate, which runs upgrade() for real against an
   isolated local database:

BILLING_INTERVAL_BACKFILL_MIGRATION_TEST_DATABASE_URL=<isolated-url> python -m pytest \
    tests/test_billing_interval_backfill_migration.py -q
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

from billing.router import (
    DEFAULT_BILLING_INTERVAL,
    SUPPORTED_BILLING_INTERVALS,
    normalized_billing_interval,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20261016_010000_backfill_canonical_billing_interval.py"
)
REVISION = "20261016_010000"
DOWN_REVISION = "20261015_010000"
SUBSCRIPTIONS_TABLE = "subscriptions"
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
    assert (
        MIGRATION_PATH.exists()
    ), f"Missing billing_interval backfill migration: {MIGRATION_PATH.name}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "billing_interval_backfill_migration", MIGRATION_PATH
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

    # Later migrations chain on top of this one, so it is no longer the head.
    # What must stay true is that there is exactly one head (no branching) and
    # that this revision is on the path to it. Pinning the head by name here
    # only made every later migration break this test for no reason.
    script_directory = _script_directory()
    heads = script_directory.get_heads()
    assert len(heads) == 1, heads
    ancestors = {
        script_revision.revision
        for script_revision in script_directory.iterate_revisions(heads[0], None, inclusive=True)
    }
    assert REVISION in ancestors


def test_migration_mapping_matches_the_sigv2_1198_read_side_normaliser() -> None:
    """The backfill must reuse SIGV2-1198's mapping exactly, never invent one.

    billing.router.normalized_billing_interval degrades ANY value outside
    SUPPORTED_BILLING_INTERVALS to DEFAULT_BILLING_INTERVAL -- it is not a
    per-spelling table ('monthly' -> 'month', 'yearly' -> 'year'); it is a
    single fallback to the default. The migration must mirror that, not a
    richer mapping, or the two would silently drift apart.
    """
    migration = _load_migration_module()

    assert migration.SUPPORTED_BILLING_INTERVALS == SUPPORTED_BILLING_INTERVALS
    assert migration.CANONICAL_BILLING_INTERVAL == DEFAULT_BILLING_INTERVAL

    for stored in ("monthly", "weekly", "annual", "yearly", "", "MONTH"):
        subscription = type("Sub", (), {"id": 1, "billing_interval": stored})()
        assert normalized_billing_interval(subscription) == migration.CANONICAL_BILLING_INTERVAL

    for stored in migration.SUPPORTED_BILLING_INTERVALS:
        subscription = type("Sub", (), {"id": 1, "billing_interval": stored})()
        assert normalized_billing_interval(subscription) == stored


def test_upgrade_is_a_single_data_only_update_with_no_schema_change() -> None:
    source = _migration_source()
    upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0].lower()

    for forbidden in (
        "add_column",
        "drop_column",
        "drop_table",
        "create_table",
        "alter_column",
        "create_check_constraint",
        "delete from",
        "truncate",
    ):
        assert forbidden not in upgrade_body

    assert "update" in upgrade_body
    assert "subscriptions" in upgrade_body
    assert "not in" in upgrade_body


def test_downgrade_is_a_documented_no_op() -> None:
    source = _migration_source()
    downgrade_body = source.split("def downgrade() -> None:", 1)[1]
    downgrade_lines = [
        line.strip()
        for line in downgrade_body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert downgrade_lines == ["pass"]
    assert "no recoverable inverse" in source


# ---------------------------------------------------------------------------
# 2. Executable PostgreSQL gate
# ---------------------------------------------------------------------------


def _create_pre_migration_subscriptions_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY,
                stripe_customer_id TEXT NOT NULL UNIQUE,
                plan_type TEXT NOT NULL,
                status TEXT NOT NULL,
                billing_interval TEXT NOT NULL DEFAULT 'month'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO subscriptions (id, stripe_customer_id, plan_type, status, billing_interval)
            VALUES
                (1, 'cus_month', 'plan_standard', 'active', 'month'),
                (2, 'cus_monthly', 'plan_standard', 'active', 'monthly'),
                (3, 'cus_year', 'plan_standard', 'active', 'year'),
                (4, 'cus_weekly', 'plan_standard', 'active', 'weekly')
            """
        )
    )


def test_migration_backfills_non_canonical_rows_on_isolated_postgresql() -> None:
    raw_database_url = os.environ.get("BILLING_INTERVAL_BACKFILL_MIGRATION_TEST_DATABASE_URL")
    if not raw_database_url:
        pytest.skip(
            "Set BILLING_INTERVAL_BACKFILL_MIGRATION_TEST_DATABASE_URL to an isolated "
            "PostgreSQL database and run this test explicitly for final migration "
            "acceptance."
        )
    database_url = _validated_local_test_database_url(raw_database_url)

    migration = _load_migration_module()
    engine = create_engine(database_url)
    schema = f"billing_interval_backfill_{uuid4().hex}"
    schema_created = False

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                schema_created = True
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                _create_pre_migration_subscriptions_table(connection)

                # RED: before the migration, the known-bad row still holds the
                # non-canonical spelling, and a healthy row is untouched.
                assert (
                    connection.execute(
                        text("SELECT billing_interval FROM subscriptions WHERE id = 2")
                    ).scalar_one()
                    == "monthly"
                )

                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()

                # GREEN: every non-canonical row now reads the canonical value.
                assert (
                    connection.execute(
                        text("SELECT billing_interval FROM subscriptions WHERE id = 2")
                    ).scalar_one()
                    == "month"
                )
                assert (
                    connection.execute(
                        text("SELECT billing_interval FROM subscriptions WHERE id = 4")
                    ).scalar_one()
                    == "month"
                )

                # Rows already canonical are untouched (and, for the annual
                # row, specifically not coerced to month).
                assert (
                    connection.execute(
                        text("SELECT billing_interval FROM subscriptions WHERE id = 1")
                    ).scalar_one()
                    == "month"
                )
                assert (
                    connection.execute(
                        text("SELECT billing_interval FROM subscriptions WHERE id = 3")
                    ).scalar_one()
                    == "year"
                )

                remaining_non_canonical = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM subscriptions "
                        "WHERE billing_interval NOT IN ('month', 'year')"
                    )
                ).scalar_one()
                assert remaining_non_canonical == 0

                inspector = inspect(connection)
                columns = {
                    column["name"]
                    for column in inspector.get_columns(SUBSCRIPTIONS_TABLE, schema=schema)
                }
                assert columns == {
                    "id",
                    "stripe_customer_id",
                    "plan_type",
                    "status",
                    "billing_interval",
                }
            finally:
                transaction.rollback()
    finally:
        try:
            if schema_created:
                with engine.begin() as cleanup_connection:
                    cleanup_connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            engine.dispose()
