"""Tests for TASK-32 / STX-32: Brand audit pipeline, workers, scheduling, and workflows."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import models
from database import Base
from job_models import AuditJobPayload, parse_job_payload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = testing_session()
    yield session
    session.close()


def _minimal_payload(**overrides) -> dict:
    base = {
        "job_id": "test-job-1",
        "request_id": "req-1",
        "user_id": 1,
        "url": "https://example.com",
        "provider": "google",
        "tier": "fast",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_job_payload: brand audits
# ---------------------------------------------------------------------------


class TestParseJobPayloadBrand:
    def test_brand_payload_without_url_succeeds(self):
        payload = _minimal_payload(
            url="",
            audit_target_type="brand",
            target_name="Acme Corp",
        )
        result = parse_job_payload(payload)
        assert result.audit_target_type == "brand"
        assert result.target_name == "Acme Corp"
        assert result.url == ""

    def test_brand_payload_with_url_succeeds(self):
        payload = _minimal_payload(
            audit_target_type="brand",
            target_name="Acme Corp",
            target_url="https://acme.com",
        )
        result = parse_job_payload(payload)
        assert result.audit_target_type == "brand"
        assert result.target_name == "Acme Corp"
        assert result.target_url == "https://acme.com"

    def test_brand_payload_without_target_name_fails(self):
        payload = _minimal_payload(
            url="",
            audit_target_type="brand",
        )
        with pytest.raises(ValueError, match="target_name"):
            parse_job_payload(payload)

    def test_website_payload_without_url_fails(self):
        payload = _minimal_payload(url="", audit_target_type="website")
        with pytest.raises(ValueError, match="url"):
            parse_job_payload(payload)

    def test_website_payload_with_url_unchanged(self):
        payload = _minimal_payload()
        result = parse_job_payload(payload)
        assert result.audit_target_type == "website"
        assert result.url == "https://example.com"

    def test_brand_payload_preserves_target_metadata(self):
        meta = {"aliases": ["Acme", "ACME Inc"], "domains": ["acme.com"]}
        payload = _minimal_payload(
            url="",
            audit_target_type="brand",
            target_name="Acme Corp",
            target_metadata=meta,
        )
        result = parse_job_payload(payload)
        assert result.target_metadata == meta

    def test_unknown_target_type_defaults_to_website(self):
        payload = _minimal_payload(audit_target_type="unknown")
        result = parse_job_payload(payload)
        assert result.audit_target_type == "website"


# ---------------------------------------------------------------------------
# ScheduledAuditConfig: brand target fields
# ---------------------------------------------------------------------------


class TestScheduledAuditConfigBrand:
    def test_brand_config_fields(self):
        from app.schemas.scheduling import ScheduledAuditConfig

        config = ScheduledAuditConfig(
            audit_target_type="brand",
            target_name="Acme Corp",
            target_metadata={"aliases": ["Acme"]},
        )
        assert config.audit_target_type == "brand"
        assert config.target_name == "Acme Corp"
        assert config.target_metadata == {"aliases": ["Acme"]}

    def test_default_config_is_website(self):
        from app.schemas.scheduling import ScheduledAuditConfig

        config = ScheduledAuditConfig()
        assert config.audit_target_type == "website"
        assert config.target_name is None

    def test_invalid_target_type_defaults_to_website(self):
        from app.schemas.scheduling import ScheduledAuditConfig

        config = ScheduledAuditConfig(audit_target_type="invalid")
        assert config.audit_target_type == "website"


# ---------------------------------------------------------------------------
# ScheduledAuditBase: brand validation
# ---------------------------------------------------------------------------


class TestScheduledAuditBaseValidation:
    def test_brand_schedule_without_url_valid(self):
        from app.schemas.scheduling import ScheduledAuditCreate, ScheduledAuditConfig

        schedule = ScheduledAuditCreate(
            project_id=1,
            audit_params=ScheduledAuditConfig(
                audit_target_type="brand",
                target_name="Acme Corp",
            ),
        )
        assert schedule.url is None
        assert schedule.audit_params.audit_target_type == "brand"

    def test_brand_schedule_missing_target_name_fails(self):
        from app.schemas.scheduling import ScheduledAuditCreate, ScheduledAuditConfig

        with pytest.raises(Exception, match="target_name"):
            ScheduledAuditCreate(
                project_id=1,
                audit_params=ScheduledAuditConfig(audit_target_type="brand"),
            )

    def test_website_schedule_without_url_fails(self):
        from app.schemas.scheduling import ScheduledAuditCreate

        with pytest.raises(Exception, match="url"):
            ScheduledAuditCreate(project_id=1)

    def test_website_schedule_with_url_valid(self):
        from app.schemas.scheduling import ScheduledAuditCreate

        schedule = ScheduledAuditCreate(url="https://example.com", project_id=1)
        assert schedule.url == "https://example.com"

    def test_schedule_update_merge_preserves_existing_brand_target_name(self):
        from app.schemas.scheduling import (
            ScheduledAuditConfig,
            ScheduledAuditConfigUpdate,
            merge_scheduled_audit_config,
        )

        merged = merge_scheduled_audit_config(
            ScheduledAuditConfig(audit_target_type="brand", target_name="Acme Corp"),
            ScheduledAuditConfigUpdate(language="ro"),
        )

        assert merged.audit_target_type == "brand"
        assert merged.target_name == "Acme Corp"
        assert merged.language == "ro"

    def test_schedule_update_rejects_switch_to_website_without_url(self):
        from app.schemas.scheduling import (
            ScheduledAuditConfig,
            ScheduledAuditConfigUpdate,
            merge_scheduled_audit_config,
            resolve_scheduled_audit_target_contract,
        )

        merged = merge_scheduled_audit_config(
            ScheduledAuditConfig(audit_target_type="brand", target_name="Acme Corp"),
            ScheduledAuditConfigUpdate(audit_target_type="website"),
        )

        with pytest.raises(ValueError, match="url"):
            resolve_scheduled_audit_target_contract(
                url=None,
                project_id=1,
                site_id=None,
                audit_params=merged,
            )


# ---------------------------------------------------------------------------
# Workflow engine: brand audit action
# ---------------------------------------------------------------------------


class TestWorkflowEngineBrandAction:
    def _seed_workflow_context(self, db, *, credits=10):
        user = models.User(
            email="wf@example.com",
            hashed_password="x",
            role="user",
            notifications_enabled=True,
            credits=credits,
        )
        db.add(user)
        db.flush()
        sub = models.Subscription(
            user_id=user.id,
            plan_type="plan_specialist",
            status="active",
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
        )
        db.add(sub)
        workspace = models.Workspace(name="WS", owner_id=user.id)
        db.add(workspace)
        db.flush()
        project = models.Project(
            workspace_id=workspace.id, name="P1", domain_url="https://example.com", language="en"
        )
        db.add(project)
        db.flush()
        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Test",
            trigger_config={
                "event": "audit.completed",
                "metric": "seo_score",
                "operator": "lt",
                "threshold": 50,
            },
            actions_config=[{"type": "run_audit", "audit_target_type": "brand"}],
            is_active=True,
        )
        db.add(workflow)
        db.commit()
        db.refresh(user)
        db.refresh(workspace)
        db.refresh(project)
        db.refresh(workflow)
        return user, workspace, project, workflow

    def test_brand_action_requires_target_name(self, db, monkeypatch):
        from services.workflow_engine import WorkflowEngine

        _, _, _, workflow = self._seed_workflow_context(db)
        engine = WorkflowEngine(db=db)

        with pytest.raises(ValueError, match="target_name"):
            engine._run_audit_action(
                workflow=workflow,
                action_config={"audit_target_type": "brand"},
                context={},
            )

    def test_brand_action_with_target_name_builds_payload(self, db, monkeypatch):
        from services.workflow_engine import WorkflowEngine
        import services.workflow_engine as workflow_engine_module

        _, _, _, workflow = self._seed_workflow_context(db, credits=100)

        enqueued_payloads: list[AuditJobPayload] = []

        def mock_enqueue(self, *, job_key, payload):
            enqueued_payloads.append(payload)

        monkeypatch.setattr(
            workflow_engine_module,
            "resolve_audit_route",
            lambda **_kwargs: type(
                "Route",
                (),
                {
                    "provider": "google",
                    "requested_tier": "fast",
                    "execution_tier": "fast",
                    "product_label": "Fast",
                    "tier_class": "fast",
                    "feature_key": "audit.main",
                    "routing_mode": "default",
                    "preferred_provider": "google",
                    "route_reason": None,
                },
            )(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "forecast_audit_cost",
            lambda **_kwargs: type("Forecast", (), {"estimated_credits": 3})(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "serialize_cost_forecast",
            lambda forecast: {"estimated_credits": forecast.estimated_credits},
        )
        monkeypatch.setattr(WorkflowEngine, "_enqueue_audit_payload", mock_enqueue)

        engine = WorkflowEngine(db=db)
        result = engine._run_audit_action(
            workflow=workflow,
            action_config={
                "audit_target_type": "brand",
                "target_name": "Acme Corp",
                "target_metadata": {"aliases": ["Acme"]},
            },
            context={},
        )

        assert result["audit_target_type"] == "brand"
        assert result["target_name"] == "Acme Corp"
        assert len(enqueued_payloads) == 1
        assert enqueued_payloads[0].audit_target_type == "brand"
        assert enqueued_payloads[0].target_name == "Acme Corp"


# ---------------------------------------------------------------------------
# Queue worker: brand audit persistence (Audit model)
# ---------------------------------------------------------------------------


class TestBrandAuditPersistence:
    def test_brand_audit_can_have_null_site_id(self, db):
        user = models.User(
            email="test@example.com", hashed_password="x", role="user", notifications_enabled=True
        )
        db.add(user)
        db.flush()

        audit = models.Audit(
            user_id=user.id,
            site_id=None,
            audit_target_type=models.AuditTargetType.BRAND,
            target_name="Acme Corp",
            target_url=None,
            target_metadata={"aliases": ["Acme"]},
            url="",
            geo_score=75.0,
            seo_score=60.0,
            aeo_score=80.0,
            full_report={"analysis": {}},
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        assert audit.id is not None
        assert audit.site_id is None
        assert audit.audit_target_type == models.AuditTargetType.BRAND
        assert audit.target_name == "Acme Corp"

    def test_website_audit_requires_url(self, db):
        user = models.User(
            email="test2@example.com", hashed_password="x", role="user", notifications_enabled=True
        )
        db.add(user)
        db.flush()
        site = models.Site(user_id=user.id, domain="example.com", display_name="example.com")
        db.add(site)
        db.flush()

        audit = models.Audit(
            user_id=user.id,
            site_id=site.id,
            audit_target_type=models.AuditTargetType.WEBSITE,
            target_name="https://example.com",
            target_url="https://example.com",
            url="https://example.com",
            geo_score=75.0,
            seo_score=60.0,
            aeo_score=80.0,
            full_report={"analysis": {}},
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        assert audit.id is not None
        assert audit.site_id == site.id
        assert audit.audit_target_type == models.AuditTargetType.WEBSITE


# ---------------------------------------------------------------------------
# Regression: website audit flows remain unchanged
# ---------------------------------------------------------------------------


class TestWebsiteAuditRegression:
    def test_website_payload_parsing_unchanged(self):
        payload = _minimal_payload()
        result = parse_job_payload(payload)
        assert result.audit_target_type == "website"
        assert result.url == "https://example.com"
        assert result.target_name is None

    def test_website_payload_with_target_url_fallback(self):
        payload = _minimal_payload(url="", target_url="https://fallback.com")
        result = parse_job_payload(payload)
        assert result.url == "https://fallback.com"
