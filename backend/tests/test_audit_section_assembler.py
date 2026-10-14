import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.audit_section_assembler import assemble_canonical_report


def test_assemble_canonical_report_derives_entities_detected_deterministically() -> None:
    payload = assemble_canonical_report(
        seo={
            "seo_findings": [],
            "technical_signals": {
                "mobile_friendliness": 80.0,
                "security_score": 90.0,
                "accessibility_score": 70.0,
            },
        },
        geo={
            "geo_findings": [],
            "geo_signals": {
                "citation_consistency_score": 72.0,
                "local_authority_score": 68.0,
                "relevance_score": 60.0,
                "competitor_overlap_score": 55.0,
            },
            "entity_analysis": {
                "entity_clarity_score": 0.8,
                "brand_trust_score": 0.7,
                "knowledge_graph_presence": True,
                "dominant_entities": ["Lavan Events", "Iasi"],
            },
        },
        aeo={
            "aeo_findings": [],
            "aeo_signals": {
                "answerability_score": 65.0,
                "content_freshness_score": 50.0,
                "schema_completeness": 40.0,
                "voice_readiness_score": 61.0,
                "key_recommendations": [],
            },
            "citation_probability_score": 0.41,
        },
        synth={
            "summary": "summary",
            "recommendations": ["rec"],
            "executive_dossier": "dossier",
            "findings": [],
            "strategic_roadmap": "roadmap",
            "neural_intelligence_grid": [],
            "market_dominance_projection": "projection",
        },
        warnings=["geo_expert_retry_recovered"],
    )

    assert payload["entities_detected"] == ["Lavan Events", "Iasi"]
    assert payload["_assembly_warnings"] == ["geo_expert_retry_recovered"]
