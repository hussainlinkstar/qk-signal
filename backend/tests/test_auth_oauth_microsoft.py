from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import MagicMock

from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import middleware.maintenance as maintenance
import routers.auth as auth_router
from database import Base, get_db as database_get_db
from main import app, get_db as api_get_db
from services.oauth_service import _microsoft_sso_compliance_fix, _bing_compliance_fix


def _build_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_get_db] = override_get_db
    app.dependency_overrides[api_get_db] = override_get_db
    maintenance._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }
    return TestClient(app), testing_session


def _cleanup_overrides() -> None:
    app.dependency_overrides.clear()


def _build_id_token(claims: dict[str, Any]) -> str:
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}."


class _FakeMicrosoftOAuthClient:
    def __init__(self, token_payload: dict[str, Any] | None = None) -> None:
        self.token_payload = token_payload or {}
        self.redirect_calls: list[dict[str, object]] = []

    async def authorize_redirect(self, request, redirect_uri: str, **kwargs):
        self.redirect_calls.append({"redirect_uri": redirect_uri, "kwargs": kwargs})
        return RedirectResponse(url="https://login.microsoftonline.com/mock/authorize")

    async def authorize_access_token(self, request):
        return self.token_payload


def test_login_microsoft_oauth_redirects_to_provider(monkeypatch):
    client, _session_factory = _build_client()
    fake_client = _FakeMicrosoftOAuthClient()
    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )

    try:
        response = client.get("/api/v1/auth/login/microsoft", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "https://login.microsoftonline.com/mock/authorize"
        assert fake_client.redirect_calls
        assert fake_client.redirect_calls[0]["redirect_uri"].endswith(
            "/api/v1/auth/microsoft/callback"
        )
    finally:
        _cleanup_overrides()


def test_microsoft_oauth_callback_creates_user_from_id_token(monkeypatch):
    client, session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    fake_client = _FakeMicrosoftOAuthClient(
        token_payload={
            "id_token": _build_id_token(
                {
                    "sub": "microsoft-subject-123",
                    "preferred_username": "azure-user@example.com",
                    "name": "Azure User",
                }
            )
        }
    )

    async def _fake_store_oauth_code(access_token: str, refresh_token: str) -> str:
        assert access_token
        assert refresh_token
        return "one-time-oauth-code"

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )
    monkeypatch.setattr(auth_router, "_store_oauth_code", _fake_store_oauth_code)

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert (
            response.headers["location"]
            == "http://localhost:3000/auth/callback?code=one-time-oauth-code"
        )

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "azure-user@example.com").one()
            assert user.auth_provider == "microsoft"
            assert user.provider_subject == "microsoft-subject-123"
            assert user.company_name == "Azure User"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_microsoft_oauth_callback_creates_user_from_ms_id_token(monkeypatch):
    """Token dict uses _ms_id_token key (compliance fix stripped id_token)."""
    client, session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    fake_client = _FakeMicrosoftOAuthClient(
        token_payload={
            "_ms_id_token": _build_id_token(
                {
                    "sub": "ms-subject-456",
                    "preferred_username": "compliance-user@example.com",
                    "name": "Compliance User",
                }
            )
        }
    )

    async def _fake_store_oauth_code(access_token: str, refresh_token: str) -> str:
        return "one-time-oauth-code-2"

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )
    monkeypatch.setattr(auth_router, "_store_oauth_code", _fake_store_oauth_code)

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert response.status_code == 307

        db = session_factory()
        try:
            user = (
                db.query(models.User)
                .filter(models.User.email == "compliance-user@example.com")
                .one()
            )
            assert user.auth_provider == "microsoft"
            assert user.provider_subject == "ms-subject-456"
            assert user.company_name == "Compliance User"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_microsoft_sso_compliance_fix_moves_id_token():
    """The compliance hook must move id_token → _ms_id_token in the response."""
    session = MagicMock()
    registered_hooks: list = []
    session.register_compliance_hook = lambda name, fn: registered_hooks.append((name, fn))

    _microsoft_sso_compliance_fix(session)

    assert len(registered_hooks) == 1
    hook_name, hook_fn = registered_hooks[0]
    assert hook_name == "access_token_response"

    fake_resp = MagicMock()
    fake_resp.json = lambda **kw: {
        "access_token": "at",
        "id_token": "raw-jwt",
        "token_type": "bearer",
    }

    patched = hook_fn(fake_resp)
    data = patched.json()

    assert "id_token" not in data
    assert data["_ms_id_token"] == "raw-jwt"
    assert data["access_token"] == "at"


def test_microsoft_sso_compliance_fix_preserves_refresh_token():
    """The compliance hook must not strip refresh_token or other fields."""
    session = MagicMock()
    registered_hooks: list = []
    session.register_compliance_hook = lambda name, fn: registered_hooks.append((name, fn))

    _microsoft_sso_compliance_fix(session)
    _, hook_fn = registered_hooks[0]

    fake_resp = MagicMock()
    fake_resp.json = lambda **kw: {
        "access_token": "at",
        "refresh_token": "rt",
        "id_token": "raw-jwt",
        "token_type": "bearer",
        "expires_in": 3600,
    }

    patched = hook_fn(fake_resp)
    data = patched.json()

    assert data["refresh_token"] == "rt"
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600
    assert "id_token" not in data
    assert data["_ms_id_token"] == "raw-jwt"


# ---------------------------------------------------------------------------
# T-2: Both id_token and _ms_id_token missing → clean error
# ---------------------------------------------------------------------------


def test_microsoft_callback_no_tokens_returns_error(monkeypatch):
    """Empty token dict (no id_token, no _ms_id_token) → 400."""
    client, _session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    fake_client = _FakeMicrosoftOAuthClient(token_payload={})

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "email" in response.json().get("detail", "").lower()
    finally:
        _cleanup_overrides()


# ---------------------------------------------------------------------------
# T-3: authorize_access_token throws → proper error handling
# ---------------------------------------------------------------------------


class _FakeErrorOAuthClient:
    """Fake client that raises an exception on authorize_access_token."""

    def __init__(self, error_msg: str) -> None:
        self.error_msg = error_msg

    async def authorize_redirect(self, request, redirect_uri: str, **kwargs):
        return RedirectResponse(url="https://login.microsoftonline.com/mock/authorize")

    async def authorize_access_token(self, request):
        raise Exception(self.error_msg)


def test_microsoft_callback_state_mismatch_redirects(monkeypatch):
    """Exception with 'mismatching_state' → redirect to /login?error=oauth_state_mismatch."""
    client, _session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    fake_client = _FakeErrorOAuthClient("mismatching_state: CSRF Warning!")

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=c&state=s",
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "oauth_state_mismatch" in location
        assert "provider=microsoft" in location
    finally:
        _cleanup_overrides()


def test_microsoft_callback_generic_error_redirects(monkeypatch):
    """Generic exception → redirect to /login?error=oauth_failed."""
    client, _session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    fake_client = _FakeErrorOAuthClient("some unexpected provider error")

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=c&state=s",
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "/login?" in location
        assert "error=oauth_failed" in location
        assert "provider=microsoft" in location
    finally:
        _cleanup_overrides()


# ---------------------------------------------------------------------------
# T-4: Malformed JWT id_token → graceful degradation
# ---------------------------------------------------------------------------


def test_extract_id_token_claims_malformed_jwt():
    """Malformed JWT strings return {} without crashing."""
    from routers.auth import _extract_id_token_claims

    assert _extract_id_token_claims(None) == {}
    assert _extract_id_token_claims("") == {}
    assert _extract_id_token_claims("not-a-jwt") == {}
    assert _extract_id_token_claims("x.INVALID_BASE64_!!!.z") == {}
    assert _extract_id_token_claims("x.") == {}
    # Valid header but payload decodes to a non-dict (e.g. a JSON string)
    payload = base64.urlsafe_b64encode(json.dumps("just-a-string").encode()).rstrip(b"=").decode()
    assert _extract_id_token_claims(f"h.{payload}.s") == {}


def test_extract_id_token_claims_valid_two_part_token():
    """A two-part token (no signature) should still decode correctly."""
    from routers.auth import _extract_id_token_claims

    claims = {"sub": "test", "email": "a@b.com"}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    result = _extract_id_token_claims(f"header.{payload}")
    assert result["sub"] == "test"
    assert result["email"] == "a@b.com"


# ---------------------------------------------------------------------------
# T-5: Bing compliance fix unit test
# ---------------------------------------------------------------------------


def test_bing_compliance_fix_strips_id_token():
    """The bing compliance hook must strip id_token entirely (not preserve it)."""
    session = MagicMock()
    registered_hooks: list = []
    session.register_compliance_hook = lambda name, fn: registered_hooks.append((name, fn))

    _bing_compliance_fix(session)

    assert len(registered_hooks) == 1
    hook_name, hook_fn = registered_hooks[0]
    assert hook_name == "access_token_response"

    fake_resp = MagicMock()
    fake_resp.json = lambda **kw: {
        "access_token": "bing-at",
        "refresh_token": "bing-rt",
        "id_token": "should-be-stripped",
        "token_type": "bearer",
    }

    patched = hook_fn(fake_resp)
    data = patched.json()

    assert "id_token" not in data
    assert "_ms_id_token" not in data  # bing strips, does not preserve
    assert data["access_token"] == "bing-at"
    assert data["refresh_token"] == "bing-rt"


def test_bing_compliance_fix_no_id_token_is_noop():
    """When no id_token is present, the bing hook is a no-op."""
    session = MagicMock()
    registered_hooks: list = []
    session.register_compliance_hook = lambda name, fn: registered_hooks.append((name, fn))

    _bing_compliance_fix(session)
    _, hook_fn = registered_hooks[0]

    fake_resp = MagicMock()
    fake_resp.json = lambda **kw: {"access_token": "at", "token_type": "bearer"}

    patched = hook_fn(fake_resp)
    data = patched.json()

    assert data == {"access_token": "at", "token_type": "bearer"}


# ---------------------------------------------------------------------------
# SEC-1: aud / exp validation in _extract_microsoft_profile
# ---------------------------------------------------------------------------


def test_microsoft_profile_rejects_wrong_audience(monkeypatch):
    """Mismatched aud claim → profile extraction returns None email/subject."""
    from routers.auth import _extract_microsoft_profile

    monkeypatch.setenv("MICROSOFT_SSO_CLIENT_ID", "correct-client-id")

    token = {
        "_ms_id_token": _build_id_token(
            {
                "sub": "sub-1",
                "preferred_username": "user@example.com",
                "name": "User",
                "aud": "wrong-client-id",
            }
        )
    }
    email, subject, name, _ = _extract_microsoft_profile(token)
    assert email is None
    assert subject is None


def test_microsoft_profile_rejects_expired_token(monkeypatch):
    """Expired exp claim → profile extraction returns None email/subject."""
    from routers.auth import _extract_microsoft_profile

    monkeypatch.delenv("MICROSOFT_SSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("BING_CLIENT_ID", raising=False)

    token = {
        "_ms_id_token": _build_id_token(
            {
                "sub": "sub-1",
                "preferred_username": "user@example.com",
                "name": "User",
                "exp": 1000000000,  # 2001-09-09, well in the past
            }
        )
    }
    email, subject, name, _ = _extract_microsoft_profile(token)
    assert email is None
    assert subject is None


def test_microsoft_profile_accepts_valid_audience(monkeypatch):
    """Matching aud claim → profile extraction succeeds."""
    from routers.auth import _extract_microsoft_profile

    monkeypatch.setenv("MICROSOFT_SSO_CLIENT_ID", "my-client-id")

    token = {
        "_ms_id_token": _build_id_token(
            {
                "sub": "sub-ok",
                "preferred_username": "ok@example.com",
                "name": "OK User",
                "aud": "my-client-id",
            }
        )
    }
    email, subject, name, _ = _extract_microsoft_profile(token)
    assert email == "ok@example.com"
    assert subject == "sub-ok"


def test_microsoft_profile_skips_aud_check_when_no_client_id(monkeypatch):
    """When no client ID is configured, aud check is skipped (permissive)."""
    from routers.auth import _extract_microsoft_profile

    monkeypatch.delenv("MICROSOFT_SSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("BING_CLIENT_ID", raising=False)

    token = {
        "_ms_id_token": _build_id_token(
            {
                "sub": "sub-ok",
                "preferred_username": "ok@example.com",
                "aud": "any-value",
            }
        )
    }
    email, subject, _, _ = _extract_microsoft_profile(token)
    assert email == "ok@example.com"
    assert subject == "sub-ok"


# ---------------------------------------------------------------------------
# SIGV2-1239: unverified Microsoft email must never auto-link to an existing
# account. Entra id_tokens often omit email_verified entirely and the claim is
# tenant-admin-settable, so absence means unverified, not verified.
# ---------------------------------------------------------------------------


def _seed_local_user(session_factory, email: str = "victim@example.com") -> None:
    from core.password_hashing import hash_password

    db = session_factory()
    try:
        db.add(
            models.User(
                email=email,
                hashed_password=hash_password("Password123"),
                role="user",
                auth_provider="local",
                provider_subject="local-victim",
                external_id="local-victim",
                email_verified=True,
            )
        )
        db.commit()
    finally:
        db.close()


def _run_microsoft_callback_with_claims(
    monkeypatch, session_factory, client, claims: dict[str, Any]
) -> Any:
    fake_client = _FakeMicrosoftOAuthClient(token_payload={"_ms_id_token": _build_id_token(claims)})

    async def _fake_store_oauth_code(access_token: str, refresh_token: str) -> str:
        return "one-time-oauth-code-3"

    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )
    monkeypatch.setattr(auth_router, "_store_oauth_code", _fake_store_oauth_code)

    return client.get(
        "/api/v1/auth/microsoft/callback?code=provider-code",
        follow_redirects=False,
    )


def test_microsoft_callback_absent_email_verified_does_not_link(monkeypatch):
    """Missing email_verified claim must not auto-link to an existing user."""
    client, session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _seed_local_user(session_factory)

    try:
        response = _run_microsoft_callback_with_claims(
            monkeypatch,
            session_factory,
            client,
            {
                "sub": "attacker-ms-subject",
                "preferred_username": "victim@example.com",
                "name": "Attacker",
            },
        )

        assert response.status_code == 400

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "victim@example.com").one()
            assert user.auth_provider == "local"
            assert user.provider_subject == "local-victim"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_microsoft_callback_false_email_verified_does_not_link(monkeypatch):
    """Explicitly false email_verified must not auto-link to an existing user."""
    client, session_factory = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _seed_local_user(session_factory)

    try:
        response = _run_microsoft_callback_with_claims(
            monkeypatch,
            session_factory,
            client,
            {
                "sub": "attacker-ms-subject",
                "preferred_username": "victim@example.com",
                "name": "Attacker",
                "email_verified": False,
            },
        )

        assert response.status_code == 400

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "victim@example.com").one()
            assert user.auth_provider == "local"
            assert user.provider_subject == "local-victim"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_microsoft_profile_absent_email_verified_is_unverified():
    """Absent email_verified claim resolves to False, not bool(email)."""
    from routers.auth import _extract_microsoft_profile

    token = {
        "_ms_id_token": _build_id_token(
            {
                "sub": "ms-sub",
                "preferred_username": "user@example.com",
            }
        )
    }
    email, _, _, email_verified = _extract_microsoft_profile(token)
    assert email == "user@example.com"
    assert email_verified is False
