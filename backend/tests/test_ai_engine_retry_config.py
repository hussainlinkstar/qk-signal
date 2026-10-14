import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.ai_engine import AIFactory


def test_provider_retry_config_uses_global_defaults(monkeypatch):
    monkeypatch.setenv("AI_RETRY_COUNT", "5")
    monkeypatch.setenv("AI_RETRY_BASE_DELAY", "0.9")
    monkeypatch.setenv("AI_RETRY_MAX_DELAY", "7.5")

    ai = AIFactory()

    # Bedrock-only: it is the single reasoning provider with a retry config.
    assert ai.provider_retry_config["bedrock"]["retries"] == 5
    assert ai.provider_retry_config["bedrock"]["base_delay"] == 0.9
    assert ai.provider_retry_config["bedrock"]["max_delay"] == 7.5


def test_provider_retry_config_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("AI_RETRY_COUNT", "3")
    monkeypatch.setenv("AI_RETRY_COUNT_BEDROCK", "9")
    monkeypatch.setenv("AI_RETRY_BASE_DELAY_BEDROCK", "1.2")
    monkeypatch.setenv("AI_RETRY_MAX_DELAY_BEDROCK", "8.1")

    ai = AIFactory()

    assert ai.provider_retry_config["bedrock"]["retries"] == 9
    assert ai.provider_retry_config["bedrock"]["base_delay"] == 1.2
    assert ai.provider_retry_config["bedrock"]["max_delay"] == 8.1
