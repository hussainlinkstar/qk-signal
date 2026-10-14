"""Passkey (WebAuthn / FIDO2) API router.

Provides registration and authentication endpoints as well as CRUD
operations for managing a user's registered passkeys.

Mounted at ``/api/v1/auth/passkeys`` via ``main.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from schemas.auth import (
    PasskeyDeleteResponse,
    PasskeyListItem,
    PasskeyLoginOptionsResponse,
    PasskeyLoginVerifyRequest,
    PasskeyRegistrationOptionsResponse,
    PasskeyRegistrationVerifyRequest,
    PasskeyRegistrationVerifyResponse,
    PasskeyRenameRequest,
    Token,
)
from services.auth_service import AuthService
from services.passkey_service import (
    delete_passkey,
    generate_authentication_options,
    generate_registration_options,
    list_passkeys,
    rename_passkey,
    user_has_passkeys,
    verify_authentication,
    verify_registration,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])


# ---------------------------------------------------------------------------
# Registration (requires authenticated session)
# ---------------------------------------------------------------------------


@router.get("/register/generate-options", response_model=PasskeyRegistrationOptionsResponse)
async def passkey_register_options(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Generate WebAuthn registration options for the current user."""
    try:
        options = generate_registration_options(db, current_user)
        return {"options": options}
    except Exception as exc:
        logger.exception("Failed to generate passkey registration options")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/register/verify", response_model=PasskeyRegistrationVerifyResponse)
async def passkey_register_verify(
    payload: PasskeyRegistrationVerifyRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Verify the attestation response and persist the new passkey."""
    try:
        passkey = verify_registration(
            db,
            current_user,
            credential=payload.credential,
            name=payload.name,
        )
        return {
            "id": passkey.id,
            "credential_id": passkey.credential_id,
            "name": passkey.name,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to verify passkey registration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Passkey registration failed. Please try again.",
        ) from exc


# ---------------------------------------------------------------------------
# Authentication (public, no session required)
# ---------------------------------------------------------------------------


@router.get("/has-credentials")
async def passkey_has_credentials(
    email: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Check whether the given email has any registered passkeys.

    Public endpoint used by the login form to conditionally show the
    passkey sign-in button.  Returns ``{has_passkeys: false}`` for
    unknown emails to avoid leaking account-existence information.
    """
    return {"has_passkeys": user_has_passkeys(db, email)}


@router.get("/login/generate-options", response_model=PasskeyLoginOptionsResponse)
async def passkey_login_options(
    email: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """Generate WebAuthn authentication options.

    If *email* is provided, the response restricts allowed credentials to
    that user's registered passkeys.  Otherwise a discoverable credential
    is requested.
    """
    try:
        options = generate_authentication_options(db, email=email)
        return {"options": options}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate passkey login options")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/login/verify", response_model=Token)
async def passkey_login_verify(
    payload: PasskeyLoginVerifyRequest,
    db: Session = Depends(get_db),
) -> Any:
    """Verify the assertion response and issue JWT tokens, identical to
    the standard ``/auth/login`` response."""
    try:
        # Extract challenge hint if provided (injected by frontend)
        challenge_hint = payload.credential.pop("_challenge_hint", None)
        user = verify_authentication(
            db, credential=payload.credential, challenge_hint=challenge_hint
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Passkey authentication failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passkey authentication failed. Please try again.",
        ) from exc

    auth_service = AuthService(db)
    return auth_service.build_token_response(user)


# ---------------------------------------------------------------------------
# Management (requires authenticated session)
# ---------------------------------------------------------------------------


@router.get("/list", response_model=list[PasskeyListItem])
async def passkey_list(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """List all passkeys for the current user."""
    creds = list_passkeys(db, current_user.id)
    return [
        {
            "id": c.id,
            "credential_id": c.credential_id,
            "name": c.name,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            "backed_up": c.backed_up,
        }
        for c in creds
    ]


@router.patch("/{passkey_id}", response_model=PasskeyListItem)
async def passkey_rename(
    passkey_id: int,
    payload: PasskeyRenameRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Rename an existing passkey."""
    passkey = rename_passkey(db, current_user.id, passkey_id, payload.name)
    if not passkey:
        raise HTTPException(status_code=404, detail="Passkey not found")
    return {
        "id": passkey.id,
        "credential_id": passkey.credential_id,
        "name": passkey.name,
        "created_at": passkey.created_at.isoformat() if passkey.created_at else None,
        "last_used_at": passkey.last_used_at.isoformat() if passkey.last_used_at else None,
        "backed_up": passkey.backed_up,
    }


@router.delete("/{passkey_id}", response_model=PasskeyDeleteResponse)
async def passkey_delete(
    passkey_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Delete a passkey."""
    deleted = delete_passkey(db, current_user.id, passkey_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Passkey not found")
    return {"deleted": True}
