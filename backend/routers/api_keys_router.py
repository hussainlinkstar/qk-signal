from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature, resolve_entitled_subscription_plan
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from services.external_api_service import (
    generate_api_key_material,
    serialize_api_key,
    validate_api_key_scopes,
)
from services.workspace_rbac import require_not_portal_only

router = APIRouter(tags=["API Keys"])


class ApiKeySummary(BaseModel):
    id: int
    name: str
    key_prefix: str
    key_last_four: str | None = None
    scopes: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeySummary]
    plan_type: str
    api_access_enabled: bool
    mcp_access_enabled: bool
    developer_hub_url: str


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    scopes: list[str] | None = Field(default=None, validate_default=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Key name is required.")
        return normalized

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str] | None) -> list[str]:
        return validate_api_key_scopes(value)


class ApiKeyCreateResponse(BaseModel):
    api_key: str
    item: ApiKeySummary
    developer_hub_url: str


class ApiKeyDeleteResponse(BaseModel):
    revoked: bool
    item: ApiKeySummary


def _api_access_state(user: models.User) -> tuple[str, bool, bool]:
    plan_type = resolve_entitled_subscription_plan(user) or "plan_starter"
    return (
        plan_type,
        can_use_feature(plan_type, "api_access"),
        can_use_feature(plan_type, "mcp_access"),
    )


@router.get("/settings/api-keys", response_model=ApiKeyListResponse)
def list_api_keys(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot manage API keys.")
    plan_type, api_access_enabled, mcp_access_enabled = _api_access_state(user)
    keys = (
        db.query(models.ApiKey)
        .filter(models.ApiKey.user_id == user.id)
        .order_by(models.ApiKey.created_at.desc(), models.ApiKey.id.desc())
        .all()
    )
    return {
        "items": [serialize_api_key(api_key) for api_key in keys],
        "plan_type": plan_type,
        "api_access_enabled": api_access_enabled,
        "mcp_access_enabled": mcp_access_enabled,
        "developer_hub_url": "/dashboard/developer",
    }


@router.post(
    "/settings/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED
)
def create_api_key(
    payload: ApiKeyCreateRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot manage API keys.")
    plan_type, api_access_enabled, _ = _api_access_state(user)
    if not api_access_enabled:
        raise HTTPException(
            status_code=403,
            detail="API keys are available on active Specialist and Executive plans.",
        )

    raw_key, key_hash, key_prefix, key_last_four = generate_api_key_material()
    api_key = models.ApiKey(
        user_id=user.id,
        name=payload.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        key_last_four=key_last_four,
        scopes=validate_api_key_scopes(payload.scopes),
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "api_key": raw_key,
        "item": serialize_api_key(api_key),
        "developer_hub_url": "/dashboard/developer",
        "plan_type": plan_type,
    }


@router.delete("/settings/api-keys/{api_key_id}", response_model=ApiKeyDeleteResponse)
def revoke_api_key(
    api_key_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot manage API keys.")
    api_key = (
        db.query(models.ApiKey)
        .filter(models.ApiKey.id == api_key_id, models.ApiKey.user_id == user.id)
        .first()
    )
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found.")

    api_key.is_active = False
    api_key.revoked_at = api_key.revoked_at or datetime.now(timezone.utc)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "revoked": True,
        "item": serialize_api_key(api_key),
    }
