"""Internal service-to-service endpoints for Qiko Signal (EPIC 2).

These are NOT part of the public external API. They are called by qiko-backend
(server-to-server) and authenticated with a shared service secret
(``settings.SIGNAL_PROVISION_SECRET``), never by end users.

Currently exposes per-tenant engine API-key provisioning: qiko-backend maps each
Signal tenant (a stable ``tenant_ref``, e.g. the Agent UUID) to a dedicated engine
user (via ``User.external_id``) and mints a scoped external API key so the engine
attributes credits/usage/cost to that tenant natively.
"""

from __future__ import annotations

import hmac
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from core.password_hashing import hash_password
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

import models
from core.config import settings
from schemas.auth import normalize_company_name
from database import get_db
from services.external_api_service import generate_api_key_material

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/signal", tags=["internal-signal"])

SIGNAL_TENANT_AUTH_PROVIDER = "signal_tenant"
# The minimal scope set the Signal flow needs (read scores, run scans).
SIGNAL_KEY_SCOPES: tuple[str, ...] = ("audit:read", "audit:write", "projects:read")


class ProvisionKeyRequest(BaseModel):
    tenant_ref: str
    name: str | None = None
    domain: str | None = None

    @field_validator("tenant_ref")
    @classmethod
    def _validate_tenant_ref(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("tenant_ref is required.")
        if len(cleaned) > 191:
            raise ValueError("tenant_ref is too long.")
        return cleaned


class ProvisionKeyResponse(BaseModel):
    api_key: str
    key_id: int
    key_prefix: str
    last_four: str
    scopes: list[str]
    tenant_ref: str
    user_id: int
    user_created: bool
    project_id: int
    workspace_id: int


def _ensure_tenant_project(
    db: Session,
    user: models.User,
    *,
    name: str | None,
    domain: str | None,
) -> models.Project:
    """Find-or-create the tenant's engine workspace + admin membership + default
    project so audits can be bound to a real project_id (and project-level buckets
    read real data). Idempotent: reuses the earliest existing workspace/project.
    """
    label = (name or f"Signal {user.external_id}")[:255]

    workspace = (
        db.query(models.Workspace)
        .filter(models.Workspace.owner_id == user.id)
        .order_by(models.Workspace.id.asc())
        .first()
    )
    if workspace is None:
        workspace = models.Workspace(name=label, owner_id=user.id)
        db.add(workspace)
        db.flush()

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=user.id,
            role=models.WorkspaceRole.ADMIN,
        )
        db.add(membership)
        db.flush()

    project = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace.id)
        .order_by(models.Project.id.asc())
        .first()
    )
    if project is None:
        project = models.Project(
            workspace_id=workspace.id,
            name=label,
            domain_url=(domain or None),
        )
        db.add(project)
        db.flush()

    return project


def require_service_secret(
    x_signal_service_secret: str | None = Header(default=None, alias="X-Signal-Service-Secret"),
) -> None:
    """Authenticate a service-to-service caller via the shared provisioning secret.

    503 when provisioning is disabled (no secret configured); 401 on mismatch.
    Uses a constant-time comparison to avoid timing oracles.
    """
    configured = (settings.SIGNAL_PROVISION_SECRET or "").strip()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signal provisioning is not enabled.",
        )
    provided = (x_signal_service_secret or "").strip()
    if not provided or not hmac.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials.",
        )


@router.post(
    "/provision-key",
    response_model=ProvisionKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
def provision_signal_key(
    payload: ProvisionKeyRequest,
    _: None = Depends(require_service_secret),
    db: Session = Depends(get_db),
) -> ProvisionKeyResponse:
    """Find-or-create the engine user for a Signal tenant and mint a scoped key.

    Idempotent on the user (keyed by ``external_id == tenant_ref``); a fresh API
    key is minted on each call (the caller stores the latest, encrypted). The raw
    key is returned exactly once and is never logged.
    """
    tenant_ref = payload.tenant_ref

    user = db.query(models.User).filter(models.User.external_id == tenant_ref).first()
    user_created = False
    if user is None:
        user = models.User(
            email=f"signal-tenant-{tenant_ref}@signal.qiko.internal",
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            external_id=tenant_ref,
            auth_provider=SIGNAL_TENANT_AUTH_PROVIDER,
            email_verified=True,
            role="user",
            credits=int(settings.SIGNAL_PROVISION_DEFAULT_CREDITS),
            # Internal tenant provisioning: cap like every other writer of
            # User.company_name; truncate, never reject a machine payload.
            company_name=normalize_company_name(
                payload.name or f"Signal {tenant_ref}", on_overlong="truncate"
            ),
        )
        db.add(user)
        db.flush()
        user_created = True

    project = _ensure_tenant_project(db, user, name=payload.name, domain=payload.domain)

    raw_key, key_hash, key_prefix, key_last_four = generate_api_key_material()
    api_key = models.ApiKey(
        user_id=user.id,
        name=(payload.name or f"signal:{tenant_ref}")[:255],
        key_hash=key_hash,
        key_prefix=key_prefix,
        key_last_four=key_last_four,
        scopes=list(SIGNAL_KEY_SCOPES),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    logger.info(
        "signal.provision_key tenant_ref=%s user_id=%s key_id=%s user_created=%s",
        tenant_ref,
        user.id,
        api_key.id,
        user_created,
    )

    return ProvisionKeyResponse(
        api_key=raw_key,
        key_id=api_key.id,
        key_prefix=key_prefix,
        last_four=key_last_four,
        scopes=list(SIGNAL_KEY_SCOPES),
        tenant_ref=tenant_ref,
        user_id=user.id,
        user_created=user_created,
        project_id=project.id,
        workspace_id=project.workspace_id,
    )
