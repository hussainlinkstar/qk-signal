from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

logger = logging.getLogger(__name__)

_MIGRATION_LOCK = Lock()


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def runtime_migrations_enabled() -> bool:
    return _parse_bool(os.getenv("RUN_MIGRATIONS"), default=True)


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _build_alembic_config() -> Config:
    backend_dir = _backend_dir()
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)

    return config


def _resolve_current_and_head_revisions(config: Config) -> tuple[tuple[str, ...], tuple[str, ...]]:
    script = ScriptDirectory.from_config(config)
    head_revisions = tuple(script.get_heads())
    database_url = config.get_main_option("sqlalchemy.url")

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_revisions = tuple(context.get_current_heads())
    finally:
        engine.dispose()

    return current_revisions, head_revisions


def _format_revisions(revisions: tuple[str, ...]) -> str:
    if not revisions:
        return "base"
    return ", ".join(revisions)


def apply_pending_migrations_if_needed() -> bool:
    if not runtime_migrations_enabled():
        logger.info("Skipping startup migrations because RUN_MIGRATIONS is disabled.")
        return False

    with _MIGRATION_LOCK:
        config = _build_alembic_config()
        current_revisions, head_revisions = _resolve_current_and_head_revisions(config)

        if set(current_revisions) == set(head_revisions):
            logger.info(
                "Database already at Alembic head (current=%s).",
                _format_revisions(current_revisions),
            )
            return False

        logger.info(
            "Applying Alembic migrations during app startup (current=%s, head=%s).",
            _format_revisions(current_revisions),
            _format_revisions(head_revisions),
        )
        command.upgrade(config, "head")
        logger.info(
            "Alembic migrations applied successfully (head=%s).",
            _format_revisions(head_revisions),
        )
        return True
