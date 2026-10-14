from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from main import app, get_current_user, get_db
from middleware import maintenance as maintenance_module
from routers.api_router import get_audit_record
from routers.workspace_router import list_project_audits


def test_audit_history_include_full_report_returns_canonical_shape_with_status() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="history@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="History Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="History Project",
        domain_url="https://example.com/",
        language="en",
        icp_roles=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id="cus_history",
        stripe_subscription_id="sub_history",
        plan_type="plan_specialist",
        status="active",
    )
    db.add(subscription)
    db.commit()

    legacy_report = {
        "schema_version": "1.0",
        "url": "https://example.com/",
        "analysis": {
            "seo_score": {"score": 81},
            "geo_score": {"score": 72},
            "aeo_score": {"score": 66},
            "recommendations": ["Add FAQ schema"],
            "entities_detected": ["ExampleCo"],
            "seo_checks": [
                {"name": "title_tag", "status": "pass", "passed": True},
                {"name": "meta_description", "status": "warn", "details": "Too short"},
            ],
        },
        "performance": {"performance_score": 79, "lcp_ms": 2100, "cls": 0.08},
        "network": {
            "http_version": "HTTP/2",
            "supports_http2": True,
            "supports_http3_inferred": True,
        },
        "metadata": {"plan": "fast"},
    }

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com/",
        geo_score=73,
        seo_score=81,
        aeo_score=66,
        full_report=legacy_report,
        created_at=datetime.now(timezone.utc),
        intent="transactional",
    )
    db.add(audit)
    db.commit()

    payload = list_project_audits(
        project_id=project.id,
        user=user,
        db=db,
        limit=25,
        include_full_report=True,
        audit_type=None,
    )

    assert len(payload) == 1
    first = payload[0]
    assert first["project_id"] == project.id
    assert first["site_id"] is None
    assert first["status"] == "completed"
    assert first["audit_target_type"] == "website"
    assert first["target_url"] == "https://example.com/"
    assert first["target_name"] == "https://example.com/"
    assert first["target_metadata"] == {}
    assert first["geo_score"] == 73
    assert first["seo_score"] == 81
    assert first["aeo_score"] == 66
    assert first["full_report"]["scores"]["seo"] == 81.0
    assert first["full_report"]["scores"]["geo"] == 73.0
    assert first["full_report"]["scores"]["aeo"] == 66.0
    assert first["full_report"]["scores"]["overall"] == 74.0
    assert first["full_report"]["site"]["url"] == "https://example.com/"
    assert first["full_report"]["target"] == {
        "type": "website",
        "name": "https://example.com/",
        "url": "https://example.com/",
        "metadata": {},
    }
    assert set(first["full_report"]["scores"].keys()) >= {
        "seo",
        "geo",
        "aeo",
        "overall",
        "seo_breakdown",
        "geo_breakdown",
        "aeo_breakdown",
        "scoring_version",
    }
    assert first["full_report"]["scores"]["scoring_version"] == "3.0"
    assert first["full_report"]["metadata"]["plan"] == "fast"
    assert first["full_report"]["metadata"]["current_plan"] == "plan_specialist"
    assert first["full_report"]["metadata"]["intent"] == "transactional"
    assert first["full_report"]["metadata"]["query_type"] == "decision_making"
    assert first["full_report"]["metadata"]["query_category"] == "other"
    assert first["full_report"]["metadata"]["audit_target_type"] == "website"
    assert first["full_report"]["metadata"]["target_name"] == "https://example.com/"
    assert first["full_report"]["metadata"]["target_url"] == "https://example.com/"
    assert first["full_report"]["metadata"]["target_metadata"] == {}

    detail = get_audit_record(audit_id=audit.id, user=user, db=db)
    assert detail["geo_score"] == 73.0
    assert detail["seo_score"] == 81.0
    assert detail["aeo_score"] == 66.0
    assert detail["intent"] == "transactional"
    assert detail["full_report"] == first["full_report"]

    technical_signals = first["full_report"]["metadata"]["technical_signals"]
    assert technical_signals["performance"] == {"score": 79.0, "lcp_ms": 2100, "cls": 0.08}
    assert technical_signals["network"] == {
        "http_version": "HTTP/2",
        "supports_http2": True,
        "supports_http3": True,
        "supports_http3_inferred": True,
    }
    assert technical_signals["seo_audit_checks"] == [
        {"name": "title_tag", "status": "pass", "passed": True, "details": None},
        {"name": "meta_description", "status": "warn", "passed": None, "details": "Too short"},
    ]

    db.refresh(audit)
    assert "site" not in audit.full_report
    assert audit.full_report["metadata"]["plan"] == "fast"

    db.close()


def test_audit_details_full_report_preserves_legacy_technical_signals() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="detail@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit = models.Audit(
        user_id=user.id,
        url="https://detail.example.com/",
        geo_score=61,
        seo_score=70,
        aeo_score=58,
        full_report={
            "analysis": {"seo_score": 70, "geo_score": 61, "aeo_score": 58},
            "performance": {"performance_score": 67, "lcp_ms": 3300, "cls": 0.19},
            "network": {
                "http_version": "HTTP/1.1",
                "supports_http2": False,
                "supports_http3": False,
            },
            "seo_audit_checks": [{"name": "canonical", "status": "fail", "passed": False}],
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    original_get_maintenance_state = maintenance_module._get_maintenance_state
    maintenance_module._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }

    client = TestClient(app)
    response = client.get(f"/api/v1/audits/{audit.id}")

    assert response.status_code == 200
    payload = response.json()
    technical_signals = payload["full_report"]["metadata"]["technical_signals"]
    assert payload["full_report"]["metadata"]["plan"] == "plan_starter"
    assert payload["full_report"]["metadata"]["current_plan"] == "plan_starter"
    assert technical_signals["performance"]["lcp_ms"] == 3300
    assert technical_signals["performance"]["cls"] == 0.19
    assert technical_signals["network"]["http_version"] == "HTTP/1.1"
    assert technical_signals["seo_audit_checks"] == [
        {"name": "canonical", "status": "fail", "passed": False, "details": None}
    ]

    maintenance_module._get_maintenance_state = original_get_maintenance_state
    app.dependency_overrides.clear()
    db.close()


def test_audit_history_sanitizes_premium_sections_after_plan_downgrade() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="downgrade@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Downgrade Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Downgrade Project",
        domain_url="https://example.com/",
        language="en",
        icp_roles=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id="cus_downgrade",
        stripe_subscription_id="sub_downgrade",
        plan_type="plan_standard",
        status="active",
    )
    db.add(subscription)
    db.commit()

    premium_report = {
        "schema_version": "2026-03-09",
        "target": {
            "type": "website",
            "name": "https://example.com/",
            "url": "https://example.com/",
            "metadata": {},
        },
        "site": {"url": "https://example.com/", "market": "us", "language": "en"},
        "seo": {"onpage": 81, "performance": 76, "indexing": 79, "eeat_trust": 88},
        "geo": {"visibility_index": 74, "citation_share": 52, "brand_anchor": 61},
        "aeo": {
            "answerability_score": 69,
            "extractable_pages": 8,
            "schema_health": {"score": 82, "detected_schema_types": ["Organization"]},
            "schema_coverage": {"coverage_percent": 84, "coverage_by_type": {"Organization": 1.0}},
        },
        "narrative": {
            "executive_summary": {
                "text": "Premium executive summary",
                "source_type": "ai_synthesis",
                "confidence": "high",
                "supported_sentence_ratio": 0.9,
                "requires_review": False,
                "client_safe": True,
            },
            "strategic_intelligence_grid": [{"title": "Premium grid"}],
            "market_dominance_blueprint": {
                "text": "Premium blueprint",
                "source_type": "ai_synthesis",
                "confidence": "medium",
                "supported_sentence_ratio": 0.8,
                "requires_review": False,
                "client_safe": True,
            },
        },
        "competitive": {"summary": {"competitor_count": 1}},
        "competitors": [
            {
                "name": "Rival One",
                "score": 83,
                "source": "SERP",
                "confidence_score": 0.84,
                "geo_visibility": 72,
                "aeo_score": 68,
                "entity_strength": 70,
                "rank": 2,
            }
        ],
        "scores": {
            "seo": 81,
            "geo": 74,
            "aeo": 69,
            "overall": 75,
            "seo_breakdown": {
                "score": 81,
                "components": {"onpage": 81, "eeat_trust": 88},
                "penalties": [],
                "bonuses": [],
            },
            "geo_breakdown": {
                "score": 74,
                "components": {"visibility_index": 74},
                "penalties": [],
                "bonuses": [],
            },
            "aeo_breakdown": {
                "score": 69,
                "components": {"answerability_score": 69},
                "penalties": [],
                "bonuses": [],
            },
            "scoring_version": "3.0",
        },
        "metadata": {
            "plan": "plan_specialist",
            "intent": "transactional",
            "query_type": "decision_making",
            "competitor_summary": {
                "total_discovered": 1,
                "total_benchmarked": 1,
                "mode": "grounded",
                "benchmark": {"rows": [{"name": "Rival One"}]},
            },
            "executive_summary": "Premium executive summary",
            "strategic_intelligence_grid": [{"title": "Premium grid"}],
            "market_dominance_blueprint": "Premium blueprint",
            "integrity_certificate_summary": {"total_claims": 2},
            "dual_track_shadow": {"claims": [{"claim_id": "1"}]},
        },
        "deltas_vs_target": {"geo_visibility": -2, "aeo_score": -1, "entity_strength": -3},
        "hallucination": {"flagged": False, "claims": []},
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": True,
            "grounding_profile": "dual_track_v1",
            "summary": {
                "total_claims": 2,
                "track_a_total": 2,
                "track_a_supported": 2,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 0,
                "track_b_supported": 0,
                "track_b_flagged": 0,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [],
            "degraded": False,
            "degraded_reason": None,
        },
    }

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com/",
        geo_score=74,
        seo_score=81,
        aeo_score=69,
        full_report=premium_report,
        created_at=datetime.now(timezone.utc),
        intent="transactional",
    )
    db.add(audit)
    db.commit()

    payload = list_project_audits(
        project_id=project.id,
        user=user,
        db=db,
        limit=25,
        include_full_report=True,
        audit_type=None,
    )

    assert len(payload) == 1
    report = payload[0]["full_report"]
    assert payload[0]["site_id"] is None
    assert report["competitors"] == []
    assert report["competitive"] == {}
    assert report["deltas_vs_target"] is None
    assert report["metadata"]["competitor_summary"] == {}
    assert report["metadata"]["intent"] is None
    assert report["metadata"]["query_type"] is None
    assert report["aeo"]["schema_health"] == {}
    assert report["aeo"]["schema_coverage"] == {}
    assert report["narrative"]["executive_summary"] is None
    # Stored report used the legacy key ``strategic_intelligence_grid``; it still
    # validates via the AliasChoices shim and is surfaced under the renamed key.
    assert report["narrative"]["debate_findings"] == []
    assert report["hallucination"] is None
    assert report["integrity_certificate"] is None
    assert report["metadata"]["locked_sections"]["competitors"]["is_locked"] is True
    assert report["metadata"]["locked_sections"]["predictive_intent"]["is_locked"] is True

    detail = get_audit_record(audit_id=audit.id, user=user, db=db)
    assert detail["intent"] is None
    assert detail["full_report"]["competitors"] == []
    assert (
        detail["full_report"]["metadata"]["locked_sections"]["competitors"]["required_plan"]
        == "plan_specialist"
    )

    db.close()
