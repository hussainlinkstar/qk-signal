import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings

# The seven REAL consumer engines measurable via OpenRouter. Bing is excluded
# on purpose — there is no public consumer API to measure it live, so it stays
# on the controlled Bedrock panel.
EXPECTED_ENGINES = {
    "openai",
    "google",
    "anthropic",
    "xai",
    "perplexity",
    "deepseek",
    "meta",
}


def test_openrouter_settings_load_with_safe_defaults():
    # SIGV2-1023: flag defaults ON — live measurement is enabled for all plans.
    assert settings.LIVE_ENGINE_MEASUREMENT_ENABLED is True
    # Key defaults empty (real value provisioned by a human into SSM/.env).
    assert settings.OPENROUTER_API_KEY == ""
    assert settings.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


def test_model_map_covers_the_seven_engines():
    model_map = settings.OPENROUTER_MEASUREMENT_MODEL_MAP
    assert isinstance(model_map, dict)
    assert set(model_map.keys()) == EXPECTED_ENGINES
    # Every mapped id is a non-empty OpenRouter "vendor/model" string.
    for engine, model_id in model_map.items():
        assert isinstance(model_id, str) and "/" in model_id, engine


def test_bing_has_no_openrouter_entry():
    # Bing/Copilot has no public consumer API on OpenRouter — must not be mapped.
    assert "bing" not in settings.OPENROUTER_MEASUREMENT_MODEL_MAP
