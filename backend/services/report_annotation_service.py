from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

import models
from schemas.annotations import AnnotationResponse
from services.email_service import EmailService
from services.reports.audit_result_adapter import extract_canonical_recommendation_items

ANNOTATION_WRITE_ROLES = {
    models.WorkspaceRole.ADMIN.value,
    models.WorkspaceRole.MANAGER.value,
    models.WorkspaceRole.EDITOR.value,
}
ANNOTATION_READ_ROLES = {
    models.WorkspaceRole.ADMIN.value,
    models.WorkspaceRole.MANAGER.value,
    models.WorkspaceRole.EDITOR.value,
    models.WorkspaceRole.VIEWER.value,
    models.WorkspaceRole.CLIENT_READONLY.value,
}


@dataclass(frozen=True)
class RecommendationTarget:
    section_path: str
    source_recommendation_key: str | None
    title: str
    description: str | None
    category: str


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _normalize_title(value: str | None) -> str:
    return str(value or "").strip()[:255]


def _normalize_description(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:4000] or None


def _normalize_category(value: str | None, *, fallback: str = "General") -> str:
    normalized = str(value or "").strip()
    return normalized[:120] or fallback


def _normalize_key_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:80]


def normalize_source_recommendation_key(
    *,
    title: str,
    category: str,
    description: str | None = None,
) -> str:
    title_key = _normalize_key_fragment(title)
    category_key = _normalize_key_fragment(category)
    description_key = _normalize_key_fragment(description or "")
    digest = hashlib.sha256(
        f"{category_key}|{title_key}|{description_key}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{category_key or 'general'}:{title_key or 'recommendation'}:{digest}"


def annotation_write_allowed(role: str) -> bool:
    return str(role or "").strip().upper() in ANNOTATION_WRITE_ROLES


def _annotation_visibility_value(
    value: models.AnnotationVisibility | str | None,
) -> str:
    if isinstance(value, models.AnnotationVisibility):
        return value.value
    return str(value or models.AnnotationVisibility.INTERNAL.value)


def _user_display_name(user: models.User | None) -> str | None:
    if user is None:
        return None
    candidate = str(getattr(user, "company_name", "") or "").strip()
    if candidate:
        return candidate
    email = str(user.email or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return email or None


def _author_can_manage(
    annotation: models.ReportAnnotation,
    *,
    user: models.User,
    role: str,
) -> bool:
    normalized_role = str(role or "").strip().upper()
    if normalized_role == models.WorkspaceRole.ADMIN.value:
        return True
    return annotation.user_id is not None and annotation.user_id == user.id


def _serialize_annotation(
    annotation: models.ReportAnnotation,
    *,
    user: models.User,
    role: str,
    replies: list[AnnotationResponse] | None = None,
) -> AnnotationResponse:
    return AnnotationResponse(
        id=annotation.id,
        audit_id=annotation.audit_id,
        project_id=annotation.project_id,
        user_id=annotation.user_id,
        user_display_name=_user_display_name(annotation.author),
        parent_id=annotation.parent_id,
        section_path=annotation.section_path,
        source_recommendation_key=annotation.source_recommendation_key,
        content="[Deleted]" if annotation.is_deleted else str(annotation.content or "").strip(),
        visibility=_annotation_visibility_value(annotation.visibility),
        is_deleted=bool(annotation.is_deleted),
        created_at=_isoformat(annotation.created_at) or "",
        updated_at=_isoformat(annotation.updated_at),
        can_edit=(not annotation.is_deleted)
        and _author_can_manage(annotation, user=user, role=role),
        can_delete=(not annotation.is_deleted)
        and _author_can_manage(annotation, user=user, role=role),
        replies=replies or [],
    )


def build_annotation_response(
    annotation: models.ReportAnnotation,
    *,
    user: models.User,
    role: str,
) -> AnnotationResponse:
    serialized_replies = [
        _serialize_annotation(reply, user=user, role=role)
        for reply in sorted(
            [reply for reply in annotation.replies if _is_reply_visible_for_listing(reply)],
            key=lambda item: (_isoformat(item.created_at) or "", item.id),
        )
    ]
    return _serialize_annotation(
        annotation,
        user=user,
        role=role,
        replies=serialized_replies,
    )


def _is_reply_visible_for_listing(reply: models.ReportAnnotation) -> bool:
    return not bool(reply.is_deleted)


def _is_top_level_visible_for_listing(
    annotation: models.ReportAnnotation,
    *,
    visible_replies: list[models.ReportAnnotation],
) -> bool:
    if not annotation.is_deleted:
        return True
    return len(visible_replies) > 0


def extract_annotation_targets(audit: models.Audit | None) -> list[RecommendationTarget]:
    if audit is None or not isinstance(audit.full_report, dict):
        return []

    raw_report = audit.full_report
    analysis = raw_report.get("analysis") if isinstance(raw_report.get("analysis"), dict) else {}
    targets: list[RecommendationTarget] = []
    seen_section_paths: set[str] = set()
    seen_source_recommendation_keys: set[str] = set()

    def append_list(
        items: Any,
        *,
        path_prefix: str,
        fallback_category: str,
        item_kind: str = "recommendation",
    ) -> None:
        if not isinstance(items, list):
            return

        for index, item in enumerate(items):
            section_path = f"{path_prefix}[{index}]"
            if section_path in seen_section_paths:
                continue

            title = ""
            description: str | None = None
            category = fallback_category

            if isinstance(item, str):
                title = _normalize_title(item)
            elif isinstance(item, dict):
                title = _normalize_title(
                    item.get("title")
                    or item.get("action")
                    or item.get("name")
                    or item.get("description")
                )
                description = _normalize_description(item.get("description") or item.get("action"))
                category = _normalize_category(
                    item.get("category"),
                    fallback=fallback_category,
                )
            else:
                continue

            if not title:
                continue

            source_key = (
                normalize_source_recommendation_key(
                    title=title,
                    category=category,
                    description=description,
                )
                if item_kind == "recommendation"
                else None
            )
            if source_key and source_key in seen_source_recommendation_keys:
                continue
            seen_section_paths.add(section_path)
            if source_key:
                seen_source_recommendation_keys.add(source_key)
            targets.append(
                RecommendationTarget(
                    section_path=section_path,
                    source_recommendation_key=source_key,
                    title=title,
                    description=description,
                    category=category,
                )
            )

    append_list(
        raw_report.get("prioritized_actions"),
        path_prefix="prioritized_actions",
        fallback_category="Technical",
    )
    append_list(
        raw_report.get("priority_actions"),
        path_prefix="priority_actions",
        fallback_category="Technical",
    )
    append_list(
        raw_report.get("suggestions"), path_prefix="suggestions", fallback_category="Technical"
    )
    canonical_recommendations = extract_canonical_recommendation_items(raw_report)
    append_list(
        canonical_recommendations,
        path_prefix="recommendations.items",
        fallback_category="Technical",
    )
    append_list(
        analysis.get("recommendations"),
        path_prefix="analysis.recommendations",
        fallback_category="Technical",
    )
    append_list(
        analysis.get("seo_findings"),
        path_prefix="analysis.seo_findings",
        fallback_category="SEO",
        item_kind="finding",
    )
    append_list(
        analysis.get("geo_findings"),
        path_prefix="analysis.geo_findings",
        fallback_category="GEO",
        item_kind="finding",
    )
    append_list(
        analysis.get("aeo_findings"),
        path_prefix="analysis.aeo_findings",
        fallback_category="AEO",
        item_kind="finding",
    )

    return targets


def resolve_source_recommendation_key(
    *,
    audit: models.Audit,
    section_path: str | None,
    explicit_source_recommendation_key: str | None,
) -> str | None:
    explicit = str(explicit_source_recommendation_key or "").strip()
    if explicit:
        return explicit[:255]
    normalized_section_path = str(section_path or "").strip()
    if not normalized_section_path:
        return None
    target = next(
        (
            candidate
            for candidate in extract_annotation_targets(audit)
            if candidate.section_path == normalized_section_path
        ),
        None,
    )
    return target.source_recommendation_key if target is not None else None


def count_annotations_by_section(
    db: Session,
    *,
    audit_id: int,
    visibility: models.AnnotationVisibility | None = None,
) -> dict[str, int]:
    query = db.query(models.ReportAnnotation).filter(
        models.ReportAnnotation.audit_id == audit_id,
        models.ReportAnnotation.section_path.isnot(None),
        models.ReportAnnotation.is_deleted.is_(False),
    )
    if visibility is not None:
        query = query.filter(models.ReportAnnotation.visibility == visibility)

    counts: dict[str, int] = {}
    for annotation in query.all():
        section_path = str(annotation.section_path or "").strip()
        if not section_path:
            continue
        counts[section_path] = counts.get(section_path, 0) + 1
    return counts


def list_annotations(
    db: Session,
    *,
    audit_id: int,
    user: models.User,
    role: str,
    visibility: models.AnnotationVisibility | None = None,
    section_path: str | None = None,
    source_recommendation_key: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or 50), 100))

    query = (
        db.query(models.ReportAnnotation)
        .options(
            selectinload(models.ReportAnnotation.author),
            selectinload(models.ReportAnnotation.replies).selectinload(
                models.ReportAnnotation.author
            ),
        )
        .filter(
            models.ReportAnnotation.audit_id == audit_id,
            models.ReportAnnotation.parent_id.is_(None),
        )
        .order_by(models.ReportAnnotation.created_at.asc(), models.ReportAnnotation.id.asc())
    )
    if visibility is not None:
        query = query.filter(models.ReportAnnotation.visibility == visibility)
    if section_path:
        query = query.filter(models.ReportAnnotation.section_path == section_path)
    if source_recommendation_key:
        query = query.filter(
            models.ReportAnnotation.source_recommendation_key == source_recommendation_key
        )

    visible_threads: list[models.ReportAnnotation] = []
    reply_map: dict[int, list[models.ReportAnnotation]] = {}

    for annotation in query.all():
        visible_replies = [
            reply
            for reply in sorted(
                annotation.replies,
                key=lambda item: (_isoformat(item.created_at) or "", item.id),
            )
            if (
                (visibility is None or reply.visibility == visibility)
                and _is_reply_visible_for_listing(reply)
            )
        ]
        if not _is_top_level_visible_for_listing(annotation, visible_replies=visible_replies):
            continue
        visible_threads.append(annotation)
        reply_map[annotation.id] = visible_replies

    total = len(visible_threads)
    start = (page - 1) * per_page
    end = start + per_page
    items = []
    for annotation in visible_threads[start:end]:
        serialized_replies = [
            _serialize_annotation(reply, user=user, role=role)
            for reply in reply_map.get(annotation.id, [])
        ]
        items.append(
            _serialize_annotation(
                annotation,
                user=user,
                role=role,
                replies=serialized_replies,
            )
        )

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": end < total,
    }


def get_annotation_or_404(
    db: Session,
    *,
    audit_id: int,
    annotation_id: int,
) -> models.ReportAnnotation:
    annotation = (
        db.query(models.ReportAnnotation)
        .options(
            selectinload(models.ReportAnnotation.author),
            selectinload(models.ReportAnnotation.replies),
            selectinload(models.ReportAnnotation.parent),
        )
        .filter(
            models.ReportAnnotation.id == annotation_id,
            models.ReportAnnotation.audit_id == audit_id,
        )
        .first()
    )
    if annotation is None:
        raise HTTPException(status_code=404, detail="Report annotation not found.")
    return annotation


def create_annotation(
    db: Session,
    *,
    audit: models.Audit,
    project: models.Project,
    user: models.User,
    role: str,
    content: str,
    visibility: models.AnnotationVisibility,
    parent_id: int | None = None,
    section_path: str | None = None,
    source_recommendation_key: str | None = None,
    portal_mode: bool = False,
) -> models.ReportAnnotation:
    if portal_mode:
        if parent_id is None:
            raise HTTPException(
                status_code=400,
                detail="Client portal replies must target an existing annotation thread.",
            )
    elif not annotation_write_allowed(role):
        raise HTTPException(status_code=403, detail="Workspace write access required.")

    parent: models.ReportAnnotation | None = None
    if parent_id is not None:
        parent = get_annotation_or_404(db, audit_id=audit.id, annotation_id=parent_id)
        if parent.parent_id is not None:
            raise HTTPException(status_code=400, detail="Only one reply level is supported.")
        if parent.is_deleted:
            raise HTTPException(
                status_code=400, detail="Deleted annotation threads cannot receive new replies."
            )
        if portal_mode and parent.visibility != models.AnnotationVisibility.CLIENT_VISIBLE:
            raise HTTPException(
                status_code=403, detail="Portal replies require a client-visible thread."
            )
        section_path = parent.section_path
        source_recommendation_key = parent.source_recommendation_key
        visibility = parent.visibility
    elif portal_mode:
        raise HTTPException(
            status_code=400,
            detail="Client portal users cannot create top-level annotations.",
        )

    annotation = models.ReportAnnotation(
        audit_id=audit.id,
        project_id=project.id,
        user_id=user.id,
        parent_id=parent.id if parent is not None else None,
        section_path=(str(section_path or "").strip() or None),
        source_recommendation_key=resolve_source_recommendation_key(
            audit=audit,
            section_path=section_path,
            explicit_source_recommendation_key=source_recommendation_key,
        ),
        content=str(content).strip(),
        visibility=visibility,
        schema_version="1",
    )
    db.add(annotation)
    db.flush()
    db.refresh(annotation)
    return annotation


def update_annotation(
    db: Session,
    *,
    annotation: models.ReportAnnotation,
    user: models.User,
    role: str,
    content: str | None = None,
    visibility: models.AnnotationVisibility | None = None,
) -> models.ReportAnnotation:
    if annotation.is_deleted:
        raise HTTPException(status_code=400, detail="Deleted annotations cannot be edited.")
    if not _author_can_manage(annotation, user=user, role=role):
        raise HTTPException(status_code=403, detail="You cannot edit this annotation.")

    changed = False
    if content is not None and str(content).strip() != str(annotation.content or "").strip():
        annotation.content = str(content).strip()
        changed = True

    if visibility is not None:
        if not annotation_write_allowed(role):
            raise HTTPException(status_code=403, detail="Workspace write access required.")
        if annotation.parent_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Reply visibility is inherited from the parent thread.",
            )
        if annotation.visibility != visibility:
            annotation.visibility = visibility
            for reply in annotation.replies:
                reply.visibility = visibility
            changed = True

    if changed:
        db.flush()
        db.refresh(annotation)
    return annotation


def delete_annotation(
    db: Session,
    *,
    annotation: models.ReportAnnotation,
    user: models.User,
    role: str,
) -> models.ReportAnnotation:
    if not _author_can_manage(annotation, user=user, role=role):
        raise HTTPException(status_code=403, detail="You cannot delete this annotation.")
    if annotation.is_deleted:
        return annotation

    annotation.is_deleted = True
    db.flush()
    db.refresh(annotation)
    return annotation


def _project_team_recipients(
    db: Session,
    *,
    project: models.Project,
) -> list[models.User]:
    recipients: dict[int, models.User] = {}

    owner = db.query(models.User).filter(models.User.id == project.workspace.owner_id).first()
    if owner is not None:
        recipients[owner.id] = owner

    memberships = (
        db.query(models.WorkspaceUser, models.User)
        .join(models.User, models.User.id == models.WorkspaceUser.user_id)
        .filter(models.WorkspaceUser.workspace_id == project.workspace_id)
        .all()
    )
    for membership, member_user in memberships:
        if membership.role == models.WorkspaceRole.CLIENT_READONLY:
            continue
        recipients[member_user.id] = member_user

    return list(recipients.values())


def _resolve_frontend_base_url() -> str:
    frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
    app_base_url = (os.getenv("APP_BASE_URL") or "").strip()
    return (frontend_url or app_base_url or "http://localhost:3000").rstrip("/")


def queue_annotation_notifications(
    db: Session,
    *,
    project: models.Project,
    audit: models.Audit,
    annotation: models.ReportAnnotation,
) -> None:
    email_service = EmailService(db)
    dashboard_url = f"{_resolve_frontend_base_url()}/dashboard/projects/{project.id}/reports"
    context = {
        "project_name": project.name,
        "domain_url": project.domain_url,
        "audit_url": audit.url,
        "report_url": dashboard_url,
        "dashboard_url": dashboard_url,
        "annotation_content": str(annotation.content or "").strip()[:500],
        "annotation_author": _user_display_name(annotation.author),
    }

    if annotation.parent_id is None:
        for recipient in _project_team_recipients(db, project=project):
            if recipient.id == annotation.user_id:
                continue
            email_service.queue_template_email(
                to_email=recipient.email,
                template_key="annotation.created",
                context=context,
                user_id=recipient.id,
                correlation_id=f"annotation.created:{annotation.id}:{recipient.id}",
            )
        return

    parent = annotation.parent
    if parent is None or parent.user_id is None or parent.user_id == annotation.user_id:
        return

    parent_author = db.query(models.User).filter(models.User.id == parent.user_id).first()
    if parent_author is None:
        return

    reply_context = {
        **context,
        "thread_author": _user_display_name(parent_author),
    }
    email_service.queue_template_email(
        to_email=parent_author.email,
        template_key="annotation.replied",
        context=reply_context,
        user_id=parent_author.id,
        correlation_id=f"annotation.replied:{annotation.id}:{parent_author.id}",
    )
