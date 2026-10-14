from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
import queue_worker
from app.schemas.scheduling import (
    ScheduledAuditConfig,
    ScheduledAuditConfigUpdate,
    ScheduledAuditCreate,
    ScheduledAuditUpdate,
)
from database import Base
from routers import scheduling_router


class _FakeRedisClient:
    def __init__(self) -> None:
        self.hash_writes: list[dict[str, object]] = []
        self.queue_pushes: list[dict[str, object]] = []

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hash_writes.append({"key": key, "mapping": dict(mapping)})

    async def rpush(self, key: str, value: str) -> None:
        self.queue_pushes.append({"key": key, "value": value})


@pytest.fixture()
def db_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    yield {
        "db": db,
        "SessionLocal": testing_session_local,
    }

    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded_context(db_context, monkeypatch: pytest.MonkeyPatch):
    db = db_context["db"]

    monkeypatch.setattr(scheduling_router.plan_validator, "can_schedule_audits", lambda _user: True)

    user = models.User(
        email="schedule@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Scheduled Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Scheduled Project",
        domain_url="https://project.example.com",
        language="en",
        icp_roles=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    site = models.Site(
        user_id=user.id,
        domain="example.com",
        display_name="Example Site",
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    return {
        **db_context,
        "user": user,
        "workspace": workspace,
        "project": project,
        "site": site,
    }


def _create_brand_schedule(context) -> models.ScheduledAudit:
    schedule = scheduling_router.create_scheduled_audit(
        ScheduledAuditCreate(
            project_id=context["project"].id,
            audit_params=ScheduledAuditConfig(
                audit_target_type="brand",
                target_name="Acme Corp",
                target_metadata={"aliases": ["Acme"]},
            ),
        ),
        user=context["user"],
        db=context["db"],
    )
    context["db"].refresh(schedule)
    return schedule


def _create_website_schedule(context) -> models.ScheduledAudit:
    schedule = scheduling_router.create_scheduled_audit(
        ScheduledAuditCreate(
            project_id=context["project"].id,
            url="https://example.com",
        ),
        user=context["user"],
        db=context["db"],
    )
    context["db"].refresh(schedule)
    return schedule


def test_patch_rejects_switch_to_brand_without_effective_target_name(seeded_context) -> None:
    schedule = _create_website_schedule(seeded_context)

    with pytest.raises(HTTPException) as exc_info:
        scheduling_router.update_scheduled_audit(
            schedule.id,
            ScheduledAuditUpdate(
                audit_params=ScheduledAuditConfigUpdate(audit_target_type="brand"),
            ),
            user=seeded_context["user"],
            db=seeded_context["db"],
        )

    assert exc_info.value.status_code == 400
    assert "target_name" in str(exc_info.value.detail)


def test_patch_rejects_switch_to_website_without_effective_url(seeded_context) -> None:
    schedule = _create_brand_schedule(seeded_context)

    with pytest.raises(HTTPException) as exc_info:
        scheduling_router.update_scheduled_audit(
            schedule.id,
            ScheduledAuditUpdate(
                audit_params=ScheduledAuditConfigUpdate(audit_target_type="website"),
            ),
            user=seeded_context["user"],
            db=seeded_context["db"],
        )

    assert exc_info.value.status_code == 400
    assert "url" in str(exc_info.value.detail)


def test_patch_switch_to_website_clears_brand_only_target_fields(seeded_context) -> None:
    schedule = _create_brand_schedule(seeded_context)

    updated = scheduling_router.update_scheduled_audit(
        schedule.id,
        ScheduledAuditUpdate(
            url="https://example.com",
            audit_params=ScheduledAuditConfigUpdate(audit_target_type="website"),
        ),
        user=seeded_context["user"],
        db=seeded_context["db"],
    )

    assert updated.url == "https://example.com"
    assert updated.audit_params["audit_target_type"] == "website"
    assert updated.audit_params["target_name"] is None
    assert updated.audit_params["target_metadata"] == {}


def test_patch_metadata_only_update_preserves_existing_brand_target_name(seeded_context) -> None:
    schedule = _create_brand_schedule(seeded_context)

    updated = scheduling_router.update_scheduled_audit(
        schedule.id,
        ScheduledAuditUpdate(
            audit_params=ScheduledAuditConfigUpdate(
                target_metadata={"aliases": ["Acme"], "entity_type": "company"},
            ),
        ),
        user=seeded_context["user"],
        db=seeded_context["db"],
    )

    assert updated.audit_params["audit_target_type"] == "brand"
    assert updated.audit_params["target_name"] == "Acme Corp"
    assert updated.audit_params["target_metadata"] == {
        "aliases": ["Acme"],
        "entity_type": "company",
    }


def test_worker_uses_resolved_target_contract_for_stale_website_schedule(
    seeded_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = seeded_context["db"]
    user = seeded_context["user"]
    site = seeded_context["site"]

    scheduled = models.ScheduledAudit(
        user_id=user.id,
        site_id=site.id,
        url="https://example.com",
        audit_type=models.AuditType.STANDARD,
        frequency=models.ScheduledAuditFrequency.WEEKLY,
        audit_params={
            "provider": "google",
            "tier": "fast",
            "audit_target_type": "website",
            "target_name": "Stale Brand Name",
            "target_metadata": {"aliases": ["Acme"]},
        },
        is_active=True,
        next_run_at=datetime.now() - timedelta(minutes=5),
    )
    db.add(scheduled)
    db.commit()
    db.refresh(scheduled)

    redis_client = _FakeRedisClient()
    dispatch_counter = {"calls": 0}

    def _select_due_ids() -> list[int]:
        dispatch_counter["calls"] += 1
        return [scheduled.id] if dispatch_counter["calls"] == 1 else []

    async def _noop_sleep(_seconds: float) -> None:
        queue_worker.shutdown_requested = True
        return None

    class _NaiveDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.now()

    previous_shutdown = queue_worker.shutdown_requested
    monkeypatch.setattr(queue_worker, "SessionLocal", seeded_context["SessionLocal"])
    monkeypatch.setattr(queue_worker, "_select_due_scheduled_audit_ids", _select_due_ids)
    monkeypatch.setattr(queue_worker, "datetime", _NaiveDateTime)
    monkeypatch.setattr(
        queue_worker,
        "_resolve_plan_capabilities",
        lambda _user: {"can_schedule_audits": True},
    )
    monkeypatch.setattr(queue_worker, "get_credit_engine_policy_version", lambda _db: "v2")
    monkeypatch.setattr(
        queue_worker,
        "_build_audit_cost_forecast",
        lambda **_kwargs: (1, {"estimated_total_cogs_usd": 0.12}),
    )
    monkeypatch.setattr(queue_worker, "decrement_credits_atomic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(queue_worker.asyncio, "sleep", _noop_sleep)
    monkeypatch.setattr(queue_worker, "_now_iso", lambda: "2026-03-11T00:00:00Z")
    monkeypatch.setattr(queue_worker, "uuid4", lambda: "scheduled-job-1")

    queue_worker.shutdown_requested = False
    try:
        asyncio.run(queue_worker.process_scheduled_audits(redis_client))
    finally:
        queue_worker.shutdown_requested = previous_shutdown

    db.expire_all()
    refreshed_schedule = (
        db.query(models.ScheduledAudit).filter(models.ScheduledAudit.id == scheduled.id).first()
    )
    queued_job = db.query(models.AuditJob).filter(models.AuditJob.id == "scheduled-job-1").first()
    queued_payload = json.loads(redis_client.queue_pushes[0]["value"])

    assert refreshed_schedule is not None
    assert refreshed_schedule.audit_params["audit_target_type"] == "website"
    assert refreshed_schedule.audit_params["target_name"] is None
    assert refreshed_schedule.audit_params["target_metadata"] == {}
    assert queued_job is not None
    assert queued_job.target_name == "https://example.com"
    assert queued_job.target_metadata == {}
    assert queued_payload["audit_target_type"] == "website"
    assert queued_payload["target_name"] == "https://example.com"
    assert queued_payload["target_metadata"] == {}
