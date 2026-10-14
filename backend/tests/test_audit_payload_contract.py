import json
from pathlib import Path

from app.models.audit import AuditNarrative, AuditResult
from report_schema import AI_AUDIT_SCHEMA_VERSION, CanonicalAuditAnalysisContract


def _minimal_canonical_payload() -> dict:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": "Versioned canonical audit analysis",
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.84,
            "brand_trust_score": 0.79,
            "knowledge_graph_presence": True,
            "dominant_entities": [],
        },
        "aeo_signals": {
            "answerability_score": 72.0,
            "voice_readiness_score": 69.0,
            "key_recommendations": [],
        },
        "geo_signals": {
            "citation_consistency_score": 71.0,
            "local_authority_score": 68.0,
        },
        "technical_signals": {
            "mobile_friendliness": 83.0,
            "security_score": 91.0,
        },
    }


def test_canonical_contract_accepts_legacy_and_renamed_keys() -> None:
    """Phase 10.4 rename: CanonicalAuditAnalysisContract.model_validate() must
    accept BOTH the legacy LLM-contract keys and the renamed keys, while
    ``model_dump()`` keeps emitting the legacy key so the downstream pipeline
    (which reads by string key) is untouched."""
    grid_item = {
        "agent_correlation": "Semantic+Intent",
        "discovery": "Category mismatch",
        "neural_logic": "Inference penalty",
        "architect_fix": "Refine category signals",
        "priority_weight": 0.9,
    }

    legacy = _minimal_canonical_payload()
    legacy["neural_intelligence_grid"] = [grid_item]
    legacy["market_dominance_projection"] = "Legacy projection"
    validated_legacy = CanonicalAuditAnalysisContract.model_validate(legacy)
    assert len(validated_legacy.neural_intelligence_grid) == 1
    assert validated_legacy.market_dominance_projection == "Legacy projection"

    renamed = _minimal_canonical_payload()
    renamed["debate_findings"] = [grid_item]
    renamed["competitive_positioning"] = "Renamed positioning"
    validated_renamed = CanonicalAuditAnalysisContract.model_validate(renamed)
    assert len(validated_renamed.neural_intelligence_grid) == 1
    assert validated_renamed.market_dominance_projection == "Renamed positioning"

    # model_dump must keep the legacy canonical key for the LLM pipeline.
    dumped = validated_renamed.model_dump()
    assert "neural_intelligence_grid" in dumped
    assert "market_dominance_projection" in dumped


def test_audit_narrative_accepts_legacy_keys_and_dumps_renamed() -> None:
    """Old persisted ``full_report`` narratives (legacy jargon keys) still
    validate, and ``model_dump()`` emits the de-jargoned keys."""
    block = {
        "text": "Premium blueprint",
        "source_type": "ai_synthesis",
        "confidence": "medium",
        "supported_sentence_ratio": 0.8,
        "requires_review": False,
        "client_safe": True,
    }

    legacy_narrative = AuditNarrative.model_validate(
        {
            "executive_summary": None,
            "strategic_intelligence_grid": [{"title": "Premium grid"}],
            "market_dominance_blueprint": block,
        }
    )
    dumped = legacy_narrative.model_dump()
    assert dumped["debate_findings"] == [{"title": "Premium grid"}]
    assert dumped["competitive_positioning"]["text"] == "Premium blueprint"
    assert "strategic_intelligence_grid" not in dumped
    assert "market_dominance_blueprint" not in dumped

    # The renamed keys also validate directly.
    renamed_narrative = AuditNarrative.model_validate(
        {"debate_findings": [{"title": "x"}], "competitive_positioning": block}
    )
    assert renamed_narrative.model_dump()["debate_findings"] == [{"title": "x"}]


def test_legacy_neural_executive_summary_renders_as_strategic_summary() -> None:
    """Descope rename: old persisted reports carrying the legacy
    ``neural_executive_summary`` metadata key must still validate
    (``AuditMetadata`` allows extras) and render into the de-jargoned
    ``strategic_summary`` key via the read-compat fallback."""
    from services.pdf_reports.assembler import _narrative_context

    repo_root = Path(__file__).resolve().parents[2]
    payload_path = repo_root / "contracts" / "canonical_audit_payload.sample.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    payload.setdefault("metadata", {}).pop("strategic_summary", None)
    payload["metadata"]["neural_executive_summary"] = "Legacy strategic roadmap text"
    # Clear the narrative block so the metadata-level fallback is exercised.
    payload.setdefault("narrative", {})["executive_summary"] = None

    # Old persisted payload still validates; the legacy key survives as an
    # allowed metadata extra (model_validate accepts both old and new keys).
    validated = AuditResult.model_validate_json(json.dumps(payload))
    dumped = validated.model_dump(mode="json")
    assert dumped["metadata"]["neural_executive_summary"] == "Legacy strategic roadmap text"

    # And it renders into the renamed ``strategic_summary`` key.
    narrative = _narrative_context(dumped)
    assert narrative["strategic_summary"] == "Legacy strategic roadmap text"
    assert narrative["executive_summary"]["text"] == "Legacy strategic roadmap text"


def test_canonical_sample_payload_matches_backend_audit_result_model() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload_path = repo_root / "contracts" / "canonical_audit_payload.sample.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    validated = AuditResult.model_validate_json(json.dumps(payload))
    dumped = validated.model_dump(mode="json")

    assert dumped["scores"]["overall"] == 73.0
    assert dumped["metadata"]["intent"] == "informational"
    assert dumped["metadata"]["query_type"] == "informational"
    assert dumped["hallucination"]["flagged_claims"] == 1
    assert dumped["hallucination"]["omitted_claims"] == 1
    assert dumped["hallucination"]["field_summaries"][0]["field_path"] == "summary"


def test_canonical_ai_analysis_contract_requires_versioned_schema() -> None:
    payload = {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": "Versioned canonical audit analysis",
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.84,
            "brand_trust_score": 0.79,
            "knowledge_graph_presence": True,
            "dominant_entities": [],
        },
        "aeo_signals": {
            "answerability_score": 72.0,
            "voice_readiness_score": 69.0,
            "key_recommendations": [],
        },
        "geo_signals": {
            "citation_consistency_score": 71.0,
            "local_authority_score": 68.0,
        },
        "technical_signals": {
            "mobile_friendliness": 83.0,
            "security_score": 91.0,
        },
    }

    validated = CanonicalAuditAnalysisContract.model_validate(payload)

    assert validated.schema_version == AI_AUDIT_SCHEMA_VERSION
