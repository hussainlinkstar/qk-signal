"""Portal business logic, Phase 2 portal enrichment (AEX-40)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from app.config.plans import (
    can_use_feature,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from services.project_audit_scope import own_project_audit_clause


def resolve_workspace_owner_plan(db: Session, *, workspace: models.Workspace) -> str:
    """Resolve the subscription plan of the workspace owner."""
    owner = db.query(models.User).filter(models.User.id == workspace.owner_id).first()
    if owner is None:
        return "plan_standard"
    subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(owner))
    if subscription_plan:
        return subscription_plan
    trial_plan = resolve_plan_alias(getattr(owner, "trial_plan", None))
    return trial_plan or "plan_starter"


def check_portal_pdf_access(db: Session, *, workspace: models.Workspace) -> bool:
    """Return True if the workspace owner's plan supports white-label PDF export."""
    plan = resolve_workspace_owner_plan(db, workspace=workspace)
    return can_use_feature(plan, "pdf_white_label")


def list_project_audits_paginated(
    db: Session,
    *,
    project_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[models.Audit], int]:
    """Return the project's own audits with pagination."""
    query = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_audit_for_project(
    db: Session,
    *,
    project_id: int,
    audit_id: int | None = None,
) -> models.Audit | None:
    """Get a specific audit or the latest audit the project owns."""
    query = db.query(models.Audit).filter(
        models.Audit.project_id == project_id, own_project_audit_clause()
    )
    if audit_id is not None:
        return query.filter(models.Audit.id == audit_id).first()
    return query.order_by(models.Audit.created_at.desc(), models.Audit.id.desc()).first()


def upsert_recommendation_approval(
    db: Session,
    *,
    audit_id: int,
    source_recommendation_key: str,
    section_path: str | None,
    status: str,
    user_id: int,
    note: str | None = None,
) -> models.RecommendationApproval:
    """Create or update a recommendation approval decision."""
    existing = (
        db.query(models.RecommendationApproval)
        .filter(
            models.RecommendationApproval.audit_id == audit_id,
            models.RecommendationApproval.source_recommendation_key == source_recommendation_key,
        )
        .first()
    )
    if existing:
        existing.status = models.RecommendationApprovalStatus(status)
        existing.decided_by_user_id = user_id
        existing.decided_at = datetime.now(timezone.utc)
        existing.note = note
        if section_path is not None:
            existing.section_path = section_path
        db.flush()
        return existing

    approval = models.RecommendationApproval(
        audit_id=audit_id,
        source_recommendation_key=source_recommendation_key,
        section_path=section_path,
        status=models.RecommendationApprovalStatus(status),
        decided_by_user_id=user_id,
        note=note,
    )
    db.add(approval)
    db.flush()
    return approval


def get_approval_counts_for_audit(
    db: Session,
    *,
    audit_id: int,
) -> dict[str, int]:
    """Return counts of each approval status for a given audit."""
    rows = (
        db.query(
            models.RecommendationApproval.status,
            models.func.count(models.RecommendationApproval.id),
        )
        .filter(models.RecommendationApproval.audit_id == audit_id)
        .group_by(models.RecommendationApproval.status)
        .all()
    )
    result: dict[str, int] = {"approved": 0, "rejected": 0, "deferred": 0}
    for status_val, count in rows:
        key = status_val.value if hasattr(status_val, "value") else str(status_val)
        if key in result:
            result[key] = count
    return result


def get_approvals_for_audit(
    db: Session,
    *,
    audit_id: int,
) -> dict[str, dict[str, Any]]:
    """Return a dict keyed by source_recommendation_key with approval info."""
    rows = (
        db.query(models.RecommendationApproval)
        .filter(models.RecommendationApproval.audit_id == audit_id)
        .all()
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.source_recommendation_key
        result[key] = {
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "note": row.note,
        }
    return result


def update_client_preferences(
    db: Session,
    *,
    membership: models.WorkspaceUser,
    email_digest_frequency: str | None = None,
    notify_on_new_audit: bool | None = None,
) -> models.WorkspaceUser:
    """Update client notification preferences on the workspace membership."""
    if email_digest_frequency is not None:
        membership.email_digest_frequency = models.ClientDigestFrequency(email_digest_frequency)
    if notify_on_new_audit is not None:
        membership.notify_on_new_audit = notify_on_new_audit
    db.flush()
    return membership
