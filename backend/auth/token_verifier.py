import logging
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWTError
from sqlalchemy.orm import Session

import models
from core.config import settings
from database import get_db
from services.workspace_rbac import (
    CLIENT_READONLY_PERMISSIONS,
    attach_portal_access_context,
)

logger = logging.getLogger(__name__)

JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_REFRESH_SECRET_KEY = settings.JWT_REFRESH_SECRET_KEY or JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM
ROLE_PERMISSIONS_MAP: dict[str, set[str]] = {
    "admin": {"*"},
    "moderator": {
        "audit:run",
        "audit:read",
        "profile:read",
        "profile:update",
        "admin:panel",
        "admin:trials",
        "admin:content",
        "admin:operations",
        "admin:monitoring",
        "admin:overview",
    },
    "user": {"audit:run", "audit:read", "profile:read", "profile:update"},
}

STAFF_ROLES: frozenset[str] = frozenset({"admin", "moderator"})


def get_admin_email_allowlist() -> set[str]:
    raw_value = str(getattr(settings, "ADMIN_EMAILS", "") or "")
    if not raw_value:
        return set()
    return {email.strip().lower() for email in raw_value.split(",") if email.strip()}


def get_moderator_email_allowlist() -> set[str]:
    raw_value = str(getattr(settings, "MODERATOR_EMAILS", "") or "")
    if not raw_value:
        return set()
    return {email.strip().lower() for email in raw_value.split(",") if email.strip()}


def should_promote_admin(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in get_admin_email_allowlist()


def should_promote_moderator(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in get_moderator_email_allowlist()


def apply_admin_promotion(user: models.User, email: str | None, db: Session) -> models.User:
    candidate_email = email or user.email
    if should_promote_admin(candidate_email) and user.role != "admin":
        user.role = "admin"
        db.commit()
        db.refresh(user)
    elif should_promote_moderator(candidate_email) and user.role not in STAFF_ROLES:
        user.role = "moderator"
        db.commit()
        db.refresh(user)
    return user


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization token missing.")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header.")
    return parts[1]


def _decode_jwt_token(token: str, *, is_refresh: bool) -> dict[str, Any]:
    secret_key = JWT_REFRESH_SECRET_KEY if is_refresh else JWT_SECRET_KEY
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token.") from exc

    expected_type = "refresh" if is_refresh else "access"
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode_jwt_token(token, is_refresh=False)


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode_jwt_token(token, is_refresh=True)


def extract_role_permissions(claims: dict[str, Any], user: models.User) -> tuple[str, list[str]]:
    role = str(getattr(user, "role", "user") or "user").strip().lower()

    if bool(getattr(user, "resolved_portal_only", False)):
        return role, list(CLIENT_READONLY_PERMISSIONS)

    token_role = claims.get("role")
    raw_permissions = claims.get("permissions")
    permissions: set[str]
    token_role_matches_user = isinstance(token_role, str) and token_role.strip().lower() == role
    if token_role_matches_user and isinstance(raw_permissions, list):
        permissions = {str(value) for value in raw_permissions if isinstance(value, str)}
    else:
        permissions = set(ROLE_PERMISSIONS_MAP.get(role, set()))

    return role, sorted(permissions)


def _resolve_user_from_claims(
    db: Session, claims: dict[str, Any]
) -> tuple[models.User, str | None]:
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Invalid authentication token payload.")

    if email is not None and not isinstance(email, str):
        email = None
    if isinstance(email, str):
        email = email.strip().lower()

    # Every token decoded by this path is minted by
    # services.auth_service.create_access_token, whose `sub` is str(user.id),
    # so resolution is a primary-key lookup only. The user row is never
    # mutated here (SIGV2-1268/1274), and an unresolvable subject is an
    # authentication failure with one generic response, never a reason to
    # create an account (SIGV2-1273).
    try:
        user_id = int(subject)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    return user, email


def get_current_user(
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> models.User:
    """
    Dependency to get the current authenticated user.
    Uses local JWT verification and promotes admins based on allowlist.
    """
    token = extract_bearer_token(authorization)
    claims = decode_access_token(token)
    user, email = _resolve_user_from_claims(db, claims)
    user = apply_admin_promotion(user, email, db)
    user = attach_portal_access_context(db, user=user)

    role, permissions = extract_role_permissions(claims, user)
    setattr(user, "resolved_role", role)
    setattr(user, "resolved_permissions", permissions)
    return user


def get_current_admin_user(user: Annotated[models.User, Depends(get_current_user)]) -> models.User:
    resolved_role = getattr(user, "resolved_role", user.role)
    if resolved_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def get_current_staff_user(user: Annotated[models.User, Depends(get_current_user)]) -> models.User:
    """Accept admin or moderator roles for general admin panel access."""
    resolved_role = getattr(user, "resolved_role", user.role)
    if resolved_role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Staff access required.")
    return user
