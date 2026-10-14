"""Contracts for the self-referential provider_subject/external_id cleanup
(SIGV2-1268), mirroring tests/test_billing_interval_backfill_migration.py:

1. Source contracts, always run. They pin the revision chain and confirm the
   migration is a data-only UPDATE with no schema change and a documented
   no-op downgrade.
2. The executable PostgreSQL gate, which runs upgrade() for real against an
   isolated local database:

PROVIDER_SUBJECT_CLEANUP_MIGRATION_TEST_DATABASE_URL=<isolated-url> python -m pytest \
    tests/test_provider_subject_cleanup_migration.py -q
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
from sqlalchemy import create_engine, text

from tests.test_billing_interval_backfill_migration import (
    _validated_local_test_database_url,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20261019_010000_clear_self_referential_provider_subject.py"
)
REVISION = "20261019_010000"
DOWN_REVISION = "20261018_010000"


def _migration_source() -> str:
    assert MIGRATION_PATH.exists(), f"Missing migration: {MIGRATION_PATH.name}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "provider_subject_cleanup_migration", MIGRATION_PATH
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


# ---------------------------------------------------------------------------
# 1. Source contracts
# ---------------------------------------------------------------------------


def test_migration_chains_onto_the_current_head_without_branching() -> None:
    source = _migration_source()

    assert re.search(rf'^revision\s*=\s*["\']{REVISION}["\']', source, flags=re.MULTILINE)
    assert re.search(rf'^down_revision\s*=\s*["\']{DOWN_REVISION}["\']', source, flags=re.MULTILINE)

    script_directory = _script_directory()
    heads = script_directory.get_heads()
    assert len(heads) == 1, heads
    ancestors = {
        script_revision.revision
        for script_revision in script_directory.iterate_revisions(heads[0], None, inclusive=True)
    }
    assert REVISION in ancestors


def test_upgrade_is_data_only_updates_with_no_schema_change() -> None:
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
    assert "provider_subject" in upgrade_body
    assert "external_id" in upgrade_body


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


def _create_pre_migration_users_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                provider_subject TEXT,
                external_id TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO users (id, email, provider_subject, external_id)
            VALUES
                (1, 'selfref@example.com', '1', '1'),
                (2, 'real-subject@example.com', 'ms-sub-abc', 'ms-ext-abc'),
                (3, 'half@example.com', 'ms-sub-def', '3'),
                (4, 'nulls@example.com', NULL, NULL)
            """
        )
    )


def test_migration_clears_self_referential_subjects_on_isolated_postgresql() -> None:
    raw_database_url = os.environ.get("PROVIDER_SUBJECT_CLEANUP_MIGRATION_TEST_DATABASE_URL")
    if not raw_database_url:
        pytest.skip(
            "Set PROVIDER_SUBJECT_CLEANUP_MIGRATION_TEST_DATABASE_URL to an isolated "
            "PostgreSQL database and run this test explicitly for final migration "
            "acceptance."
        )
    database_url = _validated_local_test_database_url(raw_database_url)

    migration = _load_migration_module()
    engine = create_engine(database_url)
    schema = f"provider_subject_cleanup_{uuid4().hex}"

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                _create_pre_migration_users_table(connection)

                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()

                rows = {
                    row.id: (row.provider_subject, row.external_id)
                    for row in connection.execute(
                        text("SELECT id, provider_subject, external_id FROM users ORDER BY id")
                    )
                }
                # Own-id values are provably ours and are cleared.
                assert rows[1] == (None, None)
                # Genuine provider subjects are left alone.
                assert rows[2] == ("ms-sub-abc", "ms-ext-abc")
                # Mixed rows clear only the self-referential column.
                assert rows[3] == ("ms-sub-def", None)
                # Already-NULL rows stay NULL.
                assert rows[4] == (None, None)

                # Idempotent: a second run updates nothing and does not raise.
                migration.upgrade()
                assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 4
                assert rows == {
                    row.id: (row.provider_subject, row.external_id)
                    for row in connection.execute(
                        text("SELECT id, provider_subject, external_id FROM users ORDER BY id")
                    )
                }

                transaction.commit()
            except Exception:
                transaction.rollback()
                raise
    finally:
        engine.dispose()
