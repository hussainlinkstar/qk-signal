from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from routers.benchmark_router import get_current_user, router as benchmark_router
from services.benchmark_engine import BenchmarkEngine


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(benchmark_router)
    return app


def _seed_user_workspace_project(
    db,
    *,
    email: str,
    plan_type: str,
    project_name: str,
    project_index: int = 0,
) -> tuple[models.User, models.Workspace, models.Project]:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{email}",
            stripe_subscription_id=f"sub_{email}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    workspace = models.Workspace(name=f"Workspace {email}", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name=project_name,
        domain_url=f"https://{project_name.lower().replace(' ', '-')}.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=project.domain_url or "https://example.com",
        geo_score=55 + project_index,
        seo_score=58 + project_index,
        aeo_score=52 + project_index,
        query_category="saas",
        full_report={"metadata": {"provider": "google", "tier_class": "deep"}},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    for score_dimension, score_value in (
        ("geo", float(audit.geo_score)),
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
    return user, workspace, project


def _build_client(
    *,
    current_plan: str = "plan_specialist",
    seed_cohort: bool = True,
) -> tuple[TestClient, FastAPI, object, models.User, models.Project]:
    app = _build_test_app()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user, _workspace, project = _seed_user_workspace_project(
        db,
        email="benchmark-owner@example.com",
        plan_type=current_plan,
        project_name="Benchmark Project",
        project_index=1,
    )

    if seed_cohort:
        for workspace_index in range(3):
            cohort_user = models.User(
                email=f"cohort-owner-{workspace_index}@example.com",
                hashed_password="x",
                role="user",
                credits=100,
                notifications_enabled=True,
            )
            db.add(cohort_user)
            db.commit()
            db.refresh(cohort_user)
            db.add(
                models.Subscription(
                    user_id=cohort_user.id,
                    stripe_customer_id=f"cus_cohort_{workspace_index}",
                    stripe_subscription_id=f"sub_cohort_{workspace_index}",
                    plan_type="plan_specialist",
                    status="active",
                )
            )
            db.commit()

            cohort_workspace = models.Workspace(
                name=f"Cohort Workspace {workspace_index}", owner_id=cohort_user.id
            )
            db.add(cohort_workspace)
            db.commit()
            db.refresh(cohort_workspace)

            for project_index in range(10):
                cohort_project = models.Project(
                    workspace_id=cohort_workspace.id,
                    name=f"Cohort Project {workspace_index}-{project_index}",
                    domain_url=f"https://cohort-{workspace_index}-{project_index}.example",
                )
                db.add(cohort_project)
                db.commit()
                db.refresh(cohort_project)

                audit = models.Audit(
                    user_id=cohort_user.id,
                    project_id=cohort_project.id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    url=cohort_project.domain_url or "https://example.com",
                    geo_score=50 + project_index + workspace_index,
                    seo_score=54 + project_index + workspace_index,
                    aeo_score=48 + project_index + workspace_index,
                    query_category="saas",
                    full_report={"metadata": {"provider": "google", "tier_class": "deep"}},
                    created_at=datetime.now(timezone.utc),
                )
                db.add(audit)
                db.commit()
                db.refresh(audit)

                db.add(
                    models.SignalAuditSnapshot(
                        audit_id=audit.id,
                        project_id=cohort_project.id,
                        workspace_id=cohort_workspace.id,
                        snapshot_date=date.today(),
                        score_dimension="geo",
                        score_value=float(audit.geo_score),
                        provider="google",
                        tier_class="deep",
                        routing_mode="server_policy",
                    )
                )
                db.commit()

    batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic="best ai visibility tools",
        provider="google",
        target_domain="benchmark-project.example",
        schedule_key="cohort-seed",
        status="succeeded",
        score=100.0,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    for index in range(4):
        run = models.VisibilityRun(
            batch_id=batch.id,
            topic=batch.topic,
            provider=batch.provider,
            target_domain=batch.target_domain,
            prompt_template="default",
            prompt="Prompt",
            raw_response={"text": f"Run {index} response"},
            valid_citations=[f"https://benchmark-project.example/source-{index}"],
            parsed_citations=[f"https://benchmark-project.example/source-{index}"],
            score=100.0,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            models.SignalCitationEvent(
                visibility_run_batch_id=batch.id,
                visibility_run_id=run.id,
                project_id=project.id,
                snapshot_date=date.today(),
                provider="google",
                query_hash=f"query-hash-{index}",
                domain_cited="benchmark-project.example",
                citation_present=True,
                answer_changed=index % 2 == 0,
                citations_hash=f"hash-{index}",
                text_similarity_score=0.95,
            )
        )
    db.commit()

    for idx in range(3):
        db.add(
            models.SignalRemediationOutcome(
                project_id=project.id,
                recommendation_category="technical",
                completed_at=datetime.now(timezone.utc),
                before_score_geo=60,
                after_score_geo=65 + idx,
                score_delta_geo=5 + idx,
                before_score_aeo=58,
                after_score_aeo=63 + idx,
                score_delta_aeo=5 + idx,
                days_to_impact=idx + 1,
            )
        )
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
    return TestClient(app), app, db, user, project


def _cleanup(app: FastAPI, db) -> None:
    app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def _seed_v3_signal_facts(db, *, project: models.Project) -> None:
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project.id)
        .order_by(models.Audit.id.desc())
        .first()
    )
    assert audit is not None

    db.add_all(
        [
            models.SignalClaimDispositionFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="delta_flow",
                domain="seo",
                claims_generated=4,
                claims_accepted=3,
                claims_downgraded=1,
                claims_rejected=0,
                claims_needs_manual_review=0,
                claims_deduplicated=0,
                debate_confidence_score=0.9,
            ),
            models.SignalClaimDispositionFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="delta_flow",
                domain="geo",
                claims_generated=4,
                claims_accepted=2,
                claims_downgraded=0,
                claims_rejected=1,
                claims_needs_manual_review=1,
                claims_deduplicated=0,
                debate_confidence_score=0.9,
            ),
            models.SignalClaimDispositionFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="smart_5step",
                domain="aeo",
                claims_generated=4,
                claims_accepted=2,
                claims_downgraded=1,
                claims_rejected=0,
                claims_needs_manual_review=0,
                claims_deduplicated=1,
                debate_confidence_score=0.82,
            ),
            models.SignalDebateAgentFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="delta_flow",
                agent_role="seo_generator",
                agent_layer=1,
                provider="google",
                model="gemini-2.5-pro",
                latency_ms=10,
                cost_usd=0.03,
                prompt_tokens=120,
                completion_tokens=30,
            ),
            models.SignalDebateAgentFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="delta_flow",
                agent_role="consolidator",
                agent_layer=3,
                provider="openai",
                model="gpt-5.4",
                latency_ms=15,
                cost_usd=0.08,
                prompt_tokens=180,
                completion_tokens=55,
            ),
            models.SignalDebateAgentFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=date.today(),
                pipeline_type="delta_flow",
                agent_role="seo_critic",
                agent_layer=2,
                provider="anthropic",
                model="claude-opus-4-6",
                latency_ms=12,
                cost_usd=0.05,
                prompt_tokens=145,
                completion_tokens=40,
            ),
        ]
    )
    db.commit()


def test_benchmark_endpoint_returns_percentile_payload() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()

        response = client.get(f"/api/v1/projects/{project.id}/benchmark")
        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == project.id
        assert payload["metric"] == "geo_score"
        assert payload["status"] == "ok"
        assert payload["percentile"] is not None
        assert payload["cohort_size"] >= 10
        assert "X-Request-ID" in response.headers
    finally:
        _cleanup(app, db)


def test_benchmark_endpoint_requires_plan_specialist_or_higher() -> None:
    client, app, db, _user, project = _build_client(current_plan="plan_standard", seed_cohort=False)
    try:
        response = client.get(f"/api/v1/projects/{project.id}/benchmark")
        assert response.status_code == 402
        assert "Specialist" in response.json()["detail"]
    finally:
        _cleanup(app, db)


def test_proprietary_score_endpoints_return_breakdowns() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        proprietary_score_count_before = db.query(models.ProprietaryScore).count()

        citation_response = client.get(f"/api/v1/projects/{project.id}/citation-stability")
        assert citation_response.status_code == 200
        citation_payload = citation_response.json()
        assert citation_payload["score_type"] == "citation_stability"
        assert "components" in citation_payload
        assert "weights" in citation_payload

        remediation_response = client.get(f"/api/v1/projects/{project.id}/remediation-impact")
        assert remediation_response.status_code == 200
        remediation_payload = remediation_response.json()
        assert remediation_payload["score_type"] == "remediation_impact"
        assert remediation_payload["data_points_used"] >= 3
        assert db.query(models.ProprietaryScore).count() == proprietary_score_count_before
    finally:
        _cleanup(app, db)


def test_v3_proprietary_score_endpoints_return_pipeline_and_provider_breakdowns() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        _seed_v3_signal_facts(db, project=project)
        proprietary_score_count_before = db.query(models.ProprietaryScore).count()

        pipeline_response = client.get(f"/api/v1/projects/{project.id}/pipeline-quality")
        assert pipeline_response.status_code == 200
        pipeline_payload = pipeline_response.json()
        assert pipeline_payload["score_type"] == "pipeline_quality"
        assert pipeline_payload["status"] == "ok"
        assert pipeline_payload["data_points_used"] == 3
        assert "delta_flow" in pipeline_payload["components"]["pipeline_breakdown"]
        assert "smart_5step" in pipeline_payload["components"]["pipeline_breakdown"]
        assert pipeline_payload["components"]["pipeline_breakdown"]["delta_flow"]["rows"] == 2

        provider_response = client.get(f"/api/v1/projects/{project.id}/provider-cost-efficiency")
        assert provider_response.status_code == 200
        provider_payload = provider_response.json()
        assert provider_payload["score_type"] == "provider_cost_efficiency"
        assert provider_payload["status"] == "ok"
        assert provider_payload["data_points_used"] == 3
        assert provider_payload["components"]["best_provider"] in {"google", "openai", "anthropic"}
        assert "google" in provider_payload["components"]["provider_breakdown"]
        assert "weights" in provider_payload

        assert db.query(models.ProprietaryScore).count() == proprietary_score_count_before
    finally:
        _cleanup(app, db)


def test_benchmark_endpoint_does_not_materialize_aggregates_on_read() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        aggregate_count_before = db.query(models.BenchmarkCohortAggregate).count()

        response = client.get(f"/api/v1/projects/{project.id}/benchmark")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "insufficient_data"
        assert db.query(models.BenchmarkCohortAggregate).count() == aggregate_count_before
    finally:
        _cleanup(app, db)


# ---------------------------------------------------------------------------
# SIGV2-1009: win-rate/authority metrics, truthful units, cohort suppression
# ---------------------------------------------------------------------------


def _seed_metric_cohort(
    db,
    *,
    values: list[float],
    metric: str = "authority_score",
    computation_version: str = "v1",
) -> list[models.Project]:
    """Create one project per value, spread across three workspaces (one owner
    each) so the cohort clears the 3-workspace diversity threshold."""
    projects: list[models.Project] = []
    workspace_count = 3
    for index, value in enumerate(values):
        ws_index = index % workspace_count
        email = f"metric-cohort-{ws_index}@example.com"
        user = db.query(models.User).filter(models.User.email == email).first()
        if user is None:
            user = models.User(email=email, hashed_password="x", role="user", credits=100)
            db.add(user)
            db.commit()
            db.refresh(user)
            db.add(
                models.Subscription(
                    user_id=user.id,
                    stripe_customer_id=f"cus_mc_{ws_index}",
                    stripe_subscription_id=f"sub_mc_{ws_index}",
                    plan_type="plan_specialist",
                    status="active",
                )
            )
            db.commit()
        workspace = db.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
        if workspace is None:
            workspace = models.Workspace(
                name=f"Metric Cohort Workspace {ws_index}", owner_id=user.id
            )
            db.add(workspace)
            db.commit()
            db.refresh(workspace)
        project = models.Project(
            workspace_id=workspace.id,
            name=f"Metric Cohort {index}",
            domain_url=f"https://metric-cohort-{index}.example",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        if metric == "authority_score":
            db.add(
                models.EntityAuthoritySnapshot(
                    project_id=project.id,
                    computed_at=datetime.now(timezone.utc),
                    authority_score=value,
                    coverage_score=value,
                    depth_score=value,
                    consistency_score=value,
                    uniqueness_score=value,
                    computation_version=computation_version,
                )
            )
        else:
            audit = models.Audit(
                user_id=user.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project.domain_url,
                query_category="saas",
                created_at=datetime.now(timezone.utc),
            )
            db.add(audit)
            db.commit()
            db.refresh(audit)
            db.add(
                models.SignalAuditSnapshot(
                    audit_id=audit.id,
                    project_id=project.id,
                    workspace_id=workspace.id,
                    snapshot_date=date.today(),
                    score_dimension=metric.replace("_score", ""),
                    score_value=value,
                    provider="google",
                )
            )
        db.commit()
        projects.append(project)
    return projects


def test_authority_metric_exposes_mean_distinct_from_percentile() -> None:
    """Hand-calculated fixture: 31 cohort observations.

    Values = 29 x 50 + 1 x 90 (cohort peers) + 1 x 90 (the queried project,
    which IS a member of its own cohort) = 29 x 50 + 2 x 90.

    mean  = (29*50 + 2*90) / 31 = 1630/31 = 52.5806 -> stored as 52.58.
    p50   : sorted values are 29 x 50 then 90, 90, so indices 0..28 are 50;
            rank = (31-1)*0.5 = 15.0 -> idx15 = 50 -> 50.0.
    The two statistics MUST differ (52.58 vs 50.0); if a future change labels
    one as the other this test fails.
    """
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        _seed_metric_cohort(db, values=[50.0] * 29 + [90.0])
        db.add(
            models.EntityAuthoritySnapshot(
                project_id=project.id,
                computed_at=datetime.now(timezone.utc),
                authority_score=90.0,
                coverage_score=90.0,
                depth_score=90.0,
                consistency_score=90.0,
                uniqueness_score=90.0,
                computation_version="v1",
            )
        )
        db.commit()
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()

        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["metric"] == "authority_score"
        assert payload["unit"] == "score"  # points out of 100, NOT a percentage
        assert payload["project_value"] == 90.0
        assert payload["cohort_mean"] == 52.58
        assert payload["percentile"] is not None
        assert payload["cohort_mean"] != payload["percentile"]
        # the cohort includes the queried project's own observation: 30 + 1
        assert payload["cohort_size"] == 31
        assert payload["source"] == "entity_authority_snapshots.authority_score"
        assert payload["period_date"] == date.today().isoformat()
        assert payload["cohort_label"] is not None
    finally:
        _cleanup(app, db)


def test_win_rate_is_reported_unavailable_not_approximated() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=win_rate")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["metric"] == "win_rate"
        assert payload["unit"] == "ratio"
        assert payload["denominator"] == "measured recommendation comparisons"
        assert payload["unavailable_reason"]
        assert payload["percentile"] is None
        assert payload["cohort_mean"] is None
        assert payload["project_value"] is None
        # no cohort rows were ever written for an unavailable metric
        assert (
            db.query(models.BenchmarkCohortAggregate)
            .filter(models.BenchmarkCohortAggregate.metric == "win_rate")
            .count()
            == 0
        )
    finally:
        _cleanup(app, db)


def test_authority_mixed_provider_versions_do_not_mix() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        # 10 v2 observations + only 9 v1 observations across 3 workspaces:
        # filtering to the admitted version leaves 9 < 10 projects -> suppressed.
        _seed_metric_cohort(db, values=[60.0] * 9, computation_version="v1")
        _seed_metric_cohort(
            db,
            values=[95.0] * 10,
            computation_version="v2",
        )
        db.add(
            models.EntityAuthoritySnapshot(
                project_id=project.id,
                computed_at=datetime.now(timezone.utc),
                authority_score=70.0,
                computation_version="v1",
            )
        )
        db.commit()
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()

        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        assert response.status_code == 200
        payload = response.json()
        # 9 v1 peers + this project = 10 projects -> not suppressed.
        assert payload["status"] == "ok"
        assert payload["cohort_size"] == 10
        # mean over 9 x 60 + 1 x 70 = 610/10 = 61.0; the ten 95.0 v2 values
        # must not have leaked in (a mixed mean would be ~76.1).
        assert payload["cohort_mean"] == 61.0
    finally:
        _cleanup(app, db)


def test_suppression_threshold_minus_one_and_exactly() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        db.add(
            models.EntityAuthoritySnapshot(
                project_id=project.id,
                computed_at=datetime.now(timezone.utc),
                authority_score=50.0,
                computation_version="v1",
            )
        )
        # 8 peers + this project = 9 < 10 -> suppressed.
        _seed_metric_cohort(db, values=[40.0] * 8)
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()

        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "insufficient_data"
        # nothing reconstructable leaks: mean, stddev and every percentile
        # are withheld on the stored aggregate AND on the response.
        assert payload["percentile"] is None
        assert payload["cohort_mean"] is None
        suppressed_rows = (
            db.query(models.BenchmarkCohortAggregate)
            .filter(models.BenchmarkCohortAggregate.suppressed.is_(True))
            .all()
        )
        assert suppressed_rows, "expected suppressed aggregate rows"
        for row in suppressed_rows:
            assert row.mean is None
            assert row.stddev is None
            assert row.p10 is None and row.p50 is None and row.p90 is None
    finally:
        _cleanup(app, db)

    # exactly threshold: 9 peers + this project = 10 -> not suppressed.
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        db.add(
            models.EntityAuthoritySnapshot(
                project_id=project.id,
                computed_at=datetime.now(timezone.utc),
                authority_score=50.0,
                computation_version="v1",
            )
        )
        _seed_metric_cohort(db, values=[40.0] * 9)
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["cohort_size"] == 10
        assert payload["cohort_mean"] is not None
    finally:
        _cleanup(app, db)


def test_missing_metric_observation_is_insufficient_not_zero() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        _seed_metric_cohort(db, values=[50.0] * 10)
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        payload = response.json()
        # this project has no authority observation of its own
        assert payload["status"] == "insufficient_data"
        assert payload["project_value"] is None
        assert payload["cohort_mean"] is None
    finally:
        _cleanup(app, db)


def test_repeated_snapshots_count_one_observation_per_project() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        _seed_metric_cohort(db, values=[50.0] * 9)
        # one tenant runs 4 authority computations in the same period;
        # only the latest may count.
        for index, score in enumerate([10.0, 20.0, 30.0, 99.0]):
            db.add(
                models.EntityAuthoritySnapshot(
                    project_id=project.id,
                    computed_at=datetime.now(timezone.utc),
                    authority_score=score,
                    computation_version="v1",
                )
            )
            db.commit()
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["cohort_size"] == 10  # not 13
        # latest value wins: mean over 9 x 50 + 1 x 99 = 549/10 = 54.9.
        assert payload["cohort_mean"] == 54.9
        assert payload["project_value"] == 99.0
    finally:
        _cleanup(app, db)


def test_out_of_range_observation_is_excluded_from_cohort() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=False
    )
    try:
        db.add(
            models.EntityAuthoritySnapshot(
                project_id=project.id,
                computed_at=datetime.now(timezone.utc),
                authority_score=50.0,
                computation_version="v1",
            )
        )
        _seed_metric_cohort(db, values=[40.0] * 8 + [150.0])
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        payload = response.json()
        # the 150.0 out-of-range value is dropped: 8 peers + self = 9 < 10.
        assert payload["status"] == "insufficient_data"
        assert payload["cohort_mean"] is None
    finally:
        _cleanup(app, db)


def test_authority_metric_respects_plan_and_project_gates() -> None:
    client, app, db, _user, project = _build_client(current_plan="plan_standard", seed_cohort=False)
    try:
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        assert response.status_code == 402
    finally:
        _cleanup(app, db)


def test_benchmark_endpoint_denies_foreign_project() -> None:
    client, app, db, _user, project = _build_client(
        current_plan="plan_specialist", seed_cohort=True
    )
    try:
        BenchmarkEngine().compute_cohort_aggregates(db=db, period_date=date.today())
        db.commit()

        foreign_user = models.User(
            email="benchmark-foreign@example.com",
            hashed_password="x",
            role="user",
            credits=100,
        )
        db.add(foreign_user)
        db.commit()
        db.refresh(foreign_user)
        db.add(
            models.Subscription(
                user_id=foreign_user.id,
                stripe_customer_id="cus_bench_foreign",
                stripe_subscription_id="sub_bench_foreign",
                plan_type="plan_specialist",
                status="active",
            )
        )
        foreign_workspace = models.Workspace(
            name="Foreign Benchmark Workspace", owner_id=foreign_user.id
        )
        db.add(foreign_workspace)
        db.commit()
        db.add(
            models.WorkspaceUser(
                workspace_id=foreign_workspace.id,
                user_id=foreign_user.id,
                role=models.WorkspaceRole.ADMIN,
            )
        )
        db.commit()

        def override_get_current_user():
            return foreign_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        response = client.get(f"/api/v1/projects/{project.id}/benchmark?metric=authority_score")
        assert response.status_code in (403, 404)
    finally:
        _cleanup(app, db)
