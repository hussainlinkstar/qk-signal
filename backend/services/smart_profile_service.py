"""Grounded smart-profile generation (SIGV2-1252).

AGENTS.md 4.4: an LLM call may never be issued from ``backend/routers/``; it
goes through the ai-service layer. This module is that layer for the project
smart profile, and it is the only place the smart-profile prompt and the
Bedrock seam live. ``routers/workspace_router.py`` now only resolves evidence,
calls :func:`generate_smart_profile`, and maps the errors below to HTTP.

The model contract is unchanged from the previous in-router implementation:
same prompt text, ``tier="smart"``, ``max_tokens=2048``, ``use_case``
``smart_profile`` and the helper's default temperature (0.2, well under the
0.7 ceiling in AGENTS.md 4.4). The model id is resolved from ``settings`` by
``core.bedrock_text``; it is never hard-coded here.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from core.bedrock_text import bedrock_available, bedrock_generate_text, resolve_bedrock_model

logger = logging.getLogger(__name__)

SMART_PROFILE_TIER = "smart"
SMART_PROFILE_MAX_TOKENS = 2048
SMART_PROFILE_USE_CASE = "smart_profile"

SMART_PROFILE_SYSTEM_PROMPT = (
    "You are a strict data extraction assistant for GEO/AEO/SEO profiles. "
    "Use only the provided evidence. Output strict JSON only, no markdown."
)


class SmartProfileError(RuntimeError):
    """Base class for smart-profile generation failures."""


class SmartProfileUnavailableError(SmartProfileError):
    """The inference backend is not configured or not reachable."""


class SmartProfileGenerationError(SmartProfileError):
    """The inference call itself failed."""


class SmartProfileInvalidResponseError(SmartProfileError):
    """The model replied with something that is not a JSON object."""


def resolve_smart_profile_model() -> str:
    """Model id reported back to the caller for this feature."""
    return os.getenv("PROJECT_PROFILE_AI_MODEL") or resolve_bedrock_model(SMART_PROFILE_TIER)


def _extract_json_dict(raw_text: str) -> dict[str, Any] | None:
    text = (raw_text or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def build_smart_profile_prompt(evidence: dict[str, Any]) -> str:
    evidence_json = json.dumps(evidence, ensure_ascii=False)
    return (
        "You are a strict data extraction assistant for GEO/AEO/SEO profiles. "
        "Use ONLY the provided EVIDENCE JSON. Never invent people, companies, claims, URLs, statistics, or market facts. "
        "If evidence is missing, return empty values for those fields.\n\n"
        "Output strict JSON only, no markdown:\n"
        "{\n"
        '  "icp_roles": ["..."],\n'
        '  "pain_points": "...",\n'
        '  "usp": "...",\n'
        '  "priority_pulse_tags": ["..."],\n'
        '  "sme_profiles": ["..."],\n'
        '  "unsupported_fields": ["..."]\n'
        "}\n\n"
        "Rules:\n"
        "- If no support exists for a field, return empty string or [] and include that field name in unsupported_fields.\n"
        "- For sme_profiles, include only role descriptors or public references that are explicitly present in evidence.\n"
        "- Keep pain_points <= 600 chars and usp <= 220 chars.\n"
        "- Do not output any field outside schema.\n\n"
        f"EVIDENCE JSON:\n{evidence_json}"
    )


def generate_smart_profile(evidence: dict[str, Any]) -> dict[str, Any]:
    """Generate a grounded smart profile from the supplied evidence.

    Raises :class:`SmartProfileUnavailableError`,
    :class:`SmartProfileGenerationError` or
    :class:`SmartProfileInvalidResponseError`; the caller maps those to HTTP.
    """
    prompt = build_smart_profile_prompt(evidence)
    if not bedrock_available():
        raise SmartProfileUnavailableError("AI generation is currently unavailable.")

    try:
        raw_text = bedrock_generate_text(
            SMART_PROFILE_SYSTEM_PROMPT,
            prompt,
            tier=SMART_PROFILE_TIER,
            max_tokens=SMART_PROFILE_MAX_TOKENS,
            use_case=SMART_PROFILE_USE_CASE,
        )
    except Exception as exc:
        logger.exception("Smart profile generation failed")
        raise SmartProfileGenerationError(str(exc)) from exc

    payload = _extract_json_dict(str(raw_text or ""))
    if payload is None:
        raise SmartProfileInvalidResponseError("AI generation returned an invalid response format.")
    return payload
