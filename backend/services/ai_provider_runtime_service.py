from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.redis_client import get_sync_redis_client

try:
    from core.config import effective_gemini_api_key_from_env
    from core.config import settings
except Exception:  # pragma: no cover - stripped test env fallback

    def effective_gemini_api_key_from_env() -> str | None:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    class _FallbackSettings:
        ANTHROPIC_API_KEY = None

    settings = _FallbackSettings()

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = frozenset({"google", "openai", "anthropic", "xai", "deepseek"})

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
AI_PROVIDER_RUNTIME_PREFIX = os.getenv("AI_PROVIDER_RUNTIME_PREFIX", "ai-provider-runtime")
AI_PROVIDER_QUOTA_COOLDOWN_SECONDS = int(os.getenv("AI_PROVIDER_QUOTA_COOLDOWN_SECONDS", "900"))
AI_PROVIDER_UNAVAILABLE_COOLDOWN_SECONDS = int(
    os.getenv("AI_PROVIDER_UNAVAILABLE_COOLDOWN_SECONDS", "60")
)
AI_PROVIDER_AUTH_COOLDOWN_SECONDS = int(os.getenv("AI_PROVIDER_AUTH_COOLDOWN_SECONDS", "300"))
AI_PROVIDER_CONFIG_COOLDOWN_SECONDS = int(os.getenv("AI_PROVIDER_CONFIG_COOLDOWN_SECONDS", "300"))


@dataclass(frozen=True)
class ProviderRuntimeStatus:
    provider: str
    configured: bool
    available: bool
    state: str
    reason: str | None = None
    blocked_until: float | None = None
    error_code: str | None = None


class AIProviderRuntimeStateService:
    def __init__(self, *, redis_client: Any | None = None, redis_url: str = REDIS_URL):
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._owned_redis_client = None
        self._memory_store: dict[str, dict[str, Any]] = {}

    def _get_client(self):
        if self._redis_client is not None:
            return self._redis_client
        if self._owned_redis_client is not None:
            return self._owned_redis_client
        try:
            self._owned_redis_client = get_sync_redis_client()
            return self._owned_redis_client
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to create redis client for provider runtime state: %s", exc)
            return None

    @staticmethod
    def _normalize_provider(provider: str | None) -> str:
        return str(provider or "").strip().lower()

    def _key(self, provider: str) -> str:
        return f"{AI_PROVIDER_RUNTIME_PREFIX}:{provider}"

    def is_provider_configured(self, provider: str) -> bool:
        normalized = self._normalize_provider(provider)
        if normalized not in _SUPPORTED_PROVIDERS:
            return False
        # The OpenRouter unified gateway and the OpenAI provider were retired
        # (engine runs on Bedrock; no OpenAI/OpenRouter API keys remain).
        if normalized == "google":
            return bool(effective_gemini_api_key_from_env())
        if normalized == "anthropic":
            return bool(getattr(settings, "ANTHROPIC_API_KEY", None))
        if normalized == "xai":
            return bool(getattr(settings, "XAI_API_KEY", None))
        if normalized == "deepseek":
            return bool(getattr(settings, "DEEPSEEK_API_KEY", None))
        return False

    def _clear_if_expired(
        self, provider: str, payload: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        blocked_until = payload.get("blocked_until")
        try:
            blocked_until_value = float(blocked_until) if blocked_until is not None else None
        except (TypeError, ValueError):
            blocked_until_value = None
        if blocked_until_value is not None and blocked_until_value <= time.time():
            self.clear(provider)
            return None
        return payload

    def _read_payload(self, provider: str) -> dict[str, Any] | None:
        normalized = self._normalize_provider(provider)
        if not normalized:
            return None
        client = self._get_client()
        if client is None:
            return self._clear_if_expired(normalized, self._memory_store.get(normalized))

        try:
            raw_value = client.get(self._key(normalized))
        except Exception as exc:
            logger.warning("Provider runtime state read failed for %s: %s", normalized, exc)
            return None
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except Exception:
            logger.warning("Provider runtime state payload is not valid JSON for %s", normalized)
            return None
        return self._clear_if_expired(normalized, parsed if isinstance(parsed, dict) else None)

    def _write_payload(self, provider: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        normalized = self._normalize_provider(provider)
        if not normalized:
            return
        ttl = max(1, int(ttl_seconds))
        client = self._get_client()
        if client is None:
            self._memory_store[normalized] = dict(payload)
            return
        try:
            client.setex(self._key(normalized), ttl, json.dumps(payload, default=str))
        except Exception as exc:
            logger.warning("Provider runtime state write failed for %s: %s", normalized, exc)

    def clear(self, provider: str) -> None:
        normalized = self._normalize_provider(provider)
        if not normalized:
            return
        self._memory_store.pop(normalized, None)
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(self._key(normalized))
        except Exception as exc:
            logger.warning("Provider runtime state delete failed for %s: %s", normalized, exc)

    def get_status(self, provider: str) -> ProviderRuntimeStatus:
        normalized = self._normalize_provider(provider)
        configured = self.is_provider_configured(normalized)
        if not configured:
            return ProviderRuntimeStatus(
                provider=normalized,
                configured=False,
                available=False,
                state="not_configured",
                reason="provider_not_configured",
                error_code="provider_config_error",
            )

        payload = self._read_payload(normalized)
        if payload is None:
            return ProviderRuntimeStatus(
                provider=normalized,
                configured=True,
                available=True,
                state="healthy",
            )

        blocked_until = payload.get("blocked_until")
        try:
            blocked_until_value = float(blocked_until) if blocked_until is not None else None
        except (TypeError, ValueError):
            blocked_until_value = None

        return ProviderRuntimeStatus(
            provider=normalized,
            configured=True,
            available=False,
            state=str(payload.get("state") or "temporarily_unavailable"),
            reason=str(
                payload.get("reason") or payload.get("error_code") or "provider_unavailable"
            ),
            blocked_until=blocked_until_value,
            error_code=(
                str(payload.get("error_code")).strip()
                if payload.get("error_code") is not None
                else None
            ),
        )

    @staticmethod
    def _resolve_failure_ttl(
        error_code: str | None, *, block_seconds: float | None = None
    ) -> tuple[str | None, int | None]:
        normalized = str(error_code or "").strip().lower()
        if normalized == "provider_quota_exhausted":
            ttl = int(block_seconds or AI_PROVIDER_QUOTA_COOLDOWN_SECONDS)
            return "quota_blocked", ttl
        if normalized == "provider_unavailable":
            ttl = int(block_seconds or AI_PROVIDER_UNAVAILABLE_COOLDOWN_SECONDS)
            return "temporarily_unavailable", ttl
        if normalized == "provider_auth_error":
            ttl = int(block_seconds or AI_PROVIDER_AUTH_COOLDOWN_SECONDS)
            return "auth_blocked", ttl
        if normalized == "provider_config_error":
            ttl = int(block_seconds or AI_PROVIDER_CONFIG_COOLDOWN_SECONDS)
            return "config_blocked", ttl
        return None, None

    def mark_provider_failure(
        self,
        provider: str,
        *,
        error_code: str | None,
        detail: str | None = None,
        block_seconds: float | None = None,
    ) -> None:
        state, ttl_seconds = self._resolve_failure_ttl(error_code, block_seconds=block_seconds)
        if state is None or ttl_seconds is None:
            return
        normalized = self._normalize_provider(provider)
        now = time.time()
        self._write_payload(
            normalized,
            {
                "state": state,
                "reason": (str(detail or error_code or state).strip() or state)[:300],
                "error_code": str(error_code or "").strip().lower() or None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "blocked_until": now + ttl_seconds,
            },
            ttl_seconds=ttl_seconds,
        )

    def mark_provider_success(self, provider: str) -> None:
        self.clear(provider)


provider_runtime_state_service = AIProviderRuntimeStateService()
