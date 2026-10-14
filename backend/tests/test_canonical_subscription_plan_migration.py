"""Preliminary source contracts plus the required executable PostgreSQL 18 gate.

The source checks guide implementation only. They do not prove migration safety. Final
acceptance must run the PostgreSQL integration test in this module against an isolated
PostgreSQL 18 database:

CANONICAL_PLAN_MIGRATION_TEST_DATABASE_URL=<isolated-url> python -m pytest \
    tests/test_canonical_subscription_plan_migration.py::test_canonical_plan_migration_executes_safely_on_isolated_postgresql_18 -q
"""

import ast
import importlib.util
import os
import re
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260730_010000_canonicalize_subscription_plan_types.py"
)
CANONICAL_PLAN_TYPES = frozenset(
    {
        "plan_starter",
        "plan_agency_trial",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
        "plan_global_enterprise",
    }
)
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
PRESERVED_FIELDS = (
    "status",
    "cancel_at_period_end",
    "billing_interval",
    "current_period_end",
    "stripe_customer_id",
    "stripe_subscription_id",
    "stripe_mode",
    "stripe_schedule_id",
    "managed_plan_change_schedule_id",
    "pending_plan_type",
    "pending_billing_interval",
    "pending_change_effective_at",
    "plan_state_event_created_at",
)


def _migration_source() -> str:
    assert MIGRATION_PATH.exists(), f"Missing canonical plan migration: {MIGRATION_PATH.name}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _subscription_updates(source: str) -> list[tuple[str, str]]:
    return re.findall(
        r"UPDATE\s+subscriptions\s+SET\s+(.*?)\s+WHERE\s+(.*?);",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _compact(value: str) -> str:
    return " ".join(value.lower().split())


def _diagnostic_counts(message: str) -> dict[str, int]:
    match = re.search(r"\{.*\}", message, flags=re.DOTALL)
    assert match is not None, f"Expected grouped value/count mapping in: {message}"
    diagnostics = ast.literal_eval(match.group(0))
    assert isinstance(diagnostics, dict)
    return diagnostics


def _load_migration_module():
    assert MIGRATION_PATH.exists(), f"Missing canonical plan migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "canonical_subscription_plan_migration", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cleared_libpq_target_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable_name in LIBPQ_TARGET_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable_name, raising=False)


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


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://user:password@localhost/test_signal",
        "postgresql://user:password@127.0.0.1/signal_test",
        "postgresql://user:password@[::1]/signal_test_migration",
    ),
)
def test_postgresql_acceptance_url_accepts_loopback_test_databases(
    database_url: str,
    cleared_libpq_target_environment: None,
) -> None:
    assert _validated_local_test_database_url(database_url).host in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def test_postgresql_acceptance_url_rejects_remote_host(
    cleared_libpq_target_environment: None,
) -> None:
    with pytest.raises(ValueError, match="loopback"):
        _validated_local_test_database_url("postgresql://user:password@db.example/test_signal")


def test_postgresql_acceptance_url_rejects_non_test_database(
    cleared_libpq_target_environment: None,
) -> None:
    with pytest.raises(ValueError, match="test-specific"):
        _validated_local_test_database_url("postgresql://user:password@localhost/signal")


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://user:password@localhost/test_signal?host=db.example",
        "postgresql://user:password@127.0.0.1/test_signal?hostaddr=203.0.113.10",
        "postgresql://user:password@localhost/test_signal?service=production",
        "postgresql://user:password@localhost/test_signal?dbname=production",
        "postgresql://user:password@localhost/test_signal?port=6543",
    ),
)
def test_postgresql_acceptance_rejects_disguised_remote_target_before_engine_creation(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    cleared_libpq_target_environment: None,
) -> None:
    engine_factory = Mock(side_effect=AssertionError("create_engine must not be called"))
    monkeypatch.setenv("CANONICAL_PLAN_MIGRATION_TEST_DATABASE_URL", database_url)
    monkeypatch.setitem(globals(), "create_engine", engine_factory)

    with pytest.raises(ValueError, match="must not override"):
        test_canonical_plan_migration_executes_safely_on_isolated_postgresql_18()

    engine_factory.assert_not_called()


@pytest.mark.parametrize(
    "variable_name, variable_value",
    (
        ("PGHOST", "db.example"),
        ("PGHOSTADDR", "203.0.113.10"),
        ("PGPORT", "6543"),
        ("PGDATABASE", "production"),
        ("PGSERVICE", "production"),
        ("PGSERVICEFILE", "/tmp/production-pg-service.conf"),
        ("PGPASSFILE", "/tmp/production-pgpass"),
        ("PGSYSCONFDIR", "/tmp/production-pg-config"),
    ),
)
def test_postgresql_acceptance_rejects_ambient_target_before_engine_creation(
    variable_name: str,
    variable_value: str,
    monkeypatch: pytest.MonkeyPatch,
    cleared_libpq_target_environment: None,
) -> None:
    engine_factory = Mock(side_effect=AssertionError("create_engine must not be called"))
    monkeypatch.setenv(
        "CANONICAL_PLAN_MIGRATION_TEST_DATABASE_URL",
        "postgresql://user:password@localhost/test_signal",
    )
    monkeypatch.setenv(variable_name, variable_value)
    monkeypatch.setitem(globals(), "create_engine", engine_factory)

    with pytest.raises(ValueError, match=variable_name):
        test_canonical_plan_migration_executes_safely_on_isolated_postgresql_18()

    engine_factory.assert_not_called()


def test_preliminary_canonical_plan_migration_source_contract_has_current_head_as_predecessor() -> (
    None
):
    source = _migration_source()

    assert re.search(r'revision\s*=\s*["\']20260730_010000["\']', source)
    assert re.search(r'down_revision\s*=\s*["\']20260727_010000["\']', source)


def test_preliminary_canonical_plan_migration_source_contract_backfills_only_exact_global_enterprise() -> (
    None
):
    updates = _subscription_updates(_migration_source())

    assert len(updates) == 1
    assignments, predicate = map(_compact, updates[0])
    assert assignments == "plan_type = 'plan_global_enterprise'"
    assert predicate == "plan_type = 'global_enterprise'"


def test_preliminary_canonical_plan_migration_source_contract_limits_update_assignments_to_plan_type() -> (
    None
):
    updates = _subscription_updates(_migration_source())

    assert updates
    assignments = " ".join(assignment.lower() for assignment, _predicate in updates)
    for field in PRESERVED_FIELDS:
        assert re.search(rf"\b{field}\s*=", assignments) is None


def test_preliminary_canonical_plan_migration_source_contract_rejects_grouped_noncanonical_values() -> (
    None
):
    source = _migration_source()
    compact_source = _compact(source)

    assert re.search(r"select\s+plan_type\s*,\s*count\s*\(\s*\*\s*\)", compact_source)
    assert "where plan_type not in" in compact_source
    assert "group by plan_type" in compact_source
    assert "raise runtimeerror" in compact_source
    for plan_type in CANONICAL_PLAN_TYPES:
        assert plan_type in source


def test_preliminary_canonical_plan_migration_source_contract_adds_and_validates_named_constraint() -> (
    None
):
    source = _migration_source()
    compact_source = _compact(source)

    assert "ck_subscriptions_plan_type_canonical" in source
    assert "not valid" in compact_source
    assert "validate constraint ck_subscriptions_plan_type_canonical" in compact_source
    assert "lock_timeout" in compact_source
    assert "statement_timeout" in compact_source
    for plan_type in CANONICAL_PLAN_TYPES:
        assert plan_type in source


def test_preliminary_canonical_plan_migration_source_contract_is_rerunnable() -> None:
    source = _migration_source()
    compact_source = _compact(source)

    assert "pg_constraint" in compact_source
    assert re.search(r"if\s+not\s+\w*constraint", compact_source)
    assert "where plan_type = 'global_enterprise'" in compact_source


def test_canonical_plan_migration_executes_safely_on_isolated_postgresql_18() -> None:
    raw_database_url = os.environ.get("CANONICAL_PLAN_MIGRATION_TEST_DATABASE_URL")
    if not raw_database_url:
        pytest.skip(
            "Set CANONICAL_PLAN_MIGRATION_TEST_DATABASE_URL to an isolated PostgreSQL 18 database "
            "and run this test explicitly for final migration acceptance."
        )
    database_url = _validated_local_test_database_url(raw_database_url)

    migration = _load_migration_module()
    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    # 20260731_010000 later narrowed this constraint, so this revision is no longer the
    # head. The chain must stay linear, and this revision must remain an ancestor of it.
    script_directory = ScriptDirectory.from_config(alembic_config)
    heads = script_directory.get_heads()
    assert len(heads) == 1
    assert migration.revision in {
        revision.revision for revision in script_directory.iterate_revisions(heads[0], "base")
    }

    engine = create_engine(database_url)
    schema = f"canonical_plan_{uuid4().hex}"
    schema_created = False
    preserved_fields = ", ".join(PRESERVED_FIELDS)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                server_version_num = int(
                    connection.execute(text("SHOW server_version_num")).scalar_one()
                )
                assert server_version_num // 10000 == 18
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                schema_created = True
                connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                connection.execute(
                    text(
                        """
                        CREATE TABLE subscriptions (
                            id INTEGER PRIMARY KEY,
                            plan_type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            cancel_at_period_end BOOLEAN NOT NULL,
                            billing_interval TEXT NOT NULL,
                            current_period_end TIMESTAMPTZ,
                            stripe_customer_id TEXT,
                            stripe_subscription_id TEXT,
                            stripe_mode TEXT,
                            stripe_schedule_id TEXT,
                            managed_plan_change_schedule_id TEXT,
                            pending_plan_type TEXT,
                            pending_billing_interval TEXT,
                            pending_change_effective_at TIMESTAMPTZ,
                            plan_state_event_created_at TIMESTAMPTZ
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO subscriptions (
                            id, plan_type, status, cancel_at_period_end, billing_interval,
                            current_period_end, stripe_customer_id, stripe_subscription_id,
                            stripe_mode, stripe_schedule_id, managed_plan_change_schedule_id,
                            pending_plan_type, pending_billing_interval,
                            pending_change_effective_at, plan_state_event_created_at
                        ) VALUES (
                            1, 'global_enterprise', 'active', true, 'year',
                            '2027-01-01T00:00:00Z', 'cus_legacy', 'sub_legacy',
                            'test', 'sched_legacy', 'managed_legacy',
                            'plan_executive', 'month',
                            '2026-12-01T00:00:00Z', '2026-11-01T00:00:00Z'
                        )
                        """
                    )
                )
                insert_plan = text(
                    """
                    INSERT INTO subscriptions (
                        id, plan_type, status, cancel_at_period_end, billing_interval,
                        stripe_customer_id
                    ) VALUES (:id, :plan_type, 'active', false, 'month', :customer_id)
                    """
                )
                next_id = 10
                for plan_type in sorted(CANONICAL_PLAN_TYPES):
                    connection.execute(
                        insert_plan,
                        {
                            "id": next_id,
                            "plan_type": plan_type,
                            "customer_id": f"cus_seed_{next_id}",
                        },
                    )
                    next_id += 1

                invalid_plan_counts = {
                    " plan_starter": 3,
                    "PLAN_EXECUTIVE": 1,
                    "unexpected_enterprise": 2,
                }
                invalid_row_ids: list[int] = []
                for plan_type, count in invalid_plan_counts.items():
                    for _ in range(count):
                        connection.execute(
                            insert_plan,
                            {
                                "id": next_id,
                                "plan_type": plan_type,
                                "customer_id": f"cus_invalid_{next_id}",
                            },
                        )
                        invalid_row_ids.append(next_id)
                        next_id += 1

                seeded_row_count = 1 + len(CANONICAL_PLAN_TYPES) + sum(invalid_plan_counts.values())
                before = (
                    connection.execute(
                        text(f"SELECT {preserved_fields} FROM subscriptions WHERE id = 1")
                    )
                    .mappings()
                    .one()
                )

                migration.op = Operations(MigrationContext.configure(connection))
                with pytest.raises(RuntimeError) as diagnostic_error:
                    migration.upgrade()
                assert _diagnostic_counts(str(diagnostic_error.value)) == invalid_plan_counts
                for canonical_plan_type in CANONICAL_PLAN_TYPES:
                    assert repr(canonical_plan_type) not in str(diagnostic_error.value)
                assert repr("global_enterprise") not in str(diagnostic_error.value)

                assert (
                    connection.execute(
                        text("SELECT plan_type FROM subscriptions WHERE id = 1")
                    ).scalar_one()
                    == "plan_global_enterprise"
                )
                connection.execute(
                    text(
                        "UPDATE subscriptions SET plan_type = 'plan_starter' "
                        "WHERE id = ANY(:invalid_row_ids)"
                    ),
                    {"invalid_row_ids": invalid_row_ids},
                )
                migration.upgrade()

                migrated = (
                    connection.execute(
                        text(
                            f"SELECT plan_type, {preserved_fields} FROM subscriptions WHERE id = 1"
                        )
                    )
                    .mappings()
                    .one()
                )
                assert migrated["plan_type"] == "plan_global_enterprise"
                assert {field: migrated[field] for field in PRESERVED_FIELDS} == dict(before)

                constraint_validated = connection.execute(
                    text(
                        """
                        SELECT constraint_record.convalidated
                        FROM pg_constraint AS constraint_record
                        JOIN pg_class AS table_record
                          ON table_record.oid = constraint_record.conrelid
                        JOIN pg_namespace AS schema_record
                          ON schema_record.oid = table_record.relnamespace
                        WHERE constraint_record.conname = 'ck_subscriptions_plan_type_canonical'
                          AND schema_record.nspname = :schema
                        """
                    ),
                    {"schema": schema},
                ).scalar_one()
                assert constraint_validated is True

                seeded_canonical_plans = set(
                    connection.execute(
                        text(
                            "SELECT plan_type FROM subscriptions "
                            "WHERE id >= 10 AND id < :invalid_start"
                        ),
                        {"invalid_start": invalid_row_ids[0]},
                    ).scalars()
                )
                assert seeded_canonical_plans == CANONICAL_PLAN_TYPES

                rejected_plan_types = (
                    " plan_starter",
                    "plan_starter ",
                    "Plan_Starter",
                    "global_enterprise",
                    "plan_unknown",
                )
                for plan_type in rejected_plan_types:
                    with pytest.raises(IntegrityError):
                        with connection.begin_nested():
                            connection.execute(
                                text(
                                    """
                                    INSERT INTO subscriptions (
                                        id, plan_type, status,
                                        cancel_at_period_end, billing_interval
                                    ) VALUES (
                                        :id, :plan_type, 'active', false, 'month'
                                    )
                                    """
                                ),
                                {"id": next_id, "plan_type": plan_type},
                            )
                    next_id += 1

                migration.upgrade()
                assert (
                    connection.execute(text("SELECT count(*) FROM subscriptions")).scalar_one()
                    == seeded_row_count
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
