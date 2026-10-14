from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260307_090000_add_pricing_v3_shadow_mode.py"
    )
    spec = importlib.util.spec_from_file_location("pricing_v3_shadow_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pricing_v3_shadow_migration_backfills_legacy_false_flags(monkeypatch) -> None:
    module = _load_migration_module()
    executed_sql: list[str] = []

    monkeypatch.setattr(module.op, "execute", lambda statement: executed_sql.append(str(statement)))

    module._backfill_legacy_pricing_flags()

    assert executed_sql
    assert "UPDATE operational_settings" in executed_sql[0]
    assert "SET pricing_v2_enabled = true" in executed_sql[0]
    assert "credit_engine_v2_enabled = true" in executed_sql[0]
    assert "WHERE pricing_v2_enabled = false" in executed_sql[0]
    assert "AND credit_engine_v2_enabled = false" in executed_sql[0]
