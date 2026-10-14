"""Static contract for the SIGV2-1186 migration.

The migration is never executed here. Running Alembic is not a verification step
(AGENTS.md 4.2 / FM-01), so what is checked is the source: that it chains onto
the current head, that both columns are additive and nullable, that the upgrade
drops and renames nothing, and that it does not freeze the old text-based guess
into the new column by backfilling it.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20261013_010000_add_visibility_query_search_type.py"
)


def _source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _upgrade_body(source: str) -> str:
    return source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]


def test_migration_exists_and_chains_onto_the_previous_head() -> None:
    source = _source()
    assert re.search(r'^revision\s*=\s*"20261013_010000"', source, flags=re.MULTILINE)
    assert re.search(r'^down_revision\s*=\s*"20261012_010000"', source, flags=re.MULTILINE)


def test_upgrade_adds_both_columns_as_nullable() -> None:
    body = _upgrade_body(_source())
    for column in ("search_type", "origin"):
        assert f'sa.Column("{column}", sa.String(), nullable=True)' in body


def test_upgrade_is_additive_only() -> None:
    body = _upgrade_body(_source()).lower()
    for forbidden in (
        "drop_column",
        "drop_table",
        "drop table",
        "alter_column",
        "set not null",
        "nullable=false",
        "alter_table",
        "truncate",
        "delete from",
    ):
        assert forbidden not in body, forbidden


def test_upgrade_backfills_origin_but_never_search_type() -> None:
    body = _upgrade_body(_source())
    # origin is backfilled, because "the customer wrote it" is provable for
    # every pre-existing row: no generator existed before this change.
    assert "SET origin = 'customer'" in body
    assert "WHERE origin IS NULL" in body
    # search_type is deliberately left NULL. Backfilling the old inference would
    # make a guess indistinguishable from the customer's own choice, which is
    # the defect this ticket removes.
    assert "SET search_type" not in body


def test_downgrade_is_present_and_documented() -> None:
    source = _source()
    downgrade = source.split("def downgrade()", 1)[1]
    assert "drop_column" in downgrade
    # The data loss a downgrade causes is stated, not discovered.
    assert "Never run against a" in downgrade
