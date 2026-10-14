from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
import base64
import hashlib
import json
import os
import secrets
from urllib.parse import urlparse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Any
from core.redis_client import get_async_redis
from database import get_db
from auth.security import get_current_user_from_token as get_current_user
from auth.token_verifier import decode_access_token, decode_refresh_token, extract_bearer_token
from middleware.rate_limiter import rate_limiter
from middleware.session_checker import (
    deactivate_user_sessions,
    revoke_session_jti,
    revoke_session_jtis,
)
from schemas.auth import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    PasswordReset,
    EmailVerification,
    LinkedIdentityListResponse,
    LinkedIdentityStartRequest,
    LinkedIdentityStartResponse,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    LogoutRequest,
    ResendVerificationRequest,
)
from services.auth_service import (
    AuthService,
    IDENTITY_LINK_TOKEN_EXPIRE_SECONDS,
    LinkedIdentityAlreadyClaimed,
    ManualAccountLinkRequired,
    REFRESH_TOKEN_EXPIRE_DAYS,
    provider_display_name,
)
from services.oauth_service import oauth
from auth.mfa import (
    MFAVerificationResult,
    mfa_throttle_retry_after,
    verify_totp_code_for_user,
)
import models
from core.password_hashing import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

_TOKEN_DENYLIST_PREFIX = "token:denied:"
_OAUTH_CODE_PREFIX = "oauth:code:"
_OAUTH_CODE_TTL_SECONDS = 60
_RESEND_VERIFICATION_PREFIX = "auth:resend_verification:"
_RESEND_VERIFICATION_TTL_SECONDS = 60
_OAUTH_LOGIN_PROVIDERS = {"google", "github", "microsoft", "linkedin"}
_TRIAL_TOKEN_SESSION_PREFIX = "_trial_token_"

# SIGV2-1257: only Microsoft is offered for manual linking. It is the one
# provider whose id_token routinely omits email_verified, so it is the only
# one SIGV2-1239's refusal strands. Widening this set means testing the
# provider's own claim behaviour first.
_IDENTITY_LINK_PROVIDERS = {"microsoft"}
_IDENTITY_LINK_SESSION_PREFIX = "_identity_link_"
_IDENTITY_LINK_NONCE_PREFIX = "auth:identity_link:"

# Session keys that are safe to purge before a new OAuth login attempt.
# Stale entries from abandoned OAuth flows accumulate and can push the
# signed session cookie past the browser's 4 KB limit, causing silent
# Set-Cookie drops and CSRF state-mismatch errors on every subsequent attempt.
_STALE_SESSION_PREFIXES = (
    "_state_",  # authlib OAuth state
    _TRIAL_TOKEN_SESSION_PREFIX,  # trial token per provider
    _IDENTITY_LINK_SESSION_PREFIX,  # armed account link per provider
    "_magic_link_oauth_",  # magic link OAuth (workspace_router)
    "_workspace_oauth_",  # workspace OAuth (workspace_router)
    "_slack_oauth_",  # Slack OAuth (slack_router)
)


async def _store_oauth_code(access_token: str, refresh_token: str) -> str:
    """Store tokens in Redis under a one-time code and return the code."""
    code = secrets.token_urlsafe(48)
    try:
        async with get_async_redis() as client:
            payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token})
            await client.setex(f"{_OAUTH_CODE_PREFIX}{code}", _OAUTH_CODE_TTL_SECONDS, payload)
    except Exception:
        pass
    return code


async def _exchange_oauth_code(code: str) -> dict | None:
    """Exchange a one-time code for tokens, deleting the code atomically."""
    try:
        async with get_async_redis() as client:
            key = f"{_OAUTH_CODE_PREFIX}{code}"
            raw = await client.getdel(key)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None


async def _deny_refresh_token(token: str) -> None:
    """Add a refresh token hash to the Redis deny list with TTL."""
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        ttl_seconds = REFRESH_TOKEN_EXPIRE_DAYS * 86400
        try:
            payload = decode_refresh_token(token)
            exp = payload.get("exp")
            if isinstance(exp, (int, float)):
                remaining_seconds = max(1, int(float(exp) - datetime.now(timezone.utc).timestamp()))
                ttl_seconds = remaining_seconds
        except HTTPException:
            pass
        async with get_async_redis() as client:
            await client.setex(f"{_TOKEN_DENYLIST_PREFIX}{token_hash}", ttl_seconds, "1")
    except Exception:
        pass  # Best-effort; don't block logout if Redis is down


async def _is_token_denied(token: str) -> bool:
    """Check if a refresh token hash exists in the deny list.

    Fails closed: this path mints new credentials, so when the deny list
    cannot be consulted we reject the refresh with 503 instead of issuing
    credentials on an unverifiable token.
    """
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with get_async_redis() as client:
            result = await client.exists(f"{_TOKEN_DENYLIST_PREFIX}{token_hash}")
            return bool(result)
    except Exception as exc:
        logger.error(
            "AUTH_DENYLIST_UNAVAILABLE: cannot verify refresh token revocation: %s",
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot verify token revocation. Please try again later.",
        ) from exc


def _extract_session_jti_from_access_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    try:
        token = extract_bearer_token(authorization)
        payload = decode_access_token(token)
    except HTTPException:
        return None
    raw_jti = payload.get("jti")
    if isinstance(raw_jti, str):
        normalized = raw_jti.strip()
        return normalized or None
    return None


def _extract_session_jti_from_refresh_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = decode_refresh_token(token)
    except HTTPException:
        return None
    raw_jti = payload.get("jti")
    if isinstance(raw_jti, str):
        normalized = raw_jti.strip()
        return normalized or None
    return None


async def _deactivate_session(db: Session, session_jti: str | None) -> None:
    if not session_jti:
        return
    session = (
        db.query(models.UserSession).filter(models.UserSession.token_jti == session_jti).first()
    )
    if session is not None and session.is_active:
        session.is_active = False
        db.commit()
    await revoke_session_jti(session_jti)


async def _acquire_resend_verification_slot(email: str) -> bool:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return False

    key_hash = hashlib.sha256(normalized_email.encode()).hexdigest()
    redis_key = f"{_RESEND_VERIFICATION_PREFIX}{key_hash}"
    try:
        async with get_async_redis() as client:
            reserved = await client.set(
                redis_key,
                "1",
                ex=_RESEND_VERIFICATION_TTL_SECONDS,
                nx=True,
            )
            return bool(reserved)
    except Exception as exc:
        # Fail open: do not block email verification fleet-wide because Redis
        # is down, but log at ERROR with a distinct code so the outage is
        # alertable instead of silent.
        logger.error(
            "RESEND_VERIFICATION_THROTTLE_UNAVAILABLE: %s",
            exc,
        )
        return True


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _extract_id_token_claims(raw_token: str | None) -> dict[str, Any]:
    if not raw_token:
        return {}
    parts = raw_token.split(".")
    if len(parts) < 2:
        return {}

    payload_part = parts[1]
    padding = "=" * ((4 - len(payload_part) % 4) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_part + padding)
        decoded_payload = decoded_bytes.decode("utf-8")
        payload = json.loads(decoded_payload)
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def _first_text_value(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_microsoft_profile(
    token: dict[str, Any],
) -> tuple[str | None, str | None, str | None, bool]:
    user_info = token.get("userinfo")
    if not isinstance(user_info, dict):
        # id_token may live under "_ms_id_token" because the Microsoft
        # compliance fix moves it there to avoid authlib issuer validation.
        id_token = token.get("id_token") or token.get("_ms_id_token")
        user_info = _extract_id_token_claims(str(id_token) if isinstance(id_token, str) else None)

        # Defense-in-depth: validate audience and expiration even though the
        # token arrived over a trusted server-to-server TLS channel.
        if user_info:
            import time

            expected_aud = os.getenv("MICROSOFT_SSO_CLIENT_ID") or os.getenv("BING_CLIENT_ID")
            token_aud = user_info.get("aud")
            if expected_aud and token_aud and token_aud != expected_aud:
                logger.warning(
                    "Microsoft id_token audience mismatch: got %s, expected %s",
                    token_aud,
                    expected_aud,
                )
                user_info = {}
            token_exp = user_info.get("exp")
            if isinstance(token_exp, (int, float)) and token_exp < time.time():
                logger.warning("Microsoft id_token expired (exp=%s)", token_exp)
                user_info = {}

    email = _first_text_value(user_info, "email", "preferred_username", "upn")
    subject = _first_text_value(user_info, "sub", "oid")
    name = _first_text_value(user_info, "name", "preferred_username")
    email_verified_raw = user_info.get("email_verified")
    # Microsoft Entra id_tokens frequently omit email_verified and the claim is
    # tenant-admin-settable, so absence means unverified, never verified.
    email_verified = _is_truthy(email_verified_raw) if email_verified_raw is not None else False
    return email, subject, name, email_verified


def _is_local_request(request: Request) -> bool:
    hostname = (request.url.hostname or "").strip().lower()
    return hostname in {"localhost", "127.0.0.1"}


def _build_oauth_redirect_uri(request: Request, provider: str) -> str:
    redirect_uri = str(request.url_for("auth_callback", provider=provider))
    if _is_local_request(request):
        return redirect_uri

    public_backend_url = os.getenv("BACKEND_PUBLIC_URL")
    if public_backend_url:
        parsed = urlparse(public_backend_url)
        callback_target = urlparse(redirect_uri)
        callback_path = callback_target.path + (
            f"?{callback_target.query}" if callback_target.query else ""
        )
        if parsed.scheme and parsed.netloc:
            base_path = parsed.path.rstrip("/")
            return f"{parsed.scheme}://{parsed.netloc}{base_path}{callback_path}"

    return redirect_uri


def _resolve_frontend_url(request: Request | None = None) -> str:
    if request is not None and _is_local_request(request):
        hostname = (request.url.hostname or "localhost").strip().lower() or "localhost"
        return f"http://{hostname}:3000"

    frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
    app_base_url = (os.getenv("APP_BASE_URL") or "").strip()
    resolved = frontend_url or app_base_url or "http://localhost:3000"
    return resolved.rstrip("/")


def _identity_link_session_key(provider: str) -> str:
    return f"{_IDENTITY_LINK_SESSION_PREFIX}{provider}"


def _provider_sso_configured(provider: str) -> bool:
    if provider != "microsoft":
        return False
    # Same resolution order as services/oauth_service.py, which falls back to
    # the Bing Entra registration when no dedicated SSO client is set.
    return bool(os.getenv("MICROSOFT_SSO_CLIENT_ID") or os.getenv("BING_CLIENT_ID"))


def _require_linkable_provider(provider: str) -> None:
    if provider not in _IDENTITY_LINK_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid provider")
    if not _provider_sso_configured(provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider_display_name(provider)} sign-in is not configured.",
        )


async def _arm_identity_link(jti: str, user_id: int) -> None:
    """Record the one-time nonce for a link token, or issue nothing.

    The token rides in a query string on the next leg, where URLs reach logs
    and referrers, so single use has to be enforced rather than assumed.
    Fails closed: without the nonce the authorize leg cannot prove single use,
    so no token is handed out at all.
    """
    try:
        async with get_async_redis() as client:
            await client.setex(
                f"{_IDENTITY_LINK_NONCE_PREFIX}{jti}",
                IDENTITY_LINK_TOKEN_EXPIRE_SECONDS,
                str(user_id),
            )
    except Exception as exc:
        logger.error("ACCOUNT_LINK_NONCE_UNAVAILABLE: cannot arm account link: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account linking is temporarily unavailable. Please try again later.",
        ) from exc


async def _consume_identity_link(jti: str) -> str | None:
    """Spend the nonce, returning the user id it was armed for."""
    try:
        async with get_async_redis() as client:
            raw = await client.getdel(f"{_IDENTITY_LINK_NONCE_PREFIX}{jti}")
    except Exception as exc:
        logger.error("ACCOUNT_LINK_NONCE_UNAVAILABLE: cannot verify account link: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account linking is temporarily unavailable. Please try again later.",
        ) from exc

    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _manual_link_required_page(request: Request, exc: ManualAccountLinkRequired) -> HTMLResponse:
    """The SIGV2-1239 refusal, as a page that names the next step.

    The status stays 400. What changes is that a browser redirected here by
    the provider now gets the recovery route instead of a JSON error body
    with nothing actionable in it. Linking is deliberately not offered from
    here: a failed sign-in is the moment the inputs are attacker-controlled,
    so ownership is proven in account settings with the account's own
    password instead.
    """
    login_url = f"{_resolve_frontend_url(request)}/login"
    name = provider_display_name(getattr(exc, "provider", ""))
    return HTMLResponse(
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f"<title>{name} sign-in could not be matched - Qiko Signal</title></head>"
        '<body style="margin:0;padding:0;background:#F7F8FA;'
        'font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
        '<div style="max-width:480px;margin:80px auto;text-align:center;padding:40px 24px;'
        'background:#fff;border-radius:12px;border:1px solid #E5E7EB;">'
        f'<h1 style="margin:0 0 12px;font-size:24px;color:#111827;">{name} sign-in '
        "could not be matched</h1>"
        '<p style="margin:0 0 20px;font-size:15px;color:#4B5563;line-height:1.6;">'
        f"{exc.detail}</p>"
        f'<p style="margin:0;font-size:15px;"><a href="{login_url}" '
        'style="color:#111827;font-weight:600;">Sign in with your password</a></p>'
        "</div></body></html>",
        status_code=exc.status_code,
    )


async def _complete_identity_link(
    *,
    request: Request,
    db: Session,
    provider: str,
    subject: str | None,
    user_id: int,
) -> RedirectResponse:
    """Attach the just-authorized provider identity to the armed account."""
    settings_url = f"{_resolve_frontend_url(request)}/dashboard/account-settings"

    if not subject:
        return RedirectResponse(url=f"{settings_url}?link_error=provider_profile_missing")

    auth_service = AuthService(db)
    # The account comes from the server-side session entry armed by the
    # password-verified start request, never from anything in this request.
    user = auth_service.get_user_by_id(user_id)
    if user is None:
        return RedirectResponse(url=f"{settings_url}?link_error=link_session_invalid")

    try:
        auth_service.link_provider_identity(user, provider, subject)
    except LinkedIdentityAlreadyClaimed:
        logger.warning(
            "ACCOUNT_LINK_REFUSED: provider=%s reason=identity_already_linked user_id=%s",
            provider,
            user.id,
        )
        _log_account_link_event(db, request, user_id=user.id, provider=provider, linked=False)
        return RedirectResponse(url=f"{settings_url}?link_error=identity_already_linked")

    _log_account_link_event(db, request, user_id=user.id, provider=provider, linked=True)
    return RedirectResponse(url=f"{settings_url}?linked={provider}")


def _log_account_link_event(
    db: Session,
    request: Request,
    *,
    user_id: int,
    provider: str,
    linked: bool,
) -> None:
    from auth.security_events import log_security_event

    try:
        log_security_event(
            db,
            event_type="account_link_success" if linked else "account_link_refused",
            user_id=user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"provider": provider},
        )
    except Exception as exc:
        logger.warning("Failed to log account link security event", exc_info=exc)


@router.get("/linked-identities", response_model=LinkedIdentityListResponse)
async def list_linked_identities(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    auth_service = AuthService(db)
    identities = []
    for provider in sorted(_IDENTITY_LINK_PROVIDERS):
        identity = auth_service.get_user_linked_identity(current_user.id, provider)
        identities.append(
            {
                "provider": provider,
                "configured": _provider_sso_configured(provider),
                "linked": identity is not None,
                "linked_at": identity.created_at.isoformat()
                if identity is not None and identity.created_at
                else None,
            }
        )
    return {"identities": identities}


@router.post(
    "/linked-identities/{provider}/start",
    response_model=LinkedIdentityStartResponse,
)
async def start_identity_link(
    provider: str,
    payload: LinkedIdentityStartRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Re-authenticate with the account password before any provider leg runs."""
    _require_linkable_provider(provider)

    auth_service = AuthService(db)
    user = auth_service.get_user_by_id(current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # verify_password returns False on a malformed hash instead of raising, so
    # an account with no usable password (OAuth-created, token-provisioned)
    # fails closed here.
    if not verify_password(payload.current_password, user.hashed_password):
        logger.warning(
            "ACCOUNT_LINK_REFUSED: provider=%s reason=password_mismatch user_id=%s",
            provider,
            user.id,
        )
        _log_account_link_event(db, request, user_id=user.id, provider=provider, linked=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    link_token, jti = auth_service.create_identity_link_token(user, provider)
    await _arm_identity_link(jti, user.id)

    return {
        "link_token": link_token,
        "authorize_path": f"/auth/linked-identities/{provider}/authorize",
    }


@router.get("/linked-identities/{provider}/authorize", name="identity_link_authorize")
async def authorize_identity_link(
    provider: str,
    link_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Second leg: arm the session, then hand the browser to the provider.

    This is a full browser navigation, so it carries no Authorization header.
    The single-use link token minted by the password-verified start request is
    the proof, and it is moved into the server-side session here so it never
    travels through the provider redirect.
    """
    _require_linkable_provider(provider)

    auth_service = AuthService(db)
    user_id, jti = auth_service.verify_identity_link_token(link_token, provider)

    armed_user_id = await _consume_identity_link(jti)
    if armed_user_id != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account link request has expired or was already used.",
        )

    request.session[_identity_link_session_key(provider)] = {"user_id": user_id}
    redirect_uri = _build_oauth_redirect_uri(request, provider)
    return await oauth.create_client(provider).authorize_redirect(request, redirect_uri)


@router.get("/login/{provider}")
async def login_oauth(provider: str, request: Request):
    if provider not in _OAUTH_LOGIN_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid provider")

    # Purge stale OAuth/session entries so the session cookie stays under the
    # 4 KB browser limit.  Each failed/abandoned OAuth flow leaves session
    # keys behind; after a few attempts the cookie overflows and the browser
    # silently drops the Set-Cookie header, making every subsequent attempt
    # fail with a CSRF / state-mismatch error.
    stale_keys = [
        k
        for k in list(request.session.keys())
        if any(k.startswith(prefix) for prefix in _STALE_SESSION_PREFIXES)
    ]
    for k in stale_keys:
        request.session.pop(k, None)
    if stale_keys:
        logger.info("[OAUTH] purged %d stale session keys: %s", len(stale_keys), stale_keys)

    redirect_uri = _build_oauth_redirect_uri(request, provider)
    session_cookie_len = len(request.cookies.get("session", ""))
    logger.debug(
        "[OAUTH] login: provider=%s redirect_uri=%s session_keys=%s cookies=%s session_cookie_len=%d",
        provider,
        redirect_uri,
        list(request.session.keys()),
        list(request.cookies.keys()),
        session_cookie_len,
    )
    return await oauth.create_client(provider).authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback", name="auth_callback")
async def auth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    if provider not in _OAUTH_LOGIN_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid provider")

    request.session.pop(f"{_TRIAL_TOKEN_SESSION_PREFIX}{provider}", None)

    # SIGV2-1257: an armed account link is spent here whatever happens next,
    # so an abandoned attempt cannot be picked up by a later callback.
    armed_link = request.session.pop(_identity_link_session_key(provider), None)
    link_user_id: int | None = None
    if isinstance(armed_link, dict):
        try:
            link_user_id = int(armed_link.get("user_id"))
        except (TypeError, ValueError):
            link_user_id = None

    import logging as _log

    _dbg = _log.getLogger("auth.oauth.debug")

    session_keys = list(request.session.keys())
    cookie_names = list(request.cookies.keys())
    query_state = request.query_params.get("state", "<missing>")
    has_session_cookie = "session" in cookie_names
    session_cookie_len = len(request.cookies.get("session", ""))

    _dbg.warning(
        "OAuth callback: provider=%s session_keys=%s cookies=%s query_state=%s "
        "has_session_cookie=%s session_cookie_len=%d",
        provider,
        session_keys,
        cookie_names,
        query_state,
        has_session_cookie,
        session_cookie_len,
    )
    logger.debug(
        "[OAUTH] callback: provider=%s session_keys=%s cookies=%s query_state=%s "
        "has_session_cookie=%s session_cookie_len=%d",
        provider,
        session_keys,
        cookie_names,
        query_state,
        has_session_cookie,
        session_cookie_len,
    )

    client = oauth.create_client(provider)
    try:
        # Microsoft Entra ID multi-tenant ("common") OIDC discovery returns a
        # template issuer containing "{tenantid}" which never matches the real
        # tenant ID in the token.  The Microsoft compliance fix in
        # oauth_service.py strips id_token from the response so authlib skips
        # OIDC issuer validation entirely; _extract_microsoft_profile decodes
        # the raw id_token manually from the "_ms_id_token" key instead.
        token = await client.authorize_access_token(request)
    except Exception as e:
        error_str = str(e)
        # Log detailed diagnostic info for CSRF/state errors
        expected_key = f"_state_{provider}_{query_state}"
        state_keys_in_session = [k for k in session_keys if k.startswith(f"_state_{provider}")]
        _dbg.warning(
            "OAuth callback FAILED: %s | expected_key=%s state_keys_found=%s "
            "has_session_cookie=%s session_cookie_len=%d all_session_keys=%s",
            e,
            expected_key,
            state_keys_in_session,
            has_session_cookie,
            session_cookie_len,
            session_keys,
        )
        logger.debug(
            "[OAUTH] callback FAILED: %s | expected_key=%s state_keys_found=%s "
            "has_session_cookie=%s session_cookie_len=%d",
            e,
            expected_key,
            state_keys_in_session,
            has_session_cookie,
            session_cookie_len,
        )

        # Always redirect to frontend login with error, never expose raw
        # JSON/401 to the browser during an OAuth redirect flow.
        frontend_url = _resolve_frontend_url(request)
        if link_user_id is not None:
            # A link attempt starts from account settings, so it returns there
            # rather than dropping an already signed-in customer on /login.
            return RedirectResponse(
                url=f"{frontend_url}/dashboard/account-settings?link_error=oauth_failed"
            )
        if "mismatching_state" in error_str or "missing_token" in error_str:
            return RedirectResponse(
                url=f"{frontend_url}/login?error=oauth_state_mismatch&provider={provider}"
            )
        return RedirectResponse(url=f"{frontend_url}/login?error=oauth_failed&provider={provider}")

    user_info = None
    email_verified = False
    avatar_url = None
    if provider == "google":
        user_info = token.get("userinfo")
        if not user_info:
            # Fallback if userinfo is not in token
            user_info_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo", token=token
            )
            user_info = user_info_resp.json()

        email = user_info.get("email")
        email_verified = _is_truthy(user_info.get("email_verified"))
        subject = user_info.get("sub")
        name = user_info.get("name")
        avatar_url = user_info.get("picture")

    elif provider == "github":
        resp = await client.get("user", token=token)
        user_data = resp.json()
        subject = str(user_data.get("id"))
        name = user_data.get("name") or user_data.get("login")
        avatar_url = user_data.get("avatar_url")

        # GitHub might hide email, fetch primary
        email_resp = await client.get("user/emails", token=token)
        email_payload = email_resp.json()
        emails = email_payload if isinstance(email_payload, list) else []
        selected_email = next((e for e in emails if e.get("primary") and e.get("email")), None)
        if not selected_email:
            selected_email = next((e for e in emails if e.get("email")), None)

        email = selected_email.get("email") if selected_email else None
        email_verified = _is_truthy(selected_email.get("verified")) if selected_email else False

    elif provider == "linkedin":
        user_info = token.get("userinfo")
        if not user_info:
            user_info_resp = await client.get("https://api.linkedin.com/v2/userinfo", token=token)
            user_info = user_info_resp.json()

        email = user_info.get("email")
        email_verified = _is_truthy(user_info.get("email_verified"))
        subject = user_info.get("sub")
        name = user_info.get("name")
        avatar_url = user_info.get("picture")

    else:
        email, subject, name, email_verified = _extract_microsoft_profile(token)
        ms_userinfo = token.get("userinfo")
        if isinstance(ms_userinfo, dict):
            avatar_url = ms_userinfo.get("picture")

    if link_user_id is not None:
        # SIGV2-1257: this leg attaches an identity to an account whose
        # ownership was already proven by its password, so it signs nobody in
        # and reads no email claim. Only the provider subject matters.
        return await _complete_identity_link(
            request=request,
            db=db,
            provider=provider,
            subject=subject,
            user_id=link_user_id,
        )

    if not email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from provider")
    if not subject:
        raise HTTPException(status_code=400, detail="Could not retrieve subject from provider")

    auth_service = AuthService(db)
    try:
        user = await auth_service.get_or_create_oauth_user(
            provider=provider,
            subject=subject,
            email=email,
            name=name,
            provider_email_verified=email_verified,
            avatar_url=avatar_url,
        )
    except ManualAccountLinkRequired as exc:
        # SIGV2-1239 refuses the silent auto-link; SIGV2-1257 answers with the
        # recovery route instead of a bare JSON error. Same 400 status.
        logger.warning(
            "OAUTH_AUTOLINK_REFUSED: provider=%s reason=unverified_provider_email",
            provider,
        )
        return _manual_link_required_page(request, exc)

    tokens = auth_service.build_token_response(user, request=request)

    # Store tokens behind a one-time code instead of passing them in the URL
    code = await _store_oauth_code(tokens["access_token"], tokens["refresh_token"])
    frontend_url = _resolve_frontend_url(request)
    return RedirectResponse(url=f"{frontend_url}/auth/callback?code={code}")


@router.post("/exchange-code", response_model=Token)
async def exchange_oauth_code(request: Request) -> Any:
    """Exchange a one-time OAuth code for access and refresh tokens."""
    body = await request.json()
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")

    tokens = await _exchange_oauth_code(code)
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code"
        )

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
    }


@router.post("/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)) -> Any:
    auth_service = AuthService(db)
    user = await auth_service.create_user(user_data)
    # Return the same message whether the account was created or already existed
    if user is None:
        return {
            "message": "If this email is not already registered, a verification link has been sent."
        }
    return {
        "message": "If this email is not already registered, a verification link has been sent."
    }


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    mfa_code: str | None = Form(default=None),
    remember_me: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> Any:
    await rate_limiter.ensure_login_allowed(request, form_data.username)

    auth_service = AuthService(db)
    try:
        user = auth_service.authenticate_user(
            UserLogin(email=form_data.username, password=form_data.password)
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            await rate_limiter.record_login_failure(request, form_data.username)
        raise

    from core.config import settings as app_settings

    if app_settings.EMAIL_VERIFICATION_REQUIRED and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_not_verified",
                "message": "Please verify your email before signing in. Check your inbox for the verification link.",
            },
        )

    mfa_secret = getattr(user, "mfa_secret", None)
    if mfa_secret:
        if not mfa_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"detail": "MFA code required", "mfa_required": True},
            )

        # SIGV2-1244: single-use TOTP codes plus a per-user attempt lockout that
        # does not depend on the source IP.
        mfa_result = await verify_totp_code_for_user(
            user_id=user.id, secret=mfa_secret, otp_code=mfa_code
        )

        if mfa_result is MFAVerificationResult.THROTTLED:
            retry_after = await mfa_throttle_retry_after(user.id) or 60
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "detail": "Too many MFA attempts. Try again later.",
                    "mfa_required": True,
                },
                headers={"Retry-After": str(retry_after)},
            )

        if mfa_result is MFAVerificationResult.UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "detail": "MFA verification is temporarily unavailable. Try again shortly.",
                    "mfa_required": True,
                },
            )

        if mfa_result is not MFAVerificationResult.OK:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"detail": "Invalid MFA code", "mfa_required": True},
            )

    remember_session = _is_truthy(remember_me)

    token = auth_service.build_token_response(user, remember_me=remember_session, request=request)
    await rate_limiter.reset_login_failures(request, form_data.username)
    return token


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request, refresh_data: RefreshTokenRequest, db: Session = Depends(get_db)
) -> Any:
    if await _is_token_denied(refresh_data.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )

    try:
        refresh_payload = decode_refresh_token(refresh_data.refresh_token)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc

    auth_service = AuthService(db)
    remember_session = bool(refresh_payload.get("remember_me"))
    user_id = auth_service.verify_token(refresh_data.refresh_token, is_refresh=True)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    session_jti = _extract_session_jti_from_refresh_token(refresh_data.refresh_token)
    if not session_jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing a valid session identifier",
        )

    session = (
        db.query(models.UserSession)
        .filter(
            models.UserSession.token_jti == session_jti,
            models.UserSession.user_id == user.id,
        )
        .first()
    )
    session_expires_at = session.expires_at if session is not None else None
    if session_expires_at is not None and session_expires_at.tzinfo is None:
        session_expires_at = session_expires_at.replace(tzinfo=timezone.utc)

    if (
        session is None
        or session.is_active is not True
        or session_expires_at is None
        or session_expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked or expired"
        )

    await _deny_refresh_token(refresh_data.refresh_token)
    await _deactivate_session(db, session_jti)
    return auth_service.build_token_response(user, remember_me=remember_session, request=request)


@router.post("/logout")
async def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    db: Session = Depends(get_db),
) -> Any:
    refresh_token = payload.refresh_token if payload else None
    session_jti = _extract_session_jti_from_access_request(request)
    if not session_jti:
        session_jti = _extract_session_jti_from_refresh_token(refresh_token)
    await _deactivate_session(db, session_jti)
    if refresh_token:
        await _deny_refresh_token(refresh_token)
    return {"message": "Logged out"}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> Any:
    auth_service = AuthService(db)
    user = auth_service.get_user_by_email(payload.email)

    if user:
        token = auth_service.create_password_reset_token(payload.email)
        await auth_service.send_password_reset_email_if_available(payload.email, token)

    # Always return success to prevent email enumeration
    return {"message": "If the email exists, password reset instructions have been sent"}


@router.post("/reset-password")
async def reset_password(reset_data: PasswordReset, db: Session = Depends(get_db)) -> Any:
    auth_service = AuthService(db)
    email = auth_service.verify_password_reset_token(reset_data.token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
        )

    user = auth_service.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
        )

    user.hashed_password = hash_password(reset_data.password)
    db.commit()

    # Invalidate every session/refresh token issued before the reset
    session_jtis = deactivate_user_sessions(db, user.id)
    await revoke_session_jtis(session_jtis)

    return {"message": "Password has been reset successfully"}


@router.post("/verify-email")
async def verify_email(verification_data: EmailVerification, db: Session = Depends(get_db)) -> Any:
    auth_service = AuthService(db)
    email = auth_service.verify_email_token(verification_data.token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token"
        )

    user = auth_service.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.email_verified = True
    db.commit()

    await auth_service.send_welcome_email_if_available(user)

    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest, db: Session = Depends(get_db)
) -> Any:
    if not await _acquire_resend_verification_slot(payload.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait 60 seconds before requesting another verification email.",
        )

    auth_service = AuthService(db)
    user = auth_service.get_user_by_email(payload.email.strip().lower())
    if user and not user.email_verified:
        token = auth_service.create_email_token(user.email)
        await auth_service.send_verification_email_if_available(user.email, token)

    return {"message": "If the email exists, a verification link has been sent."}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: models.User = Depends(get_current_user)) -> Any:
    return current_user.to_dict()


@router.get("/unsubscribe")
async def unsubscribe(token: str, db: Session = Depends(get_db)) -> HTMLResponse:
    user = db.query(models.User).filter(models.User.unsubscribe_token == token).first()
    if not user:
        raise HTTPException(status_code=404, detail="Invalid unsubscribe link")
    user.notifications_enabled = False
    db.commit()
    return HTMLResponse(
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">'
        "<title>Unsubscribed - Qiko Signal</title></head>"
        '<body style="margin:0;padding:0;background:#F7F8FA;font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
        '<div style="max-width:480px;margin:80px auto;text-align:center;padding:40px 24px;background:#fff;border-radius:12px;border:1px solid #E5E7EB;">'
        '<h1 style="margin:0 0 12px;font-size:24px;color:#111827;">Unsubscribed</h1>'
        '<p style="margin:0 0 20px;font-size:15px;color:#4B5563;line-height:1.6;">'
        "You have been unsubscribed from notification emails. "
        "You will still receive transactional emails (password resets, email verification).</p>"
        '<p style="margin:0;font-size:13px;color:#9CA3AF;">'
        "If this was a mistake, sign in to your dashboard and re-enable notifications in Settings.</p>"
        "</div></body></html>"
    )
