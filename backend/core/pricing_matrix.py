from __future__ import annotations

import os
from decimal import Decimal


# Pricing last verified: 2026-03-22
# Sources:
#   Anthropic:   https://www.anthropic.com/pricing
#   OpenAI:      https://openai.com/api/pricing
#   Google:      https://ai.google.dev/pricing
#   Perplexity:  https://docs.perplexity.ai/guides/pricing
#   xAI:         https://docs.x.ai/docs
#   DeepSeek:    https://api-docs.deepseek.com/quick_start/pricing

DEFAULT_TOKEN_COST_PER_MILLION_USD: dict[str, dict[str, Decimal]] = {
    # ── Google ──────────────────────────────────────────────────────
    "gemini-2.5-flash-lite": {
        "input": Decimal("0.10"),
        "output": Decimal("0.40"),
    },
    "gemini-2.5-flash": {
        "input": Decimal("0.30"),
        "output": Decimal("2.50"),
    },
    "gemini-2.5-pro": {
        "input": Decimal("1.25"),
        "output": Decimal("10.00"),
    },
    "gemini-2.5-flash-image": {
        "input": Decimal("0.30"),
        "output": Decimal("30.00"),
    },
    "gemini-3-pro-image-preview": {
        "input": Decimal("2.00"),
        "output": Decimal("120.00"),
    },
    "text-embedding-004": {
        "input": Decimal("0.006"),
        "output": Decimal("0.000"),
    },
    # ── OpenAI ──────────────────────────────────────────────────────
    "gpt-5.4-nano": {
        "input": Decimal("0.20"),
        "output": Decimal("1.25"),
    },
    "gpt-5.4-mini": {
        "input": Decimal("0.75"),
        "output": Decimal("4.50"),
    },
    "gpt-5.4": {
        "input": Decimal("2.50"),
        "output": Decimal("15.00"),
    },
    # ── Anthropic ───────────────────────────────────────────────────
    "claude-haiku-4-5": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
    },
    "claude-sonnet-4-5": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-sonnet-4-6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-opus-4-6": {
        "input": Decimal("5.00"),
        "output": Decimal("25.00"),
    },
    # ── Perplexity ─────────────────────────────────────────────────
    "sonar": {
        "input": Decimal("1.00"),
        "output": Decimal("1.00"),
    },
    "sonar-pro": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "sonar-reasoning": {
        "input": Decimal("2.00"),
        "output": Decimal("8.00"),
    },
    "sonar-reasoning-pro": {
        "input": Decimal("5.00"),
        "output": Decimal("25.00"),
    },
    # ── xAI ────────────────────────────────────────────────────────
    "grok-3-mini": {
        "input": Decimal("0.30"),
        "output": Decimal("0.50"),
    },
    "grok-3": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    # ── DeepSeek ───────────────────────────────────────────────────
    "deepseek-chat": {
        "input": Decimal("0.20"),
        "output": Decimal("0.80"),
    },
    "deepseek-reasoner": {
        "input": Decimal("0.55"),
        "output": Decimal("2.19"),
    },
    # ── AWS Bedrock (Amazon Nova) ───────────────────────────────────
    "amazon.nova-micro-v1:0": {
        "input": Decimal("0.035"),
        "output": Decimal("0.14"),
    },
    "amazon.nova-lite-v1:0": {
        "input": Decimal("0.06"),
        "output": Decimal("0.24"),
    },
    "amazon.nova-pro-v1:0": {
        "input": Decimal("0.80"),
        "output": Decimal("3.20"),
    },
    # ── OpenRouter-aligned current models (real OpenRouter catalogue prices) ──
    "gemini-3.5-flash": {
        "input": Decimal("1.50"),
        "output": Decimal("9.00"),
    },
    "gemini-3.1-flash-lite": {
        "input": Decimal("0.25"),
        "output": Decimal("1.50"),
    },
    "gpt-4.1": {
        "input": Decimal("2.00"),
        "output": Decimal("8.00"),
    },
    "gpt-4.1-mini": {
        "input": Decimal("0.40"),
        "output": Decimal("1.60"),
    },
    "gpt-4.1-nano": {
        "input": Decimal("0.10"),
        "output": Decimal("0.40"),
    },
    "claude-haiku-4.5": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
    },
    "claude-sonnet-4.6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-opus-4.6": {
        "input": Decimal("5.00"),
        "output": Decimal("25.00"),
    },
    "grok-4.20": {
        "input": Decimal("1.25"),
        "output": Decimal("2.50"),
    },
    "grok-4.3": {
        "input": Decimal("1.25"),
        "output": Decimal("2.50"),
    },
    "deepseek-r1": {
        "input": Decimal("0.70"),
        "output": Decimal("2.50"),
    },
}

MODEL_NAME_ALIASES: dict[str, str] = {
    "claude-4-5-haiku": "claude-haiku-4-5",
    "claude-4-6-sonnet": "claude-sonnet-4-6",
    "claude-4-6-opus": "claude-opus-4-6",
    "gpt-5-nano": "gpt-5.4-nano",
    "gpt-5-mini": "gpt-5.4-mini",
    "gpt-5": "gpt-5.4",
    "gemini-2.5-pro-image": "gemini-3-pro-image-preview",
    "sonar-medium-online": "sonar",
    "sonar-small-online": "sonar",
    "grok-3-mini-fast": "grok-3-mini",
    "deepseek-v3": "deepseek-chat",
    "deepseek-v3.1": "deepseek-chat",
    "claude-opus-4-6": "claude-opus-4.6",
    "claude-sonnet-4-6": "claude-sonnet-4.6",
    "claude-haiku-4-5": "claude-haiku-4.5",
    "grok-4": "grok-4.20",
    "grok-3": "grok-4.20",
    "grok-3-mini": "grok-4.20",
    "gpt-5.4": "gpt-4.1",
    "gpt-5.4-mini": "gpt-4.1-mini",
    "gpt-5.4-nano": "gpt-4.1-nano",
}

MODEL_FAMILY_FALLBACKS: dict[str, str] = {
    "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.5-flash-image": "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview": "gemini-3-pro-image-preview",
    "gemini-": "gemini-2.5-flash",
    "gpt-5.4-nano": "gpt-5.4-nano",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4": "gpt-5.4",
    "gpt-4.1-nano": "gpt-4.1-nano",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-4.1": "gpt-4.1",
    "gpt-4o": "gpt-4.1",
    "gpt-": "gpt-4.1",
    "claude-haiku": "claude-haiku-4.5",
    "claude-sonnet": "claude-sonnet-4.6",
    "claude-opus": "claude-opus-4.6",
    "claude-": "claude-sonnet-4.6",
    "sonar-reasoning-pro": "sonar-reasoning-pro",
    "sonar-reasoning": "sonar-reasoning",
    "sonar-pro": "sonar-pro",
    "sonar": "sonar",
    "grok-4": "grok-4.20",
    "grok-": "grok-4.20",
    "deepseek-r1": "deepseek-r1",
    "deepseek-reasoner": "deepseek-r1",
    "deepseek-": "deepseek-chat",
    "eu.amazon.nova-micro": "amazon.nova-micro-v1:0",
    "eu.amazon.nova-lite": "amazon.nova-lite-v1:0",
    "eu.amazon.nova-pro": "amazon.nova-pro-v1:0",
    "eu.anthropic.claude-sonnet-4-5": "claude-sonnet-4-5",
    "eu.anthropic.claude-sonnet-4-6": "claude-sonnet-4-6",
    "amazon.nova-micro": "amazon.nova-micro-v1:0",
    "amazon.nova-lite": "amazon.nova-lite-v1:0",
    "amazon.nova-pro": "amazon.nova-pro-v1:0",
    "amazon.nova-": "amazon.nova-lite-v1:0",
}


def canonicalize_model_name(model_name: str | None) -> str | None:
    normalized_model = str(model_name or "").strip()
    if not normalized_model:
        return None
    if "/" in normalized_model:
        # OpenRouter slug form (e.g. "openai/gpt-4.1") -> bare model id
        normalized_model = normalized_model.rsplit("/", 1)[-1].strip()
    return MODEL_NAME_ALIASES.get(normalized_model, normalized_model)


def _env_key(model_name: str, direction: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in model_name.upper())
    return f"AI_COST_{normalized}_{direction.upper()}_PER_1M_USD"


def _resolve_cost(model_name: str, direction: str, default: Decimal) -> Decimal:
    raw_value = os.getenv(_env_key(model_name, direction))
    if not raw_value:
        return default
    try:
        value = Decimal(str(raw_value).strip())
    except Exception:
        return default
    return value if value >= 0 else default


def get_token_pricing_for_model(model_name: str | None) -> dict[str, Decimal]:
    normalized_model = canonicalize_model_name(model_name)
    if not normalized_model:
        fallback = DEFAULT_TOKEN_COST_PER_MILLION_USD["gemini-2.5-flash"]
        return {
            "input": fallback["input"],
            "output": fallback["output"],
        }

    base_model = normalized_model
    if base_model not in DEFAULT_TOKEN_COST_PER_MILLION_USD:
        for prefix, fallback_model in MODEL_FAMILY_FALLBACKS.items():
            if base_model.startswith(prefix):
                base_model = fallback_model
                break
        else:
            base_model = "gemini-2.5-flash"

    defaults = DEFAULT_TOKEN_COST_PER_MILLION_USD[base_model]
    return {
        "input": _resolve_cost(base_model, "input", defaults["input"]),
        "output": _resolve_cost(base_model, "output", defaults["output"]),
    }
