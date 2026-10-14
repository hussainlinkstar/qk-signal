from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from app.services.compliance.plan_validator import PlanValidator
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from services.benchmark_engine import BenchmarkEngine
from services.proprietary_score_registry import ProprietaryScoreRegistry
from services.workspace_rbac import resolve_project_access


router = APIRouter(prefix="/api/v1/projects", tags=["Signal Benchmarks"])
plan_validator = PlanValidator()


class BenchmarkPercentileResponse(BaseModel):
    """Peer-benchmark comparison. Statistics carry explicit names: `percentile`
    is the project's estimated percentile rank and `cohort_mean` is the cohort
    arithmetic mean - they are never interchangeable. `unit` travels with the
    values ("score" = points out of 100, "ratio" = 0-1 proportion with
    `denominator`). The queried project is one observation inside its own
    cohort. Below suppression thresholds, cohort statistics are withheld."""

    project_id: int
    metric: str
    status: str
    percentile: float | None = None
    top_percent: int | None = None
    cohort_key: str | None = None
    cohort_label: str | None = None
    cohort_size: int = 0
    project_value: float | None = None
    period_date: str | None = None
    cohort_mean: float | None = None
    unit: str | None = None
    denominator: str | None = None
    source: str | None = None
    unavailable_reason: str | None = None


class ProprietaryScoreResponse(BaseModel):
    project_id: int
    score_type: str
    score_version: str
    status: str
    value: float | None = None
    confidence: str
    data_points_used: int
    components: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, Any] = Field(default_factory=dict)
    computed_at: str


def _require_signal_benchmark_access(user: models.User) -> None:
    if plan_validator.has_feature(user, "entity_authority"):
        return
    detail = "Benchmark intelligence requires Specialist or Executive."
    if plan_validator.is_basic_plan(user):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.get("/{project_id}/benchmark", response_model=BenchmarkPercentileResponse)
def get_project_benchmark_percentile(
    project_id: int,
    metric: str = Query(default="geo_score"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BenchmarkPercentileResponse:
    _require_signal_benchmark_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    benchmark_engine = BenchmarkEngine()
    result = benchmark_engine.get_project_percentile(db=db, project_id=project_id, metric=metric)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Benchmark metric is not available for this project."
        )
    return BenchmarkPercentileResponse.model_validate(result.as_dict())


@router.get("/{project_id}/citation-stability", response_model=ProprietaryScoreResponse)
def get_project_citation_stability(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProprietaryScoreResponse:
    _require_signal_benchmark_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    score_registry = ProprietaryScoreRegistry()
    result = score_registry.summarize_citation_stability(db=db, project_id=project_id)
    return ProprietaryScoreResponse.model_validate(result.as_dict())


@router.get("/{project_id}/remediation-impact", response_model=ProprietaryScoreResponse)
def get_project_remediation_impact(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProprietaryScoreResponse:
    _require_signal_benchmark_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    score_registry = ProprietaryScoreRegistry()
    result = score_registry.summarize_remediation_impact(db=db, project_id=project_id)
    return ProprietaryScoreResponse.model_validate(result.as_dict())


@router.get("/{project_id}/pipeline-quality", response_model=ProprietaryScoreResponse)
def get_project_pipeline_quality(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProprietaryScoreResponse:
    _require_signal_benchmark_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    score_registry = ProprietaryScoreRegistry()
    result = score_registry.summarize_pipeline_quality(db=db, project_id=project_id)
    return ProprietaryScoreResponse.model_validate(result.as_dict())


@router.get("/{project_id}/provider-cost-efficiency", response_model=ProprietaryScoreResponse)
def get_project_provider_cost_efficiency(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProprietaryScoreResponse:
    _require_signal_benchmark_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)

    score_registry = ProprietaryScoreRegistry()
    result = score_registry.summarize_provider_cost_efficiency(db=db, project_id=project_id)
    return ProprietaryScoreResponse.model_validate(result.as_dict())
