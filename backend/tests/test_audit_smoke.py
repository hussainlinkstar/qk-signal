import re
import logging
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock

import models
from audit_runner import _discovery_context, perform_audit
from database import Base
from services.resilience import CircuitBreaker
from services.scraper import ScraperService
import services.scraper as scraper_module
from services.ai_engine import AIFactory
from services.competitors.discovery_service import CompetitorDiscoveryService
from services.unified_truth_context_service import UnifiedTruthContextService


class MockScraperService:
    async def get_page_content_and_screenshot(self, url: str) -> dict:
        return {
            "success_status": True,
            "markdown_content": "# Sample Page\n\nThis is a test audit.",
            "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
            "metadata": {"title": "Sample Page", "url": url},
        }


class ScrapeMethodAwareScraperService(MockScraperService):
    """MockScraperService that reports which scraper actually fetched the page."""

    def __init__(self, scrape_method: str) -> None:
        self.scrape_method = scrape_method

    async def get_page_content_and_screenshot(self, url: str) -> dict:
        result = await super().get_page_content_and_screenshot(url)
        result["scrape_method"] = self.scrape_method
        return result


class MockPerformanceService:
    async def get_performance_metrics(self, url: str) -> dict:
        return {
            "performance_score": 92,
            "accessibility_score": 88,
            "best_practices_score": 90,
            "seo_score": 93,
            "metrics": {"first_contentful_paint_ms": 1234},
        }


class MockNetworkAnalysisService:
    async def analyze_network_protocols(self, url: str) -> dict:
        return {
            "protocols": ["h2", "h3"],
            "https": True,
            "http2": True,
            "http3": True,
        }


class SuggestionDetailMixin:
    async def generate_suggestion_detail(
        self,
        *,
        provider: str,
        tier: str,
        suggestion: str,
        market: str,
        language: str,
        page_type: str | None = None,
        page_type_label: str | None = None,
    ) -> dict:
        return {
            "short_title": suggestion,
            "comprehensive_action": suggestion,
            "category": "technical",
        }

    async def extract_entities(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
    ) -> list[dict]:
        pattern = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
        counts: dict[str, int] = {}
        for match in pattern.findall(content):
            counts[match] = counts.get(match, 0) + 1
        return [
            {"name": name, "confidence": 0.95 if count > 1 else 0.7}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], -len(item[0])))
        ]


class _FakeMetricCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def labels(self, *args):
        self.calls.append(tuple(str(arg) for arg in args))
        return self

    def inc(self):
        return None


def _score_summary(report: dict) -> dict[str, float]:
    scores = report["scores"]
    return {
        "seo": scores["seo"],
        "geo": scores["geo"],
        "aeo": scores["aeo"],
        "overall": scores["overall"],
    }


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db, engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_grounded_competitor_snapshot(db) -> tuple[int, int]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=100)
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Competitive Workspace", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Example Project",
        domain_url="https://example.com",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()

    competitor = models.ProjectCompetitor(
        project_id=project.id,
        target_url="https://rival-one.example",
        normalized_domain="rival-one.example",
        display_name="Rival One",
        auto_audit_enabled=True,
    )
    db.add(competitor)
    db.flush()

    source_audit = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        geo_score=75,
        seo_score=70,
        aeo_score=72,
        full_report={"metadata": {"audit_outcome": "completed"}},
        request_id="source-audit",
        created_at=datetime.now(timezone.utc),
    )
    competitor_audit = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://rival-one.example",
        geo_score=74,
        seo_score=71,
        aeo_score=69,
        full_report={"metadata": {"audit_outcome": "completed"}},
        request_id="competitor-audit",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source_audit)
    db.add(competitor_audit)
    db.flush()

    snapshot = models.ProjectCompetitorSnapshot(
        project_id=project.id,
        competitor_id=competitor.id,
        source_audit_id=source_audit.id,
        competitor_audit_id=competitor_audit.id,
        status="succeeded",
        geo_score=74,
        seo_score=71,
        aeo_score=69,
        captured_at=datetime.now(timezone.utc),
        metadata_json={},
    )
    db.add(snapshot)
    db.commit()

    return project.id, owner.id


class MockAIClient(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": "Concise summary of the page.",
                "recommendations": ["Add schema markup", "Improve entity coverage"],
                "entities_detected": ["ExampleCorp", "Audit"],
                "seo_score": {"score": 80, "recommendations": ["Fix meta tags"]},
                "geo_score": {"score": 90, "recommendations": ["Add GEO FAQ"]},
                "aeo_score": {"score": 100, "recommendations": ["Enhance citations"]},
                "entity_data": {"ExampleCorp": {"type": "Organization"}},
                "entity_summary": {"count": 2},
            },
            "model": "mock-model-1",
            "provider": provider,
        }


class UsageAwareAIClient(MockAIClient):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        payload = await super().generate_audit(
            provider=provider,
            tier=tier,
            content=content,
            screenshot_base64=screenshot_base64,
            network_data=network_data,
            **kwargs,
        )
        payload["usage"] = {
            "prompt_tokens": 220,
            "completion_tokens": 110,
            "total_tokens": 330,
        }
        return payload

    async def generate_suggestion_detail(
        self,
        *,
        provider: str,
        tier: str,
        suggestion: str,
        market: str,
        language: str,
        page_type: str | None = None,
        page_type_label: str | None = None,
    ) -> dict:
        del tier, market, language, page_type, page_type_label
        return {
            "short_title": suggestion,
            "comprehensive_action": suggestion,
            "category": "technical",
            "provider": provider,
            "model": "gpt-5.4-mini",
            "usage": {
                "prompt_tokens": 18,
                "completion_tokens": 7,
                "total_tokens": 25,
            },
            "latency_ms": 11.5,
        }


class TrackBJudgeAIClient(MockAIClient):
    async def evaluate_track_b_claim(
        self,
        *,
        provider: str,
        tier: str,
        claim: dict,
        judge_context: dict | None,
    ) -> dict:
        del provider, tier, judge_context
        return {
            "judgment": {
                "claim_id": claim["claim_id"],
                "track": "B",
                "verdict": "flagged",
                "problem_anchor_score": 0.84,
                "action_fit_score": 0.77,
                "site_specificity_score": 0.58,
                "novel_fact_risk_score": 0.18,
                "reason_codes": ["needs_narrower_wording"],
                "problem_refs": ["claim-a"],
                "evidence_refs": ["chunk-1"],
                "explanation": "Recommendation is valid but should stay at the supported market level.",
                "suggested_rewrite": "Add a supported local-market modifier to the homepage H1.",
            },
            "provider": "openai",
            "model": "gpt-5.4",
        }


class CapturingBrandAuditAIClient(SuggestionDetailMixin):
    def __init__(self) -> None:
        self.content: str | None = None
        self.context_payload: dict | None = None
        self.screenshot_base64: str | None = None

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str | None,
        network_data: dict,
        **kwargs,
    ) -> dict:
        self.content = content
        self.screenshot_base64 = screenshot_base64
        self.context_payload = kwargs.get("context_payload")
        return {
            "analysis": {
                "summary": "Brand-only audit completed.",
                "recommendations": ["Clarify entity relationships", "Expand brand citations"],
                "entities_detected": ["Acme Logistics", "Romania"],
                "seo_score": {"score": 74, "recommendations": ["Publish brand FAQs"]},
                "geo_score": {"score": 79, "recommendations": ["Strengthen location signals"]},
                "aeo_score": {"score": 81, "recommendations": ["Add answer-ready facts"]},
                "entity_analysis": {},
                "aeo_signals": {},
                "geo_signals": {},
                "technical_signals": {},
            },
            "model": "brand-capture-model",
            "provider": provider,
        }


class CapturingScreenshotAIClient(SuggestionDetailMixin):
    def __init__(self) -> None:
        self.screenshot_base64: str | None = None

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        self.screenshot_base64 = screenshot_base64
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": "Captured screenshot payload.",
                "recommendations": ["Keep validating screenshot payloads"],
                "entities_detected": ["ExampleCorp"],
                "seo_score": {"score": 80, "recommendations": ["Fix meta tags"]},
                "geo_score": {"score": 90, "recommendations": ["Add GEO FAQ"]},
                "aeo_score": {"score": 88, "recommendations": ["Enhance citations"]},
            },
            "model": "capture-model",
            "provider": provider,
        }


class MockAIClientWithoutScores(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": "Analysis returned but no explicit score values.",
                "recommendations": ["Add scoring details to payload"],
                "entities_detected": ["ExampleCorp"],
            },
            "model": "mock-model-no-scores",
            "provider": provider,
        }


class MockAIClientWithEmptyRecommendations(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": "Recommendations are empty but module findings exist.",
                "recommendations": [],
                "entities_detected": ["ExampleCorp"],
                "seo_score": {"score": 82},
                "geo_score": {
                    "score": 78,
                    "suggestions": [
                        {
                            "impact": "high",
                            "effort": "low",
                            "action": "Add local business schema",
                            "justification": "Improves local understanding.",
                        }
                    ],
                },
                "aeo_score": {"score": 74},
            },
            "model": "mock-model-empty-recs",
            "provider": provider,
        }


class GeminiShapedAIClient(SuggestionDetailMixin):
    def __init__(self) -> None:
        self._factory = AIFactory()

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        legacy_payload = {
            "analysisSummary": "Gemini response summary.",
            "technicalSeo": {"score": 86, "recommendations": ["Fix canonical tags"]},
            "onPageSeo": {"score": 84, "recommendations": ["Improve heading hierarchy"]},
            "ux": {"score": 80, "recommendations": ["Improve content scannability"]},
            "aeoScore": {"score": 77, "recommendations": ["Expand FAQ answers"]},
        }
        return {
            "analysis": self._factory._normalize_analysis_payload(legacy_payload),
            "model": "gemini-test",
            "provider": provider,
        }


class MockHallucinationService:
    def analyze(
        self,
        *,
        source_content: str,
        analysis: dict,
        brand_truth_payload: dict | None = None,
        embedding_cache: object | None = None,
    ) -> dict:
        assert source_content
        assert analysis.get("summary")
        assert brand_truth_payload is None
        return {
            "score": 50,
            "flagged": True,
            "unsupported_sentences": ["Concise summary of the page."],
            "sentence_evaluations": [],
            "total_sentences": 1,
            "supported_sentences": 0,
        }


class TrackAwareHallucinationService:
    def analyze(
        self,
        *,
        source_content: str,
        analysis: dict,
        brand_truth_payload: dict | None = None,
        embedding_cache: object | None = None,
    ) -> dict:
        del brand_truth_payload
        assert source_content
        assert analysis.get("recommendations")
        return {
            "score": 100,
            "flagged": False,
            "unsupported_sentences": [],
            "sentence_evaluations": [],
            "total_sentences": 2,
            "supported_sentences": 2,
            "claim_verifications": [
                {
                    "claim_id": "claim-a",
                    "claim_text": "Missing FAQ schema reduces answer extraction on the homepage.",
                    "field_path": "aeo_findings[0].description",
                    "disposition": "supported",
                    "hallucination": False,
                    "track": "track_a",
                    "certainty_score": 0.91,
                    "classification_basis": ["asserts_current_state"],
                    "evidence_refs": [
                        {
                            "source_type": "scraped_content",
                            "source_key": "chunk-1",
                            "excerpt": "This is a test audit.",
                            "retrieval_score": 0.91,
                        }
                    ],
                },
                {
                    "claim_id": "claim-b",
                    "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
                    "field_path": "recommendations[0]",
                    "disposition": "supported",
                    "hallucination": False,
                    "track": "track_b",
                    "certainty_score": 0.73,
                    "classification_basis": ["contains_imperative_action"],
                    "evidence_refs": [
                        {
                            "source_type": "scraped_content",
                            "source_key": "chunk-2",
                            "excerpt": "This is a test audit.",
                            "retrieval_score": 0.73,
                        }
                    ],
                },
            ],
        }


class MixedTrackHallucinationService:
    def analyze(
        self,
        *,
        source_content: str,
        analysis: dict,
        brand_truth_payload: dict | None = None,
        embedding_cache: object | None = None,
    ) -> dict:
        del brand_truth_payload
        assert source_content
        assert analysis.get("recommendations")
        return {
            "score": 100,
            "flagged": False,
            "unsupported_sentences": [],
            "sentence_evaluations": [],
            "total_sentences": 1,
            "supported_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-mixed",
                    "claim_text": "Because the business has a Paris branch, create a Paris FAQ page.",
                    "field_path": "recommendations[0]",
                    "disposition": "supported",
                    "hallucination": False,
                    "track": "mixed",
                    "certainty_score": 0.66,
                    "classification_basis": [
                        "mixed_fact_and_prescription",
                        "contains_imperative_action",
                        "contains_unsupported_concrete_token",
                    ],
                    "evidence_refs": [
                        {
                            "source_type": "scraped_content",
                            "source_key": "chunk-9",
                            "excerpt": "This is a test audit.",
                            "retrieval_score": 0.66,
                        }
                    ],
                }
            ],
        }


class HighRiskThenCleanHallucinationService:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(
        self,
        *,
        source_content: str,
        analysis: dict,
        brand_truth_payload: dict | None = None,
        embedding_cache: object | None = None,
    ) -> dict:
        del brand_truth_payload
        assert source_content
        assert analysis.get("summary")
        self.calls += 1
        if self.calls == 1:
            return {
                "claim_verifications": [
                    {
                        "claim_id": "claim-supported",
                        "hallucination": False,
                        "severity": "none",
                        "field_label": "Summary",
                        "field_path": "summary",
                        "claim_text": "The homepage does not mention Romania in the H1.",
                        "certainty_score": 0.92,
                        "disposition": "supported",
                        "track": "track_a",
                        "evidence_refs": [
                            {
                                "source_type": "scraped_content",
                                "source_key": "chunk-1",
                                "excerpt": "Hero copy does not mention Romania.",
                                "retrieval_score": 0.92,
                            }
                        ],
                    },
                    {
                        "claim_id": "claim-unsupported",
                        "hallucination": True,
                        "severity": "high",
                        "field_label": "Summary",
                        "field_path": "summary",
                        "claim_text": "Unsupported confidence claim",
                        "certainty_score": 0.21,
                        "disposition": "flagged",
                        "track": "track_a",
                        "evidence_refs": [{"excerpt": "Visible crawl evidence"}],
                    },
                ],
                "unsupported_sentences": [],
                "sentence_evaluations": [],
                "total_sentences": 1,
                "supported_sentences": 0,
                "omitted_claims": 0,
            }
        return {
            "claim_verifications": [],
            "unsupported_sentences": [],
            "sentence_evaluations": [],
            "total_sentences": 1,
            "supported_sentences": 1,
            "omitted_claims": 0,
        }


class HighConfidenceReplayAIClient(SuggestionDetailMixin):
    def __init__(self) -> None:
        self.call_count = 0
        self.requested_tiers: list[str | None] = []
        self.context_payloads: list[dict | None] = []
        self.contents: list[str] = []
        self.screenshots: list[str | None] = []

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str | None,
        network_data: dict,
        **kwargs,
    ) -> dict:
        del tier, network_data
        self.call_count += 1
        self.requested_tiers.append(kwargs.get("requested_tier"))
        self.context_payloads.append(kwargs.get("context_payload"))
        self.contents.append(content)
        self.screenshots.append(screenshot_base64)
        accepted_claims = 2 if self.call_count == 1 else 4
        model = f"high-confidence-model-{self.call_count}"
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": f"High confidence pass {self.call_count}.",
                "recommendations": [
                    "Improve grounding for the summary.",
                    "Clarify citation support.",
                ],
                "entities_detected": ["ExampleCorp", "Audit"],
                "seo_score": {"score": 80, "recommendations": ["Fix meta tags"]},
                "geo_score": {"score": 90, "recommendations": ["Add GEO FAQ"]},
                "aeo_score": {"score": 100, "recommendations": ["Enhance citations"]},
                "entity_data": {"ExampleCorp": {"type": "Organization"}},
                "entity_summary": {"count": 2},
            },
            "model": model,
            "provider": provider,
            "debate": {
                "enabled": True,
                "profile": "high_confidence",
                "final_provider": provider,
                "final_model": model,
                "debate_confidence_score": 0.88,
                "synthesis_reasoning": "Judge removed unsupported claims after review.",
                "judge_summary": {
                    "accepted_claims": accepted_claims,
                    "downgraded_claims": 1,
                    "rejected_claims": 1,
                    "unresolved_disputes": 1,
                },
                "transcript": [
                    {
                        "role": "proposer",
                        "semantic_role": "generator",
                        "provider": provider,
                        "model": f"{model}-generator",
                        "output_summary": "Generator proposal",
                        "token_usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                            "total_tokens": 150,
                        },
                        "latency_ms": 10,
                        "routing_mode": "server_policy",
                        "route_reason": None,
                        "requested_tier": kwargs.get("requested_tier"),
                        "execution_tier": "fast",
                    },
                    {
                        "role": "challenger",
                        "semantic_role": "critic",
                        "provider": provider,
                        "model": f"{model}-critic",
                        "output_summary": "Critic review",
                        "token_usage": {
                            "prompt_tokens": 120,
                            "completion_tokens": 60,
                            "total_tokens": 180,
                        },
                        "latency_ms": 12,
                        "routing_mode": "server_policy",
                        "route_reason": None,
                        "requested_tier": kwargs.get("requested_tier"),
                        "execution_tier": "smart",
                    },
                    {
                        "role": "synthesizer",
                        "semantic_role": "judge",
                        "provider": provider,
                        "model": model,
                        "output_summary": "Judge output",
                        "token_usage": {
                            "prompt_tokens": 140,
                            "completion_tokens": 70,
                            "total_tokens": 210,
                        },
                        "latency_ms": 14,
                        "routing_mode": "server_policy",
                        "route_reason": None,
                        "requested_tier": kwargs.get("requested_tier"),
                        "execution_tier": "smart",
                    },
                ],
                "total_token_usage": {
                    "prompt_tokens": 360,
                    "completion_tokens": 180,
                    "total_tokens": 540,
                },
                "total_latency_ms": 36,
                "total_estimated_cost_usd": 0.14,
            },
        }


class HighConfidenceReplayTrackBJudgeAIClient(HighConfidenceReplayAIClient):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str | None,
        network_data: dict,
        **kwargs,
    ) -> dict:
        payload = await super().generate_audit(
            provider=provider,
            tier=tier,
            content=content,
            screenshot_base64=screenshot_base64,
            network_data=network_data,
            **kwargs,
        )
        debate = dict(payload.get("debate") or {})
        debate["mode"] = "specialist_synthesis"
        debate["provider"] = "multi-provider"
        debate["model"] = "multi-agent"
        payload["debate"] = debate
        return payload

    async def evaluate_track_b_claim(
        self,
        *,
        provider: str,
        tier: str,
        claim: dict,
        judge_context: dict | None,
    ) -> dict:
        del provider, tier, judge_context
        return {
            "judgment": {
                "claim_id": claim["claim_id"],
                "track": "B",
                "verdict": "supported",
                "problem_anchor_score": 0.86,
                "action_fit_score": 0.83,
                "site_specificity_score": 0.61,
                "novel_fact_risk_score": 0.18,
                "reason_codes": [],
                "problem_refs": ["claim-supported"],
                "evidence_refs": ["chunk-1"],
                "explanation": "Recommendation is grounded against the recovered canonical shadow inputs.",
                "suggested_rewrite": claim["claim_text"],
            },
            "provider": "openai",
            "model": "gpt-5.4",
            "usage": {"prompt_tokens": 90, "completion_tokens": 40, "total_tokens": 130},
            "latency_ms": 18,
        }


class TrackingAIClient(SuggestionDetailMixin):
    def __init__(self) -> None:
        self.called = False

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        self.called = True
        return {
            "analysis": {},
            "model": "tracking-model",
            "provider": provider,
        }


class FailingScraperService:
    async def get_page_content_and_screenshot(self, url: str) -> dict:
        return {
            "success_status": False,
            "error": {"error_code": "timeout", "message": "Firecrawl timeout"},
            "url": url,
        }


class FailingAIClient(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {"error": "Gemini rate-limited"}


class NonRetryableFailingAIClient(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {
            "error": {
                "type": "validation_error",
                "error_code": "invalid_payload",
                "error_subtype": "screenshot_payload_shape",
                "http_status": 400,
                "retryable": False,
                "request_id": "req-123",
                "payload_type": "list",
                "source": "firecrawl",
                "detail": "invalid screenshot payload",
            }
        }


class MockCompetitorDiscoveryService:
    async def discover_competitors(
        self,
        *,
        site_url: str,
        category: str,
        market: str,
        content: str | None = None,
    ) -> dict:
        assert site_url
        assert category
        assert market
        assert content
        return {
            "site": "example.com",
            "category": category,
            "market": market,
            "cached": False,
            "competitors": [
                {"name": "Rival One", "source": "SERP", "confidence_score": 0.81},
                {"name": "Rival Two", "source": "Places", "confidence_score": 0.67},
            ],
        }


class FailingCompetitorDiscoveryService:
    async def discover_competitors(
        self,
        *,
        site_url: str,
        category: str,
        market: str,
        content: str | None = None,
    ) -> dict:
        raise RuntimeError("competitor provider timeout")


class MockCompetitorBenchmarkService:
    def build_benchmark_table(self, *, target: dict, competitors: list[dict]) -> dict:
        rows = [
            {"name": target["name"], "is_target": True, "overall_score": 75.0},
            {"name": competitors[0]["name"], "is_target": False, "overall_score": 84.5},
            {"name": competitors[1]["name"], "is_target": False, "overall_score": 70.0},
        ]
        return {"rows": rows}


@pytest.mark.asyncio
async def test_perform_audit_smoke() -> None:
    scraper_service = MockScraperService()
    performance_service = MockPerformanceService()
    network_service = MockNetworkAnalysisService()
    ai_client = MockAIClient()
    hallucination_service = MockHallucinationService()

    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=scraper_service,
        performance_service=performance_service,
        network_service=network_service,
        ai_client=ai_client,
        hallucination_service=hallucination_service,
    )

    assert report["site"]["url"] == "https://example.com/"
    assert report["entities"] == ["ExampleCorp", "Audit"]
    assert report["seo"]["performance"] == 92
    assert report["metadata"]["score_source"] == "blended_v3"
    assert report["metadata"]["raw_ai_scores"] == {
        "seo": 80.0,
        "geo": 90.0,
        "aeo": 100.0,
        "overall": 89.0,
    }
    assert report["metadata"]["plan"] == "business"
    assert report["metadata"]["version"] == "2.0"
    assert report["metadata"]["intent"] == "informational"
    assert score_breakdown == pytest.approx(_score_summary(report))
    assert score_breakdown != pytest.approx(report["metadata"]["raw_ai_scores"])


@pytest.mark.asyncio
async def test_perform_audit_persists_single_call_usage_and_post_processing_transcript() -> None:
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="google",
        tier="smart",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=UsageAwareAIClient(),
        hallucination_service=None,
    )

    ai_generation = report["metadata"]["ai_generation"]
    post_processing_transcript = ai_generation["post_processing_transcript"]

    assert ai_generation["mode"] == "single"
    assert ai_generation["usage"]["total_tokens"] == 330
    assert ai_generation["post_processing_usage"]["total_tokens"] > 0
    assert len(post_processing_transcript) > 0
    assert post_processing_transcript[0]["role"] == "suggestion_detail"
    assert post_processing_transcript[0]["semantic_role"] == "post_processing"
    assert post_processing_transcript[0]["operation"] == "generate_suggestion_detail"


@pytest.mark.asyncio
async def test_perform_audit_reruns_deep_judgment_secondary_validation_with_same_requested_tier() -> (
    None
):
    scraper_service = MockScraperService()
    performance_service = MockPerformanceService()
    network_service = MockNetworkAnalysisService()
    ai_client = HighConfidenceReplayAIClient()
    hallucination_service = HighRiskThenCleanHallucinationService()

    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=scraper_service,
        performance_service=performance_service,
        network_service=network_service,
        ai_client=ai_client,
        hallucination_service=hallucination_service,
    )

    assert ai_client.requested_tiers == ["deep_judgment", "deep_judgment"]
    assert report["metadata"]["ai_generation"]["profile"] == "high_confidence"
    assert report["metadata"]["ai_generation"]["model"] == "multi-agent"
    assert report["metadata"]["ai_generation"]["judge_summary"]["accepted_claims"] == 4
    assert report["metadata"]["ai_generation"]["transcript"][0]["semantic_role"] == "generator"
    assert report["metadata"]["ai_generation"]["transcript"][2]["requested_tier"] == "deep_judgment"
    assert report["metadata"]["provider"] == "mock-provider"
    assert report["metadata"]["model"] == "high-confidence-model-2"
    assert report["metadata"]["dual_track_grounding_enabled"] is True
    assert report["metadata"]["track_b_claim_count"] >= 1
    assert report["metadata"]["fallback_reason"] == "track_b_judge_unavailable"
    assert report["metadata"]["dual_track_shadow"]["claim_source"] == "canonical_analysis_fallback"
    assert report["metadata"]["dual_track_shadow"]["track_b_judge"]["available"] is False
    assert ai_client.context_payloads[1]["unified_truth_context"]["supported_track_a_claims"] == [
        {
            "claim_id": "claim-supported",
            "claim_text": "The homepage does not mention Romania in the H1.",
            "field_path": "summary",
            "reason": "Supported Track A claim retained from grounding validation.",
            "evidence_refs": [
                {
                    "source_type": "scraped_content",
                    "source_key": "chunk-1",
                    "excerpt": "Hero copy does not mention Romania.",
                    "retrieval_score": 0.92,
                }
            ],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scrape_method", "expected_label"),
    [
        ("firecrawl", "Firecrawl Scraper"),
        ("fallback", "Fallback Scraper (httpx)"),
        # Unknown methods (SIGNAL-1047 will add cheap/escalated) must not be
        # reported as one of the two known scrapers.
        ("cheap", "Cheap Scraper"),
    ],
)
async def test_perform_audit_secondary_validation_reports_the_scraper_that_actually_ran(
    scrape_method: str, expected_label: str
) -> None:
    """SIGNAL-1046: the smart-tier correction loop used to hardcode "Playwright
    Scraper" in the context payload. There is no Playwright in the backend, and
    telling the model the page was browser-rendered when it was fetched with a
    plain GET inflates its confidence in the evidence."""
    ai_client = HighConfidenceReplayAIClient()

    await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=ScrapeMethodAwareScraperService(scrape_method),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=HighRiskThenCleanHallucinationService(),
    )

    assert len(ai_client.context_payloads) == 2, "secondary validation loop did not run"
    initial_tools = ai_client.context_payloads[0]["tools_engaged"]
    correction_tools = ai_client.context_payloads[1]["tools_engaged"]

    assert initial_tools[0] == expected_label
    assert correction_tools[0] == expected_label
    assert "Playwright Scraper" not in correction_tools
    assert correction_tools[1:] == [
        "Gemini 2.0 Flash Vision",
        "Google PSI",
        "Hallucination Service",
    ]


@pytest.mark.asyncio
async def test_perform_audit_recovers_track_b_judge_shadow_from_canonical_analysis_when_verifications_are_empty() -> (
    None
):
    ai_client = HighConfidenceReplayTrackBJudgeAIClient()

    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=HighRiskThenCleanHallucinationService(),
    )

    transcript = report["metadata"]["ai_generation"]["transcript"]
    judge_entry = next(item for item in transcript if item["role"] == "track_b_judge")

    assert report["metadata"]["dual_track_grounding_enabled"] is True
    assert report["metadata"]["fallback_reason"] is None
    assert report["metadata"]["track_b_claim_count"] >= 1
    assert report["metadata"]["dual_track_shadow"]["claim_source"] == "canonical_analysis_fallback"
    assert report["metadata"]["dual_track_shadow"]["track_b_judge"]["available"] is True
    assert report["metadata"]["dual_track_shadow"]["track_b_judge"]["llm_evaluated_claims"] >= 1
    assert judge_entry["provider"] == "openai"
    assert judge_entry["model"] == "gpt-5.4"
    assert judge_entry["requested_tier"] == "deep_judgment"
    assert judge_entry["execution_tier"] == "smart"


@pytest.mark.asyncio
async def test_perform_audit_persists_dual_track_shadow_metadata_for_deep_judgment() -> None:
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=TrackAwareHallucinationService(),
    )

    dual_track_shadow = report["metadata"]["dual_track_shadow"]

    assert dual_track_shadow["status"] == "shadow"
    assert dual_track_shadow["authoritative_mode"] == "single_track"
    assert dual_track_shadow["summary"]["track_b_claims"] == 1
    assert dual_track_shadow["summary"]["supported_claims"] >= 1
    assert dual_track_shadow["claims"][1]["evaluation_mode"] == "prescriptive_derivation_review"
    assert dual_track_shadow["claims"][1]["shadow_disposition"] == "supported"
    assert dual_track_shadow["claims"][1]["reason_codes"] == []
    assert report["metadata"]["grounding_profile"] == "dual_track_shadow_v1"
    assert report["metadata"]["dual_track_grounding_enabled"] is True
    assert report["metadata"]["track_a_claim_count"] == 1
    assert report["metadata"]["track_b_claim_count"] == 1
    assert report["metadata"]["dual_track_grounding"]["rollout_mode"] == "canonical_deep_judgment"
    assert report["metadata"]["dual_track_grounding"]["effective_execution_mode"] == "shadow"
    assert report["metadata"]["integrity_certificate_summary"]["track_b_claim_count"] == 1


@pytest.mark.asyncio
async def test_perform_audit_uses_llm_track_b_judge_in_deep_judgment_shadow_mode() -> None:
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=TrackBJudgeAIClient(),
        hallucination_service=TrackAwareHallucinationService(),
    )

    dual_track_shadow = report["metadata"]["dual_track_shadow"]

    assert dual_track_shadow["track_b_judge"]["enabled"] is True
    assert dual_track_shadow["track_b_judge"]["available"] is True
    assert dual_track_shadow["track_b_judge"]["mode"] == "llm_shadow"
    assert dual_track_shadow["track_b_judge"]["llm_evaluated_claims"] == 1
    assert dual_track_shadow["claims"][1]["judge_mode"] == "llm_shadow"
    assert dual_track_shadow["claims"][1]["judge_provider"] == "openai"
    assert dual_track_shadow["claims"][1]["judge_model"] == "gpt-5.4"
    assert dual_track_shadow["claims"][1]["shadow_disposition"] == "flagged"
    assert dual_track_shadow["claims"][1]["problem_refs"] == ["claim-a"]
    assert dual_track_shadow["claims"][1]["evidence_refs"] == ["chunk-1", "chunk-2"]
    assert dual_track_shadow["claims"][1]["suggested_rewrite"] == (
        "Add a supported local-market modifier to the homepage H1."
    )


@pytest.mark.asyncio
async def test_perform_audit_atomizes_mixed_claims_in_shadow_metadata() -> None:
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=MixedTrackHallucinationService(),
    )

    dual_track_shadow = report["metadata"]["dual_track_shadow"]

    assert dual_track_shadow["atomization"]["mixed_source_claims"] == 1
    assert dual_track_shadow["atomization"]["split_claims_created"] == 2
    assert dual_track_shadow["summary"]["track_a_claims"] == 1
    assert dual_track_shadow["summary"]["track_b_claims"] == 1
    assert dual_track_shadow["claims"][0]["source_claim_id"] == "claim-mixed"
    assert dual_track_shadow["claims"][0]["atomization_role"] == "premise"
    assert dual_track_shadow["claims"][1]["source_claim_id"] == "claim-mixed"
    assert dual_track_shadow["claims"][1]["atomization_role"] == "recommendation"
    assert dual_track_shadow["claims"][1]["premise_refs"] == ["claim-mixed-a"]
    assert "unsupported_premise_ref" in dual_track_shadow["claims"][1]["reason_codes"]
    assert dual_track_shadow["claims"][1]["shadow_disposition"] == "omitted"


@pytest.mark.asyncio
async def test_perform_audit_keeps_smart_tier_single_track_under_canonical_dual_track_runtime() -> (
    None
):
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=TrackAwareHallucinationService(),
    )

    assert report["metadata"]["dual_track_shadow"] is None
    assert report["metadata"]["grounding_profile"] == "single_track_v1"
    assert report["metadata"]["dual_track_grounding_enabled"] is False
    assert report["metadata"]["dual_track_grounding"]["rollout_mode"] == "single_track_only"
    assert report["metadata"]["dual_track_grounding"]["effective_execution_mode"] == "disabled"
    assert report["metadata"]["fallback_reason"] is None


@pytest.mark.asyncio
async def test_perform_audit_marks_dual_track_fallback_when_unified_truth_context_is_unavailable(
    monkeypatch,
) -> None:
    fallback_counter = _FakeMetricCounter()
    claim_counter = _FakeMetricCounter()
    reason_counter = _FakeMetricCounter()
    monkeypatch.setattr("audit_runner.audit_dual_track_fallback_total", fallback_counter)
    monkeypatch.setattr("audit_runner.audit_dual_track_claims_total", claim_counter)
    monkeypatch.setattr("audit_runner.audit_dual_track_reason_codes_total", reason_counter)

    original_build_context = UnifiedTruthContextService.build_context
    call_count = {"value": 0}

    def _raise_utc_error(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return original_build_context(*args, **kwargs)
        raise RuntimeError("utc unavailable")

    monkeypatch.setattr(
        "audit_runner.UnifiedTruthContextService.build_context",
        _raise_utc_error,
    )

    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=TrackAwareHallucinationService(),
    )

    assert report["metadata"]["dual_track_shadow"] is None
    assert report["metadata"]["grounding_profile"] == "single_track_fallback"
    assert report["metadata"]["dual_track_grounding_enabled"] is False
    assert report["metadata"]["fallback_reason"] == "unified_truth_context_unavailable"
    assert (
        report["metadata"]["dual_track_grounding"]["fallback_reason"]
        == "unified_truth_context_unavailable"
    )
    assert fallback_counter.calls == [("unified_truth_context_unavailable",)]
    assert claim_counter.calls == []
    assert reason_counter.calls == []


@pytest.mark.asyncio
async def test_perform_audit_brand_without_url_skips_technical_probes_and_keeps_target_context() -> (
    None
):
    scraper_mock = AsyncMock()
    performance_mock = AsyncMock()
    network_mock = AsyncMock()
    ai_client = CapturingBrandAuditAIClient()

    report, score_breakdown = await perform_audit(
        url="",
        provider="mock-provider",
        tier="starter",
        audit_target_type="brand",
        target_name="Acme Logistics",
        target_metadata={"category": "logistics", "market": "Romania", "language": "ro"},
        user_plan="business",
        scraper_service=type(
            "ScraperStub", (), {"get_page_content_and_screenshot": scraper_mock}
        )(),
        performance_service=type(
            "PerformanceStub", (), {"get_performance_metrics": performance_mock}
        )(),
        network_service=type("NetworkStub", (), {"analyze_network_protocols": network_mock})(),
        ai_client=ai_client,
        hallucination_service=None,
    )

    assert scraper_mock.await_count == 0
    assert performance_mock.await_count == 0
    assert network_mock.await_count == 0
    assert (
        ai_client.content
        == "Brand audit for: Acme Logistics. Category: logistics. Market: Romania."
    )
    assert ai_client.screenshot_base64 is None
    assert isinstance(ai_client.context_payload, dict)
    assert ai_client.context_payload["target_url"] is None
    assert ai_client.context_payload["audit_target_type"] == "brand"
    assert ai_client.context_payload["target_name"] == "Acme Logistics"
    assert ai_client.context_payload["target_metadata"] == {
        "category": "logistics",
        "market": "Romania",
        "language": "ro",
    }
    assert ai_client.context_payload["unified_truth_context"]["schema_version"] == "utc-1"
    assert (
        ai_client.context_payload["unified_truth_context"]["target_profile"]["audit_target_type"]
        == "brand"
    )
    assert (
        ai_client.context_payload["unified_truth_context"]["target_profile"]["brand_truth_payload"]
        == {}
    )
    assert report["target"]["type"] == "brand"
    assert report["target"]["name"] == "Acme Logistics"
    assert report["target"]["url"] is None
    assert report["site"]["url"] is None
    assert str(report["site"]["market"]).lower() == "romania"
    assert str(report["metadata"]["market"]).lower() == "romania"
    assert score_breakdown == pytest.approx(_score_summary(report))


@pytest.mark.asyncio
async def test_perform_audit_brand_without_url_reuses_brand_payload_in_secondary_validation() -> (
    None
):
    ai_client = HighConfidenceReplayAIClient()

    class BrandOnlyHighRiskThenCleanHallucinationService:
        def __init__(self) -> None:
            self.calls = 0

        def analyze(
            self,
            *,
            source_content: str | None,
            analysis: dict,
            brand_truth_payload: dict | None = None,
            embedding_cache: object | None = None,
        ) -> dict:
            del source_content, brand_truth_payload
            assert analysis.get("summary")
            self.calls += 1
            if self.calls == 1:
                return {
                    "claim_verifications": [
                        {
                            "claim_id": "claim-supported",
                            "hallucination": False,
                            "severity": "none",
                            "field_label": "Summary",
                            "field_path": "summary",
                            "claim_text": "Acme Logistics needs stronger evidence-backed brand facts.",
                            "certainty_score": 0.92,
                            "disposition": "supported",
                            "track": "track_a",
                            "evidence_refs": [
                                {
                                    "source_type": "brand_truth",
                                    "source_key": "brand-1",
                                    "excerpt": "Brand truth is available for Acme Logistics.",
                                    "retrieval_score": 0.92,
                                }
                            ],
                        },
                        {
                            "claim_id": "claim-unsupported",
                            "hallucination": True,
                            "severity": "high",
                            "field_label": "Recommendations",
                            "field_path": "recommendations[0]",
                            "claim_text": "Claim needs correction.",
                            "certainty_score": 0.15,
                            "disposition": "flagged",
                            "track": "track_b",
                            "reason_codes": ["insufficient_brand_grounding"],
                            "evidence_refs": [],
                        },
                    ],
                    "unsupported_sentences": ["Claim needs correction."],
                    "sentence_evaluations": [],
                    "total_sentences": 2,
                    "supported_sentences": 1,
                    "omitted_claims": 1,
                }
            return {
                "claim_verifications": [],
                "unsupported_sentences": [],
                "sentence_evaluations": [],
                "total_sentences": 1,
                "supported_sentences": 1,
                "omitted_claims": 0,
            }

    hallucination_service = BrandOnlyHighRiskThenCleanHallucinationService()

    report, _score_breakdown = await perform_audit(
        url="",
        provider="mock-provider",
        tier="smart",
        requested_tier="deep_judgment",
        audit_target_type="brand",
        target_name="Acme Logistics",
        target_metadata={"category": "logistics", "market": "Romania", "language": "ro"},
        user_plan="business",
        scraper_service=type("ScraperStub", (), {"get_page_content_and_screenshot": AsyncMock()})(),
        performance_service=type("PerformanceStub", (), {"get_performance_metrics": AsyncMock()})(),
        network_service=type("NetworkStub", (), {"analyze_network_protocols": AsyncMock()})(),
        ai_client=ai_client,
        hallucination_service=hallucination_service,
    )

    expected_content = "Brand audit for: Acme Logistics. Category: logistics. Market: Romania."
    assert ai_client.call_count == 2
    assert ai_client.contents == [expected_content, expected_content]
    assert ai_client.screenshots == [None, None]
    assert report["metadata"]["model"] == "high-confidence-model-2"
    assert report["metadata"]["dual_track_grounding_enabled"] is True
    assert report["metadata"]["track_b_claim_count"] >= 1
    assert report["metadata"]["fallback_reason"] == "track_b_judge_unavailable"
    assert report["metadata"]["dual_track_shadow"]["claim_source"] == "canonical_analysis_fallback"


@pytest.mark.asyncio
async def test_perform_audit_returns_partial_report_when_scraper_fails() -> None:
    performance_service = MockPerformanceService()
    network_service = MockNetworkAnalysisService()

    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=FailingScraperService(),
        performance_service=performance_service,
        network_service=network_service,
        ai_client=MockAIClient(),
        hallucination_service=None,
    )

    assert report["scores"]["scoring_version"] == "3.0"
    assert score_breakdown == pytest.approx(_score_summary(report))
    assert report["metadata"]["service_status"]["firecrawl"] == "disabled"
    assert report["metadata"]["service_status"]["ai_service"] == "disabled"
    assert "firecrawl" in report["metadata"]["service_errors"]
    assert "raw_ai_scores" not in report["metadata"]
    assert report["metadata"]["scores_available"] is False
    assert report["metadata"]["audit_outcome"] == "failed"


@pytest.mark.asyncio
async def test_perform_audit_raises_503_when_ai_fails() -> None:
    scraper_service = MockScraperService()
    performance_service = MockPerformanceService()
    network_service = MockNetworkAnalysisService()

    with pytest.raises(HTTPException) as exc_info:
        await perform_audit(
            url="https://example.com",
            provider="mock-provider",
            tier="starter",
            user_plan="business",
            scraper_service=scraper_service,
            performance_service=performance_service,
            network_service=network_service,
            ai_client=FailingAIClient(),
            hallucination_service=None,
        )

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_perform_audit_maps_non_retryable_ai_error_to_422(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Force INFO capture regardless of any global logging level another test left
    # behind (caplog otherwise sees nothing if the root level was raised).
    caplog.set_level(logging.INFO)
    with pytest.raises(HTTPException) as exc_info:
        await perform_audit(
            url="https://example.com",
            provider="mock-provider",
            tier="starter",
            user_plan="business",
            scraper_service=MockScraperService(),
            performance_service=MockPerformanceService(),
            network_service=MockNetworkAnalysisService(),
            ai_client=NonRetryableFailingAIClient(),
            hallucination_service=None,
        )

    assert exc_info.value.status_code == 422
    assert "subtype=screenshot_payload_shape" in str(exc_info.value.detail)
    assert "source=firecrawl" in str(exc_info.value.detail)
    assert "request_id=req-123" in caplog.text
    assert "payload_type=list" in caplog.text


@pytest.mark.asyncio
async def test_perform_audit_populates_competitors_when_discovery_succeeds() -> None:
    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=MockCompetitorDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    assert report["competitors"][0]["name"] == "Rival One"
    assert report["competitors"][0]["score"] == pytest.approx(81.0)
    assert report["competitors"][0]["source"] == "SERP estimate"
    assert report["competitors"][1]["name"] == "Rival Two"
    assert report["competitors"][1]["score"] == pytest.approx(67.0)
    assert report["competitors"][1]["source"] == "Places estimate"
    assert report["metadata"]["service_status"]["competitors"] == "ok"


@pytest.mark.asyncio
async def test_perform_audit_marks_competitors_disabled_when_external_providers_unavailable() -> (
    None
):
    class _ProviderUnavailableDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            return {
                "site": "example.com",
                "category": category,
                "market": market,
                "cached": False,
                "provider_health": "disabled",
                "provider_errors": {"places": "missing API key"},
                "competitors": [],
            }

    class _MockAIClientWithSuggestions(MockAIClient):
        async def generate_suggestion_detail(
            self,
            *,
            provider: str,
            tier: str,
            suggestion: str,
            market: str,
            language: str,
            page_type: str | None = None,
            page_type_label: str | None = None,
        ) -> dict:
            return {
                "suggestion": suggestion,
                "impact": "medium",
                "effort": "low",
                "category": "seo",
            }

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=_MockAIClientWithSuggestions(),
        hallucination_service=None,
        competitor_discovery_service=_ProviderUnavailableDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    assert report["metadata"]["service_status"]["competitors"] == "disabled"
    assert "places: missing API key" in report["metadata"]["service_errors"]["competitors"]


@pytest.mark.asyncio
async def test_perform_audit_gracefully_handles_competitor_failures() -> None:
    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=FailingCompetitorDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    assert report["competitors"] == []
    assert report["metadata"]["service_status"]["competitors"] == "degraded"
    assert "competitors" in report["metadata"]["service_errors"]


@pytest.mark.asyncio
async def test_perform_audit_logs_real_reason_for_silent_competitor_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SIGV2-1233: a bare exception (e.g. ``asyncio.TimeoutError()``) has an
    empty ``str()``, so the warning log must still carry the exception type to
    be diagnosable, and the failure must not collapse into the same shape as a
    genuine zero-competitors result.
    """

    class _SilentDiscoveryTimeout(Exception):
        """Mirrors asyncio.TimeoutError: raised with no args, str() == ""."""

    class SilentlyFailingCompetitorDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            raise _SilentDiscoveryTimeout()

    caplog.set_level(logging.WARNING, logger="audit_runner")

    failed_report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=SilentlyFailingCompetitorDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    warning_records = [
        record for record in caplog.records if "Competitor discovery failed" in record.message
    ]
    assert warning_records, "expected a 'Competitor discovery failed' warning to be logged"
    logged_message = warning_records[0].message
    assert "_SilentDiscoveryTimeout" in logged_message
    assert not logged_message.rstrip().endswith(":")

    failed_status = failed_report["metadata"]["service_status"]["competitors"]
    failed_error = failed_report["metadata"]["service_errors"]["competitors"]
    assert failed_status == "degraded"
    assert failed_error
    assert "_SilentDiscoveryTimeout" in failed_error

    class GenuinelyNoCompetitorsDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            return {
                "site": "example.com",
                "category": category,
                "market": market,
                "cached": False,
                "provider_health": "ok",
                "provider_errors": {},
                "competitors": [],
            }

    honest_zero_report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=GenuinelyNoCompetitorsDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    # Both reports show an empty competitor list, but the failure must remain
    # distinguishable from the honest "we checked, there are none" case.
    assert failed_report["competitors"] == []
    assert honest_zero_report["competitors"] == []
    assert honest_zero_report["metadata"]["service_status"]["competitors"] == "ok"
    assert "competitors" not in honest_zero_report["metadata"]["service_errors"]
    assert failed_status != honest_zero_report["metadata"]["service_status"]["competitors"]


@pytest.mark.asyncio
async def test_perform_audit_skips_locked_modules_without_external_spend(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CountingDiscoveryService:
        def __init__(self) -> None:
            self.calls = 0

        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            del site_url, category, market, content
            self.calls += 1
            return {"competitors": [{"name": "Should Not Run"}]}

    class TrackingPredictiveIntentService:
        def __init__(self) -> None:
            self.calls = 0

        def classify_query_intent(self, db, *, query: str, category: str) -> str:
            del db, query, category
            self.calls += 1
            return "transactional"

    class EntityFallbackTrackingAIClient(MockAIClientWithoutEntities):
        def __init__(self) -> None:
            self.extract_entities_calls = 0

        async def extract_entities(
            self,
            *,
            provider: str,
            tier: str,
            content: str,
        ) -> list[dict]:
            del provider, tier, content
            self.extract_entities_calls += 1
            return [{"name": "Acme Entity", "confidence": 0.95}]

    competitor_service = CountingDiscoveryService()
    predictive_intent_service = TrackingPredictiveIntentService()
    ai_client = EntityFallbackTrackingAIClient()

    caplog.set_level(logging.INFO)

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="plan_standard",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=None,
        competitor_discovery_service=competitor_service,
        predictive_intent_service=predictive_intent_service,
    )

    assert competitor_service.calls == 0
    assert predictive_intent_service.calls == 0
    assert ai_client.extract_entities_calls == 0
    assert report["competitors"] == []
    assert report["metadata"]["intent"] is None
    assert report["metadata"]["query_type"] is None
    assert report["metadata"]["service_status"]["competitors"] == "skipped_plan"
    assert report["metadata"]["service_status"]["predictive_intent"] == "skipped_plan"
    assert report["metadata"]["service_status"]["entity_enhancement"] == "skipped_plan"
    assert report["metadata"]["locked_sections"]["competitors"]["is_locked"] is True
    assert report["metadata"]["locked_sections"]["predictive_intent"]["is_locked"] is True
    assert "Skipped based on plan constraints" in caplog.text


@pytest.mark.asyncio
async def test_perform_audit_handles_scraper_retry_exhaustion_with_partial_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    scraper_service = ScraperService()
    scraper_service.breaker = CircuitBreaker(failure_threshold=10, recovery_timeout=0.01)
    scraper_service.retry_config = {"retries": 2, "base_delay": 0.0, "max_delay": 0.0}

    external_error = RuntimeError("Firecrawl transient timeout")
    fake_app = type("FakeApp", (), {})()
    fake_app.scrape = AsyncMock(side_effect=[external_error, external_error, external_error])
    scraper_service._app = fake_app
    scraper_service._app_initialized = True

    # Mock fallback scraper so it doesn't attempt real HTTP requests
    scraper_service._fallback_scrape = AsyncMock(
        return_value={
            "error": {"error_code": "connection_error", "message": "Fallback also failed in test"},
            "url": "https://example.com",
            "success_status": False,
            "scrape_method": "fallback",
        }
    )

    service_events: list[dict] = []

    def capture_service_event(*_args, **kwargs) -> None:
        service_events.append(kwargs)

    monkeypatch.setattr(scraper_module, "log_external_service_event", capture_service_event)

    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=scraper_service,
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
    )

    retry_events = [event for event in service_events if event.get("status") == "retrying"]
    error_events = [event for event in service_events if event.get("status") == "error"]

    assert fake_app.scrape.await_count == 3
    assert len(retry_events) == 2
    assert error_events

    assert report["scores"]["scoring_version"] == "3.0"
    assert score_breakdown == pytest.approx(_score_summary(report))
    assert report["metadata"]["service_status"]["firecrawl"] == "disabled"
    assert report["metadata"]["service_status"]["ai_service"] == "disabled"
    assert report["metadata"]["service_status"]["pagespeed"] in {"ok", "degraded"}
    assert report["metadata"]["service_status"]["network"] in {"ok", "degraded"}
    assert report["metadata"]["service_errors"]["firecrawl"]
    assert report["metadata"]["service_errors"]["ai_service"] == "Skipped because scraping failed."
    assert "raw_ai_scores" not in report["metadata"]


@pytest.mark.asyncio
async def test_perform_audit_normalizes_scraper_url_screenshot_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    scraper_service = ScraperService()
    scraper_service._app = type("FakeApp", (), {})()
    scraper_service._app_initialized = True
    scraper_service._app.scrape = AsyncMock(
        return_value=type(
            "Scraped",
            (),
            {
                "markdown": "# Sample",
                "screenshot": "https://example.com/fake-shot.png",
                "metadata": {"title": "Sample"},
            },
        )()
    )
    scraper_service._fetch_screenshot_url_bytes = AsyncMock(return_value=b"url-screenshot-bytes")

    ai_client = CapturingScreenshotAIClient()

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=scraper_service,
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=None,
    )

    assert report["metadata"]["service_status"]["firecrawl"] == "ok"
    assert report["metadata"]["service_status"]["ai_service"] == "ok"
    assert ai_client.screenshot_base64 == "dXJsLXNjcmVlbnNob3QtYnl0ZXM="


@pytest.mark.asyncio
async def test_perform_audit_skips_ai_when_scraper_returns_invalid_screenshot_format() -> None:
    class InvalidScreenshotScraperService:
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": False,
                "error": {
                    "error_code": "invalid_screenshot_format",
                    "message": "Screenshot payload is URL-only and cannot be normalized.",
                },
                "url": url,
            }

    ai_client = TrackingAIClient()

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=InvalidScreenshotScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=None,
    )

    assert ai_client.called is False
    assert report["metadata"]["service_status"]["firecrawl"] == "disabled"
    assert report["metadata"]["service_status"]["ai_service"] == "disabled"
    assert "invalid_screenshot_format" in report["metadata"]["service_errors"]["firecrawl"]


@pytest.mark.asyncio
async def test_perform_audit_marks_discovery_only_competitors_as_exploratory() -> None:
    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=MockCompetitorDiscoveryService(),
        competitor_benchmark_service=MockCompetitorBenchmarkService(),
    )

    assert len(report["competitors"]) == 2
    assert report["competitors"][0]["name"] == "Rival One"
    assert report["competitors"][0]["source"] == "SERP estimate"
    assert report["competitors"][0]["score"] == pytest.approx(81.0)
    assert report["competitors"][0]["rank"] == 0
    assert report["metadata"]["competitor_summary"]["total_discovered"] == 2
    assert report["metadata"]["competitor_summary"]["total_benchmarked"] == 0
    assert report["metadata"]["competitor_summary"]["mode"] == "exploratory"
    assert report["metadata"]["competitor_summary"]["confidence"] == "low"
    assert report["metadata"]["competitor_summary"]["has_score_deltas"] is False
    assert report["metadata"]["competitor_summary"]["exploratory_count"] == 2


@pytest.mark.asyncio
async def test_perform_audit_uses_project_snapshots_for_grounded_competitor_benchmarks() -> None:
    db, engine = _build_db()
    try:
        project_id, _owner_id = _seed_grounded_competitor_snapshot(db)

        report, _score_breakdown = await perform_audit(
            url="https://example.com",
            provider="mock-provider",
            tier="starter",
            user_plan="business",
            project_id=project_id,
            db=db,
            scraper_service=MockScraperService(),
            performance_service=MockPerformanceService(),
            network_service=MockNetworkAnalysisService(),
            ai_client=MockAIClient(),
            hallucination_service=None,
            competitor_discovery_service=MockCompetitorDiscoveryService(),
            competitor_benchmark_service=MockCompetitorBenchmarkService(),
        )

        assert report["metadata"]["competitor_summary"]["mode"] == "mixed"
        assert report["metadata"]["competitor_summary"]["total_benchmarked"] == 1
        assert report["metadata"]["competitor_summary"]["has_score_deltas"] is True
        assert report["metadata"]["competitor_summary"]["exploratory_count"] == 1

        benchmark_rows = report["metadata"]["competitor_summary"]["benchmark"]["rows"]
        target_row = next(row for row in benchmark_rows if row["is_target"] is True)
        competitor_row = next(row for row in benchmark_rows if row["name"] == "Rival One")

        assert target_row["rank"] == 1
        assert competitor_row["measurement_source"] == "project_snapshot"
        assert competitor_row["geo_visibility"] == 74.0
        assert competitor_row["aeo_score"] == 69.0
        assert competitor_row["entity_strength"] == 71.0
        assert competitor_row["deltas_vs_target"] == {
            "geo_visibility": -16.0,
            "aeo_score": -31.0,
            "entity_strength": -9.0,
        }
        assert report["competitors"][0]["source"] == "SERP"
        assert report["competitors"][0]["rank"] == competitor_row["rank"]
        assert report["competitors"][0]["geo_visibility"] == 74.0
    finally:
        _cleanup_db(db, engine)


@pytest.mark.asyncio
async def test_perform_audit_supports_normalized_gemini_shaped_payload() -> None:
    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="google",
        tier="fast",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=GeminiShapedAIClient(),
        hallucination_service=None,
    )

    assert report["scores"]["seo"] is not None
    assert report["scores"]["geo"] is not None
    assert report["scores"]["aeo"] is not None
    assert report["seo"]["onpage"] is not None
    assert report["geo"]["visibility_index"] is not None
    assert report["aeo"]["answerability_score"] is not None
    # This payload carries no AI recommendations. Before the deterministic
    # problem channel (SIGV2-1118) that meant no suggestions at all; now the
    # failed deterministic checks on the mock page surface as fixes, and every
    # one of them carries a stable problem_code. The assertion that matters is
    # that the LLM contributed nothing here, so nothing uncoded may appear.
    items = report["recommendations"]["items"]
    assert items, "the deterministic problem channel produced no fixes"
    assert all(item["problem_code"] for item in items)
    assert len(report["suggestions"]) == len(items)
    assert score_breakdown["seo"] > 0
    assert score_breakdown["geo"] > 0
    assert score_breakdown["aeo"] > 0


@pytest.mark.asyncio
async def test_perform_audit_derives_suggestions_when_analysis_recommendations_empty() -> None:
    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClientWithEmptyRecommendations(),
        hallucination_service=None,
    )

    assert report["suggestions"]
    assert report["suggestions"][0]["action"] == "Add local business schema"


@pytest.mark.asyncio
async def test_perform_audit_marks_report_degraded_when_analysis_has_no_score_fields() -> None:
    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClientWithoutScores(),
        hallucination_service=None,
    )

    assert report["scores"]["scoring_version"] == "3.0"
    assert score_breakdown == pytest.approx(_score_summary(report))
    assert "raw_ai_scores" not in report["metadata"]
    assert report["metadata"]["scores_available"] is False
    assert report["metadata"]["audit_outcome"] == "degraded"


def test_discovery_context_infers_category_from_domain_keywords() -> None:
    category, market = _discovery_context("https://www.atlantaheatingandcooling.com/services")

    assert category == "hvac"
    assert market == "global"


def test_discovery_context_uses_page_content_when_domain_is_generic() -> None:
    category, market = _discovery_context(
        "https://example.com",
        "Our attorneys provide legal counsel for personal injury and litigation matters.",
    )

    assert category == "law firm"
    assert market == "global"


@pytest.mark.asyncio
async def test_perform_audit_uses_explicit_category_and_market_overrides() -> None:
    captured: dict[str, str] = {}

    class CaptureDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            captured["category"] = category
            captured["market"] = market
            return {"competitors": []}

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        category="local legal",
        market="bucharest",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=CaptureDiscoveryService(),
    )

    assert captured == {"category": "local legal", "market": "bucharest"}
    assert report["site"]["market"] == "bucharest"


@pytest.mark.asyncio
async def test_perform_audit_passes_manual_category_override_to_discovery_unchanged() -> None:
    captured: dict[str, str] = {}

    class CaptureDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            captured["category"] = category
            captured["market"] = market
            return {"competitors": []}

    await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        category="Space Robotics",
        market="global",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=CaptureDiscoveryService(),
    )

    assert captured["category"] == "Space Robotics"


@pytest.mark.asyncio
async def test_perform_audit_prioritizes_explicit_language_over_content_detection() -> None:
    class LocalizedScraperService(MockScraperService):
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": True,
                "markdown_content": '<html lang="fr-FR"><head><meta property="og:locale" content="fr_FR"></head></html>',
                "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
                "metadata": {"title": "Bonjour", "locale": "fr_FR", "url": url},
            }

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        market="ro",
        language="de",
        user_plan="business",
        scraper_service=LocalizedScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
    )

    assert report["site"]["market"] == "ro"
    assert report["site"]["language"] == "de"


@pytest.mark.asyncio
async def test_perform_audit_infers_category_and_market_without_overrides() -> None:
    captured: dict[str, str] = {}

    class LegalScraperService(MockScraperService):
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": True,
                "markdown_content": "Our attorneys provide litigation and legal counsel.",
                "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
                "metadata": {
                    "title": "Personal Injury Attorneys",
                    "headings": ["Injury Law", "Litigation Services"],
                    "url": url,
                },
            }

    class CaptureDiscoveryService:
        async def discover_competitors(
            self,
            *,
            site_url: str,
            category: str,
            market: str,
            content: str | None = None,
        ) -> dict:
            captured["category"] = category
            captured["market"] = market
            return {"competitors": []}

    await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=LegalScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
        competitor_discovery_service=CaptureDiscoveryService(),
    )

    assert captured["category"] == "law firm"
    assert captured["market"] == "global"


@pytest.mark.asyncio
async def test_perform_audit_detects_market_and_language_from_content_when_missing() -> None:
    class LocaleAwareScraperService(MockScraperService):
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": True,
                "markdown_content": '<html lang="es-MX"><head><meta property="og:locale" content="es_MX"></head></html>',
                "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
                "metadata": {"title": "Hola", "locale": "es_MX", "url": url},
            }

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=LocaleAwareScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
    )

    assert report["site"]["market"] == "mx"
    assert report["site"]["language"] == "es"


@pytest.mark.asyncio
async def test_competitor_discovery_returns_empty_without_real_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENABLE_TEXTUAL_COMPETITOR_FALLBACK", raising=False)
    service = CompetitorDiscoveryService()

    result = await service.discover_competitors(
        site_url="https://example.com",
        category="law firm",
        market="global",
    )

    assert result["competitors"] == []


class MockAIClientWithoutEntities(SuggestionDetailMixin):
    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str,
        network_data: dict,
        **kwargs,
    ) -> dict:
        return {
            "analysis": {
                "url": "https://example.com",
                "summary": "Entity-light analysis.",
                "recommendations": ["Add structured entities"],
                "seo_score": {"score": 75},
                "geo_score": {"score": 70},
                "aeo_score": {"score": 80},
            },
            "model": "mock-model-no-entities",
            "provider": provider,
        }


@pytest.mark.asyncio
async def test_perform_audit_merges_request_entities_as_seed_not_replacement() -> None:
    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        entities=["  Seed Brand  ", "ExampleCorp"],
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClient(),
        hallucination_service=None,
    )

    assert report["entities"] == ["Seed Brand", "ExampleCorp", "Audit"]


@pytest.mark.asyncio
async def test_perform_audit_extracts_entities_from_content_when_ai_entities_insufficient() -> None:
    class RichContentScraperService(MockScraperService):
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": True,
                "markdown_content": (
                    "Acme Dental Clinic serves Austin. Acme Dental Clinic offers Invisalign. "
                    "Visit Acme Dental Clinic for Teeth Whitening."
                ),
                "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
                "metadata": {"title": "Acme Dental Clinic", "url": url},
            }

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=RichContentScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClientWithoutEntities(),
        hallucination_service=None,
    )

    assert "Acme Dental Clinic" in report["entities"]


@pytest.mark.asyncio
async def test_perform_audit_returns_empty_entities_when_no_signals_exist() -> None:
    class MinimalScraperService(MockScraperService):
        async def get_page_content_and_screenshot(self, url: str) -> dict:
            return {
                "success_status": True,
                "markdown_content": "all lowercase plain text without named entities",
                "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
                "metadata": {"title": "", "url": url},
            }

    report, _ = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="starter",
        user_plan="business",
        scraper_service=MinimalScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=MockAIClientWithoutEntities(),
        hallucination_service=None,
    )

    assert report["entities"] == []
