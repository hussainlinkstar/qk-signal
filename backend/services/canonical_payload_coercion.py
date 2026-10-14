"""Normalize AI-generated audit payloads to match CanonicalAuditAnalysisContract.

V3 Orchestra pipelines and newer AI models may return richer structures
(object-based recommendations, extra top-level keys, non-canonical severity
values).  This module coerces those payloads into the strict contract shape
**before** Pydantic validation so the contract stays tight while the AI layer
remains tolerant.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SEVERITY_ALIASES: dict[str, str] = {
    "critical": "Critical",
    "high": "Critical",
    "strategic": "Strategic",
    "medium": "Strategic",
    "optimization": "Optimization",
    "low": "Optimization",
}

_SOURCE_AGENT_ALIASES: dict[str, str] = {
    "vision": "Vision",
    "semantic": "Semantic",
    "intent": "Intent",
    "technical": "Technical",
    "performance lab": "Technical",
    "performance": "Technical",
    "semantic knowledge graph": "Semantic",
    "predictive intent lab": "Intent",
    "thothgraph vision": "Vision",
    "validation & fact-check": "Semantic",
}


def _safe_priority_weight(value: Any, default: float = 0.5) -> float:
    """Cast *value* to float, returning *default* on failure."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_CANONICAL_ANALYSIS_ALLOWED_KEYS: set[str] = {
    "schema_version",
    "summary",
    "recommendations",
    "seo_findings",
    "geo_findings",
    "aeo_findings",
    "entity_analysis",
    "aeo_signals",
    "geo_signals",
    "technical_signals",
    "entities_detected",
    "seo_score",
    "geo_score",
    "aeo_score",
    "entity_data",
    "entity_summary",
    "executive_dossier",
    "findings",
    "citation_probability_score",
    "strategic_roadmap",
    "neural_intelligence_grid",
    "market_dominance_projection",
}


def normalize_recommendation_item(item: Any) -> str | None:
    """Convert a recommendation (string or V3 object) to a plain string."""
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        parts: list[str] = []
        agent = str(item.get("agent") or "").strip()
        if agent:
            parts.append(f"[{agent}]")
        finding = str(
            item.get("finding") or item.get("recommendation") or item.get("observation") or ""
        ).strip()
        if finding:
            parts.append(finding)
        action = str(
            item.get("comprehensive_action")
            or item.get("implementation_guide")
            or item.get("fix")
            or ""
        ).strip()
        if action and action != finding:
            parts.append(f"Action: {action}")
        return " ".join(parts).strip() or None
    return None


def normalize_fast_tier_finding(item: Any) -> dict[str, Any] | None:
    """Coerce a V3 finding dict into ``FastTierFindingContract`` shape."""
    if not isinstance(item, dict):
        return None
    raw_agent = str(item.get("source_agent") or item.get("agent") or "").strip()
    source_agent = _SOURCE_AGENT_ALIASES.get(raw_agent.lower(), None)
    if not source_agent:
        for alias, canonical in _SOURCE_AGENT_ALIASES.items():
            if alias in raw_agent.lower():
                source_agent = canonical
                break
    if not source_agent:
        source_agent = "Semantic"
    raw_severity = str(item.get("severity") or item.get("priority") or "medium").strip()
    severity = _SEVERITY_ALIASES.get(raw_severity.lower(), "Strategic")
    observation = str(
        item.get("observation")
        or item.get("finding")
        or item.get("title")
        or item.get("description")
        or ""
    ).strip()
    generative_impact = str(
        item.get("generative_impact") or item.get("why_it_matters") or item.get("detail") or ""
    ).strip()
    implementation_guide = str(
        item.get("implementation_guide")
        or item.get("fix")
        or item.get("comprehensive_action")
        or ""
    ).strip()
    if not observation:
        return None
    return {
        "source_agent": source_agent,
        "severity": severity,
        "observation": observation,
        "generative_impact": generative_impact or observation,
        "implementation_guide": implementation_guide or "Review and address this finding.",
    }


_STRING_FIELDS: tuple[str, ...] = (
    "summary",
    "executive_dossier",
    "strategic_roadmap",
    "market_dominance_projection",
)


def _coerce_string_fields(coerced: dict[str, Any]) -> None:
    """Ensure fields declared ``str`` in the contract are not dicts/lists.

    AI models (especially after Anthropic→fallback transitions) sometimes
    return structured objects for fields the contract types as plain strings.
    Flatten them to a JSON-like string so Pydantic validation passes.
    """
    import json as _json

    for key in _STRING_FIELDS:
        val = coerced.get(key)
        if val is None or isinstance(val, str):
            continue
        if isinstance(val, (dict, list)):
            try:
                coerced[key] = _json.dumps(val, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                coerced[key] = str(val)
            logger.warning(
                "coerce_payload_for_contract: field '%s' was %s, coerced to string",
                key,
                type(val).__name__,
            )
        else:
            coerced[key] = str(val)


def coerce_payload_for_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip unknown keys and normalize structures to match the canonical contract."""
    coerced = {k: v for k, v in payload.items() if k in _CANONICAL_ANALYSIS_ALLOWED_KEYS}

    recs = coerced.get("recommendations")
    if isinstance(recs, list):
        normalized_recs: list[str] = []
        for item in recs:
            text = normalize_recommendation_item(item)
            if text:
                normalized_recs.append(text)
        coerced["recommendations"] = normalized_recs

    findings = coerced.get("findings")
    if isinstance(findings, dict):
        # Some models emit ``findings`` grouped by dimension
        # ({"seo_findings": [...], "aeo_findings": [...], "geo_findings": [...]})
        # instead of the flat list the contract requires. Flatten the grouped
        # lists (insertion order preserved) so validation passes without losing
        # findings, rather than letting a dict hit ``List[...]`` and 502 the audit.
        flattened: list[Any] = []
        for group in findings.values():
            if isinstance(group, list):
                flattened.extend(group)
        logger.warning(
            "coerce_payload_for_contract: 'findings' was a dict (grouped by "
            "dimension); flattened %d grouped item(s) to a list.",
            len(flattened),
        )
        findings = flattened
    if isinstance(findings, list):
        normalized_findings: list[dict[str, Any]] = []
        for item in findings:
            normalized = normalize_fast_tier_finding(item)
            if normalized:
                normalized_findings.append(normalized)
        coerced["findings"] = normalized_findings
    elif "findings" in coerced:
        # Neither list nor dict (e.g. null/str) → drop so the contract's
        # default_factory=list applies instead of a validation error.
        coerced.pop("findings")

    grid = coerced.get("neural_intelligence_grid")
    if isinstance(grid, list):
        normalized_grid: list[dict[str, Any]] = []
        for item in grid:
            if isinstance(item, dict):
                normalized_grid.append(
                    {
                        "agent_correlation": str(item.get("agent_correlation") or "").strip(),
                        "discovery": str(item.get("discovery") or "").strip(),
                        "neural_logic": str(item.get("neural_logic") or "").strip(),
                        "architect_fix": str(item.get("architect_fix") or "").strip(),
                        "priority_weight": _safe_priority_weight(item.get("priority_weight")),
                    }
                )
        coerced["neural_intelligence_grid"] = normalized_grid

    _coerce_string_fields(coerced)
    _apply_required_field_defaults(coerced)

    return coerced


def _apply_required_field_defaults(coerced: dict[str, Any]) -> None:
    """Backfill missing required fields with safe zero-value defaults.

    This prevents Pydantic validation from blowing up when a fallback
    provider returns a structurally incomplete payload.  The result is a
    degraded-but-valid audit rather than a hard 502.
    """
    from report_schema import AI_AUDIT_SCHEMA_VERSION

    _REQUIRED_KEYS = (
        "schema_version",
        "summary",
        "recommendations",
        "seo_findings",
        "geo_findings",
        "aeo_findings",
        "entity_analysis",
        "aeo_signals",
        "geo_signals",
        "technical_signals",
    )
    original_keys = set(coerced.keys())

    coerced.setdefault("schema_version", AI_AUDIT_SCHEMA_VERSION)
    coerced.setdefault("summary", "")
    if not isinstance(coerced.get("recommendations"), list):
        coerced["recommendations"] = []
    for key in ("seo_findings", "geo_findings", "aeo_findings"):
        if not isinstance(coerced.get(key), list):
            coerced[key] = []
    if not isinstance(coerced.get("entity_analysis"), dict):
        coerced["entity_analysis"] = {
            "entity_clarity_score": 0.0,
            "brand_trust_score": 0.0,
        }
    if not isinstance(coerced.get("aeo_signals"), dict):
        coerced["aeo_signals"] = {
            "answerability_score": 0.0,
            "voice_readiness_score": 0.0,
        }
    if not isinstance(coerced.get("geo_signals"), dict):
        coerced["geo_signals"] = {
            "citation_consistency_score": 0.0,
            "local_authority_score": 0.0,
        }
    if not isinstance(coerced.get("technical_signals"), dict):
        coerced["technical_signals"] = {
            "mobile_friendliness": 0.0,
            "security_score": 0.0,
        }

    backfilled = [k for k in _REQUIRED_KEYS if k not in original_keys]
    if backfilled:
        logger.warning(
            "coerce_payload_for_contract: backfilled missing required fields: %s",
            backfilled,
        )
