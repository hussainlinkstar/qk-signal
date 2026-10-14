from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CompetitorDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    site_url: str = Field(min_length=1)
    category: str = Field(min_length=1)
    market: str = Field(min_length=1)


class DiscoveredCompetitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    shared_entities: list[str] = Field(default_factory=list)
    entity_overlap_score: float = 0
    confidence_score: float


class CompetitorDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str
    category: str
    market: str
    cached: bool
    competitors: list[DiscoveredCompetitor]


class BenchmarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    geo_visibility: float
    aeo_score: float
    entity_strength: float


class CompetitorBenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: BenchmarkInput
    competitors: list[BenchmarkInput]


class BenchmarkColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: str


class BenchmarkDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geo_visibility: float
    aeo_score: float
    entity_strength: float


class BenchmarkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    name: str
    is_target: bool
    geo_visibility: float
    aeo_score: float
    entity_strength: float
    overall_score: float
    deltas_vs_target: BenchmarkDelta


class BenchmarkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    competitor_count: int
    target_rank: int


class CompetitorBenchmarkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[BenchmarkColumn]
    rows: list[BenchmarkRow]
    summary: BenchmarkSummary


class CompetitorMatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    geo_score: float
    aeo_score: float
    seo_score: float
    gap_to_you: float


class CompetitorMatrixResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[CompetitorMatrixRow]


class CompetitorEntityGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    site_citations: int
    comp_citations: int


class CompetitorMissingAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    competitor_citations: list[str] = Field(default_factory=list)


class CompetitorCompareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[str]
    site_scores: list[float]
    comp_scores: list[float]
    base_site: str | None = None
    comp_site: str | None = None
    audit_timestamps: list[str] | None = None
    common_entities: list[CompetitorEntityGap] = Field(default_factory=list)
    missing_answers: list[CompetitorMissingAnswer] = Field(default_factory=list)


class SemanticEntityImportance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_importance: float
    frequency: float
    frequency_score: float
    avg_relevance: float
    brand_cited_rate: float
    avg_answer_relevance: float


class SemanticGapEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    normalized_key: str
    importance: SemanticEntityImportance
    evidence_queries: list[str] = Field(default_factory=list)
    recommended_topic: str


class CompetitorSemanticGapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_site_id: int
    comp_site_id: int
    missing_entities: list[SemanticGapEntity] = Field(default_factory=list)


class SiteCompetitorLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    competitor_site_id: int | None = Field(default=None, ge=1)
    competitor_domain: str | None = Field(default=None, min_length=1)
    display_name: str | None = Field(default=None, min_length=1)


class SiteCompetitorLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int
    competitor_site_id: int
    competitor_domain: str
    display_name: str


class SiteCompetitorBulkDiscoveryLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[SiteCompetitorLinkRequest] = Field(default_factory=list)


class SiteCompetitorBulkDiscoveryLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked: list[SiteCompetitorLinkResponse] = Field(default_factory=list)
