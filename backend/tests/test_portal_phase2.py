"""Tests for Phase 2 Portal Enrichment (AEX-40).

Covers: audit history, PDF download plan gate, recommendation approval workflow,
client notification preferences.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import main
import models
from database import Base
from routers.portal_router import (
    download_portal_audit_pdf,
    get_portal_preferences,
    list_portal_project_audits,
    submit_portal_recommendation_approval,
    update_portal_preferences,
    PortalRecommendationApprovalRequest,
    PortalPreferencesUpdateRequest,
)
from services.portal_service import (
    check_portal_pdf_access,
    get_approvals_for_audit,
    list_project_audits_paginated,
    upsert_recommendation_approval,
    update_client_preferences,
)
from services.workspace_rbac import attach_portal_access_context


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: Engine) -> None:
    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_portal_world(
    db: Session,
    owner_plan: str = "plan_executive",
    owner_subscription_status: str = "active",
) -> dict:
    """Create minimal workspace + project + user + audit graph for portal tests."""
    owner = models.User(
        email="owner@agency.test",
        hashed_password="x",
        role="user",
        credits=5,
        company_name="Test Agency",
    )
    db.add(owner)
    db.flush()

    sub = models.Subscription(
        user_id=owner.id,
        stripe_customer_id="cus_test_123",
        plan_type=owner_plan,
        status=owner_subscription_status,
    )
    db.add(sub)
    db.flush()

    workspace = models.Workspace(name="Agency WS", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Client Site",
        domain_url="https://example.com",
        language="en",
    )
    db.add(project)
    db.flush()

    client_user = models.User(
        email="client@portal.test",
        hashed_password="x",
        role="user",
        credits=0,
    )
    db.add(client_user)
    db.flush()

    membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=client_user.id,
        role=models.WorkspaceRole.CLIENT_READONLY,
    )
    db.add(membership)
    db.flush()

    access = models.WorkspaceUserProjectAccess(
        workspace_user_id=membership.id,
        project_id=project.id,
    )
    db.add(access)
    db.flush()

    audit = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        full_report={
            "analysis": {"summary": "Test summary for portal."},
            "metadata": {"audit_outcome": "completed"},
            "recommendations": {
                "seo": [
                    {
                        "title": "Fix titles",
                        "description": "Improve page titles",
                        "key": "fix_titles",
                    },
                    {"title": "Add schema", "description": "Structured data", "key": "add_schema"},
                ],
            },
        },
        seo_score=72,
        geo_score=65,
        aeo_score=80,
    )
    db.add(audit)
    db.flush()

    # Second audit (older)
    audit_old = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        full_report={"analysis": {"summary": "Old audit."}},
        seo_score=60,
        geo_score=55,
        aeo_score=70,
    )
    db.add(audit_old)
    db.flush()

    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    db.refresh(client_user)
    db.refresh(membership)
    db.refresh(audit)
    db.refresh(audit_old)
    return {
        "owner": owner,
        "workspace": workspace,
        "project": project,
        "client_user": client_user,
        "membership": membership,
        "audit": audit,
        "audit_old": audit_old,
    }


# ---------------------------------------------------------------------------
# Service-level: list_project_audits_paginated
# ---------------------------------------------------------------------------


def test_service_list_project_audits_paginated() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        rows, total = list_project_audits_paginated(
            db, project_id=world["project"].id, page=1, page_size=10
        )
        assert total == 2
        assert len(rows) == 2
        # Both audits created at same timestamp in SQLite; ordered by id desc
        assert rows[0].id == world["audit_old"].id
    finally:
        _cleanup(db, engine)


def test_service_list_project_audits_page2_empty() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        rows, total = list_project_audits_paginated(
            db, project_id=world["project"].id, page=2, page_size=10
        )
        assert total == 2
        assert len(rows) == 0
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Service-level: recommendation approval CRUD
# ---------------------------------------------------------------------------


def test_service_upsert_recommendation_approval_create() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        approval = upsert_recommendation_approval(
            db,
            audit_id=world["audit"].id,
            source_recommendation_key="fix_titles",
            section_path=None,
            status="approved",
            user_id=world["client_user"].id,
            note="Looks good",
        )
        db.commit()
        assert approval.status == models.RecommendationApprovalStatus.APPROVED
        assert approval.note == "Looks good"
        assert approval.audit_id == world["audit"].id
    finally:
        _cleanup(db, engine)


def test_service_upsert_recommendation_approval_update() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        approval1 = upsert_recommendation_approval(
            db,
            audit_id=world["audit"].id,
            source_recommendation_key="fix_titles",
            section_path=None,
            status="approved",
            user_id=world["client_user"].id,
        )
        db.commit()
        first_id = approval1.id

        approval2 = upsert_recommendation_approval(
            db,
            audit_id=world["audit"].id,
            source_recommendation_key="fix_titles",
            section_path=None,
            status="rejected",
            user_id=world["client_user"].id,
            note="Changed my mind",
        )
        db.commit()
        assert approval2.id == first_id  # same row
        assert approval2.status == models.RecommendationApprovalStatus.REJECTED
        assert approval2.note == "Changed my mind"
    finally:
        _cleanup(db, engine)


def test_service_get_approvals_for_audit() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        upsert_recommendation_approval(
            db,
            audit_id=world["audit"].id,
            source_recommendation_key="fix_titles",
            section_path=None,
            status="approved",
            user_id=world["client_user"].id,
        )
        upsert_recommendation_approval(
            db,
            audit_id=world["audit"].id,
            source_recommendation_key="add_schema",
            section_path=None,
            status="deferred",
            user_id=world["client_user"].id,
            note="Revisit later",
        )
        db.commit()

        approvals = get_approvals_for_audit(db, audit_id=world["audit"].id)
        assert len(approvals) == 2
        assert approvals["fix_titles"]["status"] == "approved"
        assert approvals["add_schema"]["status"] == "deferred"
        assert approvals["add_schema"]["note"] == "Revisit later"
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Service-level: check_portal_pdf_access
# ---------------------------------------------------------------------------


def test_service_check_pdf_access_plan_executive() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        result = check_portal_pdf_access(db, workspace=world["workspace"])
        assert result is True
    finally:
        _cleanup(db, engine)


def test_service_check_pdf_access_plan_standard() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db, owner_plan="plan_standard")
        result = check_portal_pdf_access(db, workspace=world["workspace"])
        assert result is False
    finally:
        _cleanup(db, engine)


def test_service_check_pdf_access_rejects_pending_executive() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(
            db,
            owner_plan="plan_executive",
            owner_subscription_status="pending",
        )
        result = check_portal_pdf_access(db, workspace=world["workspace"])
        assert result is False
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Service-level: update_client_preferences
# ---------------------------------------------------------------------------


def test_service_update_client_preferences() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        membership = world["membership"]
        assert membership.email_digest_frequency is None
        assert membership.notify_on_new_audit is None

        updated = update_client_preferences(
            db,
            membership=membership,
            email_digest_frequency="weekly",
            notify_on_new_audit=True,
        )
        db.commit()
        assert updated.email_digest_frequency == models.ClientDigestFrequency.WEEKLY
        assert updated.notify_on_new_audit is True
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Endpoint-level: audit history via direct function call
# ---------------------------------------------------------------------------


def test_endpoint_audit_history_returns_paginated() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])
        result = list_portal_project_audits(
            project_id=world["project"].id,
            page=1,
            page_size=10,
            user=portal_user,
            db=db,
        )
        assert result.total == 2
        assert len(result.items) == 2
        # Both audits created at same timestamp in SQLite; ordered by id desc
        assert result.items[0].id == world["audit_old"].id
    finally:
        _cleanup(db, engine)


def test_endpoint_audit_history_rejects_unassigned_project() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        other_project = models.Project(workspace_id=world["workspace"].id, name="Other Project")
        db.add(other_project)
        db.commit()

        portal_user = attach_portal_access_context(db, user=world["client_user"])
        with pytest.raises(HTTPException) as exc:
            list_portal_project_audits(
                project_id=other_project.id,
                page=1,
                page_size=20,
                user=portal_user,
                db=db,
            )
        assert exc.value.status_code == 403
    finally:
        _cleanup(db, engine)


def test_endpoint_audit_history_rejects_non_portal_user() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        with pytest.raises(HTTPException) as exc:
            list_portal_project_audits(
                project_id=world["project"].id,
                page=1,
                page_size=20,
                user=world["owner"],
                db=db,
            )
        assert exc.value.status_code == 403
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Endpoint-level: PDF download
# ---------------------------------------------------------------------------


def test_endpoint_pdf_download_rejected_when_plan_forbids() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db, owner_plan="plan_standard")

        portal_user = attach_portal_access_context(db, user=world["client_user"])
        with pytest.raises(HTTPException) as exc:
            download_portal_audit_pdf(
                project_id=world["project"].id,
                audit_id=world["audit"].id,
                user=portal_user,
                db=db,
            )
        assert exc.value.status_code == 403
        assert "white-label PDF" in exc.value.detail
    finally:
        _cleanup(db, engine)


def test_endpoint_pdf_download_succeeds_with_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        fake_pdf = b"%PDF-1.4 fake content"

        monkeypatch.setattr(
            "routers.portal_router.check_portal_pdf_access",
            lambda db, *, workspace: True,
        )

        import services.pdf_reports.report_suite_service as _report_mod

        monkeypatch.setattr(
            _report_mod,
            "render_report_pdf",
            lambda **kwargs: fake_pdf,
        )

        portal_user = attach_portal_access_context(db, user=world["client_user"])
        response = download_portal_audit_pdf(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            user=portal_user,
            db=db,
        )
        assert response.status_code == 200
        assert response.media_type == "application/pdf"
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Endpoint-level: recommendation approval
# ---------------------------------------------------------------------------


def test_endpoint_recommendation_approval_approve() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])
        result = submit_portal_recommendation_approval(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            recommendation_key="fix_titles",
            payload=PortalRecommendationApprovalRequest(status="approved", note="LGTM"),
            user=portal_user,
            db=db,
        )
        assert result.status == "approved"
        assert result.source_recommendation_key == "fix_titles"
        assert result.note == "LGTM"
        assert result.audit_id == world["audit"].id
    finally:
        _cleanup(db, engine)


def test_endpoint_recommendation_approval_reject() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])
        result = submit_portal_recommendation_approval(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            recommendation_key="fix_titles",
            payload=PortalRecommendationApprovalRequest(status="rejected"),
            user=portal_user,
            db=db,
        )
        assert result.status == "rejected"
    finally:
        _cleanup(db, engine)


def test_endpoint_recommendation_approval_deferred() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])
        result = submit_portal_recommendation_approval(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            recommendation_key="add_schema",
            payload=PortalRecommendationApprovalRequest(status="deferred", note="Later"),
            user=portal_user,
            db=db,
        )
        assert result.status == "deferred"
        assert result.note == "Later"
    finally:
        _cleanup(db, engine)


def test_endpoint_recommendation_approval_upsert() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])

        result1 = submit_portal_recommendation_approval(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            recommendation_key="fix_titles",
            payload=PortalRecommendationApprovalRequest(status="approved"),
            user=portal_user,
            db=db,
        )
        first_id = result1.id

        result2 = submit_portal_recommendation_approval(
            project_id=world["project"].id,
            audit_id=world["audit"].id,
            recommendation_key="fix_titles",
            payload=PortalRecommendationApprovalRequest(status="rejected", note="Nope"),
            user=portal_user,
            db=db,
        )
        assert result2.id == first_id
        assert result2.status == "rejected"
    finally:
        _cleanup(db, engine)


def test_endpoint_recommendation_approval_rejects_non_portal_user() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        with pytest.raises(HTTPException) as exc:
            submit_portal_recommendation_approval(
                project_id=world["project"].id,
                audit_id=world["audit"].id,
                recommendation_key="fix_titles",
                payload=PortalRecommendationApprovalRequest(status="approved"),
                user=world["owner"],
                db=db,
            )
        assert exc.value.status_code == 403
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Endpoint-level: client preferences
# ---------------------------------------------------------------------------


def test_endpoint_preferences_get_defaults() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])
        result = get_portal_preferences(
            workspace_id=world["workspace"].id,
            user=portal_user,
            db=db,
        )
        assert result.email_digest_frequency is None
        assert result.notify_on_new_audit is None
    finally:
        _cleanup(db, engine)


def test_endpoint_preferences_update_and_persist() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        portal_user = attach_portal_access_context(db, user=world["client_user"])

        updated = update_portal_preferences(
            payload=PortalPreferencesUpdateRequest(
                email_digest_frequency="weekly",
                notify_on_new_audit=True,
            ),
            workspace_id=world["workspace"].id,
            user=portal_user,
            db=db,
        )
        assert updated.email_digest_frequency == "weekly"
        assert updated.notify_on_new_audit is True

        # Verify persistence
        refetched = get_portal_preferences(
            workspace_id=world["workspace"].id,
            user=portal_user,
            db=db,
        )
        assert refetched.email_digest_frequency == "weekly"
        assert refetched.notify_on_new_audit is True
    finally:
        _cleanup(db, engine)


def test_endpoint_preferences_rejects_non_portal_user() -> None:
    db, engine = _build_db()
    try:
        world = _seed_portal_world(db)
        with pytest.raises(HTTPException) as exc:
            get_portal_preferences(
                workspace_id=world["workspace"].id,
                user=world["owner"],
                db=db,
            )
        assert exc.value.status_code == 403
    finally:
        _cleanup(db, engine)
