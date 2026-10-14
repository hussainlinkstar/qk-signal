from datetime import date, datetime, timedelta, timezone
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from auth.security import get_current_user_from_token
from database import Base, get_db
from middleware import maintenance as maintenance_middleware
from routers import api_router


# Fixture timestamps are anchored to "now" rather than to fixed calendar dates. They used to be
# hardcoded March 2026 datetimes, which silently expired: the remediation-history lookup uses a
# relative window (_build_remediation_category_performance, lookback_days=180), so once the
# 2026-03-09 outcome below aged past 180 days the "Historical remediation outcomes" source basis
# stopped being produced and test_strategic_insights_returns_grounded_payload began failing with
# no code change at all (green on 2026-09-04, red on 2026-09-07). Keep these relative.
_ANCHOR = datetime.now(timezone.utc) - timedelta(days=3)
_AEO_BATCH_AT = _ANCHOR
_GEO_BATCH_AT = _ANCHOR + timedelta(minutes=5)
_REMEDIATION_AT = _ANCHOR - timedelta(days=1)
_AEO_TRACKED_AT = _ANCHOR - timedelta(minutes=30)
_GEO_TRACKED_AT = _ANCHOR - timedelta(minutes=15)


@pytest.fixture
def client_with_project_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()

    user = models.User(
        email="strategic@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(
        owner_id=user.id,
        name="Acme Workspace",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Acme",
        domain_url="https://acme.example",
        target_country="Romania",
        language="en",
        icp_roles=["CMO", "Demand Gen Lead"],
        pain_points="Improve qualified pipeline. Reduce sales-cycle friction.",
        usp="Entity-led audit workflow",
        competitors_json=[{"name": "Rival One"}, {"name": "Rival Two"}],
        priority_pulse_tags=["entity authority", "buyer intent"],
        sme_profiles=["Head of SEO"],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    db.add_all(
        [
            models.TargetKeyword(project_id=project.id, keyword="revenue intelligence platform"),
            models.TargetKeyword(project_id=project.id, keyword="buyer intent software"),
        ]
    )

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://acme.example",
        target_url="https://acme.example",
        target_name="Acme",
        geo_score=61,
        seo_score=58,
        aeo_score=63,
        full_report={
            "schema_version": "2026-03-09",
            "audit_mode": "website",
            "generated_at": "2026-03-10T08:00:00Z",
            "target": {
                "type": "website",
                "name": "Acme",
                "url": "https://acme.example",
                "metadata": {},
            },
            "site": {
                "url": "https://acme.example",
                "market": "Romania",
                "language": "en",
            },
            "seo": {"onpage": 58, "performance": 49, "indexing": 55},
            "geo": {"visibility_index": 61, "citation_share": 42, "brand_anchor": 57},
            "aeo": {"answerability_score": 63, "extractable_pages": 8},
            "scores": {"seo": 58, "geo": 61, "aeo": 63, "overall": 61},
            "confidence": {
                "warnings": ["Monitoring coverage is still shallow for this project."],
            },
            "recommendations": {
                "items": [
                    {
                        "id": "aeo-schema",
                        "category": "content",
                        "title": "Expand answer blocks on commercial pages",
                        "summary": "Add structured answer sections for decision-stage questions.",
                        "action": "Add FAQ and comparison sections to key pages.",
                        "grounded_by_findings": ["aeo.no_faq_schema"],
                        "derived_from": ["analysis.answerability"],
                        "expected_score_impact": {"aeo": 12, "overall": 8},
                        "estimated_effort": "medium",
                        "confidence": "high",
                        "source_type": "deterministic",
                    }
                ]
            },
            "metadata": {
                "created_at": "2026-03-10T08:00:00Z",
                "updated_at": "2026-03-10T08:10:00Z",
                "plan": "pro",
                "version": "3.0",
                "service_status": {},
                "service_errors": {},
                "audit_outcome": "completed",
            },
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    for score_dimension, score_value in (
        ("geo", float(audit.geo_score or 0.0)),
        ("seo", float(audit.seo_score or 0.0)),
        ("aeo", float(audit.aeo_score or 0.0)),
    ):
        db.add(
            models.SignalAuditSnapshot(
                audit_id=audit.id,
                project_id=project.id,
                workspace_id=workspace.id,
                snapshot_date=date.today(),
                score_dimension=score_dimension,
                score_value=score_value,
                provider="google",
                tier_class="deep",
                routing_mode="server_policy",
            )
        )
    db.commit()

    aeo_query = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text="What is Acme and how does it work?",
        query_type="aeo",
        providers=["google"],
        is_active=True,
    )
    geo_query = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text="Acme vs Rival One",
        query_type="geo",
        providers=["google"],
        is_active=True,
    )
    db.add_all([aeo_query, geo_query])
    db.commit()

    aeo_batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic=aeo_query.query_text,
        provider="google",
        target_domain="acme.example",
        schedule_key="manual:aeo",
        status="succeeded",
        score=86,
        completed_at=_AEO_BATCH_AT,
    )
    geo_batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic=geo_query.query_text,
        provider="google",
        target_domain="acme.example",
        schedule_key="manual:geo",
        status="succeeded",
        score=54,
        completed_at=_GEO_BATCH_AT,
    )
    db.add_all([aeo_batch, geo_batch])
    db.commit()
    db.refresh(aeo_batch)
    db.refresh(geo_batch)

    aeo_run = models.VisibilityRun(
        batch_id=aeo_batch.id,
        topic=aeo_query.query_text,
        provider="google",
        target_domain="acme.example",
        prompt_template="manual",
        prompt=aeo_query.query_text,
        raw_response={},
        parsed_citations=[],
        valid_citations=[{"domain": "acme.example"}],
        score=86,
        status="succeeded",
        completed_at=_AEO_BATCH_AT,
    )
    geo_run = models.VisibilityRun(
        batch_id=geo_batch.id,
        topic=geo_query.query_text,
        provider="google",
        target_domain="acme.example",
        prompt_template="manual",
        prompt=geo_query.query_text,
        raw_response={},
        parsed_citations=[],
        valid_citations=[],
        score=54,
        status="succeeded",
        completed_at=_GEO_BATCH_AT,
    )
    db.add_all([aeo_run, geo_run])
    db.commit()
    db.refresh(aeo_run)

    db.add_all(
        [
            models.SignalCitationEvent(
                visibility_run_batch_id=aeo_batch.id,
                visibility_run_id=aeo_run.id,
                project_id=project.id,
                snapshot_date=date.today(),
                provider="google",
                query_hash="q1",
                domain_cited="acme.example",
                citation_present=True,
                answer_changed=False,
                citations_hash="stable-hash",
                text_similarity_score=0.97,
            ),
            models.SignalRemediationOutcome(
                project_id=project.id,
                recommendation_category="content",
                completed_at=_REMEDIATION_AT,
                before_score_geo=52,
                after_score_geo=60,
                score_delta_geo=8,
                before_score_aeo=55,
                after_score_aeo=63,
                score_delta_aeo=8,
            ),
            models.AeoQueryTrackerEntry(
                user_id=user.id,
                context_key="acme.example",
                query="How does Acme help CMOs reduce pipeline friction?",
                citation_hits=2,
                tracked_at=_AEO_TRACKED_AT,
            ),
            models.GeoPromptTrackerEntry(
                user_id=user.id,
                context_key="acme.example",
                prompt="Most trusted buyer intent software providers",
                citation_hits=0,
                tracked_at=_GEO_TRACKED_AT,
            ),
        ]
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    maintenance_middleware._get_maintenance_state = lambda: {
        "active": False,
        "message": "The system is currently undergoing maintenance.",
        "allowed_ips": [],
    }
    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[api_router.get_db] = override_get_db
    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user
    main.app.dependency_overrides[api_router.get_current_user] = override_get_current_user
    main.app.dependency_overrides[get_current_user_from_token] = override_get_current_user

    client = TestClient(main.app)
    try:
        yield client, project, audit
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_strategic_insights_returns_grounded_payload(client_with_project_context):
    client, project, audit = client_with_project_context

    response = client.post(
        "/api/v1/ai/strategic-insights",
        json={"audit_id": audit.id, "project_id": project.id},
    )

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    payload = response.json()
    content = json.loads(payload["content"])

    assert content["audit_id"] == audit.id
    assert content["project_id"] == project.id
    assert any(
        source["label"] == "Project visibility monitoring" and source["measured"] is True
        for source in content["grounding_sources"]
    )
    assert any(
        source["label"] == "Signal warehouse intelligence" and source["measured"] is True
        for source in content["grounding_sources"]
    )
    assert any(
        idea["text"] == "What is Acme and how does it work?" and idea["label"] == "measured"
        for idea in content["aeo_query_ideas"]
    )
    assert any(
        idea["text"] == "How does Acme help CMOs reduce pipeline friction?"
        and idea["label"] == "hypothesis"
        for idea in content["aeo_query_ideas"]
    )
    assert any(
        idea["text"] == "Most trusted buyer intent software providers"
        and idea["label"] == "hypothesis"
        for idea in content["geo_prompt_ideas"]
    )
    assert content["priority_roadmap"][0]["confidence"] in {"high", "medium"}
    assert content["priority_roadmap"][0]["label"] == "inferred"
    assert content["priority_roadmap"][0]["source_basis"]
    assert "signal_intelligence" in content
    assert content["signal_intelligence"]["available"] is True
    assert any(
        basis == "Historical remediation outcomes"
        for basis in content["priority_roadmap"][0]["source_basis"]
    )


def test_strategic_insights_rejects_mismatched_project_context(client_with_project_context):
    client, _project, audit = client_with_project_context

    response = client.post(
        "/api/v1/ai/strategic-insights",
        json={"audit_id": audit.id, "project_id": 9999},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found."}
