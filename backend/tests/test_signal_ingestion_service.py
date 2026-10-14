from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
import models
from services.signal_ingestion_service import SignalIngestionService


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def _seed_project_context(db):
    user = models.User(
        email="signal-ingestion@example.com",
        hashed_password="x",
        role="user",
        credits=50,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Signal Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Signal Project",
        domain_url="https://signal.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    site = models.Site(user_id=user.id, domain="signal.example", display_name="signal.example")
    db.add(site)
    db.commit()
    db.refresh(site)
    return user, workspace, project, site


def _v3_debate_metadata(
    *,
    pipeline_type: str,
    agent_count: int,
    parallel_layers: int,
    per_agent_costs: list[dict[str, object]],
    consolidated_claim_disposition: list[dict[str, object]] | None = None,
    judge_summary: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "pipeline_type": pipeline_type,
        "agent_count": agent_count,
        "parallel_layers": parallel_layers,
        "total_estimated_cost_usd": 0.31,
        "total_latency_ms": 99,
        "debate_confidence_score": 0.9,
        "evidence_anchor": {
            "scores": {"seo": 75, "geo": 72, "aeo": 74},
            "critical_metrics": {
                "pages_crawled": 18,
                "schema_types_found": ["FAQPage", "Organization"],
            },
            "scan_timestamp": "2026-03-16T09:30:00Z",
        },
        "per_agent_costs": per_agent_costs,
        "consolidated_claim_disposition": consolidated_claim_disposition or [],
        "judge_summary": judge_summary or {},
    }


def test_ingest_audit_is_idempotent_and_records_entity_and_remediation_signals() -> None:
    db = _build_session()
    try:
        _user, _workspace, project, site = _seed_project_context(db)
        service = SignalIngestionService()

        before_audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=58,
            seo_score=61,
            aeo_score=55,
            full_report={"metadata": {"tier_class": "fast", "provider": "google"}},
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        after_audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=72,
            seo_score=75,
            aeo_score=74,
            full_report={"metadata": {"tier_class": "deep", "provider": "google"}},
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([before_audit, after_audit])
        db.commit()
        db.refresh(before_audit)
        db.refresh(after_audit)

        db.add_all(
            [
                models.SiteEntityFact(
                    site_id=site.id,
                    audit_id=after_audit.id,
                    entity_name="Signal Platform",
                    entity_key="signal_platform",
                    entity_category="Organization",
                    relevance_score=0.83,
                ),
                models.SiteEntityFact(
                    site_id=site.id,
                    audit_id=after_audit.id,
                    entity_name="Signal Platform",
                    entity_key="signal_platform",
                    entity_category="Organization",
                    relevance_score=0.91,
                ),
                models.SiteEntityFact(
                    site_id=site.id,
                    audit_id=after_audit.id,
                    entity_name="Benchmarking",
                    entity_key="benchmarking",
                    entity_category="Concept",
                    relevance_score=0.55,
                ),
            ]
        )
        db.add(
            models.ProjectTask(
                project_id=project.id,
                title="Implement citation clean-up",
                status=models.ProjectTaskStatus.DONE,
                category="technical",
                source_audit_id=before_audit.id,
                verification_audit_id=after_audit.id,
                resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        db.commit()

        inserted_first = service.ingest_audit(db=db, audit=after_audit)
        db.commit()

        inserted_second = service.ingest_audit(db=db, audit=after_audit)
        db.commit()

        assert inserted_first >= 6
        assert inserted_second == 0
        assert (
            db.query(models.SignalAuditSnapshot)
            .filter(models.SignalAuditSnapshot.audit_id == after_audit.id)
            .count()
            == 3
        )
        assert (
            db.query(models.SignalEntityObservation)
            .filter(models.SignalEntityObservation.audit_id == after_audit.id)
            .count()
            == 2
        )
        assert (
            db.query(models.SignalRemediationOutcome)
            .filter(models.SignalRemediationOutcome.audit_after_id == after_audit.id)
            .count()
            == 1
        )
    finally:
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def test_ingest_visibility_batch_is_idempotent() -> None:
    db = _build_session()
    try:
        _user, _workspace, project, _site = _seed_project_context(db)
        service = SignalIngestionService()

        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="best ai audit tool",
            provider="google",
            target_domain="signal.example",
            schedule_key="sched-1",
            status="succeeded",
            score=100.0,
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
            prompt_template="default",
            prompt="Prompt",
            raw_response={"text": "Signal is cited."},
            parsed_citations=["https://signal.example/blog"],
            valid_citations=["https://signal.example/blog"],
            score=100.0,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.refresh(batch)

        inserted_first = service.ingest_visibility_batch(db=db, batch=batch)
        db.commit()
        inserted_second = service.ingest_visibility_batch(db=db, batch=batch)
        db.commit()

        assert inserted_first == 1
        assert inserted_second == 0
        event = (
            db.query(models.SignalCitationEvent)
            .filter(models.SignalCitationEvent.visibility_run_id == run.id)
            .first()
        )
        assert event is not None
        assert bool(event.citation_present) is True
        assert event.domain_cited == "signal.example"
    finally:
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def test_backfill_all_is_replay_safe() -> None:
    db = _build_session()
    try:
        _user, _workspace, project, site = _seed_project_context(db)
        service = SignalIngestionService()

        audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=64,
            seo_score=66,
            aeo_score=62,
            full_report={"metadata": {"tier_class": "fast", "provider": "google"}},
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="signal benchmark",
            provider="google",
            target_domain="signal.example",
            schedule_key="sched-backfill",
            status="succeeded",
            score=100.0,
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
            prompt_template="default",
            prompt="Prompt",
            raw_response={"text": "Signal cited."},
            valid_citations=["https://signal.example/source"],
            parsed_citations=["https://signal.example/source"],
            score=100.0,
            status="succeeded",
        )
        db.add(run)
        db.commit()

        first = service.backfill_all(db=db, dry_run=False)
        db.commit()
        second = service.backfill_all(db=db, dry_run=False)
        db.commit()

        assert first["rows_inserted"] > 0
        assert second["rows_inserted"] == 0
    finally:
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def test_ingest_audit_records_v3_debate_signals_and_backfills_snapshots() -> None:
    db = _build_session()
    try:
        _user, workspace, project, site = _seed_project_context(db)
        service = SignalIngestionService()

        audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=72,
            seo_score=75,
            aeo_score=74,
            full_report={
                "metadata": {
                    "tier_class": "deep",
                    "provider": "anthropic",
                    "routing_mode": "server_policy",
                },
                "debate": _v3_debate_metadata(
                    pipeline_type="delta_flow",
                    agent_count=8,
                    parallel_layers=2,
                    per_agent_costs=[
                        {
                            "role": "seo_generator",
                            "provider": "google",
                            "model": "gemini-2.5-pro",
                            "latency_ms": 10,
                            "cost_usd": 0.03,
                            "tokens": {"prompt": 120, "completion": 30},
                            "layer": 1,
                        },
                        {
                            "role": "global_magistrate",
                            "provider": "openai",
                            "model": "gpt-5.4",
                            "latency_ms": 16,
                            "cost_usd": 0.08,
                            "tokens": {"prompt": 210, "completion": 60},
                            "layer": 4,
                        },
                    ],
                    consolidated_claim_disposition=[
                        {"domain": "seo", "disposition": "accepted"},
                        {"domain": "seo", "disposition": "downgraded"},
                        {"domain": "geo", "disposition": "rejected"},
                        {"domain": "aeo", "disposition": "needs_manual_review"},
                        {"domain": "aeo", "disposition": "deduplicated"},
                    ],
                    judge_summary={
                        "accepted_claims": 1,
                        "downgraded_claims": 1,
                        "rejected_claims": 1,
                        "unresolved_disputes": 1,
                    },
                ),
            },
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
                snapshot_date=datetime.now(timezone.utc).date(),
                score_dimension="geo",
                score_value=float(audit.geo_score),
                provider="anthropic",
                tier_class="deep",
                routing_mode="server_policy",
            )
        )
        db.commit()

        inserted_first = service.ingest_audit(db=db, audit=audit)
        db.commit()

        inserted_second = service.ingest_audit(db=db, audit=audit)
        db.commit()

        assert inserted_first >= 8
        assert inserted_second == 0

        snapshots = (
            db.query(models.SignalAuditSnapshot)
            .filter(models.SignalAuditSnapshot.audit_id == audit.id)
            .order_by(models.SignalAuditSnapshot.score_dimension.asc())
            .all()
        )
        assert len(snapshots) == 3
        assert all(snapshot.pipeline_type == "delta_flow" for snapshot in snapshots)
        assert all(snapshot.agent_count == 8 for snapshot in snapshots)
        assert all(snapshot.parallel_layers == 2 for snapshot in snapshots)
        assert all(snapshot.total_debate_cost_usd == 0.31 for snapshot in snapshots)
        assert all(snapshot.total_debate_latency_ms == 99 for snapshot in snapshots)
        assert snapshots[0].evidence_anchor_json["critical_metrics"]["pages_crawled"] == 18

        agent_facts = (
            db.query(models.SignalDebateAgentFact)
            .filter(models.SignalDebateAgentFact.audit_id == audit.id)
            .order_by(models.SignalDebateAgentFact.agent_role.asc())
            .all()
        )
        assert len(agent_facts) == 2
        assert agent_facts[0].pipeline_type == "delta_flow"
        assert agent_facts[0].project_id == project.id
        assert agent_facts[0].provider in {"google", "openai"}

        claim_rows = (
            db.query(models.SignalClaimDispositionFact)
            .filter(models.SignalClaimDispositionFact.audit_id == audit.id)
            .order_by(models.SignalClaimDispositionFact.domain.asc())
            .all()
        )
        assert len(claim_rows) == 3
        aeo_row = next(row for row in claim_rows if row.domain == "aeo")
        assert aeo_row.claims_generated == 2
        assert aeo_row.claims_needs_manual_review == 1
        assert aeo_row.claims_deduplicated == 1
        seo_row = next(row for row in claim_rows if row.domain == "seo")
        assert seo_row.claims_generated == 2
        assert seo_row.claims_accepted == 1
        assert seo_row.claims_downgraded == 1
        assert all(row.debate_confidence_score == 0.9 for row in claim_rows)
    finally:
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def test_backfill_all_counts_v3_audits_processed_and_preserves_v2_audits() -> None:
    db = _build_session()
    try:
        _user, _workspace, project, site = _seed_project_context(db)
        service = SignalIngestionService()

        v2_audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=64,
            seo_score=66,
            aeo_score=62,
            full_report={"metadata": {"tier_class": "fast", "provider": "google"}},
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        v3_audit = models.Audit(
            user_id=site.user_id,
            site_id=site.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://signal.example",
            geo_score=72,
            seo_score=75,
            aeo_score=74,
            full_report={
                "metadata": {"tier_class": "deep", "provider": "openai"},
                "debate": _v3_debate_metadata(
                    pipeline_type="fast_3step",
                    agent_count=3,
                    parallel_layers=0,
                    per_agent_costs=[
                        {
                            "role": "fast_proposer",
                            "provider": "google",
                            "model": "gemini-2.5-flash",
                            "latency_ms": 9,
                            "cost_usd": 0.01,
                            "tokens": {"prompt": 90, "completion": 25},
                            "layer": 1,
                        },
                        {
                            "role": "fast_critic",
                            "provider": "anthropic",
                            "model": "claude-sonnet-4-6",
                            "latency_ms": 11,
                            "cost_usd": 0.02,
                            "tokens": {"prompt": 110, "completion": 35},
                            "layer": 2,
                        },
                        {
                            "role": "fast_synthesizer",
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "latency_ms": 13,
                            "cost_usd": 0.03,
                            "tokens": {"prompt": 120, "completion": 40},
                            "layer": 3,
                        },
                    ],
                    judge_summary={
                        "accepted_claims": 3,
                        "downgraded_claims": 1,
                        "rejected_claims": 0,
                        "unresolved_disputes": 0,
                    },
                ),
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([v2_audit, v3_audit])
        db.commit()

        result = service.backfill_all(db=db, dry_run=False)
        db.commit()

        assert result["audits_processed"] == 2
        assert result["v3_audits_processed"] == 1
        assert (
            db.query(models.SignalDebateAgentFact)
            .filter(models.SignalDebateAgentFact.audit_id == v3_audit.id)
            .count()
            == 3
        )
        assert (
            db.query(models.SignalDebateAgentFact)
            .filter(models.SignalDebateAgentFact.audit_id == v2_audit.id)
            .count()
            == 0
        )
    finally:
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)
