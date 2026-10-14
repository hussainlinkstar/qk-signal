"""Single source of truth for the configured Bedrock runtime region and the
region-aware measurement model map (SIGV2-1028).

Every Bedrock-runtime client must be built for the CURRENTLY configured region.
Cached clients (``ai_engine``, ``visibility_index_jobs``) record the region they
were built for and are rebuilt when the configured region changes, so a region
flip takes effect without a process restart.
"""

from __future__ import annotations

import logging
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Documented routing metadata for Bedrock inference-profile id prefixes. This
# records the routing TYPE and destination scope only: an ``eu.`` profile is a
# cross-region (EU) profile and an invocation can be served from any of its EU
# destination regions, so the profile prefix alone is not a residency statement
# about any single country.
BEDROCK_INFERENCE_PROFILE_ROUTING: dict[str, dict[str, str]] = {
    "eu.": {
        "routing_type": "cross-region",
        "destination_scope": "eu",
    },
    "us.": {
        "routing_type": "cross-region",
        "destination_scope": "us",
    },
    "apac.": {
        "routing_type": "cross-region",
        "destination_scope": "apac",
    },
    "global.": {
        "routing_type": "global",
        "destination_scope": "global",
    },
}

BEDROCK_EMBEDDING_DIMENSIONS = 1536


class BedrockModelUnavailableError(ValueError):
    """The configured region cannot serve a model for this engine."""


class BedrockModelAccessDeniedError(RuntimeError):
    """The role this process runs as may not invoke a configured model.

    SIGV2-1301. On the live stack every run for `google`, `perplexity` and
    `openai` failed with `AccessDeniedException` on Converse, 828 of them, while
    `bing` succeeded because its model is the only one the instance role is
    granted. Left as a bare `ClientError` that reads as an ordinary measurement
    failure, which is the shape SIGV2-1263 established must never stand in for a
    real result: an engine nobody is allowed to call has not scored zero, it has
    not been measured.

    The message names the model and the region and deliberately omits the role
    ARN and account id that the AWS message carries. A measurement table is not
    the place for an account identifier, and the two values below are what
    actually identify the gap.
    """

    def __init__(self, model_id: str, region: str) -> None:
        self.model_id = model_id
        self.region = region
        super().__init__(
            f"Not authorised to invoke measurement model '{model_id}' in {region}. "
            "This is a configuration fault, not a measurement result."
        )


def configured_bedrock_region() -> str:
    """The region Bedrock-runtime clients must be built for, right now."""
    return str(settings.BEDROCK_REGION).strip() or "eu-north-1"


def create_bedrock_runtime_client(
    *,
    read_timeout: float | None = None,
    connect_timeout: float | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Build a bedrock-runtime client for the configured region.

    Called with no arguments the client keeps boto3's default timeout and retry
    behaviour, which is what the long-running audit/debate paths need: an audit
    invocation legitimately runs for minutes.

    Interactive callers that serve a user request under a wall-clock guard
    (advisor chat) pass an explicit ``read_timeout`` so a stalled invocation is
    aborted at the socket. Without it boto3 waits 60s per attempt and retries,
    so a request-level timeout abandons the result while the worker thread
    keeps the LLM call alive in the background (SIGV2-1251).
    """
    import boto3

    if read_timeout is None and connect_timeout is None and max_attempts is None:
        return boto3.client("bedrock-runtime", region_name=configured_bedrock_region())

    from botocore.config import Config

    config_kwargs: dict[str, Any] = {}
    if read_timeout is not None:
        config_kwargs["read_timeout"] = read_timeout
    if connect_timeout is not None:
        config_kwargs["connect_timeout"] = connect_timeout
    if max_attempts is not None:
        config_kwargs["retries"] = {"max_attempts": max_attempts, "mode": "standard"}

    return boto3.client(
        "bedrock-runtime",
        region_name=configured_bedrock_region(),
        config=Config(**config_kwargs),
    )


def inference_profile_routing(model_id: str | None) -> dict[str, str]:
    """Routing type + destination scope implied by a model id's profile prefix.

    Bare model ids (no profile prefix) are regional invocations.
    """
    if model_id:
        for prefix, info in BEDROCK_INFERENCE_PROFILE_ROUTING.items():
            if model_id.startswith(prefix):
                return dict(info)
    return {"routing_type": "regional", "destination_scope": "configured-region"}


def resolve_bedrock_measurement_model(provider: str, region: str | None = None) -> str | None:
    """The Bedrock model id serving ``provider`` in ``region``, or None when the
    region cannot serve it.

    Resolution order: ``BEDROCK_MEASUREMENT_MODEL_REGION_OVERRIDES[region]``
    wins — an explicit id there substitutes (documented in-family only), an
    explicit ``None`` means explicitly unavailable; engines absent from the
    region entry keep the default ``BEDROCK_MEASUREMENT_MODEL_MAP`` entry.
    Returns None rather than an invalid id: callers must treat None as
    explicitly unavailable, never fall back to a guess.
    """
    normalized = str(provider or "").strip().lower()
    effective_region = region or configured_bedrock_region()
    overrides = getattr(settings, "BEDROCK_MEASUREMENT_MODEL_REGION_OVERRIDES", None) or {}
    region_map = overrides.get(effective_region, {})
    if normalized in region_map:
        return region_map[normalized]
    default_map = getattr(settings, "BEDROCK_MEASUREMENT_MODEL_MAP", None) or {}
    model_id = default_map.get(normalized)
    return str(model_id) if model_id else None


def measurement_map_inventory(region: str | None = None) -> dict[str, dict[str, Any]]:
    """Per-engine availability of the measurement map in ``region``.

    Non-secret display surface for the admin diagnostics payload.
    """
    effective_region = region or configured_bedrock_region()
    default_map = getattr(settings, "BEDROCK_MEASUREMENT_MODEL_MAP", None) or {}
    overrides = getattr(settings, "BEDROCK_MEASUREMENT_MODEL_REGION_OVERRIDES", None) or {}
    region_map = overrides.get(effective_region, {})

    inventory: dict[str, dict[str, Any]] = {}
    for engine in sorted(set(default_map) | set(region_map)):
        model_id = resolve_bedrock_measurement_model(engine, effective_region)
        if model_id is None:
            inventory[engine] = {
                "model": None,
                "available": False,
                "reason": f"no Bedrock measurement model configured for region {effective_region}",
                "routing": inference_profile_routing(None),
            }
        else:
            inventory[engine] = {
                "model": model_id,
                "available": True,
                "reason": None,
                "routing": inference_profile_routing(model_id),
            }
    return inventory
