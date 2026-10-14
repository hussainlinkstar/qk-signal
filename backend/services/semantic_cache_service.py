from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.redis_client import get_sync_redis_client

logger = logging.getLogger(__name__)

SEMANTIC_CACHE_PREFIX = os.getenv("SEMANTIC_CACHE_PREFIX", "semantic-cache")
SEMANTIC_CACHE_DEFAULT_TTL_SECONDS = int(os.getenv("SEMANTIC_CACHE_DEFAULT_TTL_SECONDS", "21600"))
SEMANTIC_CACHE_PRE_SCAN_TTL_SECONDS = int(
    os.getenv("SEMANTIC_CACHE_PRE_SCAN_TTL_SECONDS", str(SEMANTIC_CACHE_DEFAULT_TTL_SECONDS))
)
SEMANTIC_CACHE_SITE_CLASSIFY_TTL_SECONDS = int(
    os.getenv(
        "SEMANTIC_CACHE_SITE_CLASSIFY_TTL_SECONDS",
        str(SEMANTIC_CACHE_DEFAULT_TTL_SECONDS),
    )
)

_FEATURE_TTLS = {
    "audit.pre_scan": SEMANTIC_CACHE_PRE_SCAN_TTL_SECONDS,
    "site.classify": SEMANTIC_CACHE_SITE_CLASSIFY_TTL_SECONDS,
}


def _stable_json_dumps(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    )


class SemanticCacheService:
    def __init__(self, *, redis_client: Any | None = None):
        self._redis_client = redis_client

    def _get_client(self):
        if self._redis_client is not None:
            return self._redis_client
        return get_sync_redis_client()

    def _resolve_ttl_seconds(self, feature_key: str, ttl_seconds: int | None) -> int:
        if ttl_seconds is not None:
            return max(1, int(ttl_seconds))
        return max(1, _FEATURE_TTLS.get(feature_key, SEMANTIC_CACHE_DEFAULT_TTL_SECONDS))

    def build_key(
        self,
        *,
        feature_key: str,
        route_provider: str,
        route_tier: str,
        semantic_payload: Any,
        version: str = "v1",
    ) -> str:
        fingerprint = hashlib.sha256(
            _stable_json_dumps(semantic_payload).encode("utf-8")
        ).hexdigest()
        return (
            f"{SEMANTIC_CACHE_PREFIX}:{version}:{feature_key}:"
            f"{route_provider}:{route_tier}:{fingerprint}"
        )

    def get_json(
        self,
        *,
        feature_key: str,
        route_provider: str,
        route_tier: str,
        semantic_payload: Any,
        version: str = "v1",
    ) -> dict[str, Any] | None:
        cache_key = self.build_key(
            feature_key=feature_key,
            route_provider=route_provider,
            route_tier=route_tier,
            semantic_payload=semantic_payload,
            version=version,
        )
        try:
            raw_value = self._get_client().get(cache_key)
            if not raw_value:
                return None
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.warning("Semantic cache read failed for %s: %s", feature_key, exc)
            return None

    def set_json(
        self,
        *,
        feature_key: str,
        route_provider: str,
        route_tier: str,
        semantic_payload: Any,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
        version: str = "v1",
    ) -> None:
        cache_key = self.build_key(
            feature_key=feature_key,
            route_provider=route_provider,
            route_tier=route_tier,
            semantic_payload=semantic_payload,
            version=version,
        )
        cache_entry = {
            "response": value,
            "metadata": {
                "feature_key": feature_key,
                "route_provider": route_provider,
                "route_tier": route_tier,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        try:
            self._get_client().setex(
                cache_key,
                self._resolve_ttl_seconds(feature_key, ttl_seconds),
                _stable_json_dumps(cache_entry),
            )
        except Exception as exc:
            logger.warning("Semantic cache write failed for %s: %s", feature_key, exc)


semantic_cache_service = SemanticCacheService()
