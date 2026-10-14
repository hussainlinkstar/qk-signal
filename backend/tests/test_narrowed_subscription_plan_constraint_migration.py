"""Contracts for the migration that narrows the canonical subscription plan constraint.

Three layers, mirroring tests/test_canonical_subscription_plan_migration.py:

1. Source contracts, always run. They pin the revision chain, the constraint
   name, the allowed-value lists in both directions, and the refusal to mutate
   billing rows.
2. A SQLite behaviour check, always run. It installs the exact CHECK expression
   the migration builds and proves it rejects 'plan_global_enterprise' while
   still accepting every supported plan ID.
3. The executable PostgreSQL gate, which runs upgrade() and downgrade() for
   real against an isolated database:

NARROWED_PLAN_MIGRATION_TEST_DATABASE_URL=<isolated-url> python -m pytest \
    tests/test_narrowed_subscription_plan_constraint_migration.py -q
"""

import importlib.util
import os
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260731_010000_narrow_subscription_plan_type_constraint.py"
)
CONSTRAINT_NAME = "ck_subscriptions_plan_type_canonical"
RETIRED_PLAN_TYPE = "plan_global_enterprise"
SUPPORTED_PLAN_TYPES = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)
SELF_SERVICE_PLAN_TYPES = (
    "plan_starter",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)
PREVIOUS_PLAN_TYPES = (*SUPPORTED_PLAN_TYPES, RETIRED_PLAN_TYPE)
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
    assert MIGRATION_PATH.exists(), f"Missing narrowing migration: {MIGRATION_PATH.name}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _load_migration_module():
    assert MIGRATION_PATH.exists(), f"Missing narrowing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "narrowed_subscription_plan_constraint_migration", MIGRATION_PATH
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


def test_narrowing_migration_chains_onto_the_applied_canonicalization() -> None:
    source = _migration_source()

    assert re.search(r'^revision\s*=\s*["\']20260731_010000["\']', source, flags=re.MULTILINE)
    assert re.search(r'^down_revision\s*=\s*["\']20260730_010000["\']', source, flags=re.MULTILINE)


def test_migration_history_has_exactly_one_head_and_it_is_the_narrowing_revision() -> None:
    script_directory = _script_directory()

    # The narrowing revision stopped being head a long time ago; migrations
    # keep landing on top of it. The point of this test is branching, so it
    # asserts exactly that: one head, and the narrowing revision on the path
    # to it. Naming the current head here made every later migration fail a
    # test about a different concern.
    heads = script_directory.get_heads()
    assert len(heads) == 1, heads
    ancestors = {
        script_revision.revision
        for script_revision in script_directory.iterate_revisions(heads[0], None, inclusive=True)
    }
    assert "20260731_010000" in ancestors


def test_applied_canonicalization_migration_is_left_untouched() -> None:
    applied_source = (
        BACKEND_ROOT
        / "alembic"
        / "versions"
        / "20260730_010000_canonicalize_subscription_plan_types.py"
    ).read_text(encoding="utf-8")

    assert RETIRED_PLAN_TYPE in applied_source


def test_narrowed_allowed_list_drops_only_the_retired_plan() -> None:
    migration = _load_migration_module()

    assert migration.SUPPORTED_PLAN_TYPES == SUPPORTED_PLAN_TYPES
    assert RETIRED_PLAN_TYPE not in migration.SUPPORTED_PLAN_TYPES
    assert set(migration.PREVIOUS_PLAN_TYPES) - set(migration.SUPPORTED_PLAN_TYPES) == {
        RETIRED_PLAN_TYPE
    }
    assert set(SELF_SERVICE_PLAN_TYPES).issubset(migration.SUPPORTED_PLAN_TYPES)


def test_narrowed_allowed_list_matches_the_application_plan_catalog() -> None:
    from app.config.plans import CANONICAL_PLAN_TYPES

    migration = _load_migration_module()

    assert tuple(CANONICAL_PLAN_TYPES) == migration.SUPPORTED_PLAN_TYPES


def test_downgrade_restores_the_previous_wider_allowed_list() -> None:
    migration = _load_migration_module()

    assert migration.PREVIOUS_PLAN_TYPES == PREVIOUS_PLAN_TYPES
    assert migration._plan_check(migration.PREVIOUS_PLAN_TYPES) == (
        "plan_type IN ('plan_starter', 'plan_agency_trial', 'plan_standard', "
        "'plan_specialist', 'plan_executive', 'plan_global_enterprise')"
    )


def test_migration_reuses_the_existing_constraint_name_and_validates_it() -> None:
    migration = _load_migration_module()
    compact_source = " ".join(_migration_source().lower().split())

    assert migration.CONSTRAINT_NAME == CONSTRAINT_NAME
    assert "drop constraint if exists" in compact_source
    assert "not valid" in compact_source
    assert "validate constraint {constraint_name}" in compact_source
    assert "lock_timeout" in compact_source
    assert "statement_timeout" in compact_source


def test_migration_never_rewrites_or_deletes_subscription_rows() -> None:
    compact_source = " ".join(_migration_source().lower().split())

    assert "update subscriptions" not in compact_source
    assert "delete from" not in compact_source
    assert "truncate" not in compact_source
    assert "drop table" not in compact_source
    assert "drop column" not in compact_source
    assert "raise runtimeerror" in compact_source


# ---------------------------------------------------------------------------
# 2. Always-on behaviour of the installed CHECK expression
# ---------------------------------------------------------------------------


def _sqlite_accepts(check_expression: str, plan_type: str) -> bool:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE subscriptions ("
            "id INTEGER PRIMARY KEY, plan_type TEXT NOT NULL, "
            f"CONSTRAINT {CONSTRAINT_NAME} CHECK ({check_expression}))"
        )
        try:
            connection.execute(
                "INSERT INTO subscriptions (id, plan_type) VALUES (1, ?)", (plan_type,)
            )
        except sqlite3.IntegrityError:
            return False
        return True
    finally:
        connection.close()


@pytest.mark.parametrize("plan_type", SUPPORTED_PLAN_TYPES)
def test_narrowed_check_expression_accepts_every_supported_plan(plan_type: str) -> None:
    migration = _load_migration_module()

    assert _sqlite_accepts(migration._plan_check(migration.SUPPORTED_PLAN_TYPES), plan_type)


@pytest.mark.parametrize(
    "plan_type",
    (
        RETIRED_PLAN_TYPE,
        "global_enterprise",
        " plan_executive",
        "plan_executive ",
        "Plan_Executive",
        "plan_unknown",
    ),
)
def test_narrowed_check_expression_rejects_retired_and_noncanonical_plans(plan_type: str) -> None:
    migration = _load_migration_module()

    assert not _sqlite_accepts(migration._plan_check(migration.SUPPORTED_PLAN_TYPES), plan_type)


def test_previous_check_expression_still_accepted_the_retired_plan() -> None:
    migration = _load_migration_module()

    assert _sqlite_accepts(migration._plan_check(migration.PREVIOUS_PLAN_TYPES), RETIRED_PLAN_TYPE)


# ---------------------------------------------------------------------------
# 3. Executable PostgreSQL gate
# ---------------------------------------------------------------------------


def _create_subscriptions_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY,
                plan_type TEXT NOT NULL,
                status TEXT NOT NULL,
                cancel_at_period_end BOOLEAN NOT NULL,
                billing_interval TEXT NOT NULL,
                CONSTRAINT ck_subscriptions_plan_type_canonical CHECK (
                    plan_type IN (
                        'plan_starter',
                        'plan_agency_trial',
                        'plan_standard',
                        'plan_specialist',
                        'plan_executive',
                        'plan_global_enterprise'
                    )
                )
            )
            """
        )
    )


_INSERT_PLAN = text(
    """
    INSERT INTO subscriptions (id, plan_type, status, cancel_at_period_end, billing_interval)
    VALUES (:id, :plan_type, 'active', false, 'month')
    """
)


def test_narrowing_migration_executes_safely_on_isolated_postgresql() -> None:
    raw_database_url = os.environ.get("NARROWED_PLAN_MIGRATION_TEST_DATABASE_URL")
    if not raw_database_url:
        pytest.skip(
            "Set NARROWED_PLAN_MIGRATION_TEST_DATABASE_URL to an isolated PostgreSQL database "
            "and run this test explicitly for final migration acceptance."
        )
    database_url = _validated_local_test_database_url(raw_database_url)

    migration = _load_migration_module()
    assert _script_directory().get_heads() == [migration.revision]

    engine = create_engine(database_url)
    schema = f"narrowed_plan_{uuid4().hex}"
    schema_created = False

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                schema_created = True
                connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                _create_subscriptions_table(connection)

                # A row on the retired plan must stop the migration, not be rewritten.
                connection.execute(_INSERT_PLAN, {"id": 1, "plan_type": RETIRED_PLAN_TYPE})
                migration.op = Operations(MigrationContext.configure(connection))
                with pytest.raises(RuntimeError) as refusal:
                    migration.upgrade()
                assert "subscriptions.plan_type" in str(refusal.value)
                assert f"{{{RETIRED_PLAN_TYPE!r}: 1}}" in str(refusal.value)
                assert (
                    connection.execute(
                        text("SELECT plan_type FROM subscriptions WHERE id = 1")
                    ).scalar_one()
                    == RETIRED_PLAN_TYPE
                )

                connection.execute(text("DELETE FROM subscriptions WHERE id = 1"))
                for index, plan_type in enumerate(SUPPORTED_PLAN_TYPES, start=10):
                    connection.execute(_INSERT_PLAN, {"id": index, "plan_type": plan_type})

                migration.upgrade()

                constraint_validated = connection.execute(
                    text(
                        """
                        SELECT constraint_record.convalidated
                        FROM pg_constraint AS constraint_record
                        JOIN pg_class AS table_record
                          ON table_record.oid = constraint_record.conrelid
                        JOIN pg_namespace AS schema_record
                          ON schema_record.oid = table_record.relnamespace
                        WHERE constraint_record.conname = :constraint_name
                          AND schema_record.nspname = :schema
                        """
                    ),
                    {"constraint_name": CONSTRAINT_NAME, "schema": schema},
                ).scalar_one()
                assert constraint_validated is True

                # Every supported plan survived and is still insertable.
                assert set(
                    connection.execute(text("SELECT plan_type FROM subscriptions")).scalars()
                ) == set(SUPPORTED_PLAN_TYPES)
                for index, plan_type in enumerate(SUPPORTED_PLAN_TYPES, start=100):
                    with connection.begin_nested():
                        connection.execute(_INSERT_PLAN, {"id": index, "plan_type": plan_type})

                # The retired plan is now rejected.
                for rejected_plan_type in (RETIRED_PLAN_TYPE, "global_enterprise", "plan_unknown"):
                    with pytest.raises(IntegrityError):
                        with connection.begin_nested():
                            connection.execute(
                                _INSERT_PLAN, {"id": 900, "plan_type": rejected_plan_type}
                            )

                # Reversible: downgrade restores the previous wider list.
                migration.downgrade()
                with connection.begin_nested():
                    connection.execute(_INSERT_PLAN, {"id": 901, "plan_type": RETIRED_PLAN_TYPE})
                assert (
                    connection.execute(
                        text("SELECT plan_type FROM subscriptions WHERE id = 901")
                    ).scalar_one()
                    == RETIRED_PLAN_TYPE
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
