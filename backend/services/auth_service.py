from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import os
import secrets
import uuid

from fastapi import HTTPException, status
from core.password_hashing import hash_password, verify_password
import jwt
from jwt import PyJWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import httpx
from auth.token_verifier import decode_access_token, decode_refresh_token
from core.config import settings
from schemas.auth import UserCreate, UserLogin, normalize_company_name
from services.email_service import EmailService
from services.workspace_rbac import CLIENT_READONLY_PERMISSIONS, resolve_portal_access_context

JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_REFRESH_SECRET_KEY = settings.JWT_REFRESH_SECRET_KEY or JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM or os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
REMEMBER_ME_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("REMEMBER_ME_ACCESS_TOKEN_EXPIRE_MINUTES", "10080")
)
REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv("REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS", "30")
)
EMAIL_TOKEN_EXPIRE_HOURS = int(os.getenv("EMAIL_TOKEN_EXPIRE_HOURS", "48"))
PASSWORD_RESET_TOKEN_EXPIRE_HOURS = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_HOURS", "24"))
LINKEDIN_STATE_TOKEN_EXPIRE_MINUTES = int(os.getenv("LINKEDIN_STATE_TOKEN_EXPIRE_MINUTES", "10"))
IDENTITY_LINK_TOKEN_EXPIRE_SECONDS = int(os.getenv("IDENTITY_LINK_TOKEN_EXPIRE_SECONDS", "600"))
IDENTITY_LINK_TOKEN_PURPOSE = "oauth_identity_link"

PROVIDER_DISPLAY_NAMES = {
    "microsoft": "Microsoft",
    "google": "Google",
    "github": "GitHub",
    "linkedin": "LinkedIn",
}


def provider_display_name(provider: str) -> str:
    key = (provider or "").strip().lower()
    return PROVIDER_DISPLAY_NAMES.get(key, key.capitalize() or "the provider")


class ManualAccountLinkRequired(HTTPException):
    """SIGV2-1257: the provider identity is unknown and its email is unverified.

    Raised instead of a bare 400 so the callback can answer with the recovery
    route (sign in with the password, then link from account settings) rather
    than leaving the customer on an error with nothing to do next. The status
    code stays 400: SIGV2-1239's refusal is unchanged, only its wording and
    the response it drives.
    """

    def __init__(self, provider: str) -> None:
        name = provider_display_name(provider)
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This email already has a Qiko Signal account, and the {name} sign-in "
                "cannot be matched to it automatically. Sign in with your email and "
                f"password, then connect {name} from Account Settings, Security."
            ),
        )
        self.provider = provider


class LinkedIdentityAlreadyClaimed(HTTPException):
    """The provider identity is already attached to a different account."""

    def __init__(self, provider: str) -> None:
        name = provider_display_name(provider)
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That {name} account is already connected to another Qiko Signal account.",
        )
        self.provider = provider


def _oauth_state_signing_key() -> str:
    return settings.resolved_session_secret


def create_linkedin_oauth_state() -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=LINKEDIN_STATE_TOKEN_EXPIRE_MINUTES)
    payload = {
        "type": "linkedin_oauth_state",
        "provider": "linkedin",
        "nonce": secrets.token_urlsafe(16),
        "exp": expire,
    }
    return jwt.encode(payload, _oauth_state_signing_key(), algorithm=JWT_ALGORITHM)


def verify_linkedin_oauth_state(state: str) -> None:
    if not state:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing LinkedIn OAuth state",
        )

    try:
        payload = jwt.decode(state, _oauth_state_signing_key(), algorithms=[JWT_ALGORITHM])
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired LinkedIn OAuth state",
        ) from exc

    if payload.get("type") != "linkedin_oauth_state" or payload.get("provider") != "linkedin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid LinkedIn OAuth state",
        )


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self._email_service: EmailService | None = None
        self._email_service_initialized = False

    def _get_email_service(self) -> EmailService:
        if not self._email_service_initialized:
            self._email_service_initialized = True
            self._email_service = EmailService(self.db)
        return self._email_service

    async def send_verification_email_if_available(self, email: str, token: str) -> None:
        try:
            await self._get_email_service().send_verification_email(email, token)
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed to queue verification email", exc_info=exc)

    async def send_password_reset_email_if_available(self, email: str, token: str) -> None:
        try:
            await self._get_email_service().send_password_reset_email(email, token)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Failed to queue password reset email", exc_info=exc
            )

    async def send_welcome_email_if_available(self, user: models.User) -> None:
        correlation_id = f"auth.welcome:{user.id}"
        existing = (
            self.db.query(models.EmailOutbox)
            .filter(models.EmailOutbox.correlation_id == correlation_id)
            .first()
        )
        if existing:
            return

        try:
            await self._get_email_service().send_welcome_email(
                user.email,
                user_id=user.id,
                user_name=user.company_name,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed to queue welcome email", exc_info=exc)

    async def create_user(self, user_data: UserCreate) -> models.User | None:
        existing = self.get_user_by_email(user_data.email)
        if existing:
            # Silently notify the existing user instead of revealing account existence
            await self.send_verification_email_if_available(
                user_data.email, self.create_email_token(user_data.email)
            )
            return None

        user = models.User(
            email=(user_data.email or "").strip().lower(),
            hashed_password=hash_password(user_data.password),
            company_name=normalize_company_name(getattr(user_data, "name", None)),
            unsubscribe_token=str(uuid.uuid4()),
        )
        self.db.add(user)
        self.db.flush()

        self.db.commit()
        self.db.refresh(user)

        verification_token = self.create_email_token(user.email)
        await self.send_verification_email_if_available(user.email, verification_token)
        return user

    def authenticate_user(self, user_data: UserLogin) -> models.User:
        user = self.get_user_by_email(user_data.email)
        if not user or not verify_password(user_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
            )
        return user

    def get_user_by_email(self, email: str) -> models.User | None:
        normalized = (email or "").strip().lower()
        return (
            self.db.query(models.User).filter(func.lower(models.User.email) == normalized).first()
        )

    def get_user_by_id(self, user_id: uuid.UUID | int) -> models.User | None:
        return self.db.query(models.User).filter(models.User.id == user_id).first()

    def _resolve_token_permissions(self, user: models.User, *, portal_only: bool) -> list[str]:
        role = str(getattr(user, "role", "user") or "user").strip().lower()
        if role == "admin":
            return ["*"]
        if portal_only:
            return list(CLIENT_READONLY_PERMISSIONS)
        return ["audit:run", "audit:read", "profile:read", "profile:update"]

    def create_access_token(
        self, user: models.User, *, remember_me: bool = False, session_id: str | None = None
    ) -> str:
        ttl_minutes = (
            REMEMBER_ME_ACCESS_TOKEN_EXPIRE_MINUTES if remember_me else ACCESS_TOKEN_EXPIRE_MINUTES
        )
        expire = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        role = str(getattr(user, "role", "user") or "user").strip().lower()
        portal_only, portal_workspace_id = resolve_portal_access_context(self.db, user=user)
        permissions = self._resolve_token_permissions(user, portal_only=portal_only)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": role,
            "permissions": permissions,
            "portal_only": portal_only,
            "portal_workspace_id": portal_workspace_id,
            "exp": expire,
            "type": "access",
            "remember_me": bool(remember_me),
        }
        if session_id:
            payload["jti"] = session_id
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def create_refresh_token(
        self, user: models.User, *, remember_me: bool = False, session_id: str | None = None
    ) -> str:
        ttl_days = (
            REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS if remember_me else REFRESH_TOKEN_EXPIRE_DAYS
        )
        expire = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "exp": expire,
            "type": "refresh",
            "remember_me": bool(remember_me),
        }
        if session_id:
            payload["jti"] = session_id
        return jwt.encode(payload, JWT_REFRESH_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def verify_token(self, token: str, is_refresh: bool = False) -> uuid.UUID | int | None:
        try:
            payload = decode_refresh_token(token) if is_refresh else decode_access_token(token)
            raw_sub = payload.get("sub")
            try:
                return uuid.UUID(str(raw_sub))
            except (ValueError, TypeError):
                return int(raw_sub)
        except (HTTPException, PyJWTError, ValueError, TypeError):
            return None

    def create_email_token(self, email: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=EMAIL_TOKEN_EXPIRE_HOURS)
        return jwt.encode(
            {"sub": email, "exp": expire, "type": "email_verification"},
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )

    def verify_email_token(self, token: str) -> str | None:
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload.get("sub") if payload.get("type") == "email_verification" else None
        except PyJWTError:
            return None

    @staticmethod
    def _password_reset_credential_version(hashed_password: str) -> str:
        return hmac.new(
            JWT_SECRET_KEY.encode("utf-8"),
            hashed_password.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def create_password_reset_token(self, email: str) -> str:
        user = self.get_user_by_email(email)
        if user is None or not user.hashed_password:
            raise ValueError("Password reset target does not exist.")
        expire = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
        return jwt.encode(
            {
                "sub": user.email,
                "exp": expire,
                "type": "password_reset",
                "credential_version": self._password_reset_credential_version(user.hashed_password),
                "jti": secrets.token_urlsafe(24),
            },
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )

    def verify_password_reset_token(self, token: str) -> str | None:
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            if payload.get("type") != "password_reset":
                return None
            email = payload.get("sub")
            credential_version = payload.get("credential_version")
            if not isinstance(email, str) or not isinstance(credential_version, str):
                return None
            user = self.get_user_by_email(email)
            if user is None or not user.hashed_password:
                return None
            expected_version = self._password_reset_credential_version(user.hashed_password)
            return user.email if hmac.compare_digest(credential_version, expected_version) else None
        except PyJWTError:
            return None

    @staticmethod
    def _generate_oauth_password_hash() -> str:
        return hash_password(secrets.token_urlsafe(48))

    def build_token_response(
        self, user: models.User, *, remember_me: bool = False, request=None
    ) -> dict[str, str]:
        session_id = str(uuid.uuid4())

        ip_address = None
        user_agent = None
        if request:
            ip_address = request.client.host if request.client else None
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            user_agent = request.headers.get("user-agent")

        from auth.security_events import log_security_event

        ttl_days = (
            REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS if remember_me else REFRESH_TOKEN_EXPIRE_DAYS
        )
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

        try:
            db_session = models.UserSession(
                user_id=user.id,
                token_jti=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=expires_at,
            )
            self.db.add(db_session)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logging.getLogger(__name__).error("Failed to store user session", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to establish a secure session. Please try again.",
            ) from exc

        try:
            log_security_event(
                self.db,
                event_type="login_success",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"session_id": session_id},
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed to log security event", exc_info=exc)

        return {
            "access_token": self.create_access_token(
                user, remember_me=remember_me, session_id=session_id
            ),
            "refresh_token": self.create_refresh_token(
                user, remember_me=remember_me, session_id=session_id
            ),
            "token_type": "bearer",
        }

    def create_identity_link_token(self, user: models.User, provider: str) -> tuple[str, str]:
        """Mint the short-lived proof that this user may link ``provider``.

        Returns ``(token, jti)``; the caller records the jti so the token can
        be spent exactly once.

        Issued only after the account's own password has been re-verified. The
        OAuth leg that follows is a browser navigation with no Authorization
        header, so this token is what carries the already-proven identity
        across it. Same shape as the MFA setup token (SIGV2-1241): server
        minted, user bound, short lived.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=IDENTITY_LINK_TOKEN_EXPIRE_SECONDS
        )
        jti = secrets.token_urlsafe(16)
        payload = {
            "sub": str(user.id),
            "purpose": IDENTITY_LINK_TOKEN_PURPOSE,
            "provider": provider,
            "jti": jti,
            "exp": expires_at,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM), jti

    def verify_identity_link_token(self, token: str, provider: str) -> tuple[int, str]:
        """Return ``(user_id, jti)`` from the token, or raise 400.

        The jti is the caller's handle on single use: the router consumes it
        once, so a token that leaks out of a URL cannot be replayed.
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired account link request.",
            ) from exc

        if (
            payload.get("purpose") != IDENTITY_LINK_TOKEN_PURPOSE
            or payload.get("provider") != provider
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account link request.",
            )

        jti = payload.get("jti")
        if not isinstance(jti, str) or not jti.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account link request.",
            )

        try:
            return int(str(payload.get("sub"))), jti.strip()
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account link request.",
            ) from exc

    def get_linked_identity(self, provider: str, subject: str) -> models.UserLinkedIdentity | None:
        return (
            self.db.query(models.UserLinkedIdentity)
            .filter(
                models.UserLinkedIdentity.provider == provider,
                models.UserLinkedIdentity.subject == subject,
            )
            .first()
        )

    def get_user_linked_identity(
        self, user_id: int, provider: str
    ) -> models.UserLinkedIdentity | None:
        return (
            self.db.query(models.UserLinkedIdentity)
            .filter(
                models.UserLinkedIdentity.user_id == user_id,
                models.UserLinkedIdentity.provider == provider,
            )
            .first()
        )

    def link_provider_identity(
        self, user: models.User, provider: str, subject: str
    ) -> models.UserLinkedIdentity:
        """Attach ``subject`` to ``user``, refusing a subject owned elsewhere.

        The provider email is deliberately not consulted: ownership of this
        account was proven by its password, and ownership of the provider
        identity by the authorization-code round trip just completed. Trusting
        the email claim here is what SIGV2-1239 removed.
        """
        existing = self.get_linked_identity(provider, subject)
        if existing is not None:
            if existing.user_id != user.id:
                raise LinkedIdentityAlreadyClaimed(provider)
            return existing

        claimed_by_account = (
            self.db.query(models.User)
            .filter(
                models.User.auth_provider == provider,
                models.User.provider_subject == subject,
                models.User.id != user.id,
            )
            .first()
        )
        if claimed_by_account is not None:
            raise LinkedIdentityAlreadyClaimed(provider)

        identity = self.get_user_linked_identity(user.id, provider)
        if identity is not None:
            identity.subject = subject
        else:
            identity = models.UserLinkedIdentity(
                user_id=user.id,
                provider=provider,
                subject=subject,
            )
            self.db.add(identity)
        self.db.commit()
        self.db.refresh(identity)
        return identity

    async def get_or_create_oauth_user(
        self,
        provider: str,
        subject: str,
        email: str,
        name: str | None = None,
        provider_email_verified: bool = False,
        trial_token: str | None = None,
        avatar_url: str | None = None,
    ) -> models.User:
        created_new_user = False
        email = (email or "").strip().lower()

        # SIGV2-1257: an identity the account owner linked explicitly resolves
        # first, and on its own: the link was already proven with the
        # account's password, so no email claim is consulted here.
        linked_identity = self.get_linked_identity(provider, subject)
        if linked_identity is not None:
            linked_user = self.get_user_by_id(linked_identity.user_id)
            if linked_user is not None:
                return linked_user

        user = (
            self.db.query(models.User)
            .filter(models.User.auth_provider == provider, models.User.provider_subject == subject)
            .first()
        )

        if user:
            needs_refresh = False
            if not user.external_id:
                user.external_id = subject
                needs_refresh = True
            if name and not user.company_name:
                # Provider-supplied display name: truncate rather than reject -
                # a sign-in must not fail over a cosmetic field.
                user.company_name = normalize_company_name(name, on_overlong="truncate")
                needs_refresh = True
            if avatar_url and avatar_url != user.avatar_url:
                user.avatar_url = avatar_url
                needs_refresh = True
            if needs_refresh:
                self.db.commit()
            return user

        user = self.db.query(models.User).filter(func.lower(models.User.email) == email).first()
        if user:
            if not provider_email_verified:
                # SIGV2-1239: an unverified provider email never links itself
                # to an existing account. SIGV2-1257 only changes what the
                # refusal says, not when it fires.
                raise ManualAccountLinkRequired(provider)

            user.auth_provider = provider
            user.provider_subject = subject
            if not user.external_id:
                user.external_id = subject
            if name and not user.company_name:
                # Same provider-supplied name rule: cap it, never fail the login.
                user.company_name = normalize_company_name(name, on_overlong="truncate")
            if avatar_url:
                user.avatar_url = avatar_url
            user.email_verified = True
            self.db.commit()
            return user

        user = models.User(
            email=email,
            hashed_password=self._generate_oauth_password_hash(),
            auth_provider=provider,
            provider_subject=subject,
            external_id=subject,
            company_name=normalize_company_name(name, on_overlong="truncate"),
            email_verified=bool(provider_email_verified),
            unsubscribe_token=str(uuid.uuid4()),
            avatar_url=avatar_url,
        )
        self.db.add(user)
        self.db.flush()
        self.db.commit()
        created_new_user = True

        if created_new_user:
            await self.send_welcome_email_if_available(user)

        return user

    async def process_linkedin_login(
        self, code: str, request=None, redirect_uri: str | None = None
    ) -> dict[str, str]:
        """Exchange a LinkedIn OIDC code, upsert the user, and return application JWTs."""
        if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LinkedIn SSO is not fully configured.",
            )
        resolved_redirect_uri = redirect_uri or (
            str(settings.LINKEDIN_REDIRECT_URI) if settings.LINKEDIN_REDIRECT_URI else None
        )
        if not resolved_redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LinkedIn SSO redirect URI is not configured.",
            )
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing LinkedIn authorization code",
            )

        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        profile_url = "https://api.linkedin.com/v2/userinfo"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.LINKEDIN_CLIENT_ID,
            "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            "redirect_uri": resolved_redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            try:
                token_resp = await client.post(token_url, data=data, timeout=10.0)
                token_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logging.getLogger(__name__).warning(
                    "LinkedIn token exchange failed", extra={"response": exc.response.text}
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="LinkedIn token exchange failed",
                ) from exc
            except Exception as exc:
                logging.getLogger(__name__).warning("LinkedIn token exchange error", exc_info=exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="LinkedIn token exchange failed",
                ) from exc

            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to obtain access token from LinkedIn",
                )

            try:
                profile_resp = await client.get(
                    profile_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10.0,
                )
                profile_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logging.getLogger(__name__).warning(
                    "Failed to fetch LinkedIn profile", extra={"response": exc.response.text}
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch LinkedIn profile",
                ) from exc
            except Exception as exc:
                logging.getLogger(__name__).warning("LinkedIn profile fetch error", exc_info=exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch LinkedIn profile",
                ) from exc

        profile_data = profile_resp.json()
        subject = profile_data.get("sub")
        email = profile_data.get("email")
        name = profile_data.get("name")
        email_verified_raw = profile_data.get("email_verified")
        email_verified = (
            email_verified_raw.lower() == "true"
            if isinstance(email_verified_raw, str)
            else bool(email_verified_raw)
        )

        if not email or not subject:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incomplete profile data from LinkedIn",
            )

        user = await self.get_or_create_oauth_user(
            provider="linkedin",
            subject=subject,
            email=email,
            name=name,
            provider_email_verified=email_verified,
        )
        return self.build_token_response(user, request=request)
