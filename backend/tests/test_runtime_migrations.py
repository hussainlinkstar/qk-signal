import os
import sys
from pathlib import Path

os.environ.setdefault("SSM_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import runtime_migrations


def test_apply_pending_migrations_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MIGRATIONS", "0")

    upgrade_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        runtime_migrations.command,
        "upgrade",
        lambda config, revision: upgrade_calls.append((config, revision)),
    )

    assert runtime_migrations.apply_pending_migrations_if_needed() is False
    assert upgrade_calls == []


def test_apply_pending_migrations_noops_when_database_is_current(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MIGRATIONS", "1")
    config = object()

    monkeypatch.setattr(runtime_migrations, "_build_alembic_config", lambda: config)
    monkeypatch.setattr(
        runtime_migrations,
        "_resolve_current_and_head_revisions",
        lambda _config: (("20260303_070000",), ("20260303_070000",)),
    )

    upgrade_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        runtime_migrations.command,
        "upgrade",
        lambda config_value, revision: upgrade_calls.append((config_value, revision)),
    )

    assert runtime_migrations.apply_pending_migrations_if_needed() is False
    assert upgrade_calls == []


def test_apply_pending_migrations_upgrades_when_head_is_ahead(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MIGRATIONS", "1")
    config = object()

    monkeypatch.setattr(runtime_migrations, "_build_alembic_config", lambda: config)
    monkeypatch.setattr(
        runtime_migrations,
        "_resolve_current_and_head_revisions",
        lambda _config: (("20260303_060000",), ("20260303_070000",)),
    )

    upgrade_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        runtime_migrations.command,
        "upgrade",
        lambda config_value, revision: upgrade_calls.append((config_value, revision)),
    )

    assert runtime_migrations.apply_pending_migrations_if_needed() is True
    assert upgrade_calls == [(config, "head")]
