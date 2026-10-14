from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field

REPORT_SCHEMA_VERSION = "1.0"
AI_AUDIT_SCHEMA_VERSION = "2026-03-10"


class ScoreSummary(BaseModel):
    score: Optional[float] = None
    recommendations: Optional[List[str]] = None

    class Config:
        extra = "allow"


class EntityData(BaseModel):
    serialized_json: Optional[str] = Field(
        default=None,
        description="JSON-serialized entity payload when a strict structure is unavailable.",
    )

    class Config:
        extra = "allow"


class FindingItem(BaseModel):
    description: str
    severity: str
    category: str

    class Config:
        extra = "allow"


class EntitySummary(BaseModel):
    summary_text: Optional[str] = Field(
        default=None,
        description="High-level summary of entities detected in the analysis.",
    )

    class Config:
        extra = "allow"


class AuditAnalysis(BaseModel):
    schema_version: str = Field(default=AI_AUDIT_SCHEMA_VERSION)
    url: Optional[str] = None
    summary: Optional[str] = None
    recommendations: Optional[List[str]] = None
    entities_detected: Optional[List[str]] = None
    seo_findings: Optional[List[FindingItem]] = None
    geo_findings: Optional[List[FindingItem]] = None
    aeo_findings: Optional[List[FindingItem]] = None
    # Backward-compatible: kept so audit_runner.parse_obj() doesn't drop legacy payloads
    seo_score: Optional[Any] = None
    geo_score: Optional[Any] = None
    aeo_score: Optional[Any] = None
    entity_data: Optional[EntityData] = None
    entity_summary: Optional[EntitySummary] = None
    entity_analysis: Optional[Dict[str, Any]] = None
    aeo_signals: Optional[Dict[str, Any]] = None
    geo_signals: Optional[Dict[str, Any]] = None
    technical_signals: Optional[Dict[str, Any]] = None
    executive_dossier: Optional[str] = None
    findings: Optional[List[Dict[str, Any]]] = None
    citation_probability_score: Optional[float] = None
    strategic_roadmap: Optional[str] = None
    # Backward/forward-compatible: canonical LLM-contract field name is retained
    # (the prompt + JSON output schema still emit ``neural_intelligence_grid``),
    # while the renamed key ``debate_findings`` is also accepted on input.
    neural_intelligence_grid: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        validation_alias=AliasChoices("neural_intelligence_grid", "debate_findings"),
    )
    market_dominance_projection: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("market_dominance_projection", "competitive_positioning"),
    )

    model_config = {"extra": "allow", "populate_by_name": True}


class EntityAnalysisContract(BaseModel):
    entity_clarity_score: float
    brand_trust_score: float
    knowledge_graph_presence: Optional[bool] = None
    dominant_entities: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AeoSignalsContract(BaseModel):
    answerability_score: float
    content_freshness_score: Optional[float] = None
    schema_completeness: Optional[float] = None
    voice_readiness_score: float
    key_recommendations: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GeoSignalsContract(BaseModel):
    citation_consistency_score: float
    local_authority_score: float
    relevance_score: Optional[float] = None
    competitor_overlap_score: Optional[float] = None

    model_config = {"extra": "forbid"}


class TechnicalSignalsContract(BaseModel):
    mobile_friendliness: float
    security_score: float
    accessibility_score: Optional[float] = None

    model_config = {"extra": "forbid"}


class FastTierFindingContract(BaseModel):
    source_agent: Literal["Vision", "Semantic", "Intent", "Technical"]
    severity: Literal["Critical", "Strategic", "Optimization"]
    observation: str
    generative_impact: str
    implementation_guide: str

    model_config = {"extra": "forbid"}


class NeuralGridItemContract(BaseModel):
    agent_correlation: str
    discovery: str
    neural_logic: str
    architect_fix: str
    priority_weight: float

    model_config = {"extra": "forbid"}


class CanonicalAuditAnalysisContract(BaseModel):
    schema_version: Literal[AI_AUDIT_SCHEMA_VERSION]
    summary: str
    recommendations: List[str]
    seo_findings: List[FindingItem]
    geo_findings: List[FindingItem]
    aeo_findings: List[FindingItem]
    entity_analysis: EntityAnalysisContract
    aeo_signals: AeoSignalsContract
    geo_signals: GeoSignalsContract
    technical_signals: TechnicalSignalsContract
    entities_detected: List[str] = Field(default_factory=list)
    seo_score: Optional[Any] = None
    geo_score: Optional[Any] = None
    aeo_score: Optional[Any] = None
    entity_data: Optional[EntityData] = None
    entity_summary: Optional[EntitySummary] = None
    executive_dossier: Optional[str] = None
    findings: List[FastTierFindingContract] = Field(default_factory=list)
    citation_probability_score: Optional[float] = None
    strategic_roadmap: Optional[str] = None
    # Backward/forward-compatible: the canonical LLM-contract key name is retained
    # so ``model_dump()`` keeps emitting ``neural_intelligence_grid`` for the
    # downstream pipeline, while the renamed key ``debate_findings`` is also
    # accepted on input (model_validate accepts BOTH old and new keys).
    neural_intelligence_grid: List[NeuralGridItemContract] = Field(
        default_factory=list,
        validation_alias=AliasChoices("neural_intelligence_grid", "debate_findings"),
    )
    market_dominance_projection: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("market_dominance_projection", "competitive_positioning"),
    )

    model_config = {"extra": "forbid", "populate_by_name": True}


class AuditTargetContract(BaseModel):
    type: str = "website"
    name: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class DebateTranscriptEntry(BaseModel):
    role: str
    provider: str
    model: str
    output_summary: str
    semantic_role: Optional[str] = None
    token_usage: Dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    routing_mode: Optional[str] = None
    route_reason: Optional[str] = None
    requested_tier: Optional[str] = None
    execution_tier: Optional[str] = None
    layer: Optional[int] = None


class DebateAgentCostEntry(BaseModel):
    role: str
    provider: str
    model: str
    semantic_role: Optional[str] = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens: Dict[str, int] = Field(default_factory=dict)
    execution_tier: Optional[str] = None
    routing_mode: Optional[str] = None
    layer: Optional[int] = None


class DebateMetadata(BaseModel):
    enabled: bool = False
    mode: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    requested_tier: Optional[str] = None
    final_provider: Optional[str] = None
    final_model: Optional[str] = None
    profile: Optional[str] = None
    pipeline_type: Optional[str] = None
    parallel_layers: Optional[int] = None
    agent_count: Optional[int] = None
    debate_confidence_score: Optional[float] = None
    synthesis_reasoning: Optional[str] = None
    fallback_reason: Optional[str] = None
    judge_summary: Optional[Dict[str, int]] = None
    judge_authority: Optional[str] = None
    transcript: List[DebateTranscriptEntry] = Field(default_factory=list)
    per_agent_costs: List[DebateAgentCostEntry] = Field(default_factory=list)
    evidence_anchor: Optional[Dict[str, Any]] = None
    consolidated_claim_disposition: List[Dict[str, Any]] = Field(default_factory=list)
    dedup_count: Optional[int] = None
    usage: Optional[Dict[str, int]] = None
    total_token_usage: Optional[Dict[str, int]] = None
    total_latency_ms: Optional[float] = None
    total_estimated_cost_usd: Optional[float] = None
    total_estimated_cost_usd: Optional[float] = None
    quality_gate: Optional[Dict[str, Any]] = None


class TrackBJudgeContract(BaseModel):
    claim_id: str
    track: Literal["B"]
    verdict: Literal["supported", "flagged", "needs_manual_review", "omitted"]
    confidence_band: Literal["high", "medium", "contested"]
    problem_anchor_score: float
    action_fit_score: float
    site_specificity_score: float
    novel_fact_risk_score: float
    reason_codes: List[str] = Field(default_factory=list)
    problem_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    explanation: str
    judge_resolution: str
    suggested_rewrite: str

    model_config = {"extra": "forbid"}


class AuditReport(BaseModel):
    schema_version: str = Field(default=REPORT_SCHEMA_VERSION)
    url: Optional[str] = None
    audit_target_type: str = Field(default="website")
    target_name: Optional[str] = None
    target_url: Optional[str] = None
    target_metadata: Dict[str, Any] = Field(default_factory=dict)
    target: Optional[AuditTargetContract] = None
    analysis: AuditAnalysis
    performance: Dict[str, Any]
    network: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any]
    screenshot_base64: Optional[str] = None
    screenshot_url: Optional[str] = None
    debate: Optional[DebateMetadata] = None

    class Config:
        extra = "allow"


_STRICT_SCORE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
    },
    "required": ["score"],
    "additionalProperties": False,
}


_FINDING_ITEM_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
        "category": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
        "estimated_effort": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "description",
        "severity",
        "category",
        "rationale",
        "confidence",
        "estimated_effort",
    ],
    "additionalProperties": False,
}

_ENTITY_ANALYSIS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "entity_clarity_score": {"type": "number"},
        "brand_trust_score": {"type": "number"},
        "knowledge_graph_presence": {"type": "boolean"},
        "dominant_entities": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["entity_clarity_score", "brand_trust_score"],
    "additionalProperties": False,
}

_AEO_SIGNALS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answerability_score": {"type": "number"},
        "content_freshness_score": {"type": "number"},
        "schema_completeness": {"type": "number"},
        "voice_readiness_score": {"type": "number"},
        "key_recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["answerability_score", "voice_readiness_score"],
    "additionalProperties": False,
}

_GEO_SIGNALS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "citation_consistency_score": {"type": "number"},
        "local_authority_score": {"type": "number"},
        "relevance_score": {"type": "number"},
        "competitor_overlap_score": {"type": "number"},
    },
    "required": ["citation_consistency_score", "local_authority_score"],
    "additionalProperties": False,
}

_TECHNICAL_SIGNALS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "mobile_friendliness": {"type": "number"},
        "security_score": {"type": "number"},
        "accessibility_score": {"type": "number"},
    },
    "required": ["mobile_friendliness", "security_score"],
    "additionalProperties": False,
}

_FAST_TIER_FINDING_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_agent": {
            "type": "string",
            "enum": ["Vision", "Semantic", "Intent", "Technical"],
        },
        "severity": {
            "type": "string",
            "enum": ["Critical", "Strategic", "Optimization"],
        },
        "observation": {"type": "string"},
        "generative_impact": {"type": "string"},
        "implementation_guide": {"type": "string"},
    },
    "required": [
        "source_agent",
        "severity",
        "observation",
        "generative_impact",
        "implementation_guide",
    ],
    "additionalProperties": False,
}

_NEURAL_GRID_ITEM_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_correlation": {"type": "string"},
        "discovery": {"type": "string"},
        "neural_logic": {"type": "string"},
        "architect_fix": {"type": "string"},
        "priority_weight": {"type": "number"},
    },
    "required": [
        "agent_correlation",
        "discovery",
        "neural_logic",
        "architect_fix",
        "priority_weight",
    ],
    "additionalProperties": False,
}

_CLAIM_LEDGER_ITEM_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "domain": {"type": "string"},
        "claim_text": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_action": {"type": "string"},
    },
    "required": [
        "claim_id",
        "domain",
        "claim_text",
        "confidence",
        "evidence_refs",
        "recommended_action",
    ],
    "additionalProperties": False,
}

SEO_EXPERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_ledger": {
            "type": "array",
            "items": _CLAIM_LEDGER_ITEM_JSON_SCHEMA,
        },
        "seo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "technical_signals": _TECHNICAL_SIGNALS_JSON_SCHEMA,
    },
    "required": ["claim_ledger", "seo_findings", "technical_signals"],
    "additionalProperties": False,
}

GEO_EXPERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_ledger": {
            "type": "array",
            "items": _CLAIM_LEDGER_ITEM_JSON_SCHEMA,
        },
        "geo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "geo_signals": _GEO_SIGNALS_JSON_SCHEMA,
        "entity_analysis": _ENTITY_ANALYSIS_JSON_SCHEMA,
    },
    "required": ["claim_ledger", "geo_findings", "geo_signals", "entity_analysis"],
    "additionalProperties": False,
}

AEO_EXPERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_ledger": {
            "type": "array",
            "items": _CLAIM_LEDGER_ITEM_JSON_SCHEMA,
        },
        "aeo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "aeo_signals": _AEO_SIGNALS_JSON_SCHEMA,
        "citation_probability_score": {"type": "number"},
    },
    "required": ["claim_ledger", "aeo_findings", "aeo_signals", "citation_probability_score"],
    "additionalProperties": False,
}

AEO_GEO_COMBINED_EXPERT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_ledger": {
            "type": "array",
            "items": _CLAIM_LEDGER_ITEM_JSON_SCHEMA,
        },
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "geo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "geo_signals": _GEO_SIGNALS_JSON_SCHEMA,
        "entity_analysis": _ENTITY_ANALYSIS_JSON_SCHEMA,
        "aeo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "aeo_signals": _AEO_SIGNALS_JSON_SCHEMA,
        "citation_probability_score": {"type": "number"},
    },
    "required": [
        "claim_ledger",
        "summary",
        "recommendations",
        "geo_findings",
        "geo_signals",
        "entity_analysis",
        "aeo_findings",
        "aeo_signals",
        "citation_probability_score",
    ],
    "additionalProperties": False,
}

SYNTHESIZER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "executive_dossier": {"type": "string"},
        "findings": {
            "type": "array",
            "items": _FAST_TIER_FINDING_JSON_SCHEMA,
        },
        "strategic_roadmap": {"type": "string"},
        "neural_intelligence_grid": {
            "type": "array",
            "items": _NEURAL_GRID_ITEM_JSON_SCHEMA,
        },
        "market_dominance_projection": {"type": "string"},
    },
    "required": [
        "summary",
        "recommendations",
        "executive_dossier",
        "findings",
        "strategic_roadmap",
        "neural_intelligence_grid",
        "market_dominance_projection",
    ],
    "additionalProperties": False,
}

_CANONICAL_AUDIT_ANALYSIS_REQUIRED_FIELDS = [
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
]

FAST_TIER_INTELLIGENCE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_dossier": {"type": "string"},
        "findings": {
            "type": "array",
            "items": _FAST_TIER_FINDING_JSON_SCHEMA,
        },
        "citation_probability_score": {"type": "number"},
    },
    "required": ["executive_dossier", "findings", "citation_probability_score"],
    "additionalProperties": False,
}

SMART_TIER_NEURAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategic_roadmap": {"type": "string"},
        "neural_intelligence_grid": {
            "type": "array",
            "items": _NEURAL_GRID_ITEM_JSON_SCHEMA,
        },
        "market_dominance_projection": {"type": "string"},
    },
    "required": ["strategic_roadmap", "neural_intelligence_grid", "market_dominance_projection"],
    "additionalProperties": False,
}

CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {
            "type": "string",
            "enum": [AI_AUDIT_SCHEMA_VERSION],
        },
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "seo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "geo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "aeo_findings": {
            "type": "array",
            "items": _FINDING_ITEM_JSON_SCHEMA,
        },
        "entity_analysis": _ENTITY_ANALYSIS_JSON_SCHEMA,
        "aeo_signals": _AEO_SIGNALS_JSON_SCHEMA,
        "geo_signals": _GEO_SIGNALS_JSON_SCHEMA,
        "technical_signals": _TECHNICAL_SIGNALS_JSON_SCHEMA,
        "entities_detected": {
            "type": "array",
            "items": {"type": "string"},
        },
        "seo_score": {
            "anyOf": [
                {"type": "number"},
                _STRICT_SCORE_SCHEMA,
                {"type": "null"},
            ]
        },
        "geo_score": {
            "anyOf": [
                {"type": "number"},
                _STRICT_SCORE_SCHEMA,
                {"type": "null"},
            ]
        },
        "aeo_score": {
            "anyOf": [
                {"type": "number"},
                _STRICT_SCORE_SCHEMA,
                {"type": "null"},
            ]
        },
        "entity_data": {
            "type": "object",
            "properties": {
                "serialized_json": {"type": "string"},
            },
            "required": ["serialized_json"],
            "additionalProperties": False,
        },
        "entity_summary": {
            "type": "object",
            "properties": {
                "summary_text": {"type": "string"},
            },
            "required": ["summary_text"],
            "additionalProperties": False,
        },
        "executive_dossier": {"type": "string"},
        "findings": {
            "type": "array",
            "items": _FAST_TIER_FINDING_JSON_SCHEMA,
        },
        "citation_probability_score": {"type": "number"},
        "strategic_roadmap": {"type": "string"},
        "neural_intelligence_grid": {
            "type": "array",
            "items": _NEURAL_GRID_ITEM_JSON_SCHEMA,
        },
        "market_dominance_projection": {"type": "string"},
    },
    "required": _CANONICAL_AUDIT_ANALYSIS_REQUIRED_FIELDS,
    "additionalProperties": False,
}

AUDIT_ANALYSIS_JSON_SCHEMA: Dict[str, Any] = CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA

AUDIT_SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "entity_analysis": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["entity_analysis"],
    },
    "required": ["summary", "entity_analysis"],
    "additionalProperties": False,
}

AUDIT_SCORING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "seo_findings": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["seo_findings"],
        "geo_findings": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["geo_findings"],
        "aeo_findings": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["aeo_findings"],
        "aeo_signals": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["aeo_signals"],
        "geo_signals": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["geo_signals"],
        "technical_signals": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["technical_signals"],
    },
    "required": [
        "seo_findings",
        "geo_findings",
        "aeo_findings",
        "aeo_signals",
        "geo_signals",
        "technical_signals",
    ],
    "additionalProperties": False,
}

AUDIT_RECOMMENDATIONS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendations": AUDIT_ANALYSIS_JSON_SCHEMA["properties"]["recommendations"],
    },
    "required": ["recommendations"],
    "additionalProperties": False,
}
COMPETITOR_DISCOVERY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "source": {"type": "string", "enum": ["LLM Discovery"]},
                },
                "required": ["name", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["competitors"],
    "additionalProperties": False,
}

ENTITY_EXTRACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "salience": {"type": "number"},
                },
                "required": ["name", "type", "confidence", "salience"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entities"],
    "additionalProperties": False,
}
AI_EXPANSION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"guide_markdown": {"type": "string"}},
    "required": ["guide_markdown"],
    "additionalProperties": False,
}
TRACK_B_JUDGE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "track": {"type": "string", "enum": ["B"]},
        "verdict": {
            "type": "string",
            "enum": ["supported", "flagged", "needs_manual_review", "omitted"],
        },
        "confidence_band": {"type": "string", "enum": ["high", "medium", "contested"]},
        "problem_anchor_score": {"type": "number"},
        "action_fit_score": {"type": "number"},
        "site_specificity_score": {"type": "number"},
        "novel_fact_risk_score": {"type": "number"},
        "reason_codes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "problem_refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "explanation": {"type": "string"},
        "judge_resolution": {"type": "string"},
        "suggested_rewrite": {"type": "string"},
    },
    "required": [
        "claim_id",
        "track",
        "verdict",
        "confidence_band",
        "problem_anchor_score",
        "action_fit_score",
        "site_specificity_score",
        "novel_fact_risk_score",
        "reason_codes",
        "problem_refs",
        "evidence_refs",
        "explanation",
        "judge_resolution",
        "suggested_rewrite",
    ],
    "additionalProperties": False,
}
