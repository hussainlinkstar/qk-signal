from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from services.entity_authority_service import EntityAuthorityService
from services.project_intelligence_service import require_project_feature_access
from services.workspace_rbac import resolve_project_access, require_workspace_write_access


router = APIRouter(prefix="/api/v1/projects", tags=["Entity Authority"])


class EntityAuthorityBreakdownResponse(BaseModel):
    coverage: float
    depth: float
    consistency: float
    uniqueness: float


class EntityAuthorityResponse(BaseModel):
    project_id: int
    authority_score: float
    breakdown: EntityAuthorityBreakdownResponse
    target_entities: int
    detected_entities: int
    gap_count: int
    computed_at: str
    computation_version: str


class EntityGapResponse(BaseModel):
    entity_key: str
    entity_name: str
    reason: str


class EntityAuthorityTrendPointResponse(BaseModel):
    authority_score: float
    coverage_score: float
    depth_score: float
    consistency_score: float
    uniqueness_score: float
    target_entity_count: int
    detected_entity_count: int
    gap_count: int
    computed_at: str
    computation_version: str


class EntityAuthorityTrendResponse(BaseModel):
    project_id: int
    points: list[EntityAuthorityTrendPointResponse] = Field(default_factory=list)


class EntityGraphResponse(BaseModel):
    project_id: int
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    url_mentions: list[str] = Field(default_factory=list)
    missing_target_entities: list[EntityGapResponse] = Field(default_factory=list)
    audit_count: int


def _require_entity_authority_access(user: models.User) -> None:
    require_project_feature_access(user, "entity_authority")


@router.get("/{project_id}/entity-authority", response_model=EntityAuthorityResponse)
def get_project_entity_authority(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntityAuthorityResponse:
    _require_entity_authority_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    service = EntityAuthorityService()
    result = service.get_latest_snapshot(db=db, project_id=project_id)
    if result is None:
        result = service.compute_score(db=db, project_id=project_id)
        db.commit()

    return EntityAuthorityResponse.model_validate(result.as_dict())


@router.get("/{project_id}/entity-graph", response_model=EntityGraphResponse)
def get_project_entity_graph(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntityGraphResponse:
    _require_entity_authority_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    service = EntityAuthorityService()
    payload = service.build_project_graph(db=db, project_id=project_id)
    return EntityGraphResponse.model_validate(payload)


@router.get("/{project_id}/entity-authority/gaps", response_model=list[EntityGapResponse])
def get_project_entity_authority_gaps(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EntityGapResponse]:
    _require_entity_authority_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    service = EntityAuthorityService()
    return [
        EntityGapResponse.model_validate(gap.as_dict())
        for gap in service.compute_gaps(db=db, project_id=project_id)
    ]


@router.get("/{project_id}/entity-authority/trend", response_model=EntityAuthorityTrendResponse)
def get_project_entity_authority_trend(
    project_id: int,
    limit: int = 12,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntityAuthorityTrendResponse:
    _require_entity_authority_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    service = EntityAuthorityService()
    points = [
        EntityAuthorityTrendPointResponse.model_validate(item.as_dict())
        for item in service.compute_trend(db=db, project_id=project_id, limit=limit)
    ]
    return EntityAuthorityTrendResponse(project_id=project_id, points=points)


@router.post("/{project_id}/entity-authority/compute", response_model=EntityAuthorityResponse)
def recompute_project_entity_authority(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntityAuthorityResponse:
    _require_entity_authority_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)

    service = EntityAuthorityService()
    result = service.compute_score(db=db, project_id=project_id)
    db.commit()
    return EntityAuthorityResponse.model_validate(result.as_dict())
