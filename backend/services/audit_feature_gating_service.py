from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config.plans import (
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
    resolve_plan_alias,
    resolve_plan_requirement_alias,
)


_LEGACY_PLAN_ALIASES: dict[str, str] = {
    "basic": "plan_standard",
    "starter": "plan_standard",
    "growth": "plan_specialist",
    "pro": "plan_specialist",
    "business": "plan_specialist",
    "smart": "plan_specialist",
    "enterprise": "plan_executive",
    "deep_judgment": "plan_executive",
    "high_confidence": "plan_executive",
}

_LOCKABLE_AUDIT_FEATURES: tuple[tuple[str, str, str], ...] = (
    (
        "competitors",
        "has_competitor_analysis",
        "Competitor benchmarks and discovered rivals are locked on the current plan.",
    ),
    (
        "entities",
        "has_entity_enhancement",
        "Entity extraction and semantic node mapping are locked on the current plan.",
    ),
    (
        "predictive_intent",
        "has_predictive_intent_engine",
        "Predictive intent classification is locked on the current plan.",
    ),
    (
        "semantic_graph",
        "has_semantic_graph_mapping",
        "Semantic graph and schema coverage insights are locked on the current plan.",
    ),
    (
        "advanced_reporting",
        "has_advanced_reporting",
        "Advanced narrative reporting is locked on the current plan.",
    ),
    (
        "brand_integrity",
        "has_brand_integrity_guardrails",
        "Brand integrity and grounding guardrails are locked on the current plan.",
    ),
    (
        "eeat_trust",
        "has_eeat_trust_audit",
        "E-E-A-T trust scoring is locked on the current plan.",
    ),
)


def normalize_plan_for_audit_gating(plan: str | None) -> str:
    if not isinstance(plan, str):
        return "plan_starter"

    normalized = plan.strip().lower()
    if not normalized:
        return "plan_starter"

    if normalized in _LEGACY_PLAN_ALIASES:
        return _LEGACY_PLAN_ALIASES[normalized]

    resolved = resolve_plan_requirement_alias(normalized) or resolve_plan_alias(normalized)
    return resolved or "plan_starter"


def resolve_audit_execution_gates(plan: str | None) -> dict[str, bool | str]:
    normalized_plan = normalize_plan_for_audit_gating(plan)
    return {
        "normalized_plan": normalized_plan,
        "allow_predictive_intent": can_use_feature(normalized_plan, "has_predictive_intent_engine"),
        "allow_competitor_analysis": can_use_feature(normalized_plan, "has_competitor_analysis"),
        "allow_entity_enhancement": can_use_feature(normalized_plan, "has_entity_enhancement"),
        # Advisor (EPIC 13) rides the existing advanced-reporting entitlement (specialist+).
        "allow_advisor_synthesis": can_use_feature(normalized_plan, "has_advanced_reporting"),
    }


def _required_plan_label(capability_key: str) -> str | None:
    required_plan = MINIMUM_PLAN_BY_FEATURE.get(capability_key)
    if not required_plan:
        return None
    presentation = PLAN_PRESENTATION.get(required_plan, {})
    name = presentation.get("name")
    return str(name).strip() or required_plan


def build_lock_metadata(
    *,
    capability_key: str,
    detail: str,
    lock_origin: str,
) -> dict[str, Any]:
    """Build one ``locked_sections`` entry for a capability key.

    The required plan is read from ``MINIMUM_PLAN_BY_FEATURE`` and never
    written out by hand: a lock card tells a customer what a plan would
    unlock, so a hand-written plan name is a promise with nothing behind it.
    ``capability_key`` must be a key that exists in ``CAPABILITY_MATRIX``.
    """
    return {
        "is_locked": True,
        "capability_key": capability_key,
        "required_plan": MINIMUM_PLAN_BY_FEATURE.get(capability_key),
        "required_plan_label": _required_plan_label(capability_key),
        "detail": detail,
        "lock_origin": lock_origin,
    }


def _apply_lock_metadata(
    *,
    locked_sections: dict[str, Any],
    section_key: str,
    capability_key: str,
    detail: str,
    lock_origin: str,
) -> None:
    locked_sections[section_key] = build_lock_metadata(
        capability_key=capability_key,
        detail=detail,
        lock_origin=lock_origin,
    )


def _lock_competitors(payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    payload["competitors"] = []
    payload["competitive"] = {}
    payload["deltas_vs_target"] = None
    metadata["competitor_summary"] = {}


def _lock_entities(payload: dict[str, Any]) -> None:
    payload["entities"] = []


def _lock_predictive_intent(metadata: dict[str, Any]) -> None:
    metadata["intent"] = None
    metadata["query_type"] = None


def _lock_semantic_graph(payload: dict[str, Any]) -> None:
    aeo = payload.get("aeo")
    if not isinstance(aeo, dict):
        aeo = {}
    aeo["schema_health"] = {}
    aeo["schema_coverage"] = {}
    payload["aeo"] = aeo


def _lock_advanced_reporting(payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    narrative = payload.get("narrative")
    if not isinstance(narrative, dict):
        narrative = {}
    narrative["executive_summary"] = None
    narrative["debate_findings"] = []
    narrative["competitive_positioning"] = None
    # Clear legacy keys too so historical persisted reports are fully locked.
    narrative.pop("strategic_intelligence_grid", None)
    narrative.pop("market_dominance_blueprint", None)
    payload["narrative"] = narrative

    for key in (
        "executive_summary",
        "strategic_summary",
        "neural_executive_summary",
        "debate_findings",
        "competitive_positioning",
        "strategic_intelligence_grid",
        "market_dominance_blueprint",
    ):
        metadata.pop(key, None)


def _lock_brand_integrity(payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    payload["hallucination"] = None
    payload["integrity_certificate"] = None
    metadata.pop("hallucination", None)
    for key in (
        "integrity_certificate_summary",
        "dual_track_shadow",
        "dual_track_grounding",
        "grounding_profile",
        "dual_track_grounding_enabled",
        "unified_truth_context_version",
        "track_a_claim_count",
        "track_b_claim_count",
        "fallback_reason",
    ):
        metadata.pop(key, None)


def _lock_eeat_trust(payload: dict[str, Any]) -> None:
    seo = payload.get("seo")
    if isinstance(seo, dict):
        seo["eeat_trust"] = None
        payload["seo"] = seo

    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return

    seo_breakdown = scores.get("seo_breakdown")
    if not isinstance(seo_breakdown, dict):
        return

    components = seo_breakdown.get("components")
    if isinstance(components, dict):
        components.pop("eeat_trust", None)
        seo_breakdown["components"] = components

        # Recalculate SEO score without E-E-A-T contribution.
        # Original weights: core_web_vitals=0.25, technical_seo=0.20,
        # onpage_content=0.20, eeat_trust=0.20, security_accessibility=0.15.
        # After removing eeat_trust the remaining 4 weights sum to 0.80;
        # normalise them so the recalculated score uses the full 0-100 range.
        _SEO_WEIGHTS_WITHOUT_EEAT = {
            "core_web_vitals": 0.25,
            "technical_seo": 0.20,
            "onpage_content": 0.20,
            "security_accessibility": 0.15,
        }
        remaining_sum = sum(_SEO_WEIGHTS_WITHOUT_EEAT.values())  # 0.80
        if remaining_sum > 0:
            recalculated_seo = sum(
                float(components.get(k, 0)) * (w / remaining_sum)
                for k, w in _SEO_WEIGHTS_WITHOUT_EEAT.items()
            )
            recalculated_seo = round(min(100.0, max(0.0, recalculated_seo)), 1)
            seo_breakdown["score"] = recalculated_seo
            scores["seo_score"] = recalculated_seo

            # Recalculate overall score (SEO 40%, AEO 30%, GEO 30%).
            geo_score = scores.get("geo_score")
            aeo_score = scores.get("aeo_score")
            if isinstance(geo_score, (int, float)) and isinstance(aeo_score, (int, float)):
                recalculated_overall = round(
                    recalculated_seo * 0.4 + float(aeo_score) * 0.3 + float(geo_score) * 0.3, 1
                )
                scores["overall_score"] = min(100.0, max(0.0, recalculated_overall))

    scores["seo_breakdown"] = seo_breakdown
    payload["scores"] = scores


def sanitize_audit_payload_for_plan(
    report: dict[str, Any] | None,
    current_plan: str | None,
    *,
    lock_origin: str = "read",
    section_keys: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}

    payload = deepcopy(report)
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    normalized_plan = normalize_plan_for_audit_gating(current_plan)
    locked_sections = metadata.get("locked_sections")
    if not isinstance(locked_sections, dict):
        locked_sections = {}
    else:
        locked_sections = dict(locked_sections)

    for section_key, capability_key, detail in _LOCKABLE_AUDIT_FEATURES:
        if section_keys is not None and section_key not in section_keys:
            continue

        if can_use_feature(normalized_plan, capability_key):
            locked_sections.pop(section_key, None)
            continue

        if section_key == "competitors":
            _lock_competitors(payload, metadata)
        elif section_key == "entities":
            _lock_entities(payload)
        elif section_key == "predictive_intent":
            _lock_predictive_intent(metadata)
        elif section_key == "semantic_graph":
            _lock_semantic_graph(payload)
        elif section_key == "advanced_reporting":
            _lock_advanced_reporting(payload, metadata)
        elif section_key == "brand_integrity":
            _lock_brand_integrity(payload, metadata)
        elif section_key == "eeat_trust":
            _lock_eeat_trust(payload)

        _apply_lock_metadata(
            locked_sections=locked_sections,
            section_key=section_key,
            capability_key=capability_key,
            detail=detail,
            lock_origin=lock_origin,
        )

    if locked_sections:
        metadata["locked_sections"] = locked_sections
    else:
        metadata.pop("locked_sections", None)

    payload["metadata"] = metadata
    return payload
