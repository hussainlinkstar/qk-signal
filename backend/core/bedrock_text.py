"""Shared synchronous AWS Bedrock text-generation helper.

This is the single seam used by *synchronous* service code paths (AI pre-scan,
CMS case-study generation) that need a one-shot Bedrock ``converse`` text
completion. Async audit/debate paths use ``AIFactory._generate_with_bedrock``
in ``services/ai_engine.py`` instead.

boto3's ``converse`` is synchronous, so this helper is a plain sync function and
is safe to call from synchronous request/worker code.
"""

from __future__ import annotations

import logging

from core.bedrock_metadata import build_request_metadata
from core.bedrock_runtime import create_bedrock_runtime_client
from core.config import settings

try:
    import boto3
except ImportError:  # pragma: no cover - depends on optional provider install
    boto3 = None

logger = logging.getLogger(__name__)

_TIER_MODEL_ATTR = {
    "smart": "BEDROCK_SMART_MODEL",
    "fast": "BEDROCK_FAST_MODEL",
    "lite": "BEDROCK_LITE_MODEL",
}


def bedrock_available() -> bool:
    """Whether Bedrock text generation can be attempted."""
    return bool(getattr(settings, "BEDROCK_ENABLED", False)) and boto3 is not None


def resolve_bedrock_model(tier: str = "smart") -> str:
    """Resolve the configured Bedrock model id for the given execution tier."""
    attr = _TIER_MODEL_ATTR.get(str(tier or "smart").strip().lower(), "BEDROCK_SMART_MODEL")
    return str(getattr(settings, attr, None) or settings.BEDROCK_SMART_MODEL)


def bedrock_generate_text(
    system: str,
    user: str,
    *,
    tier: str = "smart",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    use_case: str = "signal_text",
    read_timeout: float | None = None,
    connect_timeout: float | None = None,
    max_attempts: int | None = None,
) -> str:
    """Run a single synchronous Bedrock ``converse`` call and return the reply text.

    ``use_case`` tags the invocation (requestMetadata) for EPIC 13 distillation.
    Raises ``RuntimeError`` when Bedrock is unavailable. boto3 / API errors are
    propagated to the caller so existing try/except fallbacks keep working.

    ``read_timeout`` / ``connect_timeout`` / ``max_attempts`` are opt-in and
    default to boto3's own behaviour. Interactive callers working to a wall-clock
    budget set them so a stalled invocation is aborted at the socket rather than
    left running after the caller has given up (SIGV2-1251).
    """
    if not bedrock_available():
        raise RuntimeError("Bedrock is not available for text generation.")

    if read_timeout is None and connect_timeout is None and max_attempts is None:
        # Keep the zero-argument call for every existing caller.
        client = create_bedrock_runtime_client()
    else:
        client = create_bedrock_runtime_client(
            read_timeout=read_timeout,
            connect_timeout=connect_timeout,
            max_attempts=max_attempts,
        )
    model_id = resolve_bedrock_model(tier)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": user}]}],
        system=[{"text": system}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        requestMetadata=build_request_metadata(use_case, tier=tier),
    )

    # Reasoning models can emit a reasoning block before the text block, so scan
    # all content blocks for the first text block instead of assuming index 0.
    content = (response.get("output", {}).get("message", {}) or {}).get("content", []) or []
    text = next(
        (b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)),
        "",
    )
    return text.strip()
