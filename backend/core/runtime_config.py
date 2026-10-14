"""Compatibility layer for runtime-editable configuration keys.

The shared registry and payload cache now live in `services.configuration_service`.
This module keeps the historical import surface intact for admin pages, workers,
and tests while delegating all reads and writes to the unified service.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from services.configuration_service import (
    RUNTIME_CONFIGURABLE_KEYS,
    configuration_service,
    is_sensitive_key,
    mask_value,
)

# Re-exported for the historical import surface relied on by admin pages,
# workers, and tests. Declared in ``__all__`` so lint "unused import" passes
# do not strip these compatibility re-exports.
__all__ = [
    "RUNTIME_CONFIGURABLE_KEYS",
    "is_sensitive_key",
    "mask_value",
    "invalidate_cache",
    "get_runtime_overrides",
    "get_config_value",
    "validate_config_value",
    "coerce_value",
]

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0


def invalidate_cache() -> None:
    global _cache_ts
    configuration_service.invalidate_cache()
    _cache.clear()
    _cache_ts = 0.0


def get_runtime_overrides(db: Session) -> dict[str, Any]:
    global _cache_ts
    overrides = configuration_service.get_runtime_overrides(db)
    _cache.clear()
    _cache.update(overrides)
    _cache_ts = time.time()
    return dict(overrides)


def get_config_value(key: str, db: Session) -> Any:
    return configuration_service.resolve_value(key, db=db)


def validate_config_value(key: str, value: Any) -> tuple[bool, str]:
    return configuration_service.validate_runtime_value(key, value)


def coerce_value(key: str, value: Any) -> Any:
    return configuration_service.coerce_runtime_value(key, value)
