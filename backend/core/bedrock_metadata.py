"""Bedrock Converse ``requestMetadata`` tagging for EPIC 13 (expert models).

Every Bedrock ``converse`` invocation is tagged with a stable ``use_case`` (plus
tier / role / env). When Bedrock model-invocation logging is enabled, these tags
land in the invocation logs and let a future **Bedrock Model Distillation** job
filter production prompt-response pairs by use-case and distill a smaller, faster
"student" expert model from the teacher (Claude Sonnet 4.5) responses.

Values are sanitized to Bedrock's allowed key/value pattern
(``[a-zA-Z0-9\\s:_@$#=/+,-.]``, length 1..256) and capped at 16 entries, so a
malformed tag can never break a live inference call.
"""

from __future__ import annotations

import re

from core.config import settings

# Bedrock requestMetadata constraints: keys/values match this charset, len <= 256,
# at most 16 entries (see the Converse API reference).
_DISALLOWED = re.compile(r"[^a-zA-Z0-9\s:_@$#=/+,.\-]")
_MAX_LEN = 256
_MAX_ITEMS = 16


def _clean(value: object) -> str:
    return _DISALLOWED.sub("-", str(value))[:_MAX_LEN]


def build_request_metadata(
    use_case: str,
    *,
    tier: str | None = None,
    role: str = "teacher",
    extra: dict[str, object] | None = None,
) -> dict[str, str]:
    """Build a sanitized requestMetadata map for a Bedrock ``converse`` call.

    ``role`` defaults to ``teacher`` — the production reasoning model whose logged
    responses become distillation training data for the eventual expert student.
    """
    metadata: dict[str, str] = {
        "app": "qiko_signal",
        "env": _clean(getattr(settings, "ENVIRONMENT", "") or "unknown"),
        "use_case": _clean(use_case),
        "role": _clean(role),
    }
    if tier:
        metadata["tier"] = _clean(tier)
    for key, value in (extra or {}).items():
        if len(metadata) >= _MAX_ITEMS:
            break
        cleaned_key = _clean(key)
        if cleaned_key:
            metadata[cleaned_key] = _clean(value)

    return dict(list(metadata.items())[:_MAX_ITEMS])
