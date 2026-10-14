"""Per-plan cap on tracked SERP keywords (SIGV2-1150).

Every tracked keyword costs one DataForSEO SERP task per monitoring cycle:
``DataForSEOService.sync_serp_data`` posts exactly one ``task_post`` per active
keyword and the monitoring worker's default interval is daily, so an uncapped
keyword list is an uncapped recurring cost. Tracked prompts have been capped per
plan since SIGV2-1142; keywords are the same class of metered, per-cycle
resource, so the cap lives in the same capability matrix and the refusal uses
the same wording.

Enforcement is on creation only, and that is deliberate. A project that already
tracks more keywords than its plan now allows keeps every one of them: nothing
here deactivates a row, no migration touches ``target_keywords``, and the
monitoring worker's own query (``is_active``, with no plan lookup) is untouched,
so existing keywords keep syncing.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    CAPABILITY_MATRIX,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from services.plan_limit_messaging import tracked_limit_detail

# The capability key that carries the allowance, and the plan assumed when a
# project's owner has no entitled subscription or trial.
KEYWORD_ALLOWANCE_KEY = "max_tracked_keywords"
DEFAULT_PLAN = "plan_starter"


def keyword_allowances() -> dict[str, int]:
    """The keyword cap ladder, plan id to cap (negative means unlimited)."""
    return {
        plan: int(capabilities.get(KEYWORD_ALLOWANCE_KEY, 0))
        for plan, capabilities in CAPABILITY_MATRIX.items()
    }


def resolve_project_plan(project: models.Project) -> str:
    """The plan whose allowance applies to ``project``.

    Resolved exactly as the prompt cap resolves it: the workspace owner's
    entitled subscription, else their trial plan, else the free plan.
    """
    workspace = getattr(project, "workspace", None)
    owner = getattr(workspace, "owner", None) if workspace is not None else None
    subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(owner))
    trial_plan = resolve_plan_alias(getattr(owner, "trial_plan", None))
    return subscription_plan or trial_plan or DEFAULT_PLAN


def max_tracked_keywords(plan: str) -> int:
    """The keyword allowance for ``plan``, falling back to the free plan."""
    allowances = keyword_allowances()
    if plan in allowances:
        return allowances[plan]
    return allowances.get(DEFAULT_PLAN, 0)


def count_active_keywords(db: Session, project_id: int) -> int:
    """Active keywords only: a soft-deleted keyword costs nothing per cycle."""
    return (
        db.query(models.TargetKeyword)
        .filter(
            models.TargetKeyword.project_id == project_id,
            models.TargetKeyword.is_active.is_(True),
        )
        .count()
    )


def enforce_keyword_limit(db: Session, project: models.Project) -> None:
    """Refuse with 402 when ``project`` is at or over its keyword allowance.

    Called before a keyword starts being tracked, which includes reactivating a
    soft-deleted one: reactivation puts a keyword back on the paid sync cycle,
    so leaving it ungated would be a hole straight through the cap.
    """
    plan = resolve_project_plan(project)
    maximum = max_tracked_keywords(plan)
    if maximum < 0:
        return

    used = count_active_keywords(db, project.id)
    if used < maximum:
        return

    raise HTTPException(
        status_code=402,
        detail=tracked_limit_detail(
            plan=plan,
            used=used,
            maximum=maximum,
            allowances=keyword_allowances(),
            noun_singular="keyword",
            noun_plural="keywords",
        ),
    )
