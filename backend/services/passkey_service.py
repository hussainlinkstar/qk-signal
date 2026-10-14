"""Passkey (WebAuthn / FIDO2) service layer.

Encapsulates py_webauthn calls, challenge management (Redis-backed), and
persistence via SQLAlchemy.  Designed to be consumed by the passkey router.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from core.config import settings
from core.redis_client import get_sync_redis_client

logger = logging.getLogger(__name__)

_CHALLENGE_PREFIX = "webauthn:challenge:"
_CHALLENGE_TTL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Helpers, Redis challenge store
# ---------------------------------------------------------------------------


def _redis_client():
    return get_sync_redis_client()


def store_challenge(user_id: int, challenge: bytes) -> None:
    """Persist the current challenge for a user so it can be verified later."""
    client = _redis_client()
    key = f"{_CHALLENGE_PREFIX}{user_id}"
    client.setex(key, _CHALLENGE_TTL_SECONDS, base64.urlsafe_b64encode(challenge).decode())
    client.close()


def pop_challenge(user_id: int) -> bytes | None:
    """Retrieve and delete the stored challenge (one-time use)."""
    client = _redis_client()
    key = f"{_CHALLENGE_PREFIX}{user_id}"
    pipe = client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = pipe.execute()
    client.close()
    raw = results[0]
    if raw:
        return base64.urlsafe_b64decode(raw)
    return None


def store_login_challenge(
    email_hint: str, challenge: bytes, *, allowed_credentials: list[dict] | None = None
) -> None:
    """Store challenge for passwordless login keyed by a stable identifier."""
    client = _redis_client()
    key = f"{_CHALLENGE_PREFIX}login:{email_hint}"
    payload = {
        "challenge": base64.urlsafe_b64encode(challenge).decode(),
        "allowed_credentials": allowed_credentials or [],
    }
    client.setex(key, _CHALLENGE_TTL_SECONDS, json.dumps(payload))
    client.close()


def pop_login_challenge(email_hint: str) -> tuple[bytes | None, list[dict]]:
    """Retrieve and delete the stored login challenge."""
    client = _redis_client()
    key = f"{_CHALLENGE_PREFIX}login:{email_hint}"
    pipe = client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = pipe.execute()
    client.close()
    raw = results[0]
    if raw:
        data = json.loads(raw)
        return base64.urlsafe_b64decode(data["challenge"]), data.get("allowed_credentials", [])
    return None, []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def generate_registration_options(db: Session, user: models.User) -> dict[str, Any]:
    """Build PublicKeyCredentialCreationOptions for the authenticated user."""
    from webauthn import generate_registration_options as _gen_reg_opts
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    existing_creds = (
        db.query(models.PasskeyCredential).filter(models.PasskeyCredential.user_id == user.id).all()
    )
    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64.urlsafe_b64decode(cred.credential_id + "=="),
            transports=cred.transports or [],
        )
        for cred in existing_creds
    ]

    rp_id = settings.WEBAUTHN_RP_ID
    rp_name = settings.WEBAUTHN_RP_NAME

    options = _gen_reg_opts(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.company_name or user.email,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        timeout=60000,
    )

    store_challenge(user.id, options.challenge)

    from webauthn.helpers import options_to_json

    return json.loads(options_to_json(options))


def verify_registration(
    db: Session,
    user: models.User,
    credential: dict,
    name: str,
) -> models.PasskeyCredential:
    """Verify the attestation response and persist the new passkey."""
    from webauthn import verify_registration_response
    from webauthn.helpers import parse_registration_credential_json

    challenge = pop_challenge(user.id)
    if not challenge:
        raise ValueError("Registration challenge expired or missing. Please try again.")

    reg_credential = parse_registration_credential_json(json.dumps(credential))

    verification = verify_registration_response(
        credential=reg_credential,
        expected_challenge=challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,
    )

    credential_id_b64 = base64.urlsafe_b64encode(verification.credential_id).decode().rstrip("=")

    public_key_b64 = base64.urlsafe_b64encode(verification.credential_public_key).decode()

    passkey = models.PasskeyCredential(
        user_id=user.id,
        credential_id=credential_id_b64,
        public_key=public_key_b64,
        sign_count=verification.sign_count,
        name=name or "My Passkey",
        transports=(
            [
                str(t.value) if hasattr(t, "value") else str(t)
                for t in (credential.get("response", {}).get("transports") or [])
            ]
            if credential.get("response", {}).get("transports")
            else None
        ),
        backed_up=getattr(verification, "credential_backed_up", False),
    )
    db.add(passkey)
    db.commit()
    db.refresh(passkey)
    return passkey


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def generate_authentication_options(db: Session, email: str | None = None) -> dict[str, Any]:
    """Build PublicKeyCredentialRequestOptions.

    If *email* is provided, restrict allowed credentials to that user's
    registered passkeys (conditional UI).  Otherwise, ask for a discoverable
    credential.
    """
    from webauthn import generate_authentication_options as _gen_auth_opts
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor,
        UserVerificationRequirement,
    )
    from webauthn.helpers import options_to_json

    allow_credentials: list[PublicKeyCredentialDescriptor] = []

    if email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            creds = (
                db.query(models.PasskeyCredential)
                .filter(models.PasskeyCredential.user_id == user.id)
                .all()
            )
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    id=base64.urlsafe_b64decode(c.credential_id + "=="),
                    transports=c.transports or [],
                )
                for c in creds
            ]

    options = _gen_auth_opts(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials or None,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    hint = email or "__discoverable__"
    allowed_raw = [
        {
            "id": base64.urlsafe_b64encode(ac.id).decode().rstrip("="),
            "transports": ac.transports or [],
        }
        for ac in allow_credentials
    ]
    store_login_challenge(hint, options.challenge, allowed_credentials=allowed_raw)

    result = json.loads(options_to_json(options))
    result["_challenge_hint"] = hint
    return result


def verify_authentication(
    db: Session,
    credential: dict,
    challenge_hint: str | None = None,
) -> models.User:
    """Verify the assertion response and return the authenticated user."""
    from webauthn import verify_authentication_response
    from webauthn.helpers import parse_authentication_credential_json

    # Determine the credential_id from the response
    raw_id_b64 = credential.get("rawId") or credential.get("id", "")
    # Normalise to standard base64url (no padding)
    credential_id_b64 = raw_id_b64.rstrip("=")

    passkey = (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.credential_id == credential_id_b64)
        .first()
    )
    if not passkey:
        raise ValueError("Passkey not recognised. Please try a different one.")

    user = db.query(models.User).filter(models.User.id == passkey.user_id).first()
    if not user:
        raise ValueError("User associated with passkey not found.")

    # Pop the correct challenge
    hint = challenge_hint or user.email or "__discoverable__"
    challenge, _ = pop_login_challenge(hint)
    if not challenge:
        # Try discoverable fallback
        challenge, _ = pop_login_challenge("__discoverable__")
    if not challenge:
        raise ValueError("Authentication challenge expired or missing. Please try again.")

    public_key_bytes = base64.urlsafe_b64decode(passkey.public_key)

    auth_credential = parse_authentication_credential_json(json.dumps(credential))

    verification = verify_authentication_response(
        credential=auth_credential,
        expected_challenge=challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,
        credential_public_key=public_key_bytes,
        credential_current_sign_count=passkey.sign_count,
    )

    # Update sign count and last-used timestamp
    passkey.sign_count = verification.new_sign_count
    passkey.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return user


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def user_has_passkeys(db: Session, email: str) -> bool:
    """Check whether the given email has any registered passkeys.

    Returns ``False`` for unknown emails so the endpoint does not leak
    account-existence information.
    """
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return False
    return (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.user_id == user.id)
        .limit(1)
        .count()
    ) > 0


def list_passkeys(db: Session, user_id: int) -> list[models.PasskeyCredential]:
    return (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.user_id == user_id)
        .order_by(models.PasskeyCredential.created_at.desc())
        .all()
    )


def rename_passkey(
    db: Session, user_id: int, passkey_id: int, new_name: str
) -> models.PasskeyCredential | None:
    passkey = (
        db.query(models.PasskeyCredential)
        .filter(
            models.PasskeyCredential.id == passkey_id,
            models.PasskeyCredential.user_id == user_id,
        )
        .first()
    )
    if not passkey:
        return None
    passkey.name = new_name
    db.commit()
    db.refresh(passkey)
    return passkey


def delete_passkey(db: Session, user_id: int, passkey_id: int) -> bool:
    passkey = (
        db.query(models.PasskeyCredential)
        .filter(
            models.PasskeyCredential.id == passkey_id,
            models.PasskeyCredential.user_id == user_id,
        )
        .first()
    )
    if not passkey:
        return False
    db.delete(passkey)
    db.commit()
    return True
