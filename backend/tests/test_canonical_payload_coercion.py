"""Tests for services.canonical_payload_coercion."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from report_schema import AI_AUDIT_SCHEMA_VERSION, CanonicalAuditAnalysisContract
from services.canonical_payload_coercion import (
    coerce_payload_for_contract,
    normalize_fast_tier_finding,
    normalize_recommendation_item,
)


def _minimal_valid_payload(**overrides):
    base = {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": "test",
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.8,
            "brand_trust_score": 0.7,
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
    base.update(overrides)
    return base


def test_normalize_recommendation_string():
    assert normalize_recommendation_item("Fix this") == "Fix this"
    assert normalize_recommendation_item("  ") is None
    assert normalize_recommendation_item("") is None


def test_normalize_recommendation_v3_object():
    obj = {
        "agent": "Performance Lab",
        "finding": "LCP is slow",
        "priority": "high",
        "fix": "Optimize images",
    }
    text = normalize_recommendation_item(obj)
    assert text is not None
    assert "[Performance Lab]" in text
    assert "LCP is slow" in text
    assert "Optimize images" in text


def test_normalize_recommendation_v3_object_no_agent():
    obj = {"recommendation": "Add schema markup"}
    text = normalize_recommendation_item(obj)
    assert text == "Add schema markup"


def test_normalize_fast_tier_finding_severity_aliases():
    item = {
        "source_agent": "Technical",
        "severity": "high",
        "observation": "Missing HTTPS redirect",
        "generative_impact": "Trust signals degraded",
        "implementation_guide": "Enable HSTS",
    }
    result = normalize_fast_tier_finding(item)
    assert result is not None
    assert result["severity"] == "Critical"

    item["severity"] = "medium"
    result = normalize_fast_tier_finding(item)
    assert result["severity"] == "Strategic"

    item["severity"] = "low"
    result = normalize_fast_tier_finding(item)
    assert result["severity"] == "Optimization"


def test_normalize_fast_tier_finding_agent_aliases():
    item = {
        "agent": "Semantic Knowledge Graph",
        "severity": "Critical",
        "finding": "Schema missing",
        "why_it_matters": "Reduces discoverability",
        "fix": "Add JSON-LD",
    }
    result = normalize_fast_tier_finding(item)
    assert result is not None
    assert result["source_agent"] == "Semantic"
    assert result["observation"] == "Schema missing"
    assert result["generative_impact"] == "Reduces discoverability"
    assert result["implementation_guide"] == "Add JSON-LD"


def test_coerce_strips_extra_v3_keys():
    payload = _minimal_valid_payload(
        target_name="Test Brand",
        target_url="https://example.com",
        target_entities=[{"name": "Test"}],
        competitors=[],
        semantic_deficits=["No schema"],
        evidence_inventory=[],
    )
    coerced = coerce_payload_for_contract(payload)
    assert "target_name" not in coerced
    assert "target_url" not in coerced
    assert "target_entities" not in coerced
    assert "competitors" not in coerced
    assert "semantic_deficits" not in coerced
    assert "evidence_inventory" not in coerced
    assert coerced["summary"] == "test"


def test_coerced_payload_validates_against_contract():
    payload = _minimal_valid_payload(
        recommendations=[
            {"agent": "Vision", "finding": "Low contrast", "fix": "Increase contrast"},
            "Simple string rec",
        ],
        findings=[
            {
                "agent": "Performance Lab",
                "severity": "high",
                "finding": "Slow LCP",
                "why_it_matters": "Bad UX",
                "fix": "Compress images",
            },
        ],
        target_name="Extra V3",
        evidence_inventory=[],
    )
    coerced = coerce_payload_for_contract(payload)
    validated = CanonicalAuditAnalysisContract.model_validate(coerced)
    assert validated.schema_version == AI_AUDIT_SCHEMA_VERSION
    assert len(validated.recommendations) == 2
    assert "[Vision]" in validated.recommendations[0]
    assert validated.recommendations[1] == "Simple string rec"
    assert len(validated.findings) == 1
    assert validated.findings[0].severity == "Critical"
    assert validated.findings[0].source_agent == "Technical"


def test_findings_dict_grouped_by_dimension_is_flattened():
    """Regression: production 502 — the model returned ``findings`` as a dict
    grouped by dimension ({'seo_findings': [...], ...}) instead of a flat list,
    which failed ``findings: List[FastTierFindingContract]`` validation and
    pushed every audit to the DLQ. Coercion must flatten it, not 502."""
    payload = _minimal_valid_payload(
        findings={
            "seo_findings": [
                {
                    "agent": "Technical",
                    "severity": "critical",
                    "finding": "Missing canonical tags",
                    "why_it_matters": "Duplicate content",
                    "fix": "Add canonical links",
                    "field_group": "Structured Data",
                },
            ],
            "aeo_findings": [
                {"agent": "Semantic", "severity": "medium", "observation": "No FAQ schema"},
            ],
            "geo_findings": [],
        },
    )
    coerced = coerce_payload_for_contract(payload)
    assert isinstance(coerced["findings"], list)
    assert len(coerced["findings"]) == 2
    # Must validate against the strict contract (no bypass).
    validated = CanonicalAuditAnalysisContract.model_validate(coerced)
    assert len(validated.findings) == 2
    assert validated.findings[0].severity == "Critical"


def test_findings_invalid_scalar_dropped_to_default():
    """A non-list/non-dict ``findings`` (e.g. null/str) is dropped so the
    contract's default_factory=list applies instead of a validation error."""
    payload = _minimal_valid_payload(findings="oops-not-a-list")
    coerced = coerce_payload_for_contract(payload)
    assert "findings" not in coerced
    validated = CanonicalAuditAnalysisContract.model_validate(coerced)
    assert validated.findings == []


def test_priority_weight_non_numeric_string_uses_default():
    """BUG-040: priority_weight like 'high' must not raise ValueError."""
    payload = _minimal_valid_payload(
        neural_intelligence_grid=[
            {
                "agent_correlation": "seo analysis",
                "discovery": "Missing schema",
                "neural_logic": "Reduces discoverability",
                "architect_fix": "Add JSON-LD",
                "priority_weight": "high",
            },
        ],
    )
    coerced = coerce_payload_for_contract(payload)
    grid = coerced["neural_intelligence_grid"]
    assert len(grid) == 1
    assert grid[0]["priority_weight"] == 0.5


def test_priority_weight_numeric_string_converts():
    payload = _minimal_valid_payload(
        neural_intelligence_grid=[
            {
                "agent_correlation": "test",
                "discovery": "test",
                "neural_logic": "test",
                "architect_fix": "test",
                "priority_weight": "0.8",
            },
        ],
    )
    coerced = coerce_payload_for_contract(payload)
    assert coerced["neural_intelligence_grid"][0]["priority_weight"] == 0.8


def test_priority_weight_none_uses_default():
    payload = _minimal_valid_payload(
        neural_intelligence_grid=[
            {
                "agent_correlation": "test",
                "discovery": "test",
                "neural_logic": "test",
                "architect_fix": "test",
            },
        ],
    )
    coerced = coerce_payload_for_contract(payload)
    assert coerced["neural_intelligence_grid"][0]["priority_weight"] == 0.5
