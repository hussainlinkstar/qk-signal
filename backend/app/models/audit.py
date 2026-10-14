from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    NonNegativeFloat,
    NonNegativeInt,
    StrictStr,
)


class SiteInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: HttpUrl | None = None
    market: StrictStr = Field(min_length=2, max_length=64)
    language: StrictStr = Field(min_length=2, max_length=16)


class AuditTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["website", "brand"] = "website"
    name: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    url: HttpUrl | None = None
    metadata: Dict[StrictStr, object] = Field(default_factory=dict)


class SeoBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    onpage: NonNegativeFloat | None = Field(default=None, le=100)
    performance: NonNegativeFloat | None = Field(default=None, le=100)
    indexing: NonNegativeFloat | None = Field(default=None, le=100)
    # V3 granular sub-scores
    core_web_vitals: NonNegativeFloat | None = Field(default=None, le=100)
    technical_seo: NonNegativeFloat | None = Field(default=None, le=100)
    onpage_content: NonNegativeFloat | None = Field(default=None, le=100)
    eeat_trust: NonNegativeFloat | None = Field(default=None, le=100)
    security_accessibility: NonNegativeFloat | None = Field(default=None, le=100)


class GeoBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    visibility_index: NonNegativeFloat | None = Field(default=None, le=100)
    citation_share: NonNegativeFloat | None = Field(default=None, le=100)
    brand_anchor: NonNegativeFloat | None = Field(default=None, le=100)
    # V3 granular sub-scores (legacy, kept for backward compatibility with stored data)
    advanced_local_schema: NonNegativeFloat | None = Field(default=None, le=100)
    napw_completeness: NonNegativeFloat | None = Field(default=None, le=100)
    spatial_content: NonNegativeFloat | None = Field(default=None, le=100)
    brand_citation: NonNegativeFloat | None = Field(default=None, le=100)
    # V3.1 GEO sub-scores (Generative Engine Optimization)
    content_citability: NonNegativeFloat | None = Field(default=None, le=100)
    source_authority: NonNegativeFloat | None = Field(default=None, le=100)
    entity_clarity: NonNegativeFloat | None = Field(default=None, le=100)
    # Search-based visibility audit from GeoVisibilityService
    visibility_audit: Dict[StrictStr, object] = Field(default_factory=dict)


class AeoBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answerability_score: NonNegativeFloat | None = Field(default=None, le=100)
    extractable_pages: NonNegativeInt | None = None
    schema_health: Dict[StrictStr, object] = Field(default_factory=dict)
    schema_coverage: Dict[StrictStr, object] = Field(default_factory=dict)
    readability_score: NonNegativeFloat | None = Field(default=None, le=1)
    readability_findings: List[StrictStr] = Field(default_factory=list)
    rewrite_suggestions: List[Dict[StrictStr, object]] = Field(default_factory=list)
    # V3 granular sub-scores
    llm_schema_readiness: NonNegativeFloat | None = Field(default=None, le=100)
    semantic_entity_density: NonNegativeFloat | None = Field(default=None, le=100)
    information_gain: NonNegativeFloat | None = Field(default=None, le=100)
    snippet_formatting: NonNegativeFloat | None = Field(default=None, le=100)
    # Deterministic answerability audit from AEOAnswerabilityService
    answerability_audit: Dict[StrictStr, object] = Field(default_factory=dict)


class CompetitorScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: StrictStr = Field(min_length=1, max_length=256)
    # SIGV2-1205: measured competitor fields are nullable so an absent
    # measurement stays absent instead of being stored as a fabricated 0.
    # A genuinely measured 0 still round-trips as 0.
    score: NonNegativeFloat | None = Field(default=None, le=100)
    source: StrictStr = Field(default="unknown", min_length=1, max_length=64)
    confidence_score: NonNegativeFloat = Field(default=0, le=1)
    geo_visibility: NonNegativeFloat | None = Field(default=None, le=100)
    aeo_score: NonNegativeFloat | None = Field(default=None, le=100)
    entity_strength: NonNegativeFloat | None = Field(default=None, le=100)
    rank: NonNegativeInt = 0


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    priority: NonNegativeInt
    title: StrictStr = Field(min_length=1, max_length=256)
    action: StrictStr = Field(min_length=1)
    category: Literal["Technical", "Content", "Backlinks"] = "Technical"


class ClaimVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_id: StrictStr = Field(min_length=1, max_length=128)
    claim_text: StrictStr = Field(min_length=1)
    matched_truth_key: StrictStr = Field(min_length=1, max_length=256)
    truth_value: StrictStr = Field(min_length=1)
    similarity_score: NonNegativeFloat = Field(ge=0, le=1)
    hallucination: bool
    discrepancy_type: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    severity: Literal["none", "low", "medium", "high", "critical"] = "none"
    field_path: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    field_label: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    certainty_score: NonNegativeFloat | None = Field(default=None, ge=0, le=1)
    certainty_level: Literal["high", "medium", "low"] | None = None
    disposition: Literal["supported", "flagged", "omitted"] = "supported"
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    track: Literal["track_a", "track_b", "mixed"] | None = None
    evaluation_mode: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    claim_kind: (
        Literal[
            "descriptive_observation",
            "prescriptive_recommendation",
            "causal_hypothesis",
            "forecast_or_impact",
            "mixed",
        ]
        | None
    ) = None
    classification_basis: List[StrictStr] = Field(default_factory=list)
    premise_refs: List[StrictStr] = Field(default_factory=list)
    reason_codes: List[StrictStr] = Field(default_factory=list)
    problem_refs: List[StrictStr] = Field(default_factory=list)
    problem_anchor_score: NonNegativeFloat | None = Field(default=None, ge=0, le=1)
    action_fit_score: NonNegativeFloat | None = Field(default=None, ge=0, le=1)
    site_specificity_score: NonNegativeFloat | None = Field(default=None, ge=0, le=1)
    novel_fact_risk_score: NonNegativeFloat | None = Field(default=None, ge=0, le=1)
    suggested_rewrite: StrictStr | None = None
    omittable: bool = False


class FieldCertaintySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field_path: StrictStr = Field(min_length=1, max_length=256)
    label: StrictStr = Field(min_length=1, max_length=256)
    total_claims: NonNegativeInt = 0
    supported_claims: NonNegativeInt = 0
    flagged_claims: NonNegativeInt = 0
    omitted_claims: NonNegativeInt = 0
    average_certainty: NonNegativeFloat = Field(default=0, ge=0, le=1)
    certainty_level: Literal["high", "medium", "low"] = "low"


class HallucinationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    threshold: NonNegativeFloat = Field(default=0.85, ge=0, le=1)
    total_claims: NonNegativeInt = 0
    flagged_claims: NonNegativeInt = 0
    omitted_claims: NonNegativeInt = 0
    average_certainty: NonNegativeFloat = Field(default=0, ge=0, le=1)
    claims: List[ClaimVerification] = Field(default_factory=list)
    high_risk_discrepancies: List[ClaimVerification] = Field(default_factory=list)
    field_summaries: List[FieldCertaintySummary] = Field(default_factory=list)


class IntegrityCertificateBucket(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    track: Literal["track_a", "track_b"]
    category: StrictStr = Field(min_length=1, max_length=128)
    count: NonNegativeInt = 0


class IntegrityCertificateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    total_claims: NonNegativeInt = 0
    track_a_total: NonNegativeInt = 0
    track_a_supported: NonNegativeInt = 0
    track_a_flagged: NonNegativeInt = 0
    track_a_omitted: NonNegativeInt = 0
    track_b_total: NonNegativeInt = 0
    track_b_supported: NonNegativeInt = 0
    track_b_flagged: NonNegativeInt = 0
    track_b_needs_manual_review: NonNegativeInt = 0
    track_b_omitted: NonNegativeInt = 0
    track_b_manually_approved: NonNegativeInt = 0
    track_b_manually_refused: NonNegativeInt = 0


class IntegrityCertificate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: StrictStr = Field(
        default="integrity-certificate-1", min_length=1, max_length=64
    )
    dual_track_grounding_enabled: bool = False
    grounding_profile: StrictStr = Field(default="single_track_v1", min_length=1, max_length=64)
    summary: IntegrityCertificateSummary = Field(default_factory=IntegrityCertificateSummary)
    blocked_claim_buckets: List[IntegrityCertificateBucket] = Field(default_factory=list)
    degraded: bool = False
    degraded_reason: StrictStr | None = Field(default=None, min_length=1, max_length=128)


class BenchmarkDeltaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    geo_visibility: float | int | None = None
    aeo_score: float | int | None = None
    entity_strength: float | int | None = None


class ScoreContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    public_score_source: StrictStr = Field(
        default="deterministic_matrix", min_length=1, max_length=64
    )
    public_score_version: StrictStr = Field(default="3.0", min_length=1, max_length=32)
    has_internal_alternative_scores: bool = False


class GroundingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    flagged: bool = False
    supported_sentences: NonNegativeInt = 0
    total_sentences: NonNegativeInt = 0
    support_ratio: NonNegativeFloat = Field(default=0, ge=0, le=1)


class ConfidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    audit_mode: StrictStr = Field(default="website", min_length=1, max_length=64)
    has_external_data_sources: bool = False
    external_data_coverage: NonNegativeFloat = Field(default=0, ge=0, le=1)
    finding_confidence: Literal["high", "medium", "low"] = "high"
    competitive_confidence: Literal["high", "medium", "low"] = "low"
    narrative_confidence: Literal["high", "medium", "low"] = "low"
    warnings: List[StrictStr] = Field(default_factory=list)
    grounding_status: GroundingStatus = Field(default_factory=GroundingStatus)


class NarrativeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: StrictStr | None = None
    source_type: Literal["deterministic_summary", "ai_synthesis", "hybrid"] = "ai_synthesis"
    confidence: Literal["high", "medium", "low"] = "low"
    supported_sentence_ratio: NonNegativeFloat = Field(default=0, ge=0, le=1)
    requires_review: bool = False
    client_safe: bool = True


class AuditNarrative(BaseModel):
    # populate_by_name + AliasChoices keep BOTH the new key and the legacy
    # persisted key valid, so historical ``full_report`` JSON still validates
    # while ``model_dump()`` emits the renamed (de-jargoned) key.
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    executive_summary: NarrativeBlock | None = None
    debate_findings: List[Dict[StrictStr, object]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("debate_findings", "strategic_intelligence_grid"),
    )
    competitive_positioning: NarrativeBlock | None = Field(
        default=None,
        validation_alias=AliasChoices("competitive_positioning", "market_dominance_blueprint"),
    )


class RecommendationImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    seo: float | int | None = None
    geo: float | int | None = None
    aeo: float | int | None = None
    overall: float | int | None = None


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: StrictStr = Field(min_length=1, max_length=128)
    priority: NonNegativeInt = 0
    category: StrictStr | None = Field(default=None, max_length=64)
    title: StrictStr = Field(min_length=1, max_length=256)
    summary: StrictStr | None = None
    action: StrictStr = Field(min_length=1)
    rationale: StrictStr | None = None
    derived_from: List[StrictStr] = Field(default_factory=list)
    grounded_by_findings: List[StrictStr] = Field(default_factory=list)
    # Stable identity for a recommendation raised by a deterministic check
    # (see problem_codes). Optional with a None default on purpose: reports
    # persisted before this field existed must keep validating, and an LLM-only
    # recommendation has no deterministic code to carry.
    problem_code: StrictStr | None = Field(default=None, max_length=64)
    expected_score_impact: RecommendationImpact = Field(default_factory=RecommendationImpact)
    cross_score_leverage: List[Literal["seo", "geo", "aeo", "overall"]] = Field(
        default_factory=list
    )
    estimated_effort: Literal["low", "medium", "high"] | None = None
    owner: Literal["engineering", "content", "seo", "client", "operations"] = "engineering"
    dependencies: List[StrictStr] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    source_type: Literal["deterministic", "deterministic_plus_ai_packaging", "ai_inference"] = (
        "deterministic"
    )
    client_safe: bool = True
    requires_human_review: bool = False


class RecommendationsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: List[RecommendationItem] = Field(default_factory=list)


class ScoreComponents(BaseModel):
    """Detailed score component breakdown from deterministic scoring engine."""

    model_config = ConfigDict(extra="allow", strict=True)

    score: NonNegativeFloat | None = Field(default=None, le=100)
    components: Dict[StrictStr, NonNegativeFloat] = Field(default_factory=dict)
    penalties: List[Dict[StrictStr, object]] = Field(default_factory=list)
    bonuses: List[Dict[StrictStr, object]] = Field(default_factory=list)


class GlobalScores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    seo: NonNegativeFloat | None = Field(default=None, le=100)
    geo: NonNegativeFloat | None = Field(default=None, le=100)
    aeo: NonNegativeFloat | None = Field(default=None, le=100)
    overall: NonNegativeFloat | None = Field(default=None, le=100)
    seo_breakdown: ScoreComponents | None = None
    geo_breakdown: ScoreComponents | None = None
    aeo_breakdown: ScoreComponents | None = None
    scoring_version: StrictStr = Field(default="3.0", min_length=1, max_length=16)
    dimension_relevance: Dict[StrictStr, float] | None = None
    na_dimensions: List[StrictStr] = Field(default_factory=list)


class AuditMetadata(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    created_at: datetime
    updated_at: datetime
    plan: StrictStr = Field(min_length=1, max_length=128)
    version: StrictStr = Field(min_length=1, max_length=64)
    service_status: Dict[StrictStr, StrictStr] = Field(default_factory=dict)
    service_errors: Dict[StrictStr, StrictStr] = Field(default_factory=dict)
    competitor_summary: Dict[StrictStr, object] = Field(default_factory=dict)
    scores_available: bool = True
    audit_outcome: StrictStr = Field(default="completed", min_length=1, max_length=64)
    intent: Literal["informational", "transactional", "navigational"] | None = None
    query_type: Literal["informational", "decision_making"] | None = None
    technical_signals: Dict[StrictStr, object] = Field(default_factory=dict)


class AuditResult(BaseModel):
    """Canonical audit payload for API responses, JSONB storage, and PDF rendering."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: StrictStr = Field(default="2026-03-09", min_length=1, max_length=32)
    audit_mode: Literal["website", "brand"] = "website"
    score_source: StrictStr = Field(default="deterministic_matrix", min_length=1, max_length=64)
    generated_at: datetime
    score_contract: ScoreContract = Field(default_factory=ScoreContract)
    confidence: ConfidenceSummary = Field(default_factory=ConfidenceSummary)
    narrative: AuditNarrative = Field(default_factory=AuditNarrative)
    recommendations: RecommendationsBlock = Field(default_factory=RecommendationsBlock)
    competitive: Dict[StrictStr, object] = Field(default_factory=dict)
    target: AuditTarget
    site: SiteInfo
    seo: SeoBreakdown
    geo: GeoBreakdown
    aeo: AeoBreakdown
    entities: List[StrictStr] = Field(default_factory=list)
    competitors: List[CompetitorScore] = Field(default_factory=list)
    suggestions: List[Suggestion] = Field(default_factory=list)
    scores: GlobalScores
    metadata: AuditMetadata
    deltas_vs_target: BenchmarkDeltaSummary | None = None
    hallucination: HallucinationResult | None = None
    integrity_certificate: IntegrityCertificate | None = None


__all__ = [
    "AeoBreakdown",
    "AuditMetadata",
    "AuditNarrative",
    "AuditResult",
    "AuditTarget",
    "BenchmarkDeltaSummary",
    "ConfidenceSummary",
    "CompetitorScore",
    "ClaimVerification",
    "FieldCertaintySummary",
    "GeoBreakdown",
    "GroundingStatus",
    "GlobalScores",
    "HallucinationResult",
    "IntegrityCertificate",
    "IntegrityCertificateBucket",
    "IntegrityCertificateSummary",
    "NarrativeBlock",
    "RecommendationImpact",
    "RecommendationItem",
    "RecommendationsBlock",
    "ScoreComponents",
    "ScoreContract",
    "SeoBreakdown",
    "SiteInfo",
    "Suggestion",
]
