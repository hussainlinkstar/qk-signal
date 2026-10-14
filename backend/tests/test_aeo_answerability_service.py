from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.aeo_answerability_service import AEOAnswerabilityService, AnswerabilityFeatures


@pytest.mark.asyncio
async def test_score_url_contract_and_ranges(monkeypatch):
    service = AEOAnswerabilityService()

    async def mock_fetch_page_signals(url: str):
        return (
            '<html><head><script type="application/ld+json">{"@context":"https://schema.org"}</script></head></html>',
            "Wed, 29 Jan 2025 10:00:00 GMT",
        )

    async def mock_link_metrics(domain: str):
        return 12000.0, 67.0

    monkeypatch.setattr(service, "_fetch_page_signals", mock_fetch_page_signals)
    monkeypatch.setattr(service, "_fetch_link_authority_metrics", mock_link_metrics)

    result = await service.score_url("https://example.com")

    assert result["url"] == "https://example.com"
    assert result["domain"] == "example.com"
    assert set(result["raw_features"].keys()) == {
        "schema_presence",
        "backlink_count",
        "freshness_days",
        "domain_authority",
    }
    assert set(result["normalized_features"].keys()) == {
        "schema_presence",
        "backlink_count",
        "freshness",
        "domain_authority",
    }
    assert 0 <= result["score"]["value"] <= 100
    assert result["score"]["model"] == "deterministic_logistic_v1"
    assert isinstance(result["answer_failure_reasons"], list)
    assert result["primary_failure_reason"] in {None, *result["answer_failure_reasons"]}
    assert isinstance(result["readability_score"], float)
    assert isinstance(result["readability_findings"], list)
    assert isinstance(result["rewrite_suggestions"], list)
    assert len(result["factor_explanations"]) == 3
    assert all("explanation" in factor for factor in result["factor_explanations"])
    assert isinstance(result["history"], list)
    assert result["history"]
    assert set(result["history"][0].keys()) == {"timestamp", "score"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_url",
    [
        "example.com",
        "htp://bad",
        "https://exa mple.com",
        "http://127.0.0.1",
        "http://169.254.1.10",
        "http://10.1.2.3",
        "http://192.168.0.3",
        "http://",
        "ftp://example.com",
    ],
)
async def test_score_url_rejects_blocked_or_malformed_urls(raw_url: str):
    service = AEOAnswerabilityService()
    with pytest.raises(ValueError):
        await service.score_url(raw_url)


@pytest.mark.asyncio
async def test_score_url_history_uses_persisted_audits_in_chronological_order(monkeypatch):
    service = AEOAnswerabilityService()

    async def mock_fetch_page_signals(url: str):
        return ("<html></html>", None)

    async def mock_link_metrics(domain: str):
        return 2000.0, 55.0

    monkeypatch.setattr(service, "_fetch_page_signals", mock_fetch_page_signals)
    monkeypatch.setattr(service, "_fetch_link_authority_metrics", mock_link_metrics)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()

    user = models.User(
        email="answerability-history@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add_all(
        [
            models.Audit(
                user_id=user.id,
                url="https://example.com/page-a",
                geo_score=80,
                full_report={"analysis": {"aeo_score": 41}},
                created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            models.Audit(
                user_id=user.id,
                url="https://example.com/page-b",
                geo_score=81,
                full_report={"analysis": {"aeo_score": {"score": 63}}},
                created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    result = await service.score_url("https://example.com", db=db, user_id=user.id)

    assert [point["score"] for point in result["history"][:2]] == [41, 63]
    assert all(point["timestamp"] for point in result["history"])

    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize(
    "raw,normalized,score,readability,expected_reasons,expected_primary",
    [
        (
            AnswerabilityFeatures(
                schema_presence=0.0,
                backlink_count=1000.0,
                freshness_days=220.0,
                domain_authority=20.0,
            ),
            {
                "schema_presence": 0.0,
                "backlink_count": 0.2,
                "freshness": 0.3,
                "domain_authority": 0.2,
            },
            42,
            0.2,
            ["MISSING_SCHEMA", "STALE_CONTENT", "LOW_AUTHORITY", "POOR_READABILITY"],
            "MISSING_SCHEMA",
        ),
        (
            AnswerabilityFeatures(
                schema_presence=1.0,
                backlink_count=40.0,
                freshness_days=12.0,
                domain_authority=70.0,
            ),
            {
                "schema_presence": 1.0,
                "backlink_count": 0.1,
                "freshness": 0.95,
                "domain_authority": 0.7,
            },
            62,
            0.6,
            ["AMBIGUOUS_CONTENT"],
            "AMBIGUOUS_CONTENT",
        ),
        (
            AnswerabilityFeatures(
                schema_presence=0.0,
                backlink_count=5000.0,
                freshness_days=10.0,
                domain_authority=90.0,
            ),
            {
                "schema_presence": 0.0,
                "backlink_count": 0.7,
                "freshness": 0.97,
                "domain_authority": 0.9,
            },
            78,
            0.1,
            [],
            None,
        ),
    ],
)
def test_classify_answer_failure_reasons(
    raw,
    normalized,
    score,
    readability,
    expected_reasons,
    expected_primary,
):
    service = AEOAnswerabilityService()

    reasons, primary_reason = service._classify_answer_failure_reasons(
        raw=raw,
        normalized=normalized,
        score=score,
        readability_score=readability,
    )

    assert reasons == expected_reasons
    assert primary_reason == expected_primary


@pytest.mark.asyncio
async def test_extract_readability_score_high_for_simple_copy():
    service = AEOAnswerabilityService()
    html = """
    <html><body>
      <p>This paragraph answers the question directly. It uses short sentences and plain words for readers.</p>
      <p>It keeps one idea per sentence. The tone is clear and simple for quick extraction by AI systems.</p>
    </body></html>
    """

    assessment = await service._extract_readability_score(html)

    assert assessment.score >= 0.45
    assert assessment.findings


@pytest.mark.asyncio
async def test_extract_readability_score_low_for_complex_copy():
    service = AEOAnswerabilityService()
    html = """
    <html><body>
      <p>Notwithstanding multidisciplinary operationalization paradigms, stakeholders must continuously recontextualize interoperability assumptions within exceptionally overengineered transformational governance frameworks to obtain visibility.</p>
      <p>Consequentially, implementation trajectories require simultaneous synchronization of heterogeneously abstracted taxonomies, producing syntactically elongated clauses that obscure direct answers and degrade comprehension.</p>
    </body></html>
    """

    assessment = await service._extract_readability_score(html)

    assert assessment.score < 0.45
    assert assessment.rewrite_suggestions


@pytest.mark.asyncio
async def test_extract_readability_score_gateway_fallback_when_provider_unavailable(monkeypatch):
    monkeypatch.setenv("AEO_READABILITY_PROVIDER", "llm_gateway")
    monkeypatch.setenv("AEO_READABILITY_GATEWAY_URL", "https://provider.invalid/readability")
    service = AEOAnswerabilityService()

    async def failing_gateway(html: str):
        return None

    monkeypatch.setattr(service, "_extract_readability_score_from_gateway", failing_gateway)

    assessment = await service._extract_readability_score(
        "<html><body><p>This is readable content with concise wording and short sentences for users.</p></body></html>"
    )

    assert assessment.score > 0
    assert isinstance(assessment.findings, list)
