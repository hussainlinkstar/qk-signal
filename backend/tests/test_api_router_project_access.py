from __future__ import annotations

from pathlib import Path
import os
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from job_models import parse_job_payload
from routers.api_router import _resolve_audit_type_from_tier, _resolve_project_for_audit


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory()


def _cleanup(db: Session) -> None:
    engine = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_resolve_project_for_audit_allows_workspace_owner() -> None:
    db = _build_db()
    try:
        owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=5)
        db.add(owner)
        db.flush()
        workspace = models.Workspace(name="Agency", owner_id=owner.id)
        db.add(workspace)
        db.flush()
        project = models.Project(
            workspace_id=workspace.id, name="Client", domain_url="https://client.example"
        )
        db.add(project)
        db.commit()

        resolved = _resolve_project_for_audit(project_id=project.id, user=owner, db=db)
        assert resolved.id == project.id
    finally:
        _cleanup(db)


def test_resolve_project_for_audit_allows_workspace_member() -> None:
    db = _build_db()
    try:
        owner = models.User(email="owner2@example.com", hashed_password="x", role="user", credits=5)
        member = models.User(
            email="member@example.com", hashed_password="x", role="user", credits=5
        )
        db.add_all([owner, member])
        db.flush()
        workspace = models.Workspace(name="Agency", owner_id=owner.id)
        db.add(workspace)
        db.flush()
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=member.id,
                role=models.WorkspaceRole.EDITOR,
            )
        )
        project = models.Project(
            workspace_id=workspace.id, name="Client", domain_url="https://client.example"
        )
        db.add(project)
        db.commit()

        resolved = _resolve_project_for_audit(project_id=project.id, user=member, db=db)
        assert resolved.id == project.id
    finally:
        _cleanup(db)


def test_resolve_project_for_audit_rejects_unrelated_user() -> None:
    db = _build_db()
    try:
        owner = models.User(email="owner3@example.com", hashed_password="x", role="user", credits=5)
        outsider = models.User(
            email="outsider@example.com", hashed_password="x", role="user", credits=5
        )
        db.add_all([owner, outsider])
        db.flush()
        workspace = models.Workspace(name="Agency", owner_id=owner.id)
        db.add(workspace)
        db.flush()
        project = models.Project(
            workspace_id=workspace.id, name="Client", domain_url="https://client.example"
        )
        db.add(project)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            _resolve_project_for_audit(project_id=project.id, user=outsider, db=db)
        assert exc_info.value.status_code == 403
    finally:
        _cleanup(db)


def test_resolve_audit_type_from_tier_maps_smart_and_defaults_fast() -> None:
    assert _resolve_audit_type_from_tier("smart") == models.AuditType.DEEP
    assert _resolve_audit_type_from_tier("deep_judgment") == models.AuditType.DEEP
    assert _resolve_audit_type_from_tier("SMART") == models.AuditType.DEEP
    assert _resolve_audit_type_from_tier("deep") == models.AuditType.DEEP
    assert _resolve_audit_type_from_tier("fast") == models.AuditType.STANDARD
    assert _resolve_audit_type_from_tier("lite") == models.AuditType.STANDARD
    assert _resolve_audit_type_from_tier(None) == models.AuditType.STANDARD


def test_parse_job_payload_reads_optional_project_id() -> None:
    payload = parse_job_payload(
        {
            "job_id": "job-1",
            "request_id": "req-1",
            "user_id": 10,
            "url": "https://example.com",
            "provider": "google",
            "tier": "smart",
            "project_id": 44,
        }
    )
    assert payload.project_id == 44


def test_parse_job_payload_reads_requested_tier_contract() -> None:
    payload = parse_job_payload(
        {
            "job_id": "job-2",
            "request_id": "req-2",
            "user_id": 10,
            "url": "https://example.com",
            "provider": "anthropic",
            "tier": "smart",
            "requested_tier": "deep_judgment",
            "mode_label": "High Confidence / Prescriptive Confidence mode",
        }
    )

    assert payload.requested_tier == "deep_judgment"
    assert payload.mode_label == "High Confidence / Prescriptive Confidence mode"
