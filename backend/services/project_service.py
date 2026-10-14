"""Project cloning and archive/unarchive logic (AEX-40 Phase 3)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

import models


def clone_project(
    db: Session,
    *,
    source_project: models.Project,
    new_name: str,
    new_domain_url: str | None = None,
    workspace_id: int,
) -> models.Project:
    """Clone a project's settings into a new project.

    Copies: target_country, language, icp_roles, pain_points, usp,
    competitors_json, tags.
    Does NOT copy: audits, connections, budget, bot_log_sources, etc.
    """
    new_project = models.Project(
        workspace_id=workspace_id,
        name=new_name,
        domain_url=new_domain_url,
        target_country=source_project.target_country,
        language=source_project.language or "en",
        icp_roles=list(source_project.icp_roles or []),
        pain_points=source_project.pain_points,
        usp=source_project.usp,
        competitors_json=list(source_project.competitors_json or []),
        priority_pulse_tags=list(source_project.priority_pulse_tags or []),
        sme_profiles=list(source_project.sme_profiles or []),
        tags=list(source_project.tags or []),
        cloned_from_id=source_project.id,
    )
    db.add(new_project)
    db.flush()
    return new_project


def archive_project(
    db: Session,
    *,
    project: models.Project,
) -> models.Project:
    """Archive a project."""
    project.status = models.ProjectStatus.ARCHIVED
    project.archived_at = datetime.now(timezone.utc)
    db.flush()
    return project


def unarchive_project(
    db: Session,
    *,
    project: models.Project,
) -> models.Project:
    """Restore an archived project to active status."""
    project.status = models.ProjectStatus.ACTIVE
    project.archived_at = None
    db.flush()
    return project
