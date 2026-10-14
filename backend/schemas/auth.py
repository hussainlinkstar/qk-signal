import re

from pydantic import BaseModel, EmailStr, Field, constr, field_validator
from typing import Literal, Optional

_PASSWORD_MIN_LENGTH = 8
# Matches the limit enforced by the profile update endpoint for the same column.
_NAME_MAX_LENGTH = 120


def normalize_company_name(
    value: Optional[str], *, on_overlong: Literal["reject", "truncate"] = "reject"
) -> Optional[str]:
    """The single rule for ``User.company_name``: strip, blank to None, cap
    at ``_NAME_MAX_LENGTH``. Every writer of that column goes through here.

    ``on_overlong="reject"`` raises ValueError, which pydantic surfaces as a
    422 - right for forms a person is filling in. ``on_overlong="truncate"``
    is for non-interactive writes such as OAuth provider profiles: a sign-in
    must never fail over a cosmetic display name, so the value is capped
    instead. Do not "make this consistent" by rejecting there.
    """
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > _NAME_MAX_LENGTH:
        if on_overlong == "truncate":
            return normalized[:_NAME_MAX_LENGTH]
        raise ValueError(f"name must be {_NAME_MAX_LENGTH} characters or fewer.")
    return normalized


_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_\-+=\[\]{};:'\",.<>?/\\|`~]).{8,}$"
)
_PASSWORD_POLICY_MSG = (
    "Password must be at least 8 characters and include an uppercase letter, "
    "a lowercase letter, a digit, and a special character."
)


def _validate_password_strength(value: str) -> str:
    if len(value) < _PASSWORD_MIN_LENGTH:
        raise ValueError(_PASSWORD_POLICY_MSG)
    if not _PASSWORD_PATTERN.match(value):
        raise ValueError(_PASSWORD_POLICY_MSG)
    return value


class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserCreate(UserBase):
    password: constr(min_length=8)
    trial_token: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        return normalize_company_name(value)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: str
    role: str
    subscription_plan: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)
    email_verified: bool
    created_at: str | None = None
    portal_only: bool = False
    portal_workspace_id: int | None = None
    avatar_url: str | None = None
    auth_provider: str | None = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenData(BaseModel):
    sub: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str
    password: constr(min_length=8)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class EmailVerification(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Passkey / WebAuthn schemas
# ---------------------------------------------------------------------------


class PasskeyRegistrationOptionsResponse(BaseModel):
    """Server → Client: PublicKeyCredentialCreationOptions (JSON-serialised)."""

    options: dict


class PasskeyRegistrationVerifyRequest(BaseModel):
    """Client → Server: Authenticator attestation response + friendly name."""

    credential: dict
    name: str = Field(default="My Passkey", max_length=120)


class PasskeyRegistrationVerifyResponse(BaseModel):
    id: int
    credential_id: str
    name: str


class PasskeyLoginOptionsResponse(BaseModel):
    """Server → Client: PublicKeyCredentialRequestOptions (JSON-serialised)."""

    options: dict


class PasskeyLoginVerifyRequest(BaseModel):
    """Client → Server: Authenticator assertion response."""

    credential: dict


class PasskeyListItem(BaseModel):
    id: int
    credential_id: str
    name: str
    created_at: str | None = None
    last_used_at: str | None = None
    backed_up: bool = False


class PasskeyRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasskeyDeleteResponse(BaseModel):
    deleted: bool = True


# ---------------------------------------------------------------------------
# Linked provider identities (SIGV2-1257)
# ---------------------------------------------------------------------------


class LinkedIdentityStartRequest(BaseModel):
    """Re-authentication for connecting a sign-in provider to this account.

    The password is the account's own, which is the only credential the
    product already trusts at this point: the provider's email claim is
    exactly what SIGV2-1239 stopped trusting.
    """

    current_password: str = Field(min_length=1)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirm must be true to connect a sign-in provider.")
        return value


class LinkedIdentityStartResponse(BaseModel):
    link_token: str
    authorize_path: str


class LinkedIdentityStatus(BaseModel):
    provider: str
    configured: bool
    linked: bool
    linked_at: str | None = None


class LinkedIdentityListResponse(BaseModel):
    identities: list[LinkedIdentityStatus]
