import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.ai_provider_runtime_service import AIProviderRuntimeStateService


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self.values[key] = value
        self.ttls[key] = ttl

    def delete(self, key: str):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


def test_mark_provider_failure_sets_quota_block_and_success_clears_it(monkeypatch) -> None:
    fake_redis = FakeRedis()
    service = AIProviderRuntimeStateService(redis_client=fake_redis)
    monkeypatch.setattr(service, "is_provider_configured", lambda provider: provider == "google")

    service.mark_provider_failure(
        "google",
        error_code="provider_quota_exhausted",
        detail="quota exhausted",
    )
    status = service.get_status("google")

    assert status.available is False
    assert status.state == "quota_blocked"
    assert status.error_code == "provider_quota_exhausted"

    service.mark_provider_success("google")
    healthy_status = service.get_status("google")

    assert healthy_status.available is True
    assert healthy_status.state == "healthy"


def test_expired_runtime_block_is_cleared_on_read(monkeypatch) -> None:
    fake_redis = FakeRedis()
    service = AIProviderRuntimeStateService(redis_client=fake_redis)
    monkeypatch.setattr(service, "is_provider_configured", lambda provider: provider == "openai")

    service.mark_provider_failure(
        "openai",
        error_code="provider_unavailable",
        detail="transient outage",
        block_seconds=1,
    )
    time.sleep(1.1)
    status = service.get_status("openai")

    assert status.available is True
    assert status.state == "healthy"


class _FakeSettings:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_openrouter_and_openai_providers_are_retired(monkeypatch) -> None:
    # The OpenRouter unified gateway and the OpenAI provider were removed
    # (engine runs on Bedrock). No OPENROUTER/OPENAI key can configure providers.
    import services.ai_provider_runtime_service as mod

    monkeypatch.setattr(mod, "settings", _FakeSettings())
    monkeypatch.setattr(mod, "effective_gemini_api_key_from_env", lambda: None)
    service = AIProviderRuntimeStateService(redis_client=FakeRedis())

    for provider in ("google", "openai", "anthropic", "xai", "deepseek"):
        assert service.is_provider_configured(provider) is False
    assert service.is_provider_configured("bogus") is False


def test_direct_keys_configure_individual_providers(monkeypatch) -> None:
    import services.ai_provider_runtime_service as mod

    monkeypatch.setattr(
        mod,
        "settings",
        _FakeSettings(
            ANTHROPIC_API_KEY=None,
            XAI_API_KEY="xai-key",
            DEEPSEEK_API_KEY=None,
        ),
    )
    monkeypatch.setattr(mod, "effective_gemini_api_key_from_env", lambda: "gemini-key")
    service = AIProviderRuntimeStateService(redis_client=FakeRedis())

    assert service.is_provider_configured("google") is True
    assert service.is_provider_configured("xai") is True
    # OpenAI provider was retired — it is never reported as configured now.
    assert service.is_provider_configured("openai") is False
    assert service.is_provider_configured("anthropic") is False
    assert service.is_provider_configured("deepseek") is False
