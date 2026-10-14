from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.params import Param
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from operational_settings import get_report_retention_days
from schemas.annotations import (
    AnnotationCreateRequest,
    AnnotationResponse,
    AnnotationThreadPageResponse,
)
from services.report_annotation_service import (
    build_annotation_response,
    count_annotations_by_section,
    create_annotation,
    extract_annotation_targets,
    get_annotation_or_404,
    list_annotations,
    queue_annotation_notifications,
)
from services.custom_domain_service import resolve_workspace_branding
from services.project_audit_scope import own_project_audit_clause
from services.portal_service import (
    check_portal_pdf_access,
    get_approvals_for_audit,
    list_project_audits_paginated,
    get_audit_for_project,
    upsert_recommendation_approval,
    update_client_preferences,
)
from services.workspace_rbac import resolve_portal_workspace_access, resolve_project_access

router = APIRouter(tags=["Portal"])


def _query_value(value: Any) -> Any:
    if isinstance(value, Param):
        return value.default
    return value


class PortalBrandingResponse(BaseModel):
    workspace_id: int
    workspace_name: str
    agency_name: str | None = None
    custom_logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    custom_favicon_url: str | None = None
    custom_page_title: str | None = None
    hide_powered_by: bool = False


class PortalProjectListItemResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    domain_url: str | None = None
    language: str = "en"
    latest_seo_score: float | None = None
    latest_geo_score: float | None = None
    latest_aeo_score: float | None = None
    last_audit_at: str | None = None


class PortalRecommendationResponse(BaseModel):
    title: str
    description: str | None = None
    section_path: str | None = None
    source_recommendation_key: str | None = None
    annotation_count: int = 0
    approval: PortalApprovalInfoResponse | None = None


class PortalLatestAuditResponse(BaseModel):
    id: int
    created_at: str | None
    status: str
    seo_score: float | None = None
    geo_score: float | None = None
    aeo_score: float | None = None
    summary: str | None = None


class PortalTrendPointResponse(BaseModel):
    created_at: str | None
    seo_score: float | None = None
    geo_score: float | None = None
    aeo_score: float | None = None


class PortalLatestReportResponse(BaseModel):
    report_month: str | None = None
    created_at: str | None = None
    expired: bool = False
    retention_days: int = 30


class PortalProjectDashboardResponse(BaseModel):
    project: PortalProjectListItemResponse
    latest_audit: PortalLatestAuditResponse | None = None
    latest_report: PortalLatestReportResponse | None = None
    trends: list[PortalTrendPointResponse] = Field(default_factory=list)
    recommendations: list[PortalRecommendationResponse] = Field(default_factory=list)


class PortalTaskResponse(BaseModel):
    id: int
    issue_key: str
    issue_url: str
    title: str
    issue_type: str
    status_name: str
    created_at: str | None


# --- Phase 2 response / request models ---


class PortalAuditHistoryItemResponse(BaseModel):
    id: int
    created_at: str | None
    seo_score: float | None = None
    geo_score: float | None = None
    aeo_score: float | None = None
    status: str


class PortalAuditHistoryResponse(BaseModel):
    items: list[PortalAuditHistoryItemResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class PortalApprovalInfoResponse(BaseModel):
    status: str
    decided_at: str | None = None
    note: str | None = None


class PortalRecommendationApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "deferred"]
    note: str | None = Field(default=None, max_length=1000)


class PortalRecommendationApprovalResponse(BaseModel):
    id: int
    audit_id: int
    source_recommendation_key: str
    section_path: str | None = None
    status: str
    decided_at: str | None = None
    note: str | None = None


class PortalPreferencesUpdateRequest(BaseModel):
    email_digest_frequency: Literal["daily", "weekly", "monthly", "none"] | None = None
    notify_on_new_audit: bool | None = None


class PortalPreferencesResponse(BaseModel):
    email_digest_frequency: str | None = None
    notify_on_new_audit: bool | None = None


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_portal_user(user: models.User) -> None:
    if not bool(getattr(user, "resolved_portal_only", False)):
        raise HTTPException(status_code=403, detail="Client portal access required.")


def _extract_latest_audit_summary(audit: models.Audit | None) -> str | None:
    if audit is None or not isinstance(audit.full_report, dict):
        return None

    report = audit.full_report
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    candidates = [
        analysis.get("summary") if isinstance(analysis, dict) else None,
        report.get("summary"),
        report.get("executive_summary"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:600]
    return None


def _extract_latest_audit_status(audit: models.Audit | None) -> str:
    if audit is None or not isinstance(audit.full_report, dict):
        return "completed"

    metadata = (
        audit.full_report.get("metadata")
        if isinstance(audit.full_report.get("metadata"), dict)
        else {}
    )
    outcome = str(metadata.get("audit_outcome") or "").strip().lower()
    if outcome in {"completed", "degraded", "failed"}:
        return outcome
    if metadata.get("scores_available") is False:
        return "degraded"
    if metadata.get("service_errors"):
        return "degraded"
    return "completed"


def _extract_recommendations(
    db: Session,
    *,
    audit: models.Audit | None,
) -> list[PortalRecommendationResponse]:
    if audit is None or not isinstance(audit.full_report, dict):
        return []

    annotation_counts = count_annotations_by_section(
        db,
        audit_id=audit.id,
        visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
    )
    approvals = get_approvals_for_audit(db, audit_id=audit.id)
    recommendations: list[PortalRecommendationResponse] = []
    for target in extract_annotation_targets(audit)[:8]:
        approval_info = approvals.get(target.source_recommendation_key or "")
        recommendations.append(
            PortalRecommendationResponse(
                title=target.title,
                description=target.description,
                section_path=target.section_path,
                source_recommendation_key=target.source_recommendation_key,
                annotation_count=annotation_counts.get(target.section_path, 0),
                approval=(PortalApprovalInfoResponse(**approval_info) if approval_info else None),
            )
        )
    return recommendations


def _serialize_project_list_item(
    db: Session,
    *,
    project: models.Project,
) -> PortalProjectListItemResponse:
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    return PortalProjectListItemResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        domain_url=project.domain_url,
        language=str(project.language or "en"),
        latest_seo_score=float(latest_audit.seo_score)
        if latest_audit and latest_audit.seo_score is not None
        else None,
        latest_geo_score=float(latest_audit.geo_score)
        if latest_audit and latest_audit.geo_score is not None
        else None,
        latest_aeo_score=float(latest_audit.aeo_score)
        if latest_audit and latest_audit.aeo_score is not None
        else None,
        last_audit_at=_isoformat(latest_audit.created_at if latest_audit else None),
    )


def _resolve_portal_project_audit(
    db: Session,
    *,
    user: models.User,
    project_id: int,
    audit_id: int,
) -> tuple[models.Project, models.Audit]:
    _require_portal_user(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    if access.role != models.WorkspaceRole.CLIENT_READONLY.value:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.id == audit_id,
            models.Audit.project_id == access.project.id,
            own_project_audit_clause(),
        )
        .first()
    )
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    return access.project, audit


@router.get("/portal/branding", response_model=PortalBrandingResponse)
def get_portal_branding(
    workspace_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_portal_user(user)
    access = resolve_portal_workspace_access(db, user=user, workspace_id=workspace_id)
    branding = resolve_workspace_branding(access.workspace)
    return PortalBrandingResponse(
        workspace_id=access.workspace.id,
        workspace_name=access.workspace.name,
        agency_name=branding["company_name"],
        custom_logo_url=branding["custom_logo_url"],
        primary_color=branding["primary_color"],
        secondary_color=branding["secondary_color"],
        custom_favicon_url=branding["custom_favicon_url"],
        custom_page_title=branding["custom_page_title"],
        hide_powered_by=branding["hide_powered_by"],
    )


@router.get("/portal/projects", response_model=list[PortalProjectListItemResponse])
def list_portal_projects(
    workspace_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_portal_user(user)
    access = resolve_portal_workspace_access(db, user=user, workspace_id=workspace_id)
    assigned_projects = (
        db.query(models.Project)
        .join(
            models.WorkspaceUserProjectAccess,
            models.WorkspaceUserProjectAccess.project_id == models.Project.id,
        )
        .filter(models.WorkspaceUserProjectAccess.workspace_user_id == access.membership.id)
        .order_by(models.Project.name.asc(), models.Project.id.asc())
        .all()
    )
    return [_serialize_project_list_item(db, project=project) for project in assigned_projects]


@router.get(
    "/portal/projects/{project_id}/dashboard",
    response_model=PortalProjectDashboardResponse,
)
def get_portal_project_dashboard(
    project_id: int,
    audit_id: int | None = Query(
        default=None, description="Specific audit ID to view (defaults to latest)"
    ),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_portal_user(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    if access.role != models.WorkspaceRole.CLIENT_READONLY.value:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    retention_days = get_report_retention_days(db)
    reference_now = datetime.now(timezone.utc)
    latest_audit = get_audit_for_project(
        db, project_id=access.project.id, audit_id=_query_value(audit_id)
    )
    trend_rows = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == access.project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .limit(12)
        .all()
    )
    latest_report = (
        db.query(models.ProjectProgressReport)
        .filter(models.ProjectProgressReport.project_id == access.project.id)
        .order_by(
            models.ProjectProgressReport.report_month.desc(),
            models.ProjectProgressReport.id.desc(),
        )
        .first()
    )
    trends = [
        PortalTrendPointResponse(
            created_at=_isoformat(row.created_at),
            seo_score=float(row.seo_score) if row.seo_score is not None else None,
            geo_score=float(row.geo_score) if row.geo_score is not None else None,
            aeo_score=float(row.aeo_score) if row.aeo_score is not None else None,
        )
        for row in reversed(trend_rows)
    ]

    return PortalProjectDashboardResponse(
        project=_serialize_project_list_item(db, project=access.project),
        latest_audit=(
            PortalLatestAuditResponse(
                id=latest_audit.id,
                created_at=_isoformat(latest_audit.created_at),
                status=_extract_latest_audit_status(latest_audit),
                seo_score=float(latest_audit.seo_score)
                if latest_audit.seo_score is not None
                else None,
                geo_score=float(latest_audit.geo_score)
                if latest_audit.geo_score is not None
                else None,
                aeo_score=float(latest_audit.aeo_score)
                if latest_audit.aeo_score is not None
                else None,
                summary=_extract_latest_audit_summary(latest_audit),
            )
            if latest_audit
            else None
        ),
        latest_report=(
            PortalLatestReportResponse(
                report_month=latest_report.report_month.isoformat(),
                created_at=_isoformat(latest_report.created_at),
                expired=(
                    bool(_as_utc(latest_report.created_at))
                    and _as_utc(latest_report.created_at)
                    < (reference_now - timedelta(days=max(int(retention_days), 1)))
                ),
                retention_days=int(retention_days),
            )
            if latest_report
            else None
        ),
        trends=trends,
        recommendations=_extract_recommendations(db, audit=latest_audit),
    )


@router.get("/portal/projects/{project_id}/tasks", response_model=list[PortalTaskResponse])
def list_portal_project_tasks(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_portal_user(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    if access.role != models.WorkspaceRole.CLIENT_READONLY.value:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    exports = (
        db.query(models.ProjectJiraExport)
        .filter(models.ProjectJiraExport.project_id == access.project.id)
        .order_by(models.ProjectJiraExport.created_at.desc(), models.ProjectJiraExport.id.desc())
        .limit(50)
        .all()
    )
    return [
        PortalTaskResponse(
            id=row.id,
            issue_key=row.issue_key,
            issue_url=row.issue_url,
            title=row.title,
            issue_type=row.issue_type,
            status_name=row.status_name,
            created_at=_isoformat(row.created_at),
        )
        for row in exports
    ]


@router.get(
    "/portal/projects/{project_id}/audits/{audit_id}/annotations",
    response_model=AnnotationThreadPageResponse,
)
def list_portal_audit_annotations(
    project_id: int,
    audit_id: int,
    section_path: str | None = Query(default=None, max_length=255),
    source_recommendation_key: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project, audit = _resolve_portal_project_audit(
        db,
        user=user,
        project_id=project_id,
        audit_id=audit_id,
    )
    section_path = _query_value(section_path)
    source_recommendation_key = _query_value(source_recommendation_key)
    page = _query_value(page)
    per_page = _query_value(per_page)
    return list_annotations(
        db,
        audit_id=audit.id,
        user=user,
        role=models.WorkspaceRole.CLIENT_READONLY.value,
        visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
        section_path=(str(section_path or "").strip() or None),
        source_recommendation_key=(str(source_recommendation_key or "").strip() or None),
        page=page,
        per_page=per_page,
    )


@router.post(
    "/portal/projects/{project_id}/audits/{audit_id}/annotations",
    response_model=AnnotationResponse,
)
def create_portal_audit_annotation_reply(
    project_id: int,
    audit_id: int,
    payload: AnnotationCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, audit = _resolve_portal_project_audit(
        db,
        user=user,
        project_id=project_id,
        audit_id=audit_id,
    )
    annotation = create_annotation(
        db,
        audit=audit,
        project=project,
        user=user,
        role=models.WorkspaceRole.CLIENT_READONLY.value,
        content=payload.content,
        visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
        parent_id=payload.parent_id,
        section_path=payload.section_path,
        source_recommendation_key=payload.source_recommendation_key,
        portal_mode=True,
    )
    queue_annotation_notifications(db, project=project, audit=audit, annotation=annotation)
    db.commit()
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation.id)
    return build_annotation_response(
        annotation,
        user=user,
        role=models.WorkspaceRole.CLIENT_READONLY.value,
    )


# ---------------------------------------------------------------------------
# Phase 2: Audit history, PDF download, recommendation approval, preferences
# ---------------------------------------------------------------------------


@router.get(
    "/portal/projects/{project_id}/audits",
    response_model=PortalAuditHistoryResponse,
)
def list_portal_project_audits(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paginated audit history for a portal project."""
    _require_portal_user(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    if access.role != models.WorkspaceRole.CLIENT_READONLY.value:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    rows, total = list_project_audits_paginated(
        db,
        project_id=access.project.id,
        page=page,
        page_size=page_size,
    )
    items = [
        PortalAuditHistoryItemResponse(
            id=audit.id,
            created_at=_isoformat(audit.created_at),
            seo_score=float(audit.seo_score) if audit.seo_score is not None else None,
            geo_score=float(audit.geo_score) if audit.geo_score is not None else None,
            aeo_score=float(audit.aeo_score) if audit.aeo_score is not None else None,
            status=_extract_latest_audit_status(audit),
        )
        for audit in rows
    ]
    return PortalAuditHistoryResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/portal/projects/{project_id}/audits/{audit_id}/pdf")
def download_portal_audit_pdf(
    project_id: int,
    audit_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download a white-label PDF report for a portal audit (plan-gated)."""
    _require_portal_user(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    if access.role != models.WorkspaceRole.CLIENT_READONLY.value:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    if not check_portal_pdf_access(db, workspace=access.workspace):
        raise HTTPException(
            status_code=403,
            detail="PDF report downloads require a plan with white-label PDF access. Please contact your agency to upgrade.",
        )

    audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.id == audit_id,
            models.Audit.project_id == access.project.id,
            own_project_audit_clause(),
        )
        .first()
    )
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")

    from services.pdf_reports.report_suite_service import render_report_pdf
    from services.custom_domain_service import resolve_workspace_branding as _resolve_branding

    branding = _resolve_branding(access.workspace)
    branding_config = {
        "company_name": branding.get("company_name"),
        "custom_logo_url": branding.get("custom_logo_url"),
        "primary_color": branding.get("primary_color"),
        "secondary_color": branding.get("secondary_color"),
    }

    try:
        pdf_bytes = render_report_pdf(
            db=db,
            selected_audits=[audit],
            template_type="whitelabel",
            options={"mode": "individual", "sections": ["overview", "geo", "seo", "aeo"]},
            branding_config=branding_config,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate PDF report.")

    filename = f"audit-{audit.id}-report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/portal/projects/{project_id}/audits/{audit_id}/recommendations/{recommendation_key}/approval",
    response_model=PortalRecommendationApprovalResponse,
)
def submit_portal_recommendation_approval(
    project_id: int,
    audit_id: int,
    recommendation_key: str,
    payload: PortalRecommendationApprovalRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit an approval decision (approve/reject/defer) for a recommendation."""
    project, audit = _resolve_portal_project_audit(
        db,
        user=user,
        project_id=project_id,
        audit_id=audit_id,
    )

    approval = upsert_recommendation_approval(
        db,
        audit_id=audit.id,
        source_recommendation_key=recommendation_key,
        section_path=None,
        status=payload.status,
        user_id=user.id,
        note=payload.note,
    )
    db.commit()
    db.refresh(approval)
    return PortalRecommendationApprovalResponse(
        id=approval.id,
        audit_id=approval.audit_id,
        source_recommendation_key=approval.source_recommendation_key,
        section_path=approval.section_path,
        status=approval.status.value if hasattr(approval.status, "value") else str(approval.status),
        decided_at=_isoformat(approval.decided_at),
        note=approval.note,
    )


@router.get("/portal/profile/preferences", response_model=PortalPreferencesResponse)
def get_portal_preferences(
    workspace_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the portal user's notification preferences."""
    _require_portal_user(user)
    access = resolve_portal_workspace_access(db, user=user, workspace_id=workspace_id)
    freq = access.membership.email_digest_frequency
    return PortalPreferencesResponse(
        email_digest_frequency=freq.value
        if hasattr(freq, "value")
        else (str(freq) if freq else None),
        notify_on_new_audit=access.membership.notify_on_new_audit,
    )


@router.patch("/portal/profile/preferences", response_model=PortalPreferencesResponse)
def update_portal_preferences(
    payload: PortalPreferencesUpdateRequest,
    workspace_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the portal user's notification preferences."""
    _require_portal_user(user)
    access = resolve_portal_workspace_access(db, user=user, workspace_id=workspace_id)
    membership = update_client_preferences(
        db,
        membership=access.membership,
        email_digest_frequency=payload.email_digest_frequency,
        notify_on_new_audit=payload.notify_on_new_audit,
    )
    db.commit()
    db.refresh(membership)
    freq = membership.email_digest_frequency
    return PortalPreferencesResponse(
        email_digest_frequency=freq.value
        if hasattr(freq, "value")
        else (str(freq) if freq else None),
        notify_on_new_audit=membership.notify_on_new_audit,
    )
