"""Project score targets: effective target resolution and gap projection.

Score sources are the canonical ones already used by the application:

- SEO: ``Audit.seo_score`` of the latest audit (the persisted ``scores.seo``
  value, which ``audit_normalization_service`` treats as authoritative over
  stale section mirrors).
- AIO: the ``derive_aio`` roll-up from ``app.services.aio_view`` applied to
  the latest audit's AEO and GEO scores. No new AIO formula.

Gap semantics: ``gap = max(0, target - current)`` when a current score was
measured, ``None`` when nothing has been measured yet (never ``target - 0``).
A score at or above target reports a zero gap, never negative.
"""

from __future__ import annotations

from typing import Any

import models
from app.services.aio_view import derive_aio
from core.config import settings


def _target_view(*, current: float | None, target: int, measured_at: str | None) -> dict[str, Any]:
    if current is None:
        return {
            "current": None,
            "target": target,
            "gap": None,
            "measured_at": measured_at,
        }
    return {
        "current": current,
        "target": target,
        "gap": max(0, target - current),
        "measured_at": measured_at,
    }


def resolve_project_score_targets(
    project: models.Project,
    *,
    latest_seo_score: float | None,
    latest_geo_score: float | None,
    latest_aeo_score: float | None,
    measured_at: str | None,
) -> dict[str, Any]:
    """Project the per-dimension target view for response serialization.

    The target is the persisted per-project override when set, otherwise the
    configured product default.
    """
    aio_score = derive_aio({"aeo_score": latest_aeo_score, "geo_score": latest_geo_score}).get(
        "aio_score"
    )

    aio_target = (
        project.aio_score_target
        if project.aio_score_target is not None
        else int(settings.PROJECT_DEFAULT_AIO_SCORE_TARGET)
    )
    seo_target = (
        project.seo_score_target
        if project.seo_score_target is not None
        else int(settings.PROJECT_DEFAULT_SEO_SCORE_TARGET)
    )

    return {
        "aio": _target_view(current=aio_score, target=aio_target, measured_at=measured_at),
        "seo": _target_view(current=latest_seo_score, target=seo_target, measured_at=measured_at),
    }
