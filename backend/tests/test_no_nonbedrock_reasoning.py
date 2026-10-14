"""CI guard for the single-vendor (AWS Bedrock) reasoning invariant.

After the Bedrock cutover, ``services/ai_engine.py`` must not contain any live
non-Bedrock LLM client usage. This test performs a simple, robust string/regex
scan of the source file (no imports, no network) and fails if any retired
OpenAI / OpenRouter / Anthropic / Google client attribute or helper resurfaces.

If this test fails, a non-Bedrock provider was reintroduced into the reasoning
layer. Route the call through ``_generate_with_bedrock`` / ``get_model_instance``
instead.
"""

import re
from pathlib import Path

AI_ENGINE_SOURCE = Path(__file__).resolve().parents[1] / "services" / "ai_engine.py"

# Substrings that must never appear in the reasoning layer again. These are the
# per-provider client attributes and helper symbols removed during the cutover.
FORBIDDEN_SUBSTRINGS = (
    # Per-provider client attributes
    "self.openai_client",
    "self.anthropic_client",
    "self.openrouter_client",
    "self.openrouter_enabled",
    "self.google_client",
    "self.google_types",
    "self.google_client_type",
    "self.anthropic_max_tokens",
    # Retired provider-specific helpers / dispatch methods
    "_generate_with_openai",
    "_generate_with_anthropic",
    "_generate_with_google",
    "_to_openrouter_model",
    "_extract_anthropic_text",
    "_extract_anthropic_tool_input",
    "_extract_anthropic_stop_reason",
    "_extract_google_candidate_text",
    "_extract_google_usage",
    "_strip_unsupported_google_schema_fields",
    "_is_google_image_parse_error",
    "_log_final_google_request",
)


def _read_source() -> str:
    return AI_ENGINE_SOURCE.read_text(encoding="utf-8")


def test_ai_engine_source_present():
    assert AI_ENGINE_SOURCE.is_file(), f"missing {AI_ENGINE_SOURCE}"


def test_no_nonbedrock_client_usage():
    source = _read_source()
    offenders = [needle for needle in FORBIDDEN_SUBSTRINGS if needle in source]
    assert not offenders, (
        "Non-Bedrock reasoning code reintroduced in services/ai_engine.py: "
        f"{offenders}. Reasoning must run exclusively on AWS Bedrock "
        "(_generate_with_bedrock / get_model_instance)."
    )


def test_no_nonbedrock_client_definitions():
    """Catch ``def _generate_with_<provider>`` definitions regardless of spacing."""
    source = _read_source()
    bad_defs = re.findall(
        r"def\s+_generate_with_(openai|anthropic|google|openrouter)\b",
        source,
    )
    assert not bad_defs, f"Forbidden non-Bedrock generation method definition(s): {bad_defs}"
