"""Single-source model resolution shared by debate + cost-forecast services."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.model_resolution import (
    MODEL_ENV_DEFAULTS,
    MODEL_ENV_VAR_MAP,
    resolve_model_name,
)


def test_defaults_for_google_tiers(monkeypatch):
    # Remove any env overrides so we exercise the static defaults deterministically.
    for tier_var in MODEL_ENV_VAR_MAP["google"].values():
        monkeypatch.delenv(tier_var, raising=False)
    assert resolve_model_name("google", "fast") == MODEL_ENV_DEFAULTS["google"]["fast"]
    assert resolve_model_name("google", "smart") == MODEL_ENV_DEFAULTS["google"]["smart"]


def test_unknown_provider_falls_back_to_google():
    # Compare against the function's own google/fast resolution so the test is
    # independent of any *_FAST_MODEL env override present in the environment.
    assert resolve_model_name("unknown", "fast") == resolve_model_name("google", "fast")


def test_unknown_tier_falls_back_to_fast():
    assert resolve_model_name("openai", "bogus") == resolve_model_name("openai", "fast")


def test_none_inputs_default_to_google_fast():
    assert resolve_model_name(None, None) == resolve_model_name("google", "fast")


def test_env_var_override(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR_MAP["google"]["smart"], "gemini-custom-test")
    assert resolve_model_name("google", "smart") == "gemini-custom-test"


def test_debate_and_cost_services_share_canonical_maps():
    # Both services must delegate to the shared maps (no divergent copies).
    import services.cost_forecast_service as cfs
    import services.debate_orchestrator as dbo

    assert dbo._MODEL_ENV_DEFAULTS == MODEL_ENV_DEFAULTS
    assert cfs._MODEL_ENV_DEFAULTS == MODEL_ENV_DEFAULTS
    assert dbo._resolve_model_name("anthropic", "smart") == resolve_model_name("anthropic", "smart")
    assert cfs._resolve_model_name("anthropic", "smart") == resolve_model_name("anthropic", "smart")
