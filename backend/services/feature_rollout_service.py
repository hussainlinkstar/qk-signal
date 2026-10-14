from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

import models


@dataclass(frozen=True)
class FeatureRolloutState:
    key: str
    description: str | None
    is_enabled: bool
    rollout_percentage: int
    updated_at: str | None
    source: str


def _normalize_rollout_percentage(value: int | None, *, default: int = 100) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, 100))


def get_feature_rollout_state(
    db: Session,
    *,
    key: str,
    default_enabled: bool,
    default_rollout_percentage: int = 100,
    default_description: str | None = None,
) -> FeatureRolloutState:
    flag = db.query(models.FeatureFlag).filter(models.FeatureFlag.key == key).first()
    if flag is None:
        return FeatureRolloutState(
            key=key,
            description=default_description,
            is_enabled=bool(default_enabled),
            rollout_percentage=_normalize_rollout_percentage(default_rollout_percentage),
            updated_at=None,
            source="default",
        )

    return FeatureRolloutState(
        key=flag.key,
        description=(flag.description or default_description),
        is_enabled=bool(flag.is_enabled),
        rollout_percentage=_normalize_rollout_percentage(
            flag.rollout_percentage,
            default=default_rollout_percentage,
        ),
        updated_at=flag.updated_at.isoformat() if flag.updated_at else None,
        source="feature_flag",
    )


def is_actor_in_feature_rollout(
    db: Session,
    *,
    key: str,
    actor_key: str | int | None,
    default_enabled: bool,
    default_rollout_percentage: int = 100,
    default_description: str | None = None,
) -> bool:
    state = get_feature_rollout_state(
        db,
        key=key,
        default_enabled=default_enabled,
        default_rollout_percentage=default_rollout_percentage,
        default_description=default_description,
    )
    if not state.is_enabled:
        return False
    if state.rollout_percentage >= 100:
        return True
    if state.rollout_percentage <= 0:
        return False
    normalized_actor_key = str(actor_key or "").strip()
    if not normalized_actor_key:
        return False

    digest = hashlib.sha256(normalized_actor_key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < state.rollout_percentage


def upsert_feature_rollout(
    db: Session,
    *,
    key: str,
    description: str | None,
    is_enabled: bool,
    rollout_percentage: int,
) -> models.FeatureFlag:
    flag = db.query(models.FeatureFlag).filter(models.FeatureFlag.key == key).first()
    if flag is None:
        flag = models.FeatureFlag(
            key=key,
            description=description,
            is_enabled=bool(is_enabled),
            rollout_percentage=_normalize_rollout_percentage(rollout_percentage),
        )
        db.add(flag)
        db.flush()
        return flag

    flag.description = description
    flag.is_enabled = bool(is_enabled)
    flag.rollout_percentage = _normalize_rollout_percentage(rollout_percentage)
    db.flush()
    return flag
