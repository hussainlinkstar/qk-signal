from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.benchmark_engine import BenchmarkEngine
from services.unified_truth_context_service import UnifiedTruthContextService


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


def _seed_project_bundle(
    db,
    *,
    email: str,
    workspace_name: str,
    project_name: str,
    domain: str,
    geo_score: float,
    seo_score: float,
    aeo_score: float,
) -> tuple[models.User, models.Workspace, models.Project, models.Audit]:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{email}",
            stripe_subscription_id=f"sub_{email}",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name=workspace_name, owner_id=user.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name=project_name,
        domain_url=f"https://{domain}",
    )
    db.add(project)
    db.flush()

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=project.domain_url,
        geo_score=geo_score,
        seo_score=seo_score,
        aeo_score=aeo_score,
        query_category="saas",
        full_report={"metadata": {"provider": "google", "tier_class": "deep"}},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.flush()

    for score_dimension, score_value in (
        ("geo", geo_score),
        ("seo", seo_score),
        ("aeo", aeo_score),
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
    db.refresh(project)
    db.refresh(audit)
    return user, workspace, project, audit


def test_unified_truth_context_service_embeds_signal_warehouse_insights() -> None:
    db, engine = _build_db()
    try:
        _user, workspace, project, _audit = _seed_project_bundle(
            db,
            email="owner@example.com",
            workspace_name="Primary Workspace",
            project_name="Primary Project",
            domain="primary.example",
            geo_score=74.0,
            seo_score=68.0,
            aeo_score=72.0,
        )

        for workspace_index in range(3):
            for project_index in range(10):
                _seed_project_bundle(
                    db,
                    email=f"cohort-{workspace_index}-{project_index}@example.com",
                    workspace_name=f"Cohort Workspace {workspace_index}-{project_index}",
                    project_name=f"Cohort Project {workspace_index}-{project_index}",
                    domain=f"cohort-{workspace_index}-{project_index}.example",
                    geo_score=50.0 + project_index + workspace_index,
                    seo_score=52.0 + project_index + workspace_index,
                    aeo_score=48.0 + project_index + workspace_index,
                )

        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="best ai visibility platform",
            provider="google",
            target_domain="primary.example",
            schedule_key="manual",
            status="succeeded",
            score=88.0,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        run = models.VisibilityRun(
            batch_id=batch.id,
            topic=batch.topic,
            provider=batch.provider,
            target_domain=batch.target_domain,
            prompt_template="manual",
            prompt=batch.topic,
            raw_response={"text": "Primary project is cited."},
            parsed_citations=["https://primary.example/source"],
            valid_citations=["https://primary.example/source"],
            score=88.0,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        second_run = models.VisibilityRun(
            batch_id=batch.id,
            topic=batch.topic,
            provider=batch.provider,
            target_domain=batch.target_domain,
            prompt_template="manual",
            prompt=f"{batch.topic} follow-up",
            raw_response={"text": "Primary project changed citations."},
            parsed_citations=["https://primary.example/another-source"],
            valid_citations=["https://primary.example/another-source"],
            score=72.0,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(second_run)
        db.commit()
        db.refresh(second_run)

        db.add_all(
            [
                models.SignalCitationEvent(
                    visibility_run_batch_id=batch.id,
                    visibility_run_id=run.id,
                    project_id=project.id,
                    snapshot_date=date.today(),
                    provider="google",
                    query_hash="hash-1",
                    domain_cited="primary.example",
                    citation_present=True,
                    answer_changed=False,
                    citations_hash="citations-1",
                    text_similarity_score=0.98,
                ),
                models.SignalCitationEvent(
                    visibility_run_batch_id=batch.id,
                    visibility_run_id=second_run.id,
                    project_id=project.id,
                    snapshot_date=date.today(),
                    provider="google",
                    query_hash="hash-2",
                    domain_cited="primary.example",
                    citation_present=True,
                    answer_changed=True,
                    citations_hash="citations-2",
                    text_similarity_score=0.75,
                ),
                models.SignalEntityObservation(
                    audit_id=_audit.id,
                    project_id=project.id,
                    snapshot_date=date.today(),
                    entity_key="entity authority",
                    entity_category="Concept",
                    relevance_score=0.92,
                    mention_frequency=3,
                ),
                models.SignalRemediationOutcome(
                    project_id=project.id,
                    recommendation_category="content",
                    completed_at=datetime.now(timezone.utc),
                    before_score_geo=55,
                    after_score_geo=64,
                    score_delta_geo=9,
                    before_score_aeo=58,
                    after_score_aeo=66,
                    score_delta_aeo=8,
                ),
            ]
        )
        db.commit()

        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.flush()

        service = UnifiedTruthContextService(db)
        signal_intelligence = service.build_project_signal_intelligence(project_id=project.id)
        truth_context = service.build_context(
            project_id=project.id,
            audit_target_type="website",
            target_name=project.name,
            target_url=project.domain_url,
            category="saas",
            market="romania",
            source_content="Primary Project improves entity authority with evidence-backed buyer intent pages.",
            target_metadata={"language": "en"},
            performance_metrics={"performance_score": 78},
            network_data={"http2": True, "http3": False},
            data_source_context={"mode": "ai_estimate_only"},
        )

        assert signal_intelligence["available"] is True
        assert signal_intelligence["benchmarks"]["geo_score"]["status"] == "ok"
        assert signal_intelligence["citation_stability"]["data_points_used"] == 2
        assert signal_intelligence["remediation_impact"]["data_points_used"] == 1
        assert (
            signal_intelligence["entity_history"]["top_entities"][0]["entity_key"]
            == "entity authority"
        )

        assert truth_context["schema_version"] == "utc-1"
        assert truth_context["target_profile"]["target_name"] == "Primary Project"
        assert truth_context["scraped_text"]["relevant_snippets"]
        assert isinstance(truth_context["domain_standards"], list)
        assert any(
            insight["source_label"] == "Signal Warehouse benchmark"
            for insight in truth_context["technical_agent_insights"]
        )
        assert any(
            insight["source_label"] == "Signal Warehouse remediation impact"
            for insight in truth_context["technical_agent_insights"]
        )
        assert any(
            insight["source_label"] == "Signal Warehouse entity history"
            for insight in truth_context["technical_agent_insights"]
        )
    finally:
        _cleanup_db(db, engine)


def test_build_supported_track_a_claims_filters_to_supported_descriptive_claims() -> None:
    db, engine = _build_db()
    try:
        service = UnifiedTruthContextService(db)

        supported_claims = service.build_supported_track_a_claims_from_hallucination(
            {
                "claim_verifications": [
                    {
                        "claim_id": "claim-1",
                        "claim_text": "The homepage does not mention Romania in the H1.",
                        "field_path": "summary",
                        "track": "track_a",
                        "disposition": "supported",
                        "hallucination": False,
                        "evidence_refs": [
                            {"source_key": "chunk-1", "excerpt": "No Romania mention"}
                        ],
                    },
                    {
                        "claim_id": "claim-2",
                        "claim_text": "Add Romania to the H1.",
                        "field_path": "recommendations[0]",
                        "track": "track_b",
                        "disposition": "supported",
                        "hallucination": False,
                        "evidence_refs": [{"source_key": "chunk-2", "excerpt": "Recommendation"}],
                    },
                    {
                        "claim_id": "claim-3",
                        "claim_text": "Schema markup is missing on the homepage.",
                        "field_path": "seo_findings[0].description",
                        "disposition": "supported",
                        "hallucination": False,
                        "evidence_refs": [{"source_key": "chunk-3", "excerpt": "Schema missing"}],
                    },
                    {
                        "claim_id": "claim-4",
                        "claim_text": "The site has a Paris branch.",
                        "field_path": "summary",
                        "track": "track_a",
                        "disposition": "flagged",
                        "hallucination": True,
                        "evidence_refs": [{"source_key": "chunk-4", "excerpt": "Unsupported"}],
                    },
                ]
            }
        )

        assert supported_claims == [
            {
                "claim_id": "claim-1",
                "claim_text": "The homepage does not mention Romania in the H1.",
                "field_path": "summary",
                "reason": "Supported Track A claim retained from grounding validation.",
                "evidence_refs": [{"source_key": "chunk-1", "excerpt": "No Romania mention"}],
            },
            {
                "claim_id": "claim-3",
                "claim_text": "Schema markup is missing on the homepage.",
                "field_path": "seo_findings[0].description",
                "reason": "Supported Track A claim retained from grounding validation.",
                "evidence_refs": [{"source_key": "chunk-3", "excerpt": "Schema missing"}],
            },
        ]
    finally:
        _cleanup_db(db, engine)
