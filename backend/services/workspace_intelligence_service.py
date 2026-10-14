from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from services.project_audit_scope import own_project_audit_clause

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 4.1, Client Health Dashboard
# ---------------------------------------------------------------------------


def get_client_health(db: Session, *, workspace_id: int) -> list[dict]:
    """Return per-project health data for the workspace dashboard.

    Only includes non-archived projects.  For each project the response
    contains: name, domain, latest scores, score deltas vs the previous
    audit, days_since_last_audit, recommendation_count and
    open_approval_count.
    """

    projects = (
        db.query(models.Project)
        .filter(
            models.Project.workspace_id == workspace_id,
            models.Project.status != models.ProjectStatus.ARCHIVED,
        )
        .order_by(models.Project.name.asc())
        .all()
    )

    now = _utc_now()
    results: list[dict] = []

    for project in projects:
        # Fetch the two most recent audits for delta calculation
        recent_audits = (
            db.query(models.Audit)
            .filter(models.Audit.project_id == project.id, own_project_audit_clause())
            .order_by(models.Audit.created_at.desc())
            .limit(2)
            .all()
        )

        latest = recent_audits[0] if recent_audits else None
        previous = recent_audits[1] if len(recent_audits) >= 2 else None

        # Score values
        seo_score = latest.seo_score if latest else None
        geo_score = latest.geo_score if latest else None
        aeo_score = latest.aeo_score if latest else None

        # Deltas
        seo_delta = _score_delta(seo_score, previous.seo_score if previous else None)
        geo_delta = _score_delta(geo_score, previous.geo_score if previous else None)
        aeo_delta = _score_delta(aeo_score, previous.aeo_score if previous else None)

        # Days since last audit
        days_since: int | None = None
        if latest and latest.created_at:
            audit_dt = latest.created_at
            if audit_dt.tzinfo is None:
                audit_dt = audit_dt.replace(tzinfo=timezone.utc)
            days_since = (now - audit_dt).days

        # Recommendation count from full_report
        recommendation_count = 0
        if latest is not None:
            report = latest.full_report
            if isinstance(report, dict):
                recs = report.get("recommendations")
                if isinstance(recs, list):
                    recommendation_count = len(recs)

        # Open approval count (status == "pending")
        open_approval_count = 0
        if latest is not None:
            open_approval_count = (
                db.query(func.count(models.RecommendationApproval.id))
                .filter(
                    models.RecommendationApproval.audit_id == latest.id,
                    models.RecommendationApproval.status == "pending",
                )
                .scalar()
            ) or 0

        results.append(
            {
                "project_id": project.id,
                "name": project.name,
                "domain_url": project.domain_url,
                "latest_seo_score": seo_score,
                "latest_geo_score": geo_score,
                "latest_aeo_score": aeo_score,
                "seo_delta": seo_delta,
                "geo_delta": geo_delta,
                "aeo_delta": aeo_delta,
                "days_since_last_audit": days_since,
                "recommendation_count": recommendation_count,
                "open_approval_count": open_approval_count,
            }
        )

    return results


def _score_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


# ---------------------------------------------------------------------------
# 4.2, Invitation Tracking
# ---------------------------------------------------------------------------

_INVITATION_TTL_DAYS = 7


def create_invitation(
    db: Session,
    *,
    workspace_id: int,
    invited_email: str,
    invited_name: str | None,
    invited_by_user_id: int,
    role: str,
    project_ids: list[int] | None,
) -> models.WorkspaceInvitation:
    """Create a new workspace invitation with a random token and 7-day expiry."""

    now = _utc_now()
    invitation = models.WorkspaceInvitation(
        workspace_id=workspace_id,
        invited_email=invited_email,
        invited_name=invited_name,
        invited_by_user_id=invited_by_user_id,
        role=role,
        project_ids=project_ids or [],
        status=models.InvitationStatus.PENDING,
        token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(days=_INVITATION_TTL_DAYS),
    )
    db.add(invitation)
    db.flush()
    logger.info(
        "Created invitation %s for %s in workspace %s",
        invitation.id,
        invited_email,
        workspace_id,
    )
    return invitation


def list_invitations(
    db: Session,
    *,
    workspace_id: int,
    status_filter: str | None = None,
) -> list[models.WorkspaceInvitation]:
    """List invitations for a workspace, optionally filtered by status."""

    query = db.query(models.WorkspaceInvitation).filter(
        models.WorkspaceInvitation.workspace_id == workspace_id,
    )
    if status_filter is not None:
        query = query.filter(models.WorkspaceInvitation.status == status_filter)
    return query.order_by(models.WorkspaceInvitation.created_at.desc()).all()


def resend_invitation(
    db: Session,
    *,
    invitation: models.WorkspaceInvitation,
) -> models.WorkspaceInvitation:
    """Reset the token and expiry on an existing invitation."""

    now = _utc_now()
    invitation.token = secrets.token_urlsafe(32)
    invitation.expires_at = now + timedelta(days=_INVITATION_TTL_DAYS)
    invitation.status = models.InvitationStatus.PENDING
    db.add(invitation)
    db.flush()
    logger.info("Resent invitation %s (new token issued)", invitation.id)
    return invitation


def revoke_invitation(
    db: Session,
    *,
    invitation: models.WorkspaceInvitation,
) -> models.WorkspaceInvitation:
    """Mark an invitation as revoked."""

    invitation.status = models.InvitationStatus.REVOKED
    db.add(invitation)
    db.flush()
    logger.info("Revoked invitation %s", invitation.id)
    return invitation


def accept_invitation(
    db: Session,
    *,
    invitation: models.WorkspaceInvitation,
) -> models.WorkspaceInvitation:
    """Mark an invitation as accepted."""

    now = _utc_now()
    invitation.status = models.InvitationStatus.ACCEPTED
    invitation.accepted_at = now
    db.add(invitation)
    db.flush()
    logger.info("Accepted invitation %s at %s", invitation.id, now.isoformat())
    return invitation


# ---------------------------------------------------------------------------
# 4.3, Activity Logging
# ---------------------------------------------------------------------------


def log_workspace_activity(
    db: Session,
    *,
    workspace_id: int,
    actor_user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    metadata: dict | None = None,
) -> models.WorkspaceActivityLog:
    """Create a workspace activity log entry.

    Flushes the record but **never** commits, the caller controls the
    transaction boundary.
    """

    entry = models.WorkspaceActivityLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=metadata,
    )
    db.add(entry)
    db.flush()
    logger.debug(
        "Activity logged: workspace=%s action=%s actor=%s",
        workspace_id,
        action,
        actor_user_id,
    )
    return entry


def list_workspace_activity(
    db: Session,
    *,
    workspace_id: int,
    action_filter: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return paginated activity logs for a workspace.

    Returns ``{"items": [...], "total": int, "page": int, "page_size": int}``.
    """

    base_query = db.query(models.WorkspaceActivityLog).filter(
        models.WorkspaceActivityLog.workspace_id == workspace_id,
    )
    if action_filter is not None:
        base_query = base_query.filter(
            models.WorkspaceActivityLog.action == action_filter,
        )

    total: int = base_query.count()

    offset = (max(page, 1) - 1) * page_size
    items = (
        base_query.order_by(models.WorkspaceActivityLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# 4.4, Credit Tracking
# ---------------------------------------------------------------------------
