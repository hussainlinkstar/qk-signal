"""Single source of truth for provider/tier → model-name resolution.

Previously ``_MODEL_ENV_DEFAULTS``, ``_MODEL_ENV_VAR_MAP`` and
``_resolve_model_name`` were duplicated verbatim in both
``services/debate_orchestrator.py`` and ``services/cost_forecast_service.py``.
Keeping two copies risked them diverging, e.g. the cost forecast pricing a
different model than the one the debate pipeline actually executes. This module
centralises them so both consumers stay in lock-step.
"""

from __future__ import annotations

import os

MODEL_ENV_DEFAULTS: dict[str, dict[str, str]] = {
    "google": {
        "lite": "gemini-2.5-flash",
        "fast": "gemini-2.5-flash",
        "smart": "gemini-2.5-pro",
    },
    "openai": {
        "lite": "gpt-5.4-nano",
        "fast": "gpt-5.4-mini",
        "smart": "gpt-5.4",
    },
    "anthropic": {
        "lite": "claude-haiku-4-5",
        "fast": "claude-sonnet-4-6",
        "smart": "claude-opus-4-6",
    },
    "bedrock": {
        "lite": "eu.amazon.nova-micro-v1:0",
        "fast": "eu.amazon.nova-lite-v1:0",
        "smart": "eu.amazon.nova-pro-v1:0",
    },
}

MODEL_ENV_VAR_MAP: dict[str, dict[str, str]] = {
    "google": {
        "lite": "GOOGLE_LITE_MODEL",
        "fast": "GOOGLE_FAST_MODEL",
        "smart": "GOOGLE_SMART_MODEL",
    },
    "openai": {
        "lite": "OPENAI_LITE_MODEL",
        "fast": "OPENAI_FAST_MODEL",
        "smart": "OPENAI_SMART_MODEL",
    },
    "anthropic": {
        "lite": "ANTHROPIC_LITE_MODEL",
        "fast": "ANTHROPIC_FAST_MODEL",
        "smart": "ANTHROPIC_SMART_MODEL",
    },
    "bedrock": {
        "lite": "BEDROCK_LITE_MODEL",
        "fast": "BEDROCK_FAST_MODEL",
        "smart": "BEDROCK_SMART_MODEL",
    },
}


def resolve_model_name(provider: str | None, execution_tier: str | None) -> str:
    """Resolve the concrete model name for a provider/tier.

    Honours the env-var override (e.g. GOOGLE_SMART_MODEL) and falls back to the
    static defaults, defaulting to google/fast for unknown inputs.
    """
    normalized_provider = str(provider or "").strip().lower() or "google"
    normalized_tier = str(execution_tier or "").strip().lower() or "fast"
    provider_defaults = MODEL_ENV_DEFAULTS.get(normalized_provider, MODEL_ENV_DEFAULTS["google"])
    env_map = MODEL_ENV_VAR_MAP.get(normalized_provider, MODEL_ENV_VAR_MAP["google"])
    env_var = env_map.get(normalized_tier) or env_map.get("fast") or "GOOGLE_FAST_MODEL"
    return os.getenv(env_var, provider_defaults.get(normalized_tier) or provider_defaults["fast"])
