from __future__ import annotations

from typing import Any

from report_schema import AI_AUDIT_SCHEMA_VERSION, CanonicalAuditAnalysisContract
from services.canonical_payload_coercion import coerce_payload_for_contract


def assemble_canonical_report(
    *,
    seo: dict[str, Any],
    geo: dict[str, Any],
    aeo: dict[str, Any],
    synth: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    dominant_entities = geo.get("entity_analysis", {}).get("dominant_entities", [])
    canonical = {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": synth["summary"],
        "recommendations": synth["recommendations"],
        "seo_findings": seo["seo_findings"],
        "geo_findings": geo["geo_findings"],
        "aeo_findings": aeo["aeo_findings"],
        "entity_analysis": geo["entity_analysis"],
        "aeo_signals": aeo["aeo_signals"],
        "geo_signals": geo["geo_signals"],
        "technical_signals": seo["technical_signals"],
        "entities_detected": dominant_entities if isinstance(dominant_entities, list) else [],
        "seo_score": None,
        "geo_score": None,
        "aeo_score": None,
        "executive_dossier": synth.get("executive_dossier"),
        "findings": synth.get("findings") or [],
        "citation_probability_score": aeo.get("citation_probability_score"),
        "strategic_roadmap": synth.get("strategic_roadmap"),
        "neural_intelligence_grid": synth.get("neural_intelligence_grid") or [],
        "market_dominance_projection": synth.get("market_dominance_projection"),
    }
    canonical = coerce_payload_for_contract(canonical)
    validated = CanonicalAuditAnalysisContract.model_validate(canonical)
    dumped = validated.model_dump()
    if warnings:
        dumped["_assembly_warnings"] = [str(item).strip() for item in warnings if str(item).strip()]
    return dumped
