"""Multi-agent debate orchestration for audit execution tiers.

Current runtime pipelines:
- `fast`: FAST V3 `fast_proposer -> fast_critic -> fast_synthesizer`
- `smart`: SMART V3 5-agent pipeline (domain experts + consolidator + judge)
- `deep_judgment`: Delta Flow pipeline (generators + critics + consolidator + judge)

Feature-gated via DEBATE_ENABLED env var.
Pipeline version controlled by DEBATE_PIPELINE_VERSION (v2|v3).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging

from core.model_resolution import (
    MODEL_ENV_DEFAULTS,
    MODEL_ENV_VAR_MAP,
    resolve_model_name,
)

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.config import settings
from core.pricing_matrix import get_token_pricing_for_model
from report_schema import AI_AUDIT_SCHEMA_VERSION, CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA
from report_schema import (
    AEO_EXPERT_SCHEMA,
    AEO_GEO_COMBINED_EXPERT_SCHEMA,
    GEO_EXPERT_SCHEMA,
    SEO_EXPERT_SCHEMA,
)
from services.audit_job_event_service import summarize_debate_output
from services.ai_routing_policy import (
    AuditRouteResolution,
    is_valid_audit_tier,
    normalize_audit_tier,
    resolve_debate_route,
    resolve_debate_routes_for_layer,
)
from services.claim_ledger_service import claim_ledger_service
from services.cost_forecast_service import forecast_audit_cost
from services.prompt_loader import load_prompt_with_context

if TYPE_CHECKING:
    from services.ai_engine import AIFactory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
DEBATE_ENABLED = bool(settings.DEBATE_ENABLED)
DEBATE_COST_CAP_USD = float(settings.DEBATE_COST_CAP_USD or settings.DEBATE_COST_CAP_USD)
DEBATE_COST_CAP_USD = DEBATE_COST_CAP_USD
DEBATE_COST_CAP_MULTIPLIER = float(settings.DEBATE_COST_CAP_MULTIPLIER)


@dataclass(frozen=True)
class PipelineConfig:
    total_timeout_s: int
    step_timeout_s: int
    cost_cap_usd: float
    max_completion_tokens: int
    profile_label: str


_PIPELINE_CONFIGS: dict[str, PipelineConfig] = {
    "fast": PipelineConfig(
        total_timeout_s=int(settings.DEBATE_TOTAL_TIMEOUT_FAST_S),
        step_timeout_s=int(settings.DEBATE_STEP_TIMEOUT_FAST_S),
        cost_cap_usd=float(settings.DEBATE_COST_CAP_FAST_USD),
        max_completion_tokens=3_000,
        profile_label="fast_3step",
    ),
    "smart": PipelineConfig(
        total_timeout_s=int(settings.DEBATE_TOTAL_TIMEOUT_SMART_S),
        step_timeout_s=int(settings.DEBATE_STEP_TIMEOUT_SMART_S),
        cost_cap_usd=float(settings.DEBATE_COST_CAP_SMART_USD),
        max_completion_tokens=6_000,
        profile_label="smart_5step",
    ),
    "deep_judgment": PipelineConfig(
        total_timeout_s=int(settings.DEBATE_TOTAL_TIMEOUT_DEEP_S),
        step_timeout_s=int(settings.DEBATE_STEP_TIMEOUT_DEEP_S),
        cost_cap_usd=float(settings.DEBATE_COST_CAP_DEEP_USD),
        max_completion_tokens=8_000,
        profile_label="delta_flow",
    ),
}
_ANTHROPIC_MAX_TRANSFER_PACKET_CHARS = int(
    getattr(settings, "ANTHROPIC_MAX_TRANSFER_PACKET_CHARS", 8_000) or 8_000
)
_ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS = int(
    getattr(settings, "ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS", 6_000) or 6_000
)
_ANTHROPIC_MAX_CONSOLIDATED_PACKET_CHARS = int(
    getattr(settings, "ANTHROPIC_MAX_CONSOLIDATED_PACKET_CHARS", 12_000) or 12_000
)
_ANTHROPIC_MAX_AUDIT_DATA_CHARS = int(
    getattr(settings, "ANTHROPIC_MAX_AUDIT_DATA_CHARS", 10_000) or 10_000
)
_ANTHROPIC_MAX_TOTAL_INPUT_CHARS = 50_000
_ANTHROPIC_MAX_SYSTEM_PROMPT_CHARS = 12_000
_ANTHROPIC_TRUNCATION_NOTICE = "\n\n[Truncated for Anthropic payload budget]"

_LEGACY_ROLE_CONFIG: dict[str, dict[str, Any]] = {
    "proposer": {"max_completion_tokens": 4_000, "timeout_s": 30},
    "challenger": {"max_completion_tokens": 6_000, "timeout_s": 60},
    "synthesizer": {"max_completion_tokens": 6_000, "timeout_s": 60},
}
DEBATE_TOTAL_TIMEOUT_S = 180
_LEGACY_DEBATE_TOTAL_TIMEOUT_S = DEBATE_TOTAL_TIMEOUT_S

_SEMANTIC_ROLE_BY_COMPAT_ROLE: dict[str, str] = {
    "proposer": "generator",
    "challenger": "critic",
    "synthesizer": "judge",
}

_PIPELINE_PROGRESS_LAYOUTS: dict[str, dict[str, Any]] = {
    "fast_3step": {
        "total_agents": 3,
        "parallel_layers": 0,
        "layers": {
            1: {"layer_name": "Proposal", "agents_in_layer": 1, "parallel": False},
            2: {"layer_name": "Critique", "agents_in_layer": 1, "parallel": False},
            3: {"layer_name": "Synthesis", "agents_in_layer": 1, "parallel": False},
        },
    },
    "smart_5step": {
        "total_agents": 5,
        "parallel_layers": 1,
        "layers": {
            1: {
                "layer_name": "Specialized Generation",
                "agents_in_layer": 2,
                "parallel": True,
            },
            2: {"layer_name": "Centralized Critique", "agents_in_layer": 1, "parallel": False},
            3: {"layer_name": "Synthesis", "agents_in_layer": 1, "parallel": False},
            4: {"layer_name": "Magistrate Review", "agents_in_layer": 1, "parallel": False},
        },
    },
    "delta_flow": {
        "total_agents": 8,
        "parallel_layers": 2,
        "layers": {
            1: {
                "layer_name": "Specialized Generation",
                "agents_in_layer": 3,
                "parallel": True,
            },
            2: {
                "layer_name": "Domain Critique",
                "agents_in_layer": 3,
                "parallel": True,
            },
            3: {"layer_name": "Consolidation", "agents_in_layer": 1, "parallel": False},
            4: {"layer_name": "Global Magistrate", "agents_in_layer": 1, "parallel": False},
        },
    },
}

_STANDARD_DEBATE_SYNTHESIS_SCHEMA: dict[str, Any] = copy.deepcopy(
    CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA
)
_STANDARD_DEBATE_SYNTHESIS_SCHEMA["properties"].update(
    {
        "synthesis_reasoning": {"type": "string"},
        "debate_confidence_score": {"type": "number"},
    }
)
_STANDARD_DEBATE_SYNTHESIS_SCHEMA["required"] = [
    *CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA["required"],
    "synthesis_reasoning",
    "debate_confidence_score",
]

_CRITIC_CHALLENGE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_claim": {"type": "string"},
        "issue_type": {
            "type": "string",
            "enum": [
                "unsupported_claim",
                "invented_link_or_citation",
                "weak_recommendation",
                "reasoning_gap",
                "grounding_gap",
            ],
        },
        "severity": {"type": "string", "enum": ["critical", "moderate", "minor"]},
        "counter_argument": {"type": "string"},
        "suggested_disposition": {"type": "string", "enum": ["keep", "downgrade", "remove"]},
    },
    "required": [
        "target_claim",
        "issue_type",
        "severity",
        "counter_argument",
        "suggested_disposition",
    ],
    "additionalProperties": False,
}

_CHALLENGER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "challenges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_claim": {"type": "string"},
                    "counter_argument": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "moderate", "minor"]},
                },
                "required": ["target_claim", "counter_argument", "severity"],
                "additionalProperties": False,
            },
        },
        "missed_items": {
            "type": "array",
            "items": {"type": "string"},
        },
        "disagreements": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence_delta": {"type": "number"},
    },
    "required": ["challenges", "missed_items", "disagreements", "confidence_delta"],
    "additionalProperties": False,
}

_HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "unsupported_claims": {
            "type": "array",
            "items": copy.deepcopy(_CRITIC_CHALLENGE_ITEM_SCHEMA),
        },
        "invented_links_or_citations": {
            "type": "array",
            "items": copy.deepcopy(_CRITIC_CHALLENGE_ITEM_SCHEMA),
        },
        "weak_recommendations": {
            "type": "array",
            "items": copy.deepcopy(_CRITIC_CHALLENGE_ITEM_SCHEMA),
        },
        "missed_items": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "confidence_delta": {"type": "number"},
    },
    "required": [
        "unsupported_claims",
        "invented_links_or_citations",
        "weak_recommendations",
        "missed_items",
        "unresolved_questions",
        "confidence_delta",
    ],
    "additionalProperties": False,
}

_HIGH_CONFIDENCE_JUDGE_SCHEMA: dict[str, Any] = copy.deepcopy(CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA)
_HIGH_CONFIDENCE_JUDGE_SCHEMA["properties"].update(
    {
        "synthesis_reasoning": {"type": "string"},
        "debate_confidence_score": {"type": "number"},
        "judge_summary": {
            "type": "object",
            "properties": {
                "accepted_claims": {"type": "integer", "minimum": 0},
                "downgraded_claims": {"type": "integer", "minimum": 0},
                "rejected_claims": {"type": "integer", "minimum": 0},
                "unresolved_disputes": {"type": "integer", "minimum": 0},
            },
            "required": [
                "accepted_claims",
                "downgraded_claims",
                "rejected_claims",
                "unresolved_disputes",
            ],
            "additionalProperties": False,
        },
    }
)
_HIGH_CONFIDENCE_JUDGE_SCHEMA["required"] = [
    *CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA["required"],
    "synthesis_reasoning",
    "debate_confidence_score",
    "judge_summary",
]

_DOMAIN_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accepted_claims": {"type": "integer", "minimum": 0},
        "downgraded_claims": {"type": "integer", "minimum": 0},
        "rejected_claims": {"type": "integer", "minimum": 0},
        "needs_manual_review": {"type": "integer", "minimum": 0},
        "top_findings": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "accepted_claims",
        "downgraded_claims",
        "rejected_claims",
        "needs_manual_review",
        "top_findings",
        "recommended_actions",
    ],
    "additionalProperties": False,
}

_CROSS_DOMAIN_CONFLICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "array",
            "items": {"type": "string"},
        },
        "description": {"type": "string"},
        "resolution_recommendation": {"type": "string"},
    },
    "required": ["domains", "description", "resolution_recommendation"],
    "additionalProperties": False,
}

_CONSOLIDATED_DISPOSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "domain": {"type": "string"},
        "original_confidence": {"type": "number"},
        "post_critique_confidence": {"type": "number"},
        "disposition": {
            "type": "string",
            "enum": ["accepted", "downgraded", "rejected", "needs_manual_review", "deduplicated"],
        },
        "critique_reference": {"type": "string"},
    },
    "required": [
        "claim_id",
        "domain",
        "original_confidence",
        "post_critique_confidence",
        "disposition",
        "critique_reference",
    ],
    "additionalProperties": False,
}

_DEDUP_DETAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "removed_domain": {"type": "string"},
        "kept_domain": {"type": "string"},
        "topic": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["removed_domain", "kept_domain", "topic", "reason"],
    "additionalProperties": False,
}

_CONSOLIDATED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain_summaries": {
            "type": "object",
            "properties": {
                "seo": copy.deepcopy(_DOMAIN_SUMMARY_SCHEMA),
                "geo": copy.deepcopy(_DOMAIN_SUMMARY_SCHEMA),
                "aeo": copy.deepcopy(_DOMAIN_SUMMARY_SCHEMA),
            },
            "required": ["seo", "geo", "aeo"],
            "additionalProperties": False,
        },
        "cross_domain_conflicts": {
            "type": "array",
            "items": copy.deepcopy(_CROSS_DOMAIN_CONFLICT_SCHEMA),
        },
        "consolidated_claim_disposition": {
            "type": "array",
            "items": copy.deepcopy(_CONSOLIDATED_DISPOSITION_SCHEMA),
        },
        "dedup_count": {"type": "integer", "minimum": 0},
        "dedup_details": {
            "type": "array",
            "items": copy.deepcopy(_DEDUP_DETAIL_SCHEMA),
        },
        "synthesis_reasoning": {"type": "string"},
        "overall_confidence_score": {"type": "number"},
    },
    "required": [
        "domain_summaries",
        "cross_domain_conflicts",
        "consolidated_claim_disposition",
        "dedup_count",
        "dedup_details",
        "synthesis_reasoning",
        "overall_confidence_score",
    ],
    "additionalProperties": False,
}

_CANONICAL_REQUIRED_KEYS: tuple[str, ...] = tuple(CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA["required"])
_STANDARD_CRITIC_REQUIRED_KEYS: tuple[str, ...] = tuple(_CHALLENGER_OUTPUT_SCHEMA["required"])
_STANDARD_SYNTHESIS_REQUIRED_KEYS: tuple[str, ...] = tuple(
    _STANDARD_DEBATE_SYNTHESIS_SCHEMA["required"]
)
_STRICT_CRITIC_REQUIRED_KEYS: tuple[str, ...] = tuple(
    _HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA["required"]
)
_HIGH_CONFIDENCE_JUDGE_REQUIRED_KEYS: tuple[str, ...] = tuple(
    _HIGH_CONFIDENCE_JUDGE_SCHEMA["required"]
)
_CONSOLIDATED_REQUIRED_KEYS: tuple[str, ...] = tuple(_CONSOLIDATED_OUTPUT_SCHEMA["required"])

_AEO_GEO_REQUIRED_KEYS: tuple[str, ...] = tuple(AEO_GEO_COMBINED_EXPERT_SCHEMA["required"])


# ---------------------------------------------------------------------------
# Consolidation status constants (AEX-14)
# ---------------------------------------------------------------------------
CONSOLIDATION_FULL = "full"  # Normal consolidation completed
CONSOLIDATION_PARTIAL = "partial"  # Some domains consolidated, others fell back
CONSOLIDATION_BYPASSED = "bypassed"  # Consolidator entirely skipped (exception)
CONSOLIDATION_DEGRADED = "degraded"  # Consolidator ran but produced incomplete output


# ---------------------------------------------------------------------------
# Empty generator outputs, used when one Layer-1 generator fails but the
# other succeeds, so the pipeline can continue with partial data.
# ---------------------------------------------------------------------------


def _empty_seo_generator_output() -> dict[str, Any]:
    """Minimal valid SEO generator output (conforms to SEO_EXPERT_SCHEMA)."""
    return {
        "claim_ledger": [],
        "seo_findings": [],
        "technical_signals": {
            "mobile_friendliness": 0,
            "security_score": 0,
        },
    }


def _empty_aeo_geo_generator_output() -> dict[str, Any]:
    """Minimal valid AEO/GEO combined generator output."""
    return {
        "claim_ledger": [],
        "summary": "Generator failed, partial audit results only.",
        "recommendations": [],
        "geo_findings": [],
        "geo_signals": {
            "citation_consistency_score": 0,
            "local_authority_score": 0,
        },
        "entity_analysis": {
            "entity_clarity_score": 0,
            "brand_trust_score": 0,
        },
        "aeo_findings": [],
        "aeo_signals": {
            "answerability_score": 0,
            "voice_readiness_score": 0,
        },
        "citation_probability_score": 0,
    }


# ---------------------------------------------------------------------------
# Safe JSON truncation, avoids mid-token slicing that breaks JSON.
# ---------------------------------------------------------------------------

# Keys the magistrate actually needs from the synthesizer output, in priority
# order.  Lower-priority keys are dropped first when the payload exceeds the
# char budget.
_SYNTHESIS_PRIORITY_KEYS: tuple[str, ...] = (
    # Must-have: scores & reasoning
    "synthesis_reasoning",
    "debate_confidence_score",
    "schema_version",
    # Core domain signals (compact)
    "technical_signals",
    "geo_signals",
    "aeo_signals",
    "entity_analysis",
    "citation_probability_score",
    # Scores
    "overall_score",
    "seo_score",
    "geo_score",
    "aeo_score",
    # Essential narrative fields
    "executive_dossier",
    "summary",
    # Findings (lists, can be large)
    "seo_findings",
    "geo_findings",
    "aeo_findings",
    "findings",
    "recommendations",
    "claim_ledger",
    # Lower priority (dropped first)
    "neural_intelligence_grid",
    "strategic_roadmap",
    "market_dominance_projection",
)


def _safe_json_section(payload: Any, max_chars: int) -> str:
    """Serialize *payload* to JSON, truncating at a safe boundary.

    Instead of raw ``json.dumps(...)[:N]`` which can break mid-token, this
    function:
    1. Returns the full serialization if it fits within *max_chars*.
    2. If the payload is a ``dict``, drops the lowest-priority keys
       (by ``_SYNTHESIS_PRIORITY_KEYS`` ordering) until it fits.
    3. As a last resort, slices at the last complete JSON value boundary
       (looking for ``}`` or ``]``) and appends a truncation marker.
    """
    full = json.dumps(payload, default=str)
    if len(full) <= max_chars:
        return full

    # For dicts, progressively drop lowest-priority keys
    if isinstance(payload, dict):
        trimmed = dict(payload)
        # Build a drop order: keys NOT in priority list first, then
        # priority list in reverse order (lowest priority = dropped first).
        all_keys = set(trimmed.keys())
        priority_set = set(_SYNTHESIS_PRIORITY_KEYS)
        unranked = [k for k in all_keys if k not in priority_set]
        ranked_rev = [k for k in reversed(_SYNTHESIS_PRIORITY_KEYS) if k in all_keys]
        drop_order = unranked + ranked_rev

        for key in drop_order:
            trimmed.pop(key, None)
            attempt = json.dumps(trimmed, default=str)
            if len(attempt) <= max_chars:
                return attempt

    # Fallback: slice at last valid JSON boundary
    truncated = full[:max_chars]
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in ("}", "]", '"'):
            return truncated[: i + 1] + " ...[truncated]"
    return truncated + " ...[truncated]"


def _build_synthesis_transfer_packet(synthesis_output: dict) -> dict:
    """Extract a compact transfer packet from synthesizer output for the
    magistrate.

    Instead of feeding the full CANONICAL schema output (which can be
    15,000-25,000+ chars), this keeps only the fields the magistrate
    actually needs to issue a verdict.
    """
    packet: dict[str, Any] = {}

    # Always include reasoning + confidence
    for key in (
        "synthesis_reasoning",
        "debate_confidence_score",
        "schema_version",
    ):
        if key in synthesis_output:
            packet[key] = synthesis_output[key]

    # Include score fields
    for key in (
        "overall_score",
        "seo_score",
        "geo_score",
        "aeo_score",
        "citation_probability_score",
    ):
        if key in synthesis_output:
            packet[key] = synthesis_output[key]

    # Include signal objects (compact)
    for key in (
        "technical_signals",
        "geo_signals",
        "aeo_signals",
        "entity_analysis",
    ):
        if key in synthesis_output:
            packet[key] = synthesis_output[key]

    # Include narratives (cap each at 800 chars)
    for key in ("executive_dossier", "summary", "strategic_roadmap"):
        val = synthesis_output.get(key)
        if isinstance(val, str) and val:
            packet[key] = val[:800]

    # Include findings arrays, cap each at 6 items
    _MAX_TRANSFER_FINDINGS = 6
    for key in (
        "seo_findings",
        "geo_findings",
        "aeo_findings",
        "findings",
        "recommendations",
    ):
        val = synthesis_output.get(key)
        if isinstance(val, list):
            packet[key] = val[:_MAX_TRANSFER_FINDINGS]

    # Include claim ledger (already capped upstream, but guard here too)
    cl = synthesis_output.get("claim_ledger")
    if isinstance(cl, list):
        packet["claim_ledger"] = cl[:12]

    return packet


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------
@dataclass
class DebateAgentResult:
    role: str
    semantic_role: str
    provider: str
    model: str
    output: dict
    token_usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    route_resolution: AuditRouteResolution | None = None
    step_cost_usd: float = 0.0
    layer_index: int | None = None
    cascade_waste_cost_usd: float = 0.0


@dataclass
class DebateResult:
    rounds: list[DebateAgentResult]
    final_synthesis: dict
    synthesis_reasoning: str
    debate_confidence_score: float
    total_token_usage: dict = field(default_factory=dict)
    total_latency_ms: float = 0.0
    total_estimated_cost_usd: float = 0.0
    profile: str | None = None
    judge_summary: dict[str, int] | None = None
    judge_authority: str | None = None
    fallback_reason: str | None = None
    final_provider: str | None = None
    final_model: str | None = None
    pipeline_type: str | None = None
    parallel_layers: int = 0
    agent_count: int = 0
    per_agent_costs: list[dict[str, Any]] = field(default_factory=list)
    trace_records: list[dict[str, Any]] = field(default_factory=list)
    consolidation_status: str = CONSOLIDATION_FULL


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_proposer_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = (
        "You are the **Proposer** agent in a multi-agent audit debate. "
        "Generate a comprehensive initial analysis of the provided website data. "
        "Your analysis will be critically reviewed by a Challenger agent, so be thorough and precise. "
        "Return ONLY valid JSON matching the exact contract. "
        f"Set 'schema_version' to '{AI_AUDIT_SCHEMA_VERSION}'. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English.\n\n"
        f"{prompt_context}"
    )
    user_prompt = [
        "Analyze the following audit data and produce a complete audit analysis report.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _append_prompt_context(base_prompt: str, prompt_context: str) -> str:
    cleaned_prompt_context = str(prompt_context or "").strip()
    if not cleaned_prompt_context:
        return base_prompt
    return f"{base_prompt}\n\n## Orchestrator Context\n{cleaned_prompt_context}"


def _build_fast_proposer_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("fast", "proposer", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Generate a concise but complete first-pass audit analysis.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_seo_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("smart", "seo_generator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Return SEO-only expert output for the provided audit evidence.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_deep_seo_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("deep_judgment", "seo_generator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Return SEO-only expert output for the provided audit evidence.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_aeo_geo_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("smart", "aeo_geo_generator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Return combined AEO+GEO expert output for the provided audit evidence.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_geo_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("deep_judgment", "geo_generator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Return GEO-only expert output for the provided audit evidence.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_aeo_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("deep_judgment", "aeo_generator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Return AEO-only expert output for the provided audit evidence.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_generator_prompt(
    audit_data: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = (
        "You are the **Generator** agent in a high-confidence multi-agent audit review. "
        "Produce the strongest defensible first-pass analysis from the provided evidence. "
        "Do not invent citations, URLs, competitors, or capabilities that are not grounded in the supplied audit data. "
        "If evidence is weak, state the conclusion conservatively inside the structured output. "
        "Return ONLY valid JSON matching the exact contract. "
        f"Set 'schema_version' to '{AI_AUDIT_SCHEMA_VERSION}'. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English.\n\n"
        f"{prompt_context}"
    )
    user_prompt = [
        "Generate a grounded first-pass audit analysis report from the audit evidence below.\n\n"
        f"## Audit Data:\n{json.dumps(audit_data, default=str)[:15000]}"
    ]
    return system_prompt, user_prompt


def _build_challenger_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    system_prompt = (
        "You are the **Challenger** agent in a multi-agent audit debate. "
        "Critically examine the Proposer's compact transfer packet below instead of asking for the full transcript. "
        "Identify flawed reasoning, missed optimization opportunities, overstated claims, and gaps. "
        "Your critique will be used by a Synthesizer to produce the final output. "
        "Return ONLY valid JSON matching the exact contract. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English."
    )
    user_prompt = [
        "## Proposer Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:8000]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:10000]}\n\n"
        "Produce a structured critique identifying challenges, missed items, and disagreements from the compact claim ledger."
    ]
    return system_prompt, user_prompt


def _build_fast_critic_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    system_prompt = load_prompt_with_context("fast", "critic", audit_data=audit_data)
    user_prompt = [
        "Review the compact proposer transfer packet only. Do not assume access to the full proposer output.\n\n"
        "## Proposer Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:7000]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:9000]}\n\n"
        "Return a short structured critique covering challenges, missed_items, disagreements, and confidence_delta."
    ]
    return system_prompt, user_prompt


def _build_centralized_critic_prompt(
    audit_data: dict,
    *,
    seo_proposal: dict,
    aeo_geo_proposal: dict,
) -> tuple[str, list]:
    seo_transfer = claim_ledger_service.build_analysis_transfer_packet(
        seo_proposal,
        expert_domain="seo",
    )
    aeo_geo_transfer = claim_ledger_service.build_analysis_transfer_packet(
        aeo_geo_proposal,
        expert_domain="aeo_geo",
    )
    system_prompt = load_prompt_with_context("smart", "centralized_critic", audit_data=audit_data)
    user_prompt = [
        "Challenge the supplied expert claim ledgers only. Do not assume access to the raw generator outputs.\n\n"
        "## SEO Transfer Packet:\n"
        f"{_safe_json_section(seo_transfer, 4500)}\n\n"
        "## AEO+GEO Transfer Packet:\n"
        f"{_safe_json_section(aeo_geo_transfer, 4500)}\n\n"
        "## Original Audit Data:\n"
        f"{_safe_json_section(audit_data, 9000)}\n\n"
        "Return a centralized critique covering unsupported_claims, invented_links_or_citations, "
        "weak_recommendations, missed_items, unresolved_questions, and confidence_delta."
    ]
    return system_prompt, user_prompt


def _build_delta_domain_critic_prompt(
    audit_data: dict,
    *,
    role: str,
    label: str,
    expert_domain: str,
    proposal: dict,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(
        proposal,
        expert_domain=expert_domain,
    )
    system_prompt = load_prompt_with_context("deep_judgment", role, audit_data=audit_data)
    user_prompt = [
        f"Review only the supplied {label} transfer packet. Do not critique other domains.\n\n"
        f"## {label} Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:5000]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:9000]}\n\n"
        "Return unsupported_claims, invented_links_or_citations, weak_recommendations, "
        "missed_items, unresolved_questions, and confidence_delta."
    ]
    return system_prompt, user_prompt


def _build_seo_critic_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    return _build_delta_domain_critic_prompt(
        audit_data,
        role="seo_critic",
        label="SEO",
        expert_domain="seo",
        proposal=proposal,
    )


def _build_geo_critic_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    return _build_delta_domain_critic_prompt(
        audit_data,
        role="geo_critic",
        label="GEO",
        expert_domain="geo",
        proposal=proposal,
    )


def _build_aeo_critic_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    return _build_delta_domain_critic_prompt(
        audit_data,
        role="aeo_critic",
        label="AEO",
        expert_domain="aeo",
        proposal=proposal,
    )


def _build_critic_prompt(
    audit_data: dict,
    proposal: dict,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    system_prompt = (
        "You are the **Critic** agent in a high-confidence multi-agent audit review. "
        "Behave like a red-team reviewer, not a polite editor. "
        "You will receive a compact generator claim ledger instead of the full generator transcript. "
        "You must look for unsupported claims, invented links or citations, weak recommendations, reasoning gaps, and grounding failures. "
        "If a claim cannot be defended from the provided evidence, recommend whether it should be kept, downgraded, or removed. "
        "Return ONLY valid JSON matching the exact contract. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English."
    )
    user_prompt = [
        "## Generator Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:8000]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:10000]}\n\n"
        "Return a strict red-team critique covering unsupported_claims, invented_links_or_citations, weak_recommendations, "
        "missed_items, unresolved_questions, and confidence_delta using the compact claim ledger."
    ]
    return system_prompt, user_prompt


def _build_fast_synthesizer_prompt(
    audit_data: dict,
    proposal: dict,
    challenge: dict,
    prompt_context: str,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    challenge_transfer = claim_ledger_service.build_challenge_transfer_packet(challenge)
    system_prompt = _append_prompt_context(
        load_prompt_with_context("fast", "synthesizer", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Produce the final reconciled analysis.\n\n"
        "Your output JSON must contain the standard analysis keys plus "
        "'synthesis_reasoning' and 'debate_confidence_score'.\n\n"
        "## Proposer Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:6500]}\n\n"
        "## Critic Review Packet:\n"
        f"{json.dumps(challenge_transfer, default=str)[:4500]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:8000]}"
    ]
    return system_prompt, user_prompt


def _build_smart_synthesizer_prompt(
    audit_data: dict,
    *,
    seo_proposal: dict,
    aeo_geo_proposal: dict,
    critique: dict,
    prompt_context: str,
) -> tuple[str, list]:
    seo_transfer = claim_ledger_service.build_analysis_transfer_packet(
        seo_proposal,
        expert_domain="seo",
    )
    aeo_geo_transfer = claim_ledger_service.build_analysis_transfer_packet(
        aeo_geo_proposal,
        expert_domain="aeo_geo",
    )
    critique_transfer = claim_ledger_service.build_challenge_transfer_packet(critique)
    system_prompt = _append_prompt_context(
        load_prompt_with_context("smart", "synthesizer", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Assemble a compact synthesis packet for the magistrate.\n\n"
        "Your output must contain the canonical analysis fields plus "
        "'synthesis_reasoning' and 'debate_confidence_score'.\n\n"
        "## SEO Transfer Packet:\n"
        f"{_safe_json_section(seo_transfer, 3500)}\n\n"
        "## AEO+GEO Transfer Packet:\n"
        f"{_safe_json_section(aeo_geo_transfer, 3500)}\n\n"
        "## Centralized Critique Packet:\n"
        f"{_safe_json_section(critique_transfer, 5000)}\n\n"
        "## Original Audit Data:\n"
        f"{_safe_json_section(audit_data, 7000)}"
    ]
    return system_prompt, user_prompt


def _build_synthesizer_prompt(
    audit_data: dict,
    proposal: dict,
    challenge: dict,
    prompt_context: str,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    challenge_transfer = claim_ledger_service.build_challenge_transfer_packet(challenge)
    system_prompt = (
        "You are the **Synthesizer** agent in a multi-agent audit debate. "
        "You have received a compact Proposer claim ledger and a compact Challenger review packet. "
        "Reconcile both perspectives into a final, authoritative analysis. "
        "Where the Challenger's objections are valid, adjust the Proposer's output accordingly. "
        "Where the Proposer was correct, retain the original analysis. "
        "Include a 'synthesis_reasoning' narrative explaining your reconciliation choices "
        "and produce a 'debate_confidence_score' between 0.0 and 1.0. "
        "Return ONLY valid JSON matching the exact contract. "
        f"Set 'schema_version' to '{AI_AUDIT_SCHEMA_VERSION}'. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English.\n\n"
        f"{prompt_context}"
    )

    synthesis_schema_note = (
        "Your output JSON must contain these top-level keys: "
        "the standard analysis keys PLUS 'synthesis_reasoning' (string) and 'debate_confidence_score' (number 0-1)."
    )

    user_prompt = [
        f"{synthesis_schema_note}\n\n"
        "## Proposer Transfer Packet:\n"
        f"{_safe_json_section(proposal_transfer, 7000)}\n\n"
        "## Challenger Review Packet:\n"
        f"{_safe_json_section(challenge_transfer, 5000)}\n\n"
        "## Original Audit Data:\n"
        f"{_safe_json_section(audit_data, 8000)}\n\n"
        "Produce the final reconciled analysis."
    ]
    return system_prompt, user_prompt


def _build_magistrate_prompt(
    audit_data: dict,
    *,
    synthesis_packet: dict,
    critique: dict,
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("smart", "magistrate", audit_data=audit_data),
        prompt_context,
    )
    critique_transfer = claim_ledger_service.build_challenge_transfer_packet(critique)
    # Compress the full synthesizer output into a compact transfer packet
    # before serializing, avoids the 9000-char mid-JSON slice on rich audits.
    synthesis_transfer = _build_synthesis_transfer_packet(synthesis_packet)
    user_prompt = [
        "Issue the final grounded verdict from the synthesis packet.\n\n"
        "Your output must contain the canonical analysis fields plus "
        "'synthesis_reasoning', 'debate_confidence_score', and 'judge_summary'.\n\n"
        "## Synthesis Packet:\n"
        f"{_safe_json_section(synthesis_transfer, 10000)}\n\n"
        "## Centralized Critique Packet:\n"
        f"{_safe_json_section(critique_transfer, 4000)}\n\n"
        "## Original Audit Data:\n"
        f"{_safe_json_section(audit_data, 6000)}"
    ]
    return system_prompt, user_prompt


def _build_consolidator_prompt(
    audit_data: dict,
    *,
    generator_packets: dict[str, dict[str, Any]],
    critique_packets: dict[str, dict[str, Any]],
    prompt_context: str,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("deep_judgment", "consolidator", audit_data=audit_data),
        prompt_context,
    )
    user_prompt = [
        "Merge the domain critique streams into one consolidated packet.\n\n"
        "Your output must contain domain_summaries, cross_domain_conflicts, "
        "consolidated_claim_disposition, dedup_count, dedup_details, synthesis_reasoning, and overall_confidence_score.\n\n"
        "## Generator Transfer Packets:\n"
        f"{json.dumps(generator_packets, default=str)[:7000]}\n\n"
        "## Critique Packets:\n"
        f"{json.dumps(critique_packets, default=str)[:7000]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:6000]}"
    ]
    return system_prompt, user_prompt


def _build_global_magistrate_prompt(
    audit_data: dict,
    *,
    generator_packets: dict[str, dict[str, Any]],
    consolidated_packet: dict[str, Any] | None,
    critique_packets: dict[str, dict[str, Any]] | None,
    prompt_context: str,
    consolidation_status: str = CONSOLIDATION_FULL,
) -> tuple[str, list]:
    system_prompt = _append_prompt_context(
        load_prompt_with_context("deep_judgment", "global_magistrate", audit_data=audit_data),
        prompt_context,
    )
    user_sections = [
        "Issue the highest-authority final verdict for the Delta Flow.\n\n"
        "Your output must contain the canonical analysis fields plus "
        "'synthesis_reasoning', 'debate_confidence_score', and 'judge_summary'.\n\n"
        "## Generator Transfer Packets:\n"
        f"{json.dumps(generator_packets, default=str)[:7000]}"
    ]
    if consolidation_status != CONSOLIDATION_FULL:
        status_notices = {
            CONSOLIDATION_BYPASSED: (
                "## CONSOLIDATION STATUS: BYPASSED\n"
                "The consolidator stage failed entirely. You are receiving raw critique "
                "packets instead of a consolidated analysis. Apply stricter cross-domain "
                "consistency checks: verify that SEO, GEO, and AEO recommendations do not "
                "contradict each other. Perform your own mini-consolidation before issuing "
                "the final verdict. Lower your debate_confidence_score accordingly."
            ),
            CONSOLIDATION_DEGRADED: (
                "## CONSOLIDATION STATUS: DEGRADED\n"
                "The consolidator produced an incomplete output (missing critical fields). "
                "Treat the consolidated packet with reduced trust. Apply stricter cross-domain "
                "consistency checks and verify claims independently against the original "
                "generator outputs. Lower your debate_confidence_score accordingly."
            ),
            CONSOLIDATION_PARTIAL: (
                "## CONSOLIDATION STATUS: PARTIAL\n"
                "Some domains were consolidated successfully but others fell back. "
                "Apply extra scrutiny to cross-domain findings and verify consistency. "
                "Lower your debate_confidence_score accordingly."
            ),
        }
        notice = status_notices.get(consolidation_status)
        if notice:
            user_sections.append(notice)
    if isinstance(consolidated_packet, dict):
        user_sections.append(
            "## Consolidated Packet:\n" f"{json.dumps(consolidated_packet, default=str)[:7000]}"
        )
    elif isinstance(critique_packets, dict):
        user_sections.append(
            "## Critique Packets:\n" f"{json.dumps(critique_packets, default=str)[:7000]}"
        )
    user_sections.append(
        "## Original Audit Data:\n" f"{json.dumps(audit_data, default=str)[:6000]}"
    )
    return system_prompt, ["\n\n".join(user_sections)]


def _build_judge_prompt(
    audit_data: dict,
    proposal: dict,
    critique: dict,
    prompt_context: str,
) -> tuple[str, list]:
    proposal_transfer = claim_ledger_service.build_analysis_transfer_packet(proposal)
    critique_transfer = claim_ledger_service.build_challenge_transfer_packet(critique)
    system_prompt = (
        "You are the **Judge** agent in a high-confidence multi-agent audit review. "
        "You must keep only grounded, defensible conclusions. "
        "You will receive compact generator and critic transfer packets, not the full transcript. "
        "If the Critic surfaces an unresolved dispute, unsupported claim, invented citation, or weak recommendation, "
        "you must explicitly downgrade or remove it from the final analysis. "
        "Penalize unresolved disputes in the debate_confidence_score. "
        "Return ONLY valid JSON matching the exact contract. "
        f"Set 'schema_version' to '{AI_AUDIT_SCHEMA_VERSION}'. "
        "Never include markdown, code fences, commentary, or extra keys. "
        "Always communicate in English.\n\n"
        f"{prompt_context}"
    )
    judge_schema_note = (
        "Your output JSON must contain the standard analysis keys plus synthesis_reasoning, debate_confidence_score, and judge_summary. "
        "judge_summary must count accepted_claims, downgraded_claims, rejected_claims, and unresolved_disputes."
    )
    user_prompt = [
        f"{judge_schema_note}\n\n"
        "## Generator Transfer Packet:\n"
        f"{json.dumps(proposal_transfer, default=str)[:7000]}\n\n"
        "## Critic Review Packet:\n"
        f"{json.dumps(critique_transfer, default=str)[:5500]}\n\n"
        "## Original Audit Data:\n"
        f"{json.dumps(audit_data, default=str)[:8000]}\n\n"
        "Produce the final adjudicated analysis from the compact transfer packets and remove or downgrade anything that remains unsupported."
    ]
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Cost estimation helper
# ---------------------------------------------------------------------------

# Canonical model maps live in core.model_resolution (single source of truth).
_MODEL_ENV_DEFAULTS = MODEL_ENV_DEFAULTS
_MODEL_ENV_VAR_MAP = MODEL_ENV_VAR_MAP


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _resolve_model_name(provider: str | None, execution_tier: str | None) -> str:
    return resolve_model_name(provider, execution_tier)


def _estimate_step_cost(
    role: str,
    usage: dict[str, int],
    *,
    provider: str | None = None,
    model_name: str | None = None,
    execution_tier: str | None = None,
) -> float:
    resolved_provider = provider
    resolved_execution_tier = execution_tier
    if resolved_provider is None or resolved_execution_tier is None:
        route = resolve_debate_route(role)
        resolved_provider = resolved_provider or route.provider
        resolved_execution_tier = resolved_execution_tier or route.execution_tier

    resolved_model_name = model_name or _resolve_model_name(
        resolved_provider,
        resolved_execution_tier,
    )
    pricing = get_token_pricing_for_model(resolved_model_name)
    input_rate = Decimal(str(pricing.get("input", 0)))
    output_rate = Decimal(str(pricing.get("output", 0)))
    prompt_tokens = _safe_int(usage.get("prompt_tokens"))
    completion_tokens = _safe_int(usage.get("completion_tokens"))
    total_tokens = _safe_int(usage.get("total_tokens"))
    if prompt_tokens == 0 and completion_tokens == 0 and total_tokens > 0:
        prompt_tokens = total_tokens

    input_cost_usd = (Decimal(prompt_tokens) / Decimal("1000000")) * input_rate
    output_cost_usd = (Decimal(completion_tokens) / Decimal("1000000")) * output_rate
    return float(input_cost_usd + output_cost_usd)


def _resolve_debate_cost_cap(
    audit_data: dict,
    *,
    tier_class: str,
    requested_tier: str | None = None,
) -> float:
    try:
        forecast = forecast_audit_cost(
            audit_data=audit_data,
            dataforseo_results=None,
            tier_class=tier_class,
            requested_tier=requested_tier,
            policy_version=None,
            feature_key="audit.main",
        )
        forecast_cost = float(forecast.estimated_llm_cost_usd)
    except Exception:
        logger.debug("Falling back to static debate cost cap.", exc_info=True)
        forecast_cost = 0.0
    return max(DEBATE_COST_CAP_USD, forecast_cost * max(1.0, DEBATE_COST_CAP_MULTIPLIER))


# ---------------------------------------------------------------------------
# Event helpers (for frontend SSE/WebSocket streaming)
# ---------------------------------------------------------------------------


def _emit_event(event: str, **kwargs: Any) -> dict:
    """Build a debate progress event dict. Caller is responsible for sending."""
    return {"event": event, "timestamp": time.time(), **kwargs}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_required_keys(
    payload: Any, required_keys: tuple[str, ...], *, label: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} output must be a JSON object.")
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise ValueError(f"{label} output missing required keys: {', '.join(missing)}")
    return payload


def _select_required_keys(*, role: str, requested_tier: str) -> tuple[str, ...]:
    if requested_tier == "deep_judgment":
        if role == "proposer":
            return _CANONICAL_REQUIRED_KEYS
        if role == "challenger":
            return _STRICT_CRITIC_REQUIRED_KEYS
        return _HIGH_CONFIDENCE_JUDGE_REQUIRED_KEYS
    if role == "proposer":
        return _CANONICAL_REQUIRED_KEYS
    if role == "challenger":
        return _STANDARD_CRITIC_REQUIRED_KEYS
    return _STANDARD_SYNTHESIS_REQUIRED_KEYS


def _profile_label(requested_tier: str) -> str | None:
    return "high_confidence" if requested_tier == "deep_judgment" else None


def _judge_authority_label(agent_result: DebateAgentResult | None) -> str | None:
    if agent_result is None or agent_result.semantic_role != "judge":
        return None
    if agent_result.provider == "openai" and (
        agent_result.route_resolution is None
        or agent_result.route_resolution.execution_tier == "smart"
    ):
        return "primary"
    return "fallback"


def _resolve_pipeline_config(requested_tier: str) -> PipelineConfig:
    normalized_requested_tier = normalize_audit_tier(requested_tier)
    config = _PIPELINE_CONFIGS.get(normalized_requested_tier)
    if config is None:
        raise ValueError(f"Unknown debate tier: {requested_tier}")
    return config


def _semantic_role_for_step(role: str) -> str:
    normalized_role = str(role or "").strip().lower()
    if normalized_role in {"proposer", "generator", "fast_proposer"} or normalized_role.endswith(
        "_generator"
    ):
        return "generator"
    if normalized_role in {"challenger", "critic", "fast_critic"} or normalized_role.endswith(
        "_critic"
    ):
        return "critic"
    if normalized_role == "consolidator":
        return "consolidator"
    if normalized_role in {
        "synthesizer",
        "judge",
        "fast_synthesizer",
        "smart_synthesizer",
        "magistrate",
        "global_magistrate",
    }:
        return "judge"
    return normalized_role or "unknown"


def _temperature_for_role(role: str) -> float:
    """Return the LLM temperature for a debate step based on its semantic role.

    Every role in this pipeline feeds the judge, and the judge sets the scores
    the customer sees, so every role decodes greedily (SIGV2-1109). Critics
    included: a critique produced by sampling moves the final score between two
    identical runs, which is the defect this function used to cause.

    ``or`` was used here as a default, which treats a configured 0.0 as missing
    and silently restored a sampling temperature. Only ``None`` is a missing
    value.
    """
    semantic = _semantic_role_for_step(role)
    if semantic == "critic":
        configured = getattr(settings, "AUDIT_CRITIC_TEMPERATURE", None)
    else:
        configured = getattr(settings, "AUDIT_AI_TEMPERATURE", None)
    if configured is None:
        return 0.0
    return float(configured)


def _domain_for_role(role: str) -> str | None:
    normalized_role = str(role or "").strip().lower()
    if normalized_role == "aeo_geo_generator":
        return "aeo_geo"
    if normalized_role == "centralized_critic":
        return "cross_domain"
    for domain in ("seo", "geo", "aeo"):
        if normalized_role.startswith(f"{domain}_"):
            return domain
    return None


def _pipeline_progress_layout(pipeline_type: str | None) -> dict[str, Any] | None:
    normalized_pipeline_type = str(pipeline_type or "").strip().lower()
    if not normalized_pipeline_type:
        return None
    return _PIPELINE_PROGRESS_LAYOUTS.get(normalized_pipeline_type)


def _pipeline_layer_metadata(
    *,
    pipeline_type: str | None,
    layer: int | None,
) -> dict[str, Any] | None:
    layout = _pipeline_progress_layout(pipeline_type)
    if layout is None or layer is None:
        return None
    layers = layout.get("layers")
    if not isinstance(layers, dict):
        return None
    return layers.get(int(layer))


async def _emit_pipeline_started_event(
    on_event: Any | None,
    *,
    pipeline_type: str,
    estimated_duration_s: int,
) -> None:
    layout = _pipeline_progress_layout(pipeline_type)
    if layout is None:
        return
    await _emit_debate_event(
        on_event,
        "debate_pipeline_started",
        pipeline_type=pipeline_type,
        total_agents=int(layout.get("total_agents") or 0),
        parallel_layers=int(layout.get("parallel_layers") or 0),
        estimated_duration_s=max(0, int(estimated_duration_s or 0)),
    )


async def _emit_layer_started_event(
    on_event: Any | None,
    *,
    pipeline_type: str,
    layer: int,
) -> None:
    layer_metadata = _pipeline_layer_metadata(pipeline_type=pipeline_type, layer=layer)
    if layer_metadata is None:
        return
    await _emit_debate_event(
        on_event,
        "debate_layer_started",
        pipeline_type=pipeline_type,
        layer=layer,
        layer_name=layer_metadata.get("layer_name"),
        agents_in_layer=int(layer_metadata.get("agents_in_layer") or 0),
        parallel=bool(layer_metadata.get("parallel")),
    )


async def _emit_layer_completed_event(
    on_event: Any | None,
    *,
    pipeline_type: str,
    layer: int,
    started_at: float,
    agents_completed: int,
    agents_failed: int = 0,
) -> None:
    layer_metadata = _pipeline_layer_metadata(pipeline_type=pipeline_type, layer=layer)
    if layer_metadata is None:
        return
    await _emit_debate_event(
        on_event,
        "debate_layer_completed",
        pipeline_type=pipeline_type,
        layer=layer,
        layer_name=layer_metadata.get("layer_name"),
        total_latency_ms=round(max(0.0, (time.monotonic() - started_at) * 1000)),
        agents_completed=max(0, int(agents_completed)),
        agents_failed=max(0, int(agents_failed)),
    )


async def _emit_pipeline_finished_event(
    on_event: Any | None,
    *,
    pipeline_type: str,
    profile: str | None,
    confidence: float | None,
    total_latency_ms: float,
    total_cost_usd: float,
    judge_authority: str | None = None,
    fallback_reason: str | None = None,
) -> None:
    layout = _pipeline_progress_layout(pipeline_type)
    await _emit_debate_event(
        on_event,
        "debate_complete",
        confidence=confidence,
        profile=profile,
        judge_authority=judge_authority,
        fallback_reason=fallback_reason,
        pipeline_type=pipeline_type,
        total_agents=(int(layout.get("total_agents") or 0) if layout is not None else None),
        parallel_layers=(int(layout.get("parallel_layers") or 0) if layout is not None else None),
        total_latency_ms=round(max(0.0, total_latency_ms)),
        total_cost_usd=round(float(total_cost_usd or 0.0), 6),
    )


def _count_prompt_chars(system_prompt: str, user_prompt: list[Any]) -> int:
    total = len(str(system_prompt or ""))
    for part in user_prompt:
        if isinstance(part, str):
            total += len(part)
    return total


def _truncate_prompt_text(value: str, limit: int) -> str:
    text = str(value or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_ANTHROPIC_TRUNCATION_NOTICE):
        return text[:limit]
    return f"{text[: limit - len(_ANTHROPIC_TRUNCATION_NOTICE)].rstrip()}{_ANTHROPIC_TRUNCATION_NOTICE}"


def _resolve_anthropic_user_prompt_budget(role: str) -> int:
    normalized_role = str(role or "").strip().lower()
    instruction_budget = 4_000
    if normalized_role in {
        "proposer",
        "generator",
        "fast_proposer",
        "seo_generator",
        "aeo_geo_generator",
        "geo_generator",
        "aeo_generator",
    }:
        return _ANTHROPIC_MAX_AUDIT_DATA_CHARS + instruction_budget
    if normalized_role in {
        "challenger",
        "critic",
        "fast_critic",
        "seo_critic",
        "geo_critic",
        "aeo_critic",
    }:
        return (
            _ANTHROPIC_MAX_TRANSFER_PACKET_CHARS
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    if normalized_role == "centralized_critic":
        return (
            (_ANTHROPIC_MAX_TRANSFER_PACKET_CHARS * 2)
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    if normalized_role in {"fast_synthesizer", "synthesizer"}:
        return (
            _ANTHROPIC_MAX_TRANSFER_PACKET_CHARS
            + _ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    if normalized_role == "smart_synthesizer":
        return (
            (_ANTHROPIC_MAX_TRANSFER_PACKET_CHARS * 2)
            + _ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    if normalized_role == "magistrate":
        return (
            _ANTHROPIC_MAX_CONSOLIDATED_PACKET_CHARS
            + _ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    if normalized_role in {"consolidator", "global_magistrate"}:
        return (
            _ANTHROPIC_MAX_CONSOLIDATED_PACKET_CHARS
            + _ANTHROPIC_MAX_TRANSFER_PACKET_CHARS
            + _ANTHROPIC_MAX_AUDIT_DATA_CHARS
            + instruction_budget
        )
    return _ANTHROPIC_MAX_TOTAL_INPUT_CHARS - _ANTHROPIC_MAX_SYSTEM_PROMPT_CHARS


def _prepare_anthropic_prompt_inputs(
    *,
    role: str,
    system_prompt: str,
    user_prompt: list[Any],
) -> tuple[str, list[Any], bool, int]:
    original_total_chars = _count_prompt_chars(system_prompt, user_prompt)
    prepared_system_prompt = str(system_prompt or "")
    prepared_user_prompt: list[Any] = []
    truncated = False
    user_prompt_limit = _resolve_anthropic_user_prompt_budget(role)

    for part in user_prompt:
        if isinstance(part, str):
            trimmed_part = _truncate_prompt_text(part, user_prompt_limit)
            truncated = truncated or trimmed_part != part
            prepared_user_prompt.append(trimmed_part)
        else:
            prepared_user_prompt.append(part)

    trimmed_system_prompt = _truncate_prompt_text(
        prepared_system_prompt,
        _ANTHROPIC_MAX_SYSTEM_PROMPT_CHARS,
    )
    truncated = truncated or trimmed_system_prompt != prepared_system_prompt
    prepared_system_prompt = trimmed_system_prompt

    total_chars = _count_prompt_chars(prepared_system_prompt, prepared_user_prompt)
    while total_chars > _ANTHROPIC_MAX_TOTAL_INPUT_CHARS:
        string_lengths = [
            (len(part), index)
            for index, part in enumerate(prepared_user_prompt)
            if isinstance(part, str)
        ]
        if string_lengths:
            _, largest_index = max(string_lengths)
            current_value = str(prepared_user_prompt[largest_index] or "")
            target_limit = max(
                1_024, len(current_value) - (total_chars - _ANTHROPIC_MAX_TOTAL_INPUT_CHARS)
            )
            updated_value = _truncate_prompt_text(current_value, target_limit)
            if updated_value == current_value:
                break
            prepared_user_prompt[largest_index] = updated_value
            truncated = True
        elif len(prepared_system_prompt) > 1_024:
            target_limit = max(
                1_024,
                len(prepared_system_prompt) - (total_chars - _ANTHROPIC_MAX_TOTAL_INPUT_CHARS),
            )
            updated_system_prompt = _truncate_prompt_text(prepared_system_prompt, target_limit)
            if updated_system_prompt == prepared_system_prompt:
                break
            prepared_system_prompt = updated_system_prompt
            truncated = True
        else:
            break
        total_chars = _count_prompt_chars(prepared_system_prompt, prepared_user_prompt)

    return prepared_system_prompt, prepared_user_prompt, truncated, original_total_chars


def _is_anthropic_payload_too_large_error(exc: Exception) -> bool:
    message = str(exc or "").strip().lower()
    if not message:
        return False
    signals = (
        "payload too large",
        "input too large",
        "input is too large",
        "prompt is too long",
        "context length",
        "maximum context length",
        "too many input tokens",
        "too many tokens",
        "request_too_large",
        "compiled grammar is too large",
        "413",
    )
    return any(signal in message for signal in signals)


def _build_per_agent_costs(rounds: list[DebateAgentResult]) -> list[dict[str, Any]]:
    per_agent_costs: list[dict[str, Any]] = []
    for round_result in rounds:
        usage = round_result.token_usage if isinstance(round_result.token_usage, dict) else {}
        item: dict[str, Any] = {
            "role": round_result.role,
            "semantic_role": round_result.semantic_role,
            "provider": round_result.provider,
            "model": round_result.model,
            "latency_ms": round(round_result.latency_ms, 2),
            "cost_usd": round(round_result.step_cost_usd, 6),
            "tokens": {
                "prompt": int(usage.get("prompt_tokens") or 0),
                "completion": int(usage.get("completion_tokens") or 0),
                "total": int(usage.get("total_tokens") or 0),
            },
        }
        if round_result.layer_index is not None:
            item["layer"] = int(round_result.layer_index)
        if round_result.route_resolution is not None:
            item["execution_tier"] = round_result.route_resolution.execution_tier
            item["routing_mode"] = round_result.route_resolution.routing_mode
        per_agent_costs.append(item)
    return per_agent_costs


def _safe_json_dumps(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return json.dumps(
            {"unserializable_payload_type": type(payload).__name__}, ensure_ascii=True
        )


def _serialize_trace_input(*, system_prompt: str, user_prompt: list[Any]) -> str:
    return _safe_json_dumps(
        {
            "system_prompt": str(system_prompt or ""),
            "user_prompt": list(user_prompt or []),
        }
    )


def _resolve_trace_pipeline_type(*, requested_tier: str, pipeline_type: str | None) -> str:
    if isinstance(pipeline_type, str) and pipeline_type.strip():
        return pipeline_type.strip()
    if normalize_audit_tier(requested_tier) == "deep_judgment":
        return "legacy_high_confidence"
    return "legacy_3step"


def _build_trace_claim_ledger(*, role: str, output: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None

    normalized_role = str(role or "").strip().lower()
    if normalized_role in {
        "challenger",
        "fast_critic",
        "centralized_critic",
        "seo_critic",
        "geo_critic",
        "aeo_critic",
    }:
        return claim_ledger_service.build_challenge_transfer_packet(output)

    if normalized_role == "consolidator":
        return {
            "domain_summaries": output.get("domain_summaries")
            if isinstance(output.get("domain_summaries"), dict)
            else {},
            "consolidated_claim_disposition": list(
                output.get("consolidated_claim_disposition") or []
            ),
            "cross_domain_conflicts": list(output.get("cross_domain_conflicts") or []),
            "dedup_count": int(output.get("dedup_count") or 0),
            "dedup_details": list(output.get("dedup_details") or []),
        }

    if "claim_ledger" in output or "recommendations" in output or "seo_findings" in output:
        return claim_ledger_service.build_analysis_transfer_packet(output)

    if "judge_summary" in output:
        trace_packet: dict[str, Any] = {
            "judge_summary": dict(output.get("judge_summary") or {}),
        }
        summary_text = str(output.get("summary") or "").strip()
        if summary_text:
            trace_packet["summary"] = summary_text[:280]
        return trace_packet

    return None


def _append_trace_record(
    trace_records: list[dict[str, Any]] | None,
    *,
    agent_role: str,
    agent_layer: int | None,
    pipeline_type: str,
    provider: str,
    model: str,
    input_payload_json: str,
    output_payload: Any,
    output_claim_ledger: dict[str, Any] | None,
    latency_ms: float,
    cost_usd: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    status: str,
    error_message: str | None = None,
) -> None:
    if trace_records is None:
        return

    input_summary = input_payload_json[:500] if input_payload_json else None
    trace_records.append(
        {
            "agent_role": str(agent_role or ""),
            "agent_layer": int(agent_layer or 0),
            "pipeline_type": str(pipeline_type or "legacy_3step"),
            "provider": str(provider or "unknown"),
            "model": str(model or ""),
            "input_payload_hash": hashlib.sha256(input_payload_json.encode("utf-8")).hexdigest(),
            "input_payload_chars": len(input_payload_json),
            "input_summary": input_summary,
            "input_payload_raw": input_payload_json,
            "output_raw": _safe_json_dumps(output_payload),
            "output_claim_ledger": output_claim_ledger,
            "latency_ms": max(0, int(round(latency_ms))),
            "cost_usd": round(float(cost_usd or 0.0), 6) if cost_usd is not None else None,
            "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
            "completion_tokens": int(completion_tokens) if completion_tokens is not None else None,
            "status": str(status or "completed"),
            "error_message": str(error_message or "").strip() or None,
        }
    )


def _build_debate_result(
    *,
    rounds: list[DebateAgentResult],
    final_synthesis: dict[str, Any],
    synthesis_reasoning: str,
    debate_confidence_score: float,
    total_token_usage: dict[str, int],
    total_latency_ms: float,
    total_estimated_cost_usd: float,
    profile: str | None,
    judge_summary: dict[str, int] | None = None,
    judge_authority: str | None = None,
    fallback_reason: str | None = None,
    final_provider: str | None = None,
    final_model: str | None = None,
    pipeline_type: str | None = None,
    parallel_layers: int = 0,
    trace_records: list[dict[str, Any]] | None = None,
    consolidation_status: str = CONSOLIDATION_FULL,
) -> DebateResult:
    return DebateResult(
        rounds=rounds,
        final_synthesis=final_synthesis,
        synthesis_reasoning=synthesis_reasoning,
        debate_confidence_score=debate_confidence_score,
        total_token_usage=total_token_usage,
        total_latency_ms=total_latency_ms,
        total_estimated_cost_usd=total_estimated_cost_usd,
        profile=profile,
        judge_summary=judge_summary,
        judge_authority=judge_authority,
        fallback_reason=fallback_reason,
        final_provider=final_provider,
        final_model=final_model,
        pipeline_type=pipeline_type,
        parallel_layers=parallel_layers,
        agent_count=len(rounds),
        per_agent_costs=_build_per_agent_costs(rounds),
        trace_records=list(trace_records or []),
        consolidation_status=consolidation_status,
    )


async def _emit_debate_event(on_event: Any | None, event: str, **kwargs: Any) -> None:
    if on_event and callable(on_event):
        try:
            evt = _emit_event(event, **kwargs)
            if asyncio.iscoroutinefunction(on_event):
                await on_event(evt)
            else:
                on_event(evt)
        except Exception:
            logger.debug("Failed to emit debate event %s", event, exc_info=True)


async def _run_agent_step(
    *,
    ai_factory: "AIFactory",
    rounds: list[DebateAgentResult],
    role: str,
    system_prompt: str,
    user_prompt: list,
    schema: dict[str, Any] | None,
    required_keys: tuple[str, ...],
    requested_tier: str,
    step_timeout_s: int,
    on_event: Any | None = None,
    exclude_provider: str | None = None,
    layer_index: int | None = None,
    route_override: AuditRouteResolution | None = None,
    record_result: bool = True,
    trace_records: list[dict[str, Any]] | None = None,
    pipeline_type: str | None = None,
    preferred_provider: str | None = None,
) -> DebateAgentResult:
    semantic_role = _semantic_role_for_step(role)
    route = route_override or resolve_debate_route(
        role,
        requested_tier=requested_tier,
        exclude_provider=exclude_provider,
        preferred_provider=preferred_provider,
    )
    resolved_pipeline_type = _resolve_trace_pipeline_type(
        requested_tier=requested_tier,
        pipeline_type=pipeline_type,
    )
    model_info = ai_factory.get_model_instance(route.provider, route.execution_tier)
    provider = route.provider
    model_name = ""
    system_prompt_to_use = system_prompt
    user_prompt_to_use = list(user_prompt)
    raw_output: Any = {}
    usage: dict[str, Any] = {}
    step_cost = 0.0
    step_start = time.monotonic()

    if not model_info:
        input_payload_json = _serialize_trace_input(
            system_prompt=system_prompt_to_use,
            user_prompt=user_prompt_to_use,
        )
        _append_trace_record(
            trace_records,
            agent_role=role,
            agent_layer=layer_index,
            pipeline_type=resolved_pipeline_type,
            provider=provider,
            model=model_name,
            input_payload_json=input_payload_json,
            output_payload={"error": "Model not available for route."},
            output_claim_ledger=None,
            latency_ms=(time.monotonic() - step_start) * 1000,
            cost_usd=None,
            prompt_tokens=None,
            completion_tokens=None,
            status="failed",
            error_message=f"No model available for debate role {role} ({route.provider}/{route.execution_tier})",
        )
        raise RuntimeError(
            f"No model available for debate role {role} ({route.provider}/{route.execution_tier})"
        )
    provider, model_name = model_info
    if provider == "anthropic":
        (
            system_prompt_to_use,
            user_prompt_to_use,
            anthropic_truncated,
            original_total_chars,
        ) = _prepare_anthropic_prompt_inputs(
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if anthropic_truncated or original_total_chars > _ANTHROPIC_MAX_TOTAL_INPUT_CHARS:
            logger.warning(
                "[ANTHROPIC_GUARD] Payload too large for %s: %d chars. Truncating.",
                role,
                original_total_chars,
            )

    await _emit_debate_event(
        on_event,
        "debate_step_started",
        role=role,
        semantic_role=semantic_role,
        provider=provider,
        model=model_name,
        layer=layer_index,
        pipeline_type=resolved_pipeline_type,
        domain=_domain_for_role(role),
    )

    try:
        step_temperature = _temperature_for_role(role)
        result = await asyncio.wait_for(
            ai_factory._generate_with_provider(
                provider,
                model_name,
                system_prompt_to_use,
                user_prompt_to_use,
                schema=schema,
                temperature=step_temperature,
            ),
            timeout=step_timeout_s,
        )
        raw_output = result
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"Debate step '{role}' timed out after {step_timeout_s}s") from exc
    except Exception as exc:
        if provider == "anthropic" and _is_anthropic_payload_too_large_error(exc):
            fallback_route = resolve_debate_route(
                role,
                requested_tier=requested_tier,
                exclude_provider="anthropic",
                preferred_provider=preferred_provider,
            )
            fallback_model_info = ai_factory.get_model_instance(
                fallback_route.provider,
                fallback_route.execution_tier,
            )
            if fallback_route.provider == "anthropic" or not fallback_model_info:
                raise
            provider, model_name = fallback_model_info
            route = fallback_route
            logger.warning(
                "[ANTHROPIC_GUARD] Anthropic payload too large for %s; falling back to %s/%s.",
                role,
                provider,
                model_name,
            )
            system_prompt_to_use = system_prompt
            user_prompt_to_use = list(user_prompt)
            result = await asyncio.wait_for(
                ai_factory._generate_with_provider(
                    provider,
                    model_name,
                    system_prompt,
                    user_prompt,
                    schema=schema,
                    temperature=step_temperature,
                ),
                timeout=step_timeout_s,
            )
            raw_output = result
        else:
            raise
    try:
        validated_output = _validate_required_keys(raw_output, required_keys, label=semantic_role)
        latency_ms = (time.monotonic() - step_start) * 1000
        usage = ai_factory.extract_generation_metadata(validated_output).get("usage", {})
        step_cost = _estimate_step_cost(
            role,
            usage,
            provider=provider,
            model_name=model_name,
            execution_tier=route.execution_tier,
        )

        agent_result = DebateAgentResult(
            role=role,
            semantic_role=semantic_role,
            provider=provider,
            model=model_name,
            output=validated_output,
            token_usage=usage,
            latency_ms=latency_ms,
            route_resolution=route,
            step_cost_usd=step_cost,
            layer_index=layer_index,
        )
        if record_result:
            rounds.append(agent_result)

        input_payload_json = _serialize_trace_input(
            system_prompt=system_prompt_to_use,
            user_prompt=user_prompt_to_use,
        )
        _append_trace_record(
            trace_records,
            agent_role=role,
            agent_layer=layer_index,
            pipeline_type=resolved_pipeline_type,
            provider=provider,
            model=model_name,
            input_payload_json=input_payload_json,
            output_payload=validated_output,
            output_claim_ledger=_build_trace_claim_ledger(role=role, output=validated_output),
            latency_ms=latency_ms,
            cost_usd=step_cost,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            status="completed",
        )

        await _emit_debate_event(
            on_event,
            "debate_step_completed",
            role=role,
            semantic_role=semantic_role,
            provider=provider,
            model=model_name,
            latency_ms=round(latency_ms),
            summary=summarize_debate_output(role, validated_output),
            layer=layer_index,
            pipeline_type=resolved_pipeline_type,
            domain=_domain_for_role(role),
        )
        logger.info(
            "[DEBATE] %s/%s completed: provider=%s model=%s latency=%.0fms tokens=%s cost_est_usd=%.4f",
            role,
            semantic_role,
            provider,
            model_name,
            latency_ms,
            usage.get("total_tokens", "?"),
            step_cost,
        )
        if latency_ms > step_timeout_s * 800:
            logger.warning(
                "[DEBATE_SLOW_STEP] %s exceeded 80%% of step timeout: %.0fms / %ds",
                role,
                latency_ms,
                step_timeout_s,
            )
        return agent_result
    except Exception as exc:
        latency_ms = (time.monotonic() - step_start) * 1000
        usage_payload = (
            ai_factory.extract_generation_metadata(raw_output).get("usage", {})
            if isinstance(raw_output, dict)
            else {}
        )
        input_payload_json = _serialize_trace_input(
            system_prompt=system_prompt_to_use,
            user_prompt=user_prompt_to_use,
        )
        _append_trace_record(
            trace_records,
            agent_role=role,
            agent_layer=layer_index,
            pipeline_type=resolved_pipeline_type,
            provider=provider,
            model=model_name,
            input_payload_json=input_payload_json,
            output_payload=raw_output if raw_output else {"error": str(exc)},
            output_claim_ledger=(
                _build_trace_claim_ledger(role=role, output=raw_output)
                if isinstance(raw_output, dict)
                else None
            ),
            latency_ms=latency_ms,
            cost_usd=None,
            prompt_tokens=(
                int(usage_payload.get("prompt_tokens") or 0)
                if isinstance(usage_payload, dict)
                else None
            ),
            completion_tokens=(
                int(usage_payload.get("completion_tokens") or 0)
                if isinstance(usage_payload, dict)
                else None
            ),
            status="timeout" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "failed",
            error_message=str(exc),
        )
        raise


# ── Provider cascade fallback wrapper ──────────────────────────────
# Retries a failed agent step with the next available provider from
# the per-role candidate list.  Timeouts are NOT retried (the overall
# pipeline timeout governs budget), but provider errors (429, 500,
# auth failures, payload rejections) trigger cascade to the next
# candidate.

_CASCADE_MAX_RETRIES = 2  # At most 2 fallback attempts per step


async def _run_agent_step_with_cascade(
    *,
    ai_factory: "AIFactory",
    rounds: list[DebateAgentResult],
    role: str,
    system_prompt: str,
    user_prompt: list,
    schema: dict[str, Any] | None,
    required_keys: tuple[str, ...],
    requested_tier: str,
    step_timeout_s: int,
    on_event: Any | None = None,
    exclude_provider: str | None = None,
    layer_index: int | None = None,
    route_override: AuditRouteResolution | None = None,
    record_result: bool = True,
    trace_records: list[dict[str, Any]] | None = None,
    pipeline_type: str | None = None,
    preferred_provider: str | None = None,
) -> DebateAgentResult:
    """Wrap ``_run_agent_step`` with automatic provider cascade on failure.

    On non-timeout errors the function re-resolves the route excluding the
    failed provider and retries up to ``_CASCADE_MAX_RETRIES`` times.  An
    SSE ``debate_step_started`` event with ``cascade_retry=True`` is emitted
    before each retry so the frontend can visualize the fallback.
    """
    excluded: set[str] = set()
    # Providers excluded only as a *preference* (e.g. the critic prefers a
    # different provider than the generator) vs. providers that actually
    # FAILED. A preference exclusion may be relaxed as a last resort so the
    # step falls back instead of degrading when it is the only credited
    # provider available.
    preference_excluded = exclude_provider
    failed_providers: set[str] = set()
    preference_relaxed = False
    if exclude_provider:
        excluded.add(exclude_provider)
    last_exc: Exception | None = None

    for attempt in range(_CASCADE_MAX_RETRIES + 1):
        try:
            current_route = route_override if attempt == 0 else None
            if attempt > 0:
                # Re-resolve route excluding all previously failed providers
                current_route = resolve_debate_route(
                    role,
                    requested_tier=requested_tier,
                    exclude_provider=None,
                    preferred_provider=preferred_provider,
                )
                # Manually deprioritize excluded providers by selecting the
                # first candidate whose provider is not in the excluded set.
                # This is a lightweight re-resolution since resolve_debate_route
                # only supports a single exclude_provider.
                if excluded and current_route.provider in excluded:
                    for ex_p in excluded:
                        alt_route = resolve_debate_route(
                            role,
                            requested_tier=requested_tier,
                            exclude_provider=ex_p,
                            preferred_provider=preferred_provider,
                        )
                        if alt_route.provider not in excluded:
                            current_route = alt_route
                            break

                if current_route.provider in excluded:
                    # All candidates exhausted, re-raise the last error
                    break

                logger.warning(
                    "[CASCADE] Retry %d/%d for %s: switching to %s (excluded=%s)",
                    attempt,
                    _CASCADE_MAX_RETRIES,
                    role,
                    current_route.provider,
                    excluded,
                )
                await _emit_debate_event(
                    on_event,
                    "debate_step_started",
                    role=role,
                    semantic_role=_semantic_role_for_step(role),
                    provider=current_route.provider,
                    model="",
                    layer=layer_index,
                    pipeline_type=_resolve_trace_pipeline_type(
                        requested_tier=requested_tier,
                        pipeline_type=pipeline_type,
                    ),
                    domain=_domain_for_role(role),
                    cascade_retry=True,
                    cascade_attempt=attempt,
                    cascade_excluded=list(excluded),
                )

            # On retries, exclude_provider is irrelevant because current_route
            # (route_override) is always set, _run_agent_step skips its own
            # resolve_debate_route call when route_override is present.
            # NOTE: the Anthropic payload-too-large inner fallback inside
            # _run_agent_step hardcodes exclude_provider="anthropic" and does
            # not know about our broader `excluded` set.  If that inner fallback
            # selects a previously-failed provider, the outer cascade loop here
            # will catch the failure and continue normally.
            result = await _run_agent_step(
                ai_factory=ai_factory,
                rounds=rounds,
                role=role,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                required_keys=required_keys,
                requested_tier=requested_tier,
                step_timeout_s=step_timeout_s,
                on_event=on_event,
                exclude_provider=None if attempt > 0 else exclude_provider,
                layer_index=layer_index,
                route_override=current_route,
                record_result=record_result,
                trace_records=trace_records,
                pipeline_type=pipeline_type,
                preferred_provider=preferred_provider,
            )
            # Estimate cascade waste: assume each failed attempt consumed
            # roughly the same tokens as the successful one (conservative).
            if attempt > 0 and result.step_cost_usd > 0:
                result.cascade_waste_cost_usd = result.step_cost_usd * attempt
                logger.info(
                    "[CASCADE] %s succeeded on attempt %d; estimated waste %.4f EUR from %d failed attempt(s)",
                    role,
                    attempt + 1,
                    result.cascade_waste_cost_usd,
                    attempt,
                )
            return result
        except (TimeoutError, asyncio.TimeoutError):
            # Timeouts are NOT retried, let the overall pipeline budget decide
            raise
        except Exception as exc:
            last_exc = exc
            # Extract failed provider from the route that was actually used
            # NOTE: do NOT fall back to exclude_provider here, on attempt 0 the
            # actual provider is resolved inside _run_agent_step and is never the
            # excluded one, so attributing the failure to exclude_provider would
            # wrongly poison the failed set and block the last-resort fallback.
            failed_provider = (
                (current_route.provider if current_route else None)
                or (route_override.provider if route_override else None)
                or "unknown"
            )
            excluded.add(failed_provider)
            failed_providers.add(failed_provider)
            logger.warning(
                "[CASCADE] %s failed on provider %s (attempt %d/%d): %s",
                role,
                failed_provider,
                attempt + 1,
                _CASCADE_MAX_RETRIES + 1,
                str(exc)[:200],
            )
            continue

    # Last resort: a provider excluded only as a *preference* (e.g. the critic
    # wanting a different provider than the generator) may be the only credited
    # provider available. Rather than degrading the audit, make one final
    # attempt with it before giving up. Providers that actually FAILED are not
    # retried here (they are in failed_providers).
    if (
        preference_excluded
        and not preference_relaxed
        and preference_excluded not in failed_providers
    ):
        preference_relaxed = True
        try:
            relaxed_route = resolve_debate_route(
                role,
                requested_tier=requested_tier,
                exclude_provider=None,
                preferred_provider=preference_excluded,
            )
            if relaxed_route.provider not in failed_providers:
                logger.warning(
                    "[CASCADE] %s last-resort fallback to preference-excluded provider %s (failed=%s)",
                    role,
                    relaxed_route.provider,
                    failed_providers,
                )
                return await _run_agent_step(
                    ai_factory=ai_factory,
                    rounds=rounds,
                    role=role,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=schema,
                    required_keys=required_keys,
                    requested_tier=requested_tier,
                    step_timeout_s=step_timeout_s,
                    on_event=on_event,
                    exclude_provider=None,
                    layer_index=layer_index,
                    route_override=relaxed_route,
                    record_result=record_result,
                    trace_records=trace_records,
                    pipeline_type=pipeline_type,
                    preferred_provider=preferred_provider,
                )
        except (TimeoutError, asyncio.TimeoutError):
            raise
        except Exception as final_exc:
            last_exc = final_exc

    # All cascade attempts exhausted, re-raise
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Cascade exhausted for {role} with no result")


async def _run_legacy_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    requested_tier: str,
    tier_class: str,
    config: PipelineConfig,
    on_event: Any | None = None,
) -> DebateResult:
    normalized_requested_tier = normalize_audit_tier(requested_tier)
    debate_start = time.monotonic()
    rounds: list[DebateAgentResult] = []
    trace_records: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    debate_cost_cap = _resolve_debate_cost_cap(
        audit_data,
        tier_class=tier_class,
        requested_tier=normalized_requested_tier,
    )
    profile = _profile_label(normalized_requested_tier)
    pipeline_type = _resolve_trace_pipeline_type(
        requested_tier=normalized_requested_tier,
        pipeline_type=None,
    )

    async def _record_step(
        *,
        role: str,
        system_prompt: str,
        user_prompt: list,
        schema: dict[str, Any] | None,
        required_keys: tuple[str, ...],
        exclude_provider: str | None = None,
    ) -> DebateAgentResult:
        nonlocal cumulative_cost

        legacy_config = _LEGACY_ROLE_CONFIG.get(role, {})
        agent_result = await _run_agent_step(
            ai_factory=ai_factory,
            rounds=rounds,
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            required_keys=required_keys,
            requested_tier=normalized_requested_tier,
            step_timeout_s=int(legacy_config.get("timeout_s") or config.step_timeout_s),
            on_event=on_event,
            exclude_provider=exclude_provider,
            trace_records=trace_records,
            pipeline_type=pipeline_type,
        )
        cumulative_cost += agent_result.step_cost_usd
        if cumulative_cost > debate_cost_cap:
            raise RuntimeError(
                f"Debate cost cap exceeded: EUR {cumulative_cost:.4f} > EUR {debate_cost_cap:.2f}"
            )
        return agent_result

    try:
        async with asyncio.timeout(_LEGACY_DEBATE_TOTAL_TIMEOUT_S):
            if normalized_requested_tier == "deep_judgment":
                proposer_system, proposer_user = _build_generator_prompt(audit_data, prompt_context)
            else:
                proposer_system, proposer_user = _build_proposer_prompt(audit_data, prompt_context)
            proposer_result = await _record_step(
                role="proposer",
                system_prompt=proposer_system,
                user_prompt=proposer_user,
                schema=CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA,
                required_keys=_CANONICAL_REQUIRED_KEYS,
            )

            try:
                if normalized_requested_tier == "deep_judgment":
                    challenger_system, challenger_user = _build_critic_prompt(
                        audit_data,
                        proposer_result.output,
                    )
                    challenger_schema = _HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA
                    challenger_required_keys = _STRICT_CRITIC_REQUIRED_KEYS
                else:
                    challenger_system, challenger_user = _build_challenger_prompt(
                        audit_data,
                        proposer_result.output,
                    )
                    challenger_schema = _CHALLENGER_OUTPUT_SCHEMA
                    challenger_required_keys = _STANDARD_CRITIC_REQUIRED_KEYS
                challenger_result = await _record_step(
                    role="challenger",
                    system_prompt=challenger_system,
                    user_prompt=challenger_user,
                    schema=challenger_schema,
                    required_keys=challenger_required_keys,
                    exclude_provider=(
                        proposer_result.provider
                        if normalized_requested_tier != "deep_judgment"
                        else None
                    ),
                )
            except Exception as challenger_exc:
                logger.warning(
                    "[DEBATE] %s failed: %s, accepting proposal unchallenged",
                    "Critic" if normalized_requested_tier == "deep_judgment" else "Challenger",
                    challenger_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                await _emit_debate_event(
                    on_event,
                    "debate_complete",
                    confidence=None,
                    profile=profile,
                    fallback_reason=(
                        "critic_unavailable"
                        if normalized_requested_tier == "deep_judgment"
                        else None
                    ),
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=proposer_result.output,
                    synthesis_reasoning=(
                        "Critic unavailable, generator proposal accepted without challenge."
                        if normalized_requested_tier == "deep_judgment"
                        else "Challenger unavailable, proposal accepted without challenge."
                    ),
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="critic_unavailable"
                    if normalized_requested_tier == "deep_judgment"
                    else None,
                    final_provider=proposer_result.provider,
                    final_model=proposer_result.model,
                    pipeline_type=pipeline_type,
                    trace_records=trace_records,
                )

            try:
                if normalized_requested_tier == "deep_judgment":
                    synthesizer_system, synthesizer_user = _build_judge_prompt(
                        audit_data,
                        proposer_result.output,
                        challenger_result.output,
                        prompt_context,
                    )
                    synthesizer_schema = _HIGH_CONFIDENCE_JUDGE_SCHEMA
                    synthesizer_required_keys = _HIGH_CONFIDENCE_JUDGE_REQUIRED_KEYS
                else:
                    synthesizer_system, synthesizer_user = _build_synthesizer_prompt(
                        audit_data,
                        proposer_result.output,
                        challenger_result.output,
                        prompt_context,
                    )
                    synthesizer_schema = _STANDARD_DEBATE_SYNTHESIS_SCHEMA
                    synthesizer_required_keys = _STANDARD_SYNTHESIS_REQUIRED_KEYS
                synthesizer_result = await _record_step(
                    role="synthesizer",
                    system_prompt=synthesizer_system,
                    user_prompt=synthesizer_user,
                    schema=synthesizer_schema,
                    required_keys=synthesizer_required_keys,
                    exclude_provider=(
                        challenger_result.provider
                        if normalized_requested_tier != "deep_judgment"
                        else None
                    ),
                )
            except Exception as synth_exc:
                logger.warning(
                    "[DEBATE] %s failed: %s, returning proposal with critique notes",
                    "Judge" if normalized_requested_tier == "deep_judgment" else "Synthesizer",
                    synth_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                await _emit_debate_event(
                    on_event,
                    "debate_complete",
                    confidence=None,
                    profile=profile,
                    fallback_reason=(
                        "judge_unavailable"
                        if normalized_requested_tier == "deep_judgment"
                        else None
                    ),
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=proposer_result.output,
                    synthesis_reasoning=(
                        "Judge unavailable, generator proposal returned with critic notes."
                        if normalized_requested_tier == "deep_judgment"
                        else "Synthesizer unavailable, proposal returned with challenger notes."
                    ),
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="judge_unavailable"
                    if normalized_requested_tier == "deep_judgment"
                    else None,
                    final_provider=proposer_result.provider,
                    final_model=proposer_result.model,
                    pipeline_type=pipeline_type,
                    trace_records=trace_records,
                )

    except (TimeoutError, asyncio.TimeoutError):
        if not rounds:
            raise
        total_latency = (time.monotonic() - debate_start) * 1000
        total_usage = _aggregate_usage(rounds)
        proposer_result = rounds[0]
        logger.error(
            "[DEBATE] Total debate timeout after %.0fms with %d steps completed",
            total_latency,
            len(rounds),
        )
        await _emit_debate_event(
            on_event,
            "debate_complete",
            confidence=None,
            profile=profile,
            fallback_reason=(
                "judge_unavailable" if normalized_requested_tier == "deep_judgment" else None
            ),
        )
        return _build_debate_result(
            rounds=rounds,
            final_synthesis=proposer_result.output,
            synthesis_reasoning=f"Debate timed out after {len(rounds)} of 3 steps.",
            debate_confidence_score=0.0,
            total_token_usage=total_usage,
            total_latency_ms=total_latency,
            total_estimated_cost_usd=cumulative_cost,
            profile=profile,
            fallback_reason="judge_unavailable"
            if normalized_requested_tier == "deep_judgment"
            else None,
            final_provider=proposer_result.provider,
            final_model=proposer_result.model,
            pipeline_type=pipeline_type,
            trace_records=trace_records,
        )

    synthesis_output = (
        dict(synthesizer_result.output) if isinstance(synthesizer_result.output, dict) else {}
    )
    synthesis_reasoning = synthesis_output.pop("synthesis_reasoning", "")
    confidence = synthesis_output.pop("debate_confidence_score", 0.0)
    judge_summary = None
    if normalized_requested_tier == "deep_judgment":
        judge_summary = synthesis_output.pop("judge_summary", None)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    total_latency = (time.monotonic() - debate_start) * 1000
    total_usage = _aggregate_usage(rounds)
    judge_authority = (
        _judge_authority_label(synthesizer_result)
        if normalized_requested_tier == "deep_judgment"
        else None
    )

    await _emit_debate_event(
        on_event,
        "debate_complete",
        confidence=round(confidence, 2),
        profile=profile,
        judge_authority=judge_authority,
    )

    logger.info(
        "[DEBATE] Complete: requested_tier=%s steps=%d confidence=%.2f latency=%.0fms cost_usd=%.4f",
        normalized_requested_tier,
        len(rounds),
        confidence,
        total_latency,
        cumulative_cost,
    )

    return _build_debate_result(
        rounds=rounds,
        final_synthesis=synthesis_output,
        synthesis_reasoning=synthesis_reasoning,
        debate_confidence_score=confidence,
        total_token_usage=total_usage,
        total_latency_ms=total_latency,
        total_estimated_cost_usd=cumulative_cost,
        profile=profile,
        judge_summary=dict(judge_summary) if isinstance(judge_summary, dict) else None,
        judge_authority=judge_authority,
        final_provider=synthesizer_result.provider,
        final_model=synthesizer_result.model,
        pipeline_type=pipeline_type,
        trace_records=trace_records,
    )


async def _run_fast_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    config: PipelineConfig,
    on_event: Any | None = None,
    preferred_provider: str | None = None,
) -> DebateResult:
    debate_start = time.monotonic()
    rounds: list[DebateAgentResult] = []
    trace_records: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    profile = config.profile_label
    pipeline_type = config.profile_label
    debate_cost_cap = max(0.0, float(config.cost_cap_usd))

    # NOTE: The fast pipeline does NOT use _run_agent_step_with_cascade.
    # Fast tier has tight time budgets (15s step / 60s total) where cascade
    # retries would likely exceed the pipeline timeout.  Provider errors in
    # fast mode propagate directly and the caller falls back to non-debate.
    async def _record_step(
        *,
        role: str,
        system_prompt: str,
        user_prompt: list,
        schema: dict[str, Any] | None,
        required_keys: tuple[str, ...],
        exclude_provider: str | None = None,
        layer_index: int,
    ) -> DebateAgentResult:
        nonlocal cumulative_cost

        agent_result = await _run_agent_step(
            ai_factory=ai_factory,
            rounds=rounds,
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            required_keys=required_keys,
            requested_tier="fast",
            step_timeout_s=config.step_timeout_s,
            on_event=on_event,
            exclude_provider=exclude_provider,
            layer_index=layer_index,
            trace_records=trace_records,
            pipeline_type=pipeline_type,
            preferred_provider=preferred_provider,
        )
        cumulative_cost += agent_result.step_cost_usd
        if cumulative_cost > debate_cost_cap:
            raise RuntimeError(
                f"FAST debate cost cap exceeded: EUR {cumulative_cost:.4f} > EUR {debate_cost_cap:.2f}"
            )
        return agent_result

    await _emit_pipeline_started_event(
        on_event,
        pipeline_type=pipeline_type,
        estimated_duration_s=config.total_timeout_s,
    )

    try:
        async with asyncio.timeout(config.total_timeout_s):
            proposer_layer_started_at = time.monotonic()
            await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=1)
            proposer_system, proposer_user = _build_fast_proposer_prompt(
                audit_data,
                prompt_context,
            )
            proposer_result = await _record_step(
                role="fast_proposer",
                system_prompt=proposer_system,
                user_prompt=proposer_user,
                schema=CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA,
                required_keys=_CANONICAL_REQUIRED_KEYS,
                layer_index=1,
            )
            await _emit_layer_completed_event(
                on_event,
                pipeline_type=pipeline_type,
                layer=1,
                started_at=proposer_layer_started_at,
                agents_completed=1,
            )

            try:
                critic_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=2)
                critic_system, critic_user = _build_fast_critic_prompt(
                    audit_data,
                    proposer_result.output,
                )
                critic_result = await _record_step(
                    role="fast_critic",
                    system_prompt=critic_system,
                    user_prompt=critic_user,
                    schema=_CHALLENGER_OUTPUT_SCHEMA,
                    required_keys=_STANDARD_CRITIC_REQUIRED_KEYS,
                    exclude_provider=proposer_result.provider,
                    layer_index=2,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=2,
                    started_at=critic_layer_started_at,
                    agents_completed=1,
                )
            except Exception as critic_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=2,
                    started_at=critic_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] FAST critic failed: %s, accepting proposer output without challenge",
                    critic_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="critic_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=proposer_result.output,
                    synthesis_reasoning="Critic unavailable, proposer analysis accepted without challenge.",
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="critic_unavailable",
                    final_provider=proposer_result.provider,
                    final_model=proposer_result.model,
                    pipeline_type=pipeline_type,
                    parallel_layers=0,
                    trace_records=trace_records,
                )

            try:
                synthesizer_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=3)
                synthesizer_system, synthesizer_user = _build_fast_synthesizer_prompt(
                    audit_data,
                    proposer_result.output,
                    critic_result.output,
                    prompt_context,
                )
                synthesizer_result = await _record_step(
                    role="fast_synthesizer",
                    system_prompt=synthesizer_system,
                    user_prompt=synthesizer_user,
                    schema=_STANDARD_DEBATE_SYNTHESIS_SCHEMA,
                    required_keys=_STANDARD_SYNTHESIS_REQUIRED_KEYS,
                    exclude_provider=critic_result.provider,
                    layer_index=3,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=synthesizer_layer_started_at,
                    agents_completed=1,
                )
            except Exception as synth_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=synthesizer_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] FAST synthesizer failed: %s, returning proposer output with critic notes",
                    synth_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="synthesizer_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=proposer_result.output,
                    synthesis_reasoning="Synthesizer unavailable, proposer analysis returned with critic notes.",
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="synthesizer_unavailable",
                    final_provider=proposer_result.provider,
                    final_model=proposer_result.model,
                    pipeline_type=pipeline_type,
                    parallel_layers=0,
                    trace_records=trace_records,
                )
    except (TimeoutError, asyncio.TimeoutError):
        if not rounds:
            raise
        total_latency = (time.monotonic() - debate_start) * 1000
        total_usage = _aggregate_usage(rounds)
        proposer_result = rounds[0]
        logger.error(
            "[DEBATE] FAST pipeline timeout after %.0fms with %d steps completed",
            total_latency,
            len(rounds),
        )
        await _emit_pipeline_finished_event(
            on_event,
            pipeline_type=pipeline_type,
            profile=profile,
            confidence=None,
            total_latency_ms=total_latency,
            total_cost_usd=cumulative_cost,
            fallback_reason="timeout",
        )
        return _build_debate_result(
            rounds=rounds,
            final_synthesis=proposer_result.output,
            synthesis_reasoning=f"FAST debate timed out after {len(rounds)} of 3 steps.",
            debate_confidence_score=0.0,
            total_token_usage=total_usage,
            total_latency_ms=total_latency,
            total_estimated_cost_usd=cumulative_cost,
            profile=profile,
            fallback_reason="timeout",
            final_provider=proposer_result.provider,
            final_model=proposer_result.model,
            pipeline_type=pipeline_type,
            parallel_layers=0,
            trace_records=trace_records,
        )

    synthesis_output = (
        dict(synthesizer_result.output) if isinstance(synthesizer_result.output, dict) else {}
    )
    synthesis_reasoning = synthesis_output.pop("synthesis_reasoning", "")
    confidence = synthesis_output.pop("debate_confidence_score", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    total_latency = (time.monotonic() - debate_start) * 1000
    total_usage = _aggregate_usage(rounds)

    await _emit_pipeline_finished_event(
        on_event,
        pipeline_type=pipeline_type,
        profile=profile,
        confidence=round(confidence, 2),
        total_latency_ms=total_latency,
        total_cost_usd=cumulative_cost,
    )

    logger.info(
        "[DEBATE] FAST pipeline complete: steps=%d confidence=%.2f latency=%.0fms cost_usd=%.4f",
        len(rounds),
        confidence,
        total_latency,
        cumulative_cost,
    )

    return _build_debate_result(
        rounds=rounds,
        final_synthesis=synthesis_output,
        synthesis_reasoning=synthesis_reasoning,
        debate_confidence_score=confidence,
        total_token_usage=total_usage,
        total_latency_ms=total_latency,
        total_estimated_cost_usd=cumulative_cost,
        profile=profile,
        final_provider=synthesizer_result.provider,
        final_model=synthesizer_result.model,
        pipeline_type=pipeline_type,
        parallel_layers=0,
        trace_records=trace_records,
    )


async def _run_legacy_smart_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    config: PipelineConfig,
    on_event: Any | None = None,
) -> DebateResult:
    return await _run_legacy_pipeline(
        ai_factory=ai_factory,
        audit_data=audit_data,
        prompt_context=prompt_context,
        requested_tier="smart",
        tier_class="deep",
        config=config,
        on_event=on_event,
    )


async def _run_legacy_deep_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    config: PipelineConfig,
    on_event: Any | None = None,
) -> DebateResult:
    return await _run_legacy_pipeline(
        ai_factory=ai_factory,
        audit_data=audit_data,
        prompt_context=prompt_context,
        requested_tier="deep_judgment",
        tier_class="deep",
        config=config,
        on_event=on_event,
    )


async def _run_smart_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    config: PipelineConfig,
    on_event: Any | None = None,
    preferred_provider: str | None = None,
) -> DebateResult:
    debate_start = time.monotonic()
    rounds: list[DebateAgentResult] = []
    trace_records: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    profile = config.profile_label
    pipeline_type = config.profile_label
    debate_cost_cap = max(0.0, float(config.cost_cap_usd))

    async def _record_step(
        *,
        role: str,
        system_prompt: str,
        user_prompt: list,
        schema: dict[str, Any] | None,
        required_keys: tuple[str, ...],
        exclude_provider: str | None = None,
        layer_index: int,
        route_override: AuditRouteResolution | None = None,
        record_result: bool = True,
    ) -> DebateAgentResult:
        nonlocal cumulative_cost
        agent_result = await _run_agent_step_with_cascade(
            ai_factory=ai_factory,
            rounds=rounds,
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            required_keys=required_keys,
            requested_tier="smart",
            step_timeout_s=config.step_timeout_s,
            on_event=on_event,
            exclude_provider=exclude_provider,
            layer_index=layer_index,
            route_override=route_override,
            record_result=record_result,
            trace_records=trace_records,
            pipeline_type=pipeline_type,
            preferred_provider=preferred_provider,
        )
        cumulative_cost += agent_result.step_cost_usd + agent_result.cascade_waste_cost_usd
        if cumulative_cost > debate_cost_cap:
            raise RuntimeError(
                f"SMART debate cost cap exceeded: EUR {cumulative_cost:.4f} > EUR {debate_cost_cap:.2f}"
            )
        return agent_result

    def _safe_smart_fallback(
        *,
        seo_output: dict[str, Any],
        aeo_geo_output: dict[str, Any],
        summary: str,
        recommendations: list[str] | None = None,
    ) -> dict[str, Any]:
        entity_analysis = (
            dict(aeo_geo_output.get("entity_analysis"))
            if isinstance(aeo_geo_output.get("entity_analysis"), dict)
            else {
                "entity_clarity_score": 0.0,
                "brand_trust_score": 0.0,
                "knowledge_graph_presence": False,
                "dominant_entities": [],
            }
        )
        dominant_entities = entity_analysis.get("dominant_entities")
        if not isinstance(dominant_entities, list):
            dominant_entities = []
        aeo_signals = (
            dict(aeo_geo_output.get("aeo_signals"))
            if isinstance(aeo_geo_output.get("aeo_signals"), dict)
            else {
                "answerability_score": 0.0,
                "content_freshness_score": 0.0,
                "schema_completeness": 0.0,
                "voice_readiness_score": 0.0,
                "key_recommendations": [],
            }
        )
        geo_signals = (
            dict(aeo_geo_output.get("geo_signals"))
            if isinstance(aeo_geo_output.get("geo_signals"), dict)
            else {
                "citation_consistency_score": 0.0,
                "local_authority_score": 0.0,
                "relevance_score": 0.0,
                "competitor_overlap_score": 0.0,
            }
        )
        technical_signals = (
            dict(seo_output.get("technical_signals"))
            if isinstance(seo_output.get("technical_signals"), dict)
            else {
                "mobile_friendliness": 0.0,
                "security_score": 0.0,
                "accessibility_score": 0.0,
            }
        )
        generated_recommendations: list[str] = []
        for rec in recommendations or []:
            cleaned = str(rec or "").strip()
            if cleaned and cleaned not in generated_recommendations:
                generated_recommendations.append(cleaned)
        if not generated_recommendations:
            for payload in (seo_output, aeo_geo_output):
                for claim in payload.get("claim_ledger") or []:
                    if not isinstance(claim, dict):
                        continue
                    action = str(claim.get("recommended_action") or "").strip()
                    if action and action not in generated_recommendations:
                        generated_recommendations.append(action)
                    if len(generated_recommendations) >= 8:
                        break
                if len(generated_recommendations) >= 8:
                    break
        return {
            "schema_version": AI_AUDIT_SCHEMA_VERSION,
            "summary": summary,
            "recommendations": generated_recommendations,
            "seo_findings": list(seo_output.get("seo_findings") or []),
            "geo_findings": list(aeo_geo_output.get("geo_findings") or []),
            "aeo_findings": list(aeo_geo_output.get("aeo_findings") or []),
            "entity_analysis": entity_analysis,
            "aeo_signals": aeo_signals,
            "geo_signals": geo_signals,
            "technical_signals": technical_signals,
            "entities_detected": dominant_entities,
            "seo_score": None,
            "geo_score": None,
            "aeo_score": None,
            "executive_dossier": "",
            "findings": [],
            "citation_probability_score": float(
                aeo_geo_output.get("citation_probability_score") or 0.0
            ),
            "strategic_roadmap": "",
            "neural_intelligence_grid": [],
            "market_dominance_projection": "",
        }

    await _emit_pipeline_started_event(
        on_event,
        pipeline_type=pipeline_type,
        estimated_duration_s=config.total_timeout_s,
    )

    try:
        async with asyncio.timeout(config.total_timeout_s):
            generator_layer_started_at = time.monotonic()
            await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=1)
            generator_routes = resolve_debate_routes_for_layer(
                ["seo_generator", "aeo_geo_generator"],
                requested_tier="smart",
                preferred_provider=preferred_provider,
            )
            seo_system, seo_user = _build_seo_generator_prompt(audit_data, prompt_context)
            aeo_geo_system, aeo_geo_user = _build_aeo_geo_generator_prompt(
                audit_data, prompt_context
            )

            # Layer 1, parallel generators with return_exceptions so a
            # single provider failure doesn't crash both generators.
            generator_results = await asyncio.gather(
                _record_step(
                    role="seo_generator",
                    system_prompt=seo_system,
                    user_prompt=seo_user,
                    schema=SEO_EXPERT_SCHEMA,
                    required_keys=tuple(SEO_EXPERT_SCHEMA["required"]),
                    layer_index=1,
                    route_override=generator_routes.get("seo_generator"),
                    record_result=False,
                ),
                _record_step(
                    role="aeo_geo_generator",
                    system_prompt=aeo_geo_system,
                    user_prompt=aeo_geo_user,
                    schema=AEO_GEO_COMBINED_EXPERT_SCHEMA,
                    required_keys=_AEO_GEO_REQUIRED_KEYS,
                    layer_index=1,
                    route_override=generator_routes.get("aeo_geo_generator"),
                    record_result=False,
                ),
                return_exceptions=True,
            )

            # Unpack results, if one generator failed, synthesize a
            # partial result from whichever succeeded.
            seo_raw, aeo_geo_raw = generator_results
            seo_failed = isinstance(seo_raw, BaseException)
            aeo_geo_failed = isinstance(aeo_geo_raw, BaseException)

            if seo_failed and aeo_geo_failed:
                # Both generators failed, nothing to work with
                logger.error(
                    "[PIPELINE] Both generators failed: seo=%s  aeo_geo=%s",
                    seo_raw,
                    aeo_geo_raw,
                )
                raise seo_raw  # propagate to the timeout/fallback handler

            generators_total = 2
            generators_failed = 0

            if seo_failed:
                logger.warning(
                    "[PIPELINE] SEO generator failed: %s, using empty SEO output", seo_raw
                )
                generators_failed = 1
                seo_result = DebateAgentResult(
                    role="seo_generator",
                    semantic_role="generator",
                    provider="none",
                    model="fallback",
                    output=_empty_seo_generator_output(),
                    token_usage={},
                    latency_ms=0.0,
                    route_resolution=generator_routes.get("seo_generator")
                    or resolve_debate_route("seo_generator", requested_tier="smart"),
                    step_cost_usd=0.0,
                    layer_index=1,
                )
                aeo_geo_result = aeo_geo_raw
            elif aeo_geo_failed:
                logger.warning(
                    "[PIPELINE] AEO/GEO generator failed: %s, using empty AEO/GEO output",
                    aeo_geo_raw,
                )
                generators_failed = 1
                seo_result = seo_raw
                aeo_geo_result = DebateAgentResult(
                    role="aeo_geo_generator",
                    semantic_role="generator",
                    provider="none",
                    model="fallback",
                    output=_empty_aeo_geo_generator_output(),
                    token_usage={},
                    latency_ms=0.0,
                    route_resolution=generator_routes.get("aeo_geo_generator")
                    or resolve_debate_route("aeo_geo_generator", requested_tier="smart"),
                    step_cost_usd=0.0,
                    layer_index=1,
                )
            else:
                seo_result = seo_raw
                aeo_geo_result = aeo_geo_raw

            rounds.extend([seo_result, aeo_geo_result])
            await _emit_layer_completed_event(
                on_event,
                pipeline_type=pipeline_type,
                layer=1,
                started_at=generator_layer_started_at,
                agents_completed=generators_total - generators_failed,
                agents_failed=generators_failed,
            )

            try:
                critic_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=2)
                critic_system, critic_user = _build_centralized_critic_prompt(
                    audit_data,
                    seo_proposal=seo_result.output,
                    aeo_geo_proposal=aeo_geo_result.output,
                )
                critic_result = await _record_step(
                    role="centralized_critic",
                    system_prompt=critic_system,
                    user_prompt=critic_user,
                    schema=_HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA,
                    required_keys=_STRICT_CRITIC_REQUIRED_KEYS,
                    exclude_provider=seo_result.provider,
                    layer_index=2,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=2,
                    started_at=critic_layer_started_at,
                    agents_completed=1,
                )
            except Exception as critic_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=2,
                    started_at=critic_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] SMART centralized critic failed: %s, returning combined generators without challenge",
                    critic_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                fallback = _safe_smart_fallback(
                    seo_output=seo_result.output,
                    aeo_geo_output=aeo_geo_result.output,
                    summary="Centralized critic unavailable, combined expert outputs returned without challenge.",
                    recommendations=list(aeo_geo_result.output.get("recommendations") or []),
                )
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="critic_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=fallback,
                    synthesis_reasoning="Centralized critic unavailable, combined generators accepted without challenge.",
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="critic_unavailable",
                    final_provider=aeo_geo_result.provider,
                    final_model=aeo_geo_result.model,
                    pipeline_type=pipeline_type,
                    parallel_layers=1,
                    trace_records=trace_records,
                )

            try:
                synthesizer_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=3)
                synthesizer_system, synthesizer_user = _build_smart_synthesizer_prompt(
                    audit_data,
                    seo_proposal=seo_result.output,
                    aeo_geo_proposal=aeo_geo_result.output,
                    critique=critic_result.output,
                    prompt_context=prompt_context,
                )
                synthesizer_result = await _record_step(
                    role="smart_synthesizer",
                    system_prompt=synthesizer_system,
                    user_prompt=synthesizer_user,
                    schema=_STANDARD_DEBATE_SYNTHESIS_SCHEMA,
                    required_keys=_STANDARD_SYNTHESIS_REQUIRED_KEYS,
                    exclude_provider=critic_result.provider,
                    layer_index=3,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=synthesizer_layer_started_at,
                    agents_completed=1,
                )
            except Exception as synth_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=synthesizer_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] SMART synthesizer failed: %s, returning combined generators with critic notes",
                    synth_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                fallback = _safe_smart_fallback(
                    seo_output=seo_result.output,
                    aeo_geo_output=aeo_geo_result.output,
                    summary="SMART synthesizer unavailable, combined expert outputs returned with centralized critic notes pending manual review.",
                    recommendations=list(aeo_geo_result.output.get("recommendations") or []),
                )
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="synthesizer_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=fallback,
                    synthesis_reasoning="SMART synthesizer unavailable, combined generators returned with critic notes.",
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="synthesizer_unavailable",
                    final_provider=aeo_geo_result.provider,
                    final_model=aeo_geo_result.model,
                    pipeline_type=pipeline_type,
                    parallel_layers=1,
                    trace_records=trace_records,
                )

            try:
                magistrate_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=4)
                magistrate_system, magistrate_user = _build_magistrate_prompt(
                    audit_data,
                    synthesis_packet=synthesizer_result.output,
                    critique=critic_result.output,
                    prompt_context=prompt_context,
                )
                magistrate_result = await _record_step(
                    role="magistrate",
                    system_prompt=magistrate_system,
                    user_prompt=magistrate_user,
                    schema=_HIGH_CONFIDENCE_JUDGE_SCHEMA,
                    required_keys=_HIGH_CONFIDENCE_JUDGE_REQUIRED_KEYS,
                    exclude_provider=synthesizer_result.provider,
                    layer_index=4,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=4,
                    started_at=magistrate_layer_started_at,
                    agents_completed=1,
                )
            except Exception as magistrate_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=4,
                    started_at=magistrate_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] SMART magistrate failed: %s, returning synthesizer packet as final",
                    magistrate_exc,
                )
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                synthesis_output = (
                    dict(synthesizer_result.output)
                    if isinstance(synthesizer_result.output, dict)
                    else {}
                )
                synthesis_reasoning = str(synthesis_output.pop("synthesis_reasoning", "") or "")
                confidence = float(synthesis_output.pop("debate_confidence_score", 0.0) or 0.0)
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=round(confidence, 2),
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="judge_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=synthesis_output,
                    synthesis_reasoning=synthesis_reasoning
                    or "SMART magistrate unavailable, synthesizer packet returned as final.",
                    debate_confidence_score=confidence,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="judge_unavailable",
                    final_provider=synthesizer_result.provider,
                    final_model=synthesizer_result.model,
                    pipeline_type=pipeline_type,
                    parallel_layers=1,
                    trace_records=trace_records,
                )
    except (TimeoutError, asyncio.TimeoutError):
        if not rounds:
            raise
        total_latency = (time.monotonic() - debate_start) * 1000
        total_usage = _aggregate_usage(rounds)
        seo_output = rounds[0].output if rounds else {}
        aeo_geo_output = rounds[1].output if len(rounds) > 1 else {}
        fallback = _safe_smart_fallback(
            seo_output=seo_output if isinstance(seo_output, dict) else {},
            aeo_geo_output=aeo_geo_output if isinstance(aeo_geo_output, dict) else {},
            summary=f"SMART debate timed out after {len(rounds)} of 5 steps.",
        )
        await _emit_pipeline_finished_event(
            on_event,
            pipeline_type=pipeline_type,
            profile=profile,
            confidence=None,
            total_latency_ms=total_latency,
            total_cost_usd=cumulative_cost,
            fallback_reason="timeout",
        )
        return _build_debate_result(
            rounds=rounds,
            final_synthesis=fallback,
            synthesis_reasoning=f"SMART debate timed out after {len(rounds)} of 5 steps.",
            debate_confidence_score=0.0,
            total_token_usage=total_usage,
            total_latency_ms=total_latency,
            total_estimated_cost_usd=cumulative_cost,
            profile=profile,
            fallback_reason="timeout",
            final_provider=rounds[-1].provider if rounds else None,
            final_model=rounds[-1].model if rounds else None,
            pipeline_type=pipeline_type,
            parallel_layers=1,
            trace_records=trace_records,
        )

    magistrate_output = (
        dict(magistrate_result.output) if isinstance(magistrate_result.output, dict) else {}
    )
    synthesis_reasoning = str(magistrate_output.pop("synthesis_reasoning", "") or "")
    confidence = magistrate_output.pop("debate_confidence_score", 0.0)
    judge_summary = magistrate_output.pop("judge_summary", None)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    total_latency = (time.monotonic() - debate_start) * 1000
    total_usage = _aggregate_usage(rounds)
    judge_authority = _judge_authority_label(magistrate_result)

    await _emit_pipeline_finished_event(
        on_event,
        pipeline_type=pipeline_type,
        profile=profile,
        confidence=round(confidence, 2),
        total_latency_ms=total_latency,
        total_cost_usd=cumulative_cost,
        judge_authority=judge_authority,
    )

    logger.info(
        "[DEBATE] SMART V3 complete: steps=%d confidence=%.2f latency=%.0fms cost_usd=%.4f",
        len(rounds),
        confidence,
        total_latency,
        cumulative_cost,
    )

    return _build_debate_result(
        rounds=rounds,
        final_synthesis=magistrate_output,
        synthesis_reasoning=synthesis_reasoning,
        debate_confidence_score=confidence,
        total_token_usage=total_usage,
        total_latency_ms=total_latency,
        total_estimated_cost_usd=cumulative_cost,
        profile=profile,
        judge_summary=dict(judge_summary) if isinstance(judge_summary, dict) else None,
        judge_authority=judge_authority,
        final_provider=magistrate_result.provider,
        final_model=magistrate_result.model,
        pipeline_type=pipeline_type,
        parallel_layers=1,
        trace_records=trace_records,
    )


async def _run_delta_flow_pipeline(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    config: PipelineConfig,
    on_event: Any | None = None,
    preferred_provider: str | None = None,
) -> DebateResult:
    debate_start = time.monotonic()
    rounds: list[DebateAgentResult] = []
    trace_records: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    profile = config.profile_label
    pipeline_type = config.profile_label
    debate_cost_cap = max(0.0, float(config.cost_cap_usd))
    degradation_reason: str | None = None

    # NOTE: The delta-flow (deep_judgment) pipeline does NOT use
    # _run_agent_step_with_cascade.  Deep judgment runs use pre-resolved
    # per-layer routes with provider diversity as a hard constraint;
    # cascade retries would weaken that diversity guarantee and risk
    # exceeding the higher per-step cost budget.  Failures degrade
    # gracefully via _mark_degraded() instead.
    async def _record_step(
        *,
        role: str,
        system_prompt: str,
        user_prompt: list,
        schema: dict[str, Any] | None,
        required_keys: tuple[str, ...],
        exclude_provider: str | None = None,
        layer_index: int,
        route_override: AuditRouteResolution | None = None,
        record_result: bool = True,
    ) -> DebateAgentResult:
        nonlocal cumulative_cost
        agent_result = await _run_agent_step(
            ai_factory=ai_factory,
            rounds=rounds,
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            required_keys=required_keys,
            requested_tier="deep_judgment",
            step_timeout_s=config.step_timeout_s,
            on_event=on_event,
            exclude_provider=exclude_provider,
            layer_index=layer_index,
            route_override=route_override,
            record_result=record_result,
            trace_records=trace_records,
            pipeline_type=pipeline_type,
            preferred_provider=preferred_provider,
        )
        cumulative_cost += agent_result.step_cost_usd
        if cumulative_cost > debate_cost_cap:
            raise RuntimeError(
                f"DELTA debate cost cap exceeded: EUR {cumulative_cost:.4f} > EUR {debate_cost_cap:.2f}"
            )
        return agent_result

    def _mark_degraded(reason: str) -> None:
        nonlocal degradation_reason
        severity = {
            "generator_unavailable": 1,
            "critic_unavailable": 2,
            "consolidator_unavailable": 3,
            "judge_unavailable": 4,
            "timeout": 5,
        }
        current = severity.get(degradation_reason or "", 0)
        incoming = severity.get(reason, 0)
        if degradation_reason is None or incoming >= current:
            degradation_reason = reason

    def _default_entity_analysis(payload: dict[str, Any]) -> dict[str, Any]:
        entity_analysis = (
            dict(payload.get("entity_analysis"))
            if isinstance(payload.get("entity_analysis"), dict)
            else {
                "entity_clarity_score": 0.0,
                "brand_trust_score": 0.0,
                "knowledge_graph_presence": False,
                "dominant_entities": [],
            }
        )
        dominant_entities = entity_analysis.get("dominant_entities")
        if not isinstance(dominant_entities, list):
            entity_analysis["dominant_entities"] = []
        return entity_analysis

    def _default_aeo_signals(payload: dict[str, Any]) -> dict[str, Any]:
        return (
            dict(payload.get("aeo_signals"))
            if isinstance(payload.get("aeo_signals"), dict)
            else {
                "answerability_score": 0.0,
                "content_freshness_score": 0.0,
                "schema_completeness": 0.0,
                "voice_readiness_score": 0.0,
                "key_recommendations": [],
            }
        )

    def _default_geo_signals(payload: dict[str, Any]) -> dict[str, Any]:
        return (
            dict(payload.get("geo_signals"))
            if isinstance(payload.get("geo_signals"), dict)
            else {
                "citation_consistency_score": 0.0,
                "local_authority_score": 0.0,
                "relevance_score": 0.0,
                "competitor_overlap_score": 0.0,
            }
        )

    def _default_technical_signals(payload: dict[str, Any]) -> dict[str, Any]:
        return (
            dict(payload.get("technical_signals"))
            if isinstance(payload.get("technical_signals"), dict)
            else {
                "mobile_friendliness": 0.0,
                "security_score": 0.0,
                "accessibility_score": 0.0,
            }
        )

    def _collect_recommendations(
        *payloads: dict[str, Any],
        seeds: list[str] | None = None,
        limit: int = 8,
    ) -> list[str]:
        recommendations: list[str] = []
        for seed in seeds or []:
            cleaned = str(seed or "").strip()
            if cleaned and cleaned not in recommendations:
                recommendations.append(cleaned)
            if len(recommendations) >= limit:
                return recommendations

        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for recommendation in payload.get("recommendations") or []:
                cleaned = str(recommendation or "").strip()
                if cleaned and cleaned not in recommendations:
                    recommendations.append(cleaned)
                if len(recommendations) >= limit:
                    return recommendations
            for claim in payload.get("claim_ledger") or []:
                if not isinstance(claim, dict):
                    continue
                action = str(claim.get("recommended_action") or "").strip()
                if action and action not in recommendations:
                    recommendations.append(action)
                if len(recommendations) >= limit:
                    return recommendations
        return recommendations

    def _safe_delta_fallback(
        *,
        seo_output: dict[str, Any],
        geo_output: dict[str, Any],
        aeo_output: dict[str, Any],
        summary: str,
        recommendations: list[str] | None = None,
    ) -> dict[str, Any]:
        entity_analysis = _default_entity_analysis(geo_output)
        dominant_entities = entity_analysis.get("dominant_entities")
        return {
            "schema_version": AI_AUDIT_SCHEMA_VERSION,
            "summary": summary,
            "recommendations": _collect_recommendations(
                seo_output,
                geo_output,
                aeo_output,
                seeds=recommendations,
            ),
            "seo_findings": list(seo_output.get("seo_findings") or []),
            "geo_findings": list(geo_output.get("geo_findings") or []),
            "aeo_findings": list(aeo_output.get("aeo_findings") or []),
            "entity_analysis": entity_analysis,
            "aeo_signals": _default_aeo_signals(aeo_output),
            "geo_signals": _default_geo_signals(geo_output),
            "technical_signals": _default_technical_signals(seo_output),
            "entities_detected": dominant_entities if isinstance(dominant_entities, list) else [],
            "seo_score": None,
            "geo_score": None,
            "aeo_score": None,
            "executive_dossier": "",
            "findings": [],
            "citation_probability_score": float(
                aeo_output.get("citation_probability_score") or 0.0
            ),
            "strategic_roadmap": "",
            "neural_intelligence_grid": [],
            "market_dominance_projection": "",
        }

    def _derive_judge_summary_from_consolidated(packet: dict[str, Any]) -> dict[str, int] | None:
        dispositions = packet.get("consolidated_claim_disposition")
        if not isinstance(dispositions, list):
            return None
        summary = {
            "accepted_claims": 0,
            "downgraded_claims": 0,
            "rejected_claims": 0,
            "unresolved_disputes": 0,
        }
        for item in dispositions:
            if not isinstance(item, dict):
                continue
            disposition = str(item.get("disposition") or "").strip().lower()
            if disposition == "accepted":
                summary["accepted_claims"] += 1
            elif disposition in {"downgraded", "deduplicated"}:
                summary["downgraded_claims"] += 1
            elif disposition == "rejected":
                summary["rejected_claims"] += 1
            elif disposition == "needs_manual_review":
                summary["unresolved_disputes"] += 1
        return summary

    await _emit_pipeline_started_event(
        on_event,
        pipeline_type=pipeline_type,
        estimated_duration_s=config.total_timeout_s,
    )

    try:
        async with asyncio.timeout(config.total_timeout_s):
            generator_layer_started_at = time.monotonic()
            await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=1)
            generator_roles = ["seo_generator", "geo_generator", "aeo_generator"]
            generator_routes = resolve_debate_routes_for_layer(
                generator_roles,
                requested_tier="deep_judgment",
                preferred_provider=preferred_provider,
            )
            generator_specs = [
                (
                    "seo",
                    "seo_generator",
                    _build_deep_seo_generator_prompt(audit_data, prompt_context),
                    SEO_EXPERT_SCHEMA,
                    tuple(SEO_EXPERT_SCHEMA["required"]),
                ),
                (
                    "geo",
                    "geo_generator",
                    _build_geo_generator_prompt(audit_data, prompt_context),
                    GEO_EXPERT_SCHEMA,
                    tuple(GEO_EXPERT_SCHEMA["required"]),
                ),
                (
                    "aeo",
                    "aeo_generator",
                    _build_aeo_generator_prompt(audit_data, prompt_context),
                    AEO_EXPERT_SCHEMA,
                    tuple(AEO_EXPERT_SCHEMA["required"]),
                ),
            ]
            generator_outcomes = await asyncio.gather(
                *[
                    _record_step(
                        role=role,
                        system_prompt=prompt[0],
                        user_prompt=prompt[1],
                        schema=schema,
                        required_keys=required_keys,
                        layer_index=1,
                        route_override=generator_routes.get(role),
                        record_result=False,
                    )
                    for _, role, prompt, schema, required_keys in generator_specs
                ],
                return_exceptions=True,
            )

            generator_results: dict[str, DebateAgentResult] = {}
            for (domain_key, role, _prompt, _schema, _required_keys), outcome in zip(
                generator_specs,
                generator_outcomes,
                strict=False,
            ):
                if isinstance(outcome, DebateAgentResult):
                    generator_results[domain_key] = outcome
                else:
                    logger.warning("[DEBATE] DELTA %s failed: %s", role, outcome)
                    _mark_degraded("generator_unavailable")
            rounds.extend(
                [
                    generator_results[domain_key]
                    for domain_key in ("seo", "geo", "aeo")
                    if domain_key in generator_results
                ]
            )
            await _emit_layer_completed_event(
                on_event,
                pipeline_type=pipeline_type,
                layer=1,
                started_at=generator_layer_started_at,
                agents_completed=len(generator_results),
                agents_failed=max(0, len(generator_specs) - len(generator_results)),
            )

            if not generator_results:
                raise RuntimeError("Delta Flow generators unavailable for all domains.")

            critic_specs: list[
                tuple[str, str, tuple[str, list], dict[str, Any], tuple[str, ...]]
            ] = []
            if "seo" in generator_results:
                critic_specs.append(
                    (
                        "seo",
                        "seo_critic",
                        _build_seo_critic_prompt(audit_data, generator_results["seo"].output),
                        _HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA,
                        _STRICT_CRITIC_REQUIRED_KEYS,
                    )
                )
            if "geo" in generator_results:
                critic_specs.append(
                    (
                        "geo",
                        "geo_critic",
                        _build_geo_critic_prompt(audit_data, generator_results["geo"].output),
                        _HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA,
                        _STRICT_CRITIC_REQUIRED_KEYS,
                    )
                )
            if "aeo" in generator_results:
                critic_specs.append(
                    (
                        "aeo",
                        "aeo_critic",
                        _build_aeo_critic_prompt(audit_data, generator_results["aeo"].output),
                        _HIGH_CONFIDENCE_CRITIC_OUTPUT_SCHEMA,
                        _STRICT_CRITIC_REQUIRED_KEYS,
                    )
                )

            critic_routes = resolve_debate_routes_for_layer(
                [role for _, role, _prompt, _schema, _required_keys in critic_specs],
                requested_tier="deep_judgment",
                preferred_provider=preferred_provider,
            )
            critic_layer_started_at = time.monotonic()
            await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=2)
            critic_outcomes = await asyncio.gather(
                *[
                    _record_step(
                        role=role,
                        system_prompt=prompt[0],
                        user_prompt=prompt[1],
                        schema=schema,
                        required_keys=required_keys,
                        layer_index=2,
                        route_override=critic_routes.get(role),
                        record_result=False,
                    )
                    for _domain_key, role, prompt, schema, required_keys in critic_specs
                ],
                return_exceptions=True,
            )

            critic_results: dict[str, DebateAgentResult] = {}
            for (domain_key, role, _prompt, _schema, _required_keys), outcome in zip(
                critic_specs,
                critic_outcomes,
                strict=False,
            ):
                if isinstance(outcome, DebateAgentResult):
                    critic_results[domain_key] = outcome
                else:
                    logger.warning("[DEBATE] DELTA %s failed: %s", role, outcome)
                    _mark_degraded("critic_unavailable")
            rounds.extend(
                [
                    critic_results[domain_key]
                    for domain_key in ("seo", "geo", "aeo")
                    if domain_key in critic_results
                ]
            )
            await _emit_layer_completed_event(
                on_event,
                pipeline_type=pipeline_type,
                layer=2,
                started_at=critic_layer_started_at,
                agents_completed=len(critic_results),
                agents_failed=max(0, len(critic_specs) - len(critic_results)),
            )

            seo_output = generator_results.get("seo").output if "seo" in generator_results else {}
            geo_output = generator_results.get("geo").output if "geo" in generator_results else {}
            aeo_output = generator_results.get("aeo").output if "aeo" in generator_results else {}
            generator_packets = {
                domain_key: claim_ledger_service.build_analysis_transfer_packet(
                    result.output,
                    expert_domain=domain_key,
                )
                for domain_key, result in generator_results.items()
            }

            if not critic_results:
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                fallback = _safe_delta_fallback(
                    seo_output=seo_output if isinstance(seo_output, dict) else {},
                    geo_output=geo_output if isinstance(geo_output, dict) else {},
                    aeo_output=aeo_output if isinstance(aeo_output, dict) else {},
                    summary="Delta Flow critics unavailable, generator outputs returned without red-team review.",
                )
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="critic_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=fallback,
                    synthesis_reasoning="Delta Flow critics unavailable, generator outputs returned without red-team review.",
                    debate_confidence_score=0.0,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    fallback_reason="critic_unavailable",
                    final_provider=rounds[-1].provider if rounds else None,
                    final_model=rounds[-1].model if rounds else None,
                    pipeline_type=pipeline_type,
                    parallel_layers=2,
                    trace_records=trace_records,
                    consolidation_status=CONSOLIDATION_BYPASSED,
                )

            critique_packets = {
                domain_key: claim_ledger_service.build_challenge_transfer_packet(result.output)
                for domain_key, result in critic_results.items()
            }

            consolidator_result: DebateAgentResult | None = None
            consolidation_status = CONSOLIDATION_FULL
            try:
                consolidator_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=3)
                consolidator_system, consolidator_user = _build_consolidator_prompt(
                    audit_data,
                    generator_packets=generator_packets,
                    critique_packets=critique_packets,
                    prompt_context=prompt_context,
                )
                consolidator_result = await _record_step(
                    role="consolidator",
                    system_prompt=consolidator_system,
                    user_prompt=consolidator_user,
                    schema=_CONSOLIDATED_OUTPUT_SCHEMA,
                    required_keys=_CONSOLIDATED_REQUIRED_KEYS,
                    exclude_provider=next(iter(critic_results.values())).provider,
                    layer_index=3,
                )
                # Check for degraded output (missing critical keys)
                if isinstance(consolidator_result.output, dict):
                    missing = [
                        k
                        for k in (
                            "domain_summaries",
                            "consolidated_claim_disposition",
                            "synthesis_reasoning",
                        )
                        if k not in consolidator_result.output
                    ]
                    if missing:
                        consolidation_status = CONSOLIDATION_DEGRADED
                        logger.warning(
                            "[DEBATE] DELTA consolidator output degraded, missing keys: %s",
                            missing,
                        )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=consolidator_layer_started_at,
                    agents_completed=1,
                )
            except Exception as consolidator_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=3,
                    started_at=consolidator_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] DELTA consolidator failed: %s, sending direct critique packets to the magistrate",
                    consolidator_exc,
                )
                _mark_degraded("consolidator_unavailable")
                consolidation_status = CONSOLIDATION_BYPASSED

            if consolidation_status != CONSOLIDATION_FULL:
                logger.warning(
                    "[DEBATE] Consolidation status: %s (pipeline will proceed with degraded input)",
                    consolidation_status,
                )

            try:
                magistrate_layer_started_at = time.monotonic()
                await _emit_layer_started_event(on_event, pipeline_type=pipeline_type, layer=4)
                magistrate_system, magistrate_user = _build_global_magistrate_prompt(
                    audit_data,
                    generator_packets=generator_packets,
                    consolidated_packet=consolidator_result.output
                    if consolidator_result is not None
                    else None,
                    critique_packets=None if consolidator_result is not None else critique_packets,
                    prompt_context=prompt_context,
                    consolidation_status=consolidation_status,
                )
                magistrate_result = await _record_step(
                    role="global_magistrate",
                    system_prompt=magistrate_system,
                    user_prompt=magistrate_user,
                    schema=_HIGH_CONFIDENCE_JUDGE_SCHEMA,
                    required_keys=_HIGH_CONFIDENCE_JUDGE_REQUIRED_KEYS,
                    exclude_provider=consolidator_result.provider
                    if consolidator_result is not None
                    else None,
                    layer_index=4,
                )
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=4,
                    started_at=magistrate_layer_started_at,
                    agents_completed=1,
                )
            except Exception as magistrate_exc:
                await _emit_layer_completed_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    layer=4,
                    started_at=magistrate_layer_started_at,
                    agents_completed=0,
                    agents_failed=1,
                )
                logger.warning(
                    "[DEBATE] DELTA global magistrate failed: %s, returning degraded consolidator-backed output",
                    magistrate_exc,
                )
                _mark_degraded("judge_unavailable")
                total_latency = (time.monotonic() - debate_start) * 1000
                total_usage = _aggregate_usage(rounds)
                consolidated_output = (
                    dict(consolidator_result.output)
                    if consolidator_result is not None
                    and isinstance(consolidator_result.output, dict)
                    else {}
                )
                consolidated_summary = str(
                    consolidated_output.get("synthesis_reasoning")
                    or "Global Magistrate unavailable, consolidator-backed output returned as final."
                )
                domain_summaries = (
                    consolidated_output.get("domain_summaries")
                    if isinstance(consolidated_output.get("domain_summaries"), dict)
                    else {}
                )
                fallback_recommendations: list[str] = []
                for domain_key in ("seo", "geo", "aeo"):
                    summary_payload = domain_summaries.get(domain_key)
                    if not isinstance(summary_payload, dict):
                        continue
                    for recommendation in summary_payload.get("recommended_actions") or []:
                        cleaned = str(recommendation or "").strip()
                        if cleaned and cleaned not in fallback_recommendations:
                            fallback_recommendations.append(cleaned)
                fallback = _safe_delta_fallback(
                    seo_output=seo_output if isinstance(seo_output, dict) else {},
                    geo_output=geo_output if isinstance(geo_output, dict) else {},
                    aeo_output=aeo_output if isinstance(aeo_output, dict) else {},
                    summary=consolidated_summary,
                    recommendations=fallback_recommendations,
                )
                confidence = float(consolidated_output.get("overall_confidence_score") or 0.0)
                judge_summary = _derive_judge_summary_from_consolidated(consolidated_output)
                await _emit_pipeline_finished_event(
                    on_event,
                    pipeline_type=pipeline_type,
                    profile=profile,
                    confidence=round(confidence, 2) if confidence else None,
                    total_latency_ms=total_latency,
                    total_cost_usd=cumulative_cost,
                    fallback_reason="judge_unavailable",
                )
                return _build_debate_result(
                    rounds=rounds,
                    final_synthesis=fallback,
                    synthesis_reasoning=consolidated_summary,
                    debate_confidence_score=confidence,
                    total_token_usage=total_usage,
                    total_latency_ms=total_latency,
                    total_estimated_cost_usd=cumulative_cost,
                    profile=profile,
                    judge_summary=judge_summary,
                    fallback_reason="judge_unavailable",
                    final_provider=(
                        consolidator_result.provider
                        if consolidator_result is not None
                        else rounds[-1].provider
                    ),
                    final_model=(
                        consolidator_result.model
                        if consolidator_result is not None
                        else rounds[-1].model
                    ),
                    pipeline_type=pipeline_type,
                    parallel_layers=2,
                    trace_records=trace_records,
                    consolidation_status=consolidation_status,
                )
    except (TimeoutError, asyncio.TimeoutError):
        if not rounds:
            raise
        total_latency = (time.monotonic() - debate_start) * 1000
        total_usage = _aggregate_usage(rounds)
        round_by_role = {round_result.role: round_result for round_result in rounds}
        fallback = _safe_delta_fallback(
            seo_output=(
                round_by_role.get("seo_generator").output
                if "seo_generator" in round_by_role
                and isinstance(round_by_role["seo_generator"].output, dict)
                else {}
            ),
            geo_output=(
                round_by_role.get("geo_generator").output
                if "geo_generator" in round_by_role
                and isinstance(round_by_role["geo_generator"].output, dict)
                else {}
            ),
            aeo_output=(
                round_by_role.get("aeo_generator").output
                if "aeo_generator" in round_by_role
                and isinstance(round_by_role["aeo_generator"].output, dict)
                else {}
            ),
            summary=f"Delta Flow timed out after {len(rounds)} of 8 steps.",
        )
        await _emit_pipeline_finished_event(
            on_event,
            pipeline_type=pipeline_type,
            profile=profile,
            confidence=None,
            total_latency_ms=total_latency,
            total_cost_usd=cumulative_cost,
            fallback_reason="timeout",
        )
        return _build_debate_result(
            rounds=rounds,
            final_synthesis=fallback,
            synthesis_reasoning=f"Delta Flow timed out after {len(rounds)} of 8 steps.",
            debate_confidence_score=0.0,
            total_token_usage=total_usage,
            total_latency_ms=total_latency,
            total_estimated_cost_usd=cumulative_cost,
            profile=profile,
            fallback_reason="timeout",
            final_provider=rounds[-1].provider if rounds else None,
            final_model=rounds[-1].model if rounds else None,
            pipeline_type=pipeline_type,
            parallel_layers=2,
            trace_records=trace_records,
            consolidation_status=CONSOLIDATION_BYPASSED,
        )

    magistrate_output = (
        dict(magistrate_result.output) if isinstance(magistrate_result.output, dict) else {}
    )
    synthesis_reasoning = str(magistrate_output.pop("synthesis_reasoning", "") or "")
    confidence = magistrate_output.pop("debate_confidence_score", 0.0)
    judge_summary = magistrate_output.pop("judge_summary", None)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    total_latency = (time.monotonic() - debate_start) * 1000
    total_usage = _aggregate_usage(rounds)
    judge_authority = _judge_authority_label(magistrate_result)

    await _emit_pipeline_finished_event(
        on_event,
        pipeline_type=pipeline_type,
        profile=profile,
        confidence=round(confidence, 2),
        total_latency_ms=total_latency,
        total_cost_usd=cumulative_cost,
        judge_authority=judge_authority,
        fallback_reason=degradation_reason,
    )

    logger.info(
        "[DEBATE] DELTA Flow complete: steps=%d confidence=%.2f latency=%.0fms cost_usd=%.4f",
        len(rounds),
        confidence,
        total_latency,
        cumulative_cost,
    )

    return _build_debate_result(
        rounds=rounds,
        final_synthesis=magistrate_output,
        synthesis_reasoning=synthesis_reasoning,
        debate_confidence_score=confidence,
        total_token_usage=total_usage,
        total_latency_ms=total_latency,
        total_estimated_cost_usd=cumulative_cost,
        profile=profile,
        judge_summary=dict(judge_summary) if isinstance(judge_summary, dict) else None,
        judge_authority=judge_authority,
        fallback_reason=degradation_reason,
        final_provider=magistrate_result.provider,
        final_model=magistrate_result.model,
        pipeline_type=pipeline_type,
        parallel_layers=2,
        trace_records=trace_records,
        consolidation_status=consolidation_status,
    )


# ---------------------------------------------------------------------------
# Pipeline version selection
# ---------------------------------------------------------------------------


def _select_pipeline_runner(
    *,
    version: str,
    normalized_tier: str,
):
    """Return the pipeline coroutine for the given version and tier.

    V3 runners: ``_run_fast_pipeline``, ``_run_smart_pipeline``, ``_run_delta_flow_pipeline``.
    V2 runners: ``_run_legacy_pipeline`` (wraps the 3-step proposer/challenger/synthesizer).

    Returns an async callable with signature
    ``(ai_factory, audit_data, prompt_context, config, on_event) -> DebateResult``.
    """
    if version == "v3":
        v3_map = {
            "fast": _run_fast_pipeline,
            "smart": _run_smart_pipeline,
            "deep_judgment": _run_delta_flow_pipeline,
        }
        runner = v3_map.get(normalized_tier)
        if runner is None:
            raise ValueError(f"No V3 pipeline for tier: {normalized_tier}")
        return runner

    # V2 legacy, adapt signature to match V3 runners
    async def _v2_wrapper(
        *,
        ai_factory,
        audit_data,
        prompt_context,
        config,
        on_event=None,
        preferred_provider=None,
    ):
        if preferred_provider:
            logger.warning(
                "preferred_provider=%s ignored, V2 legacy pipeline does not support provider routing",
                preferred_provider,
            )
        return await _run_legacy_pipeline(
            ai_factory=ai_factory,
            audit_data=audit_data,
            prompt_context=prompt_context,
            requested_tier=normalized_tier,
            tier_class="deep",
            config=config,
            on_event=on_event,
        )

    return _v2_wrapper


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def run_debate(
    *,
    ai_factory: "AIFactory",
    audit_data: dict,
    prompt_context: str,
    requested_tier: str = "smart",
    tier_class: str = "deep",
    on_event: Any | None = None,
    preferred_provider: str | None = None,
) -> DebateResult:
    """Execute the appropriate debate pipeline for the requested tier."""
    cleaned_requested_tier = str(requested_tier or "").strip().lower()
    if cleaned_requested_tier and not is_valid_audit_tier(cleaned_requested_tier):
        raise ValueError(f"Unknown debate tier: {requested_tier}")

    normalized_requested_tier = normalize_audit_tier(requested_tier)
    config = _resolve_pipeline_config(normalized_requested_tier)

    pipeline_version = str(settings.DEBATE_PIPELINE_VERSION or "v3").strip().lower()

    active_runner = _select_pipeline_runner(
        version=pipeline_version,
        normalized_tier=normalized_requested_tier,
    )
    return await active_runner(
        ai_factory=ai_factory,
        audit_data=audit_data,
        prompt_context=prompt_context,
        config=config,
        on_event=on_event,
        preferred_provider=preferred_provider,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aggregate_usage(rounds: list[DebateAgentResult]) -> dict[str, int]:
    total: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for round_result in rounds:
        for key in total:
            total[key] += round_result.token_usage.get(key, 0)
    return total
