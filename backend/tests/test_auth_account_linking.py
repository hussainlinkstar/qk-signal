"""SIGV2-1257: manual Microsoft account linking from account settings.

SIGV2-1239 stopped the OAuth callback from auto-linking a Microsoft identity
to an existing account on the strength of an unverified email claim. That
refusal stays. These tests cover the recovery path it left missing: an
explicit, password-proven link started from account settings, plus the
guarantee that the callback still refuses the silent auto-link.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import middleware.maintenance as maintenance
import models
import routers.auth as auth_router
from auth.security import get_current_user_from_token as get_current_user
from core.password_hashing import hash_password
from database import Base, get_db as database_get_db
from main import app, get_db as api_get_db

ACCOUNT_PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def microsoft_sso_configured(monkeypatch):
    monkeypatch.setenv("MICROSOFT_SSO_CLIENT_ID", "sso-client-id")


@pytest.fixture(autouse=True)
def identity_link_nonce_store(monkeypatch):
    """Stand in for Redis while keeping the real single-use semantics."""
    store: dict[str, str] = {}

    async def _arm(jti: str, user_id: int) -> None:
        store[jti] = str(user_id)

    async def _consume(jti: str) -> str | None:
        return store.pop(jti, None)

    monkeypatch.setattr(auth_router, "_arm_identity_link", _arm)
    monkeypatch.setattr(auth_router, "_consume_identity_link", _consume)
    return store


def _build_client(
    *, seed_account: bool = True
) -> tuple[TestClient, sessionmaker, models.User | None]:
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

    account: models.User | None = None
    if seed_account:
        db = testing_session()
        try:
            account = models.User(
                email="owner@example.com",
                hashed_password=hash_password(ACCOUNT_PASSWORD),
                auth_provider="local",
                provider_subject="owner-local",
                external_id="owner-local",
                email_verified=True,
                role="user",
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        finally:
            db.close()

        def override_get_current_user():
            db = testing_session()
            try:
                return db.query(models.User).filter(models.User.email == "owner@example.com").one()
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), testing_session, account


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


def _install_fake_client(monkeypatch, claims: dict[str, Any]) -> _FakeMicrosoftOAuthClient:
    fake_client = _FakeMicrosoftOAuthClient(token_payload={"_ms_id_token": _build_id_token(claims)})
    monkeypatch.setattr(
        auth_router.oauth,
        "create_client",
        lambda provider: fake_client if provider == "microsoft" else None,
    )

    async def _fake_store_oauth_code(access_token: str, refresh_token: str) -> str:
        return "one-time-oauth-code"

    monkeypatch.setattr(auth_router, "_store_oauth_code", _fake_store_oauth_code)
    return fake_client


def _start_link(client: TestClient, *, password: str = ACCOUNT_PASSWORD, **extra: Any):
    payload: dict[str, Any] = {"current_password": password, "confirm": True}
    payload.update(extra)
    return client.post("/api/v1/auth/linked-identities/microsoft/start", json=payload)


MS_CLAIMS = {
    "sub": "ms-subject-owner",
    "preferred_username": "owner@contoso.example",
    "name": "Owner At Work",
}


# ---------------------------------------------------------------------------
# The linking flow itself
# ---------------------------------------------------------------------------


def test_link_succeeds_with_correct_password_and_confirmation(monkeypatch):
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    try:
        start = _start_link(client)
        assert start.status_code == 200
        link_token = start.json()["link_token"]
        assert link_token

        authorize = client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={link_token}",
            follow_redirects=False,
        )
        assert authorize.status_code in (302, 307)

        callback = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )
        assert callback.status_code in (302, 307)
        assert "/dashboard/account-settings" in callback.headers["location"]
        assert "linked=microsoft" in callback.headers["location"]

        db = session_factory()
        try:
            identity = db.query(models.UserLinkedIdentity).one()
            assert identity.user_id == account.id
            assert identity.provider == "microsoft"
            assert identity.subject == "ms-subject-owner"
            # The account keeps its own password credentials: linking adds a
            # way in, it does not convert the account to an SSO-only one.
            owner = db.query(models.User).filter(models.User.id == account.id).one()
            assert owner.auth_provider == "local"
            assert db.query(models.User).count() == 1
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_microsoft_signin_resolves_the_linked_account(monkeypatch):
    """Once linked, the normal callback signs the user into their own account."""
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    db = session_factory()
    try:
        db.add(
            models.UserLinkedIdentity(
                user_id=account.id,
                provider="microsoft",
                subject="ms-subject-owner",
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        assert (
            response.headers["location"]
            == "http://localhost:3000/auth/callback?code=one-time-oauth-code"
        )

        db = session_factory()
        try:
            assert db.query(models.User).count() == 1
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_link_refused_without_the_correct_password():
    client, _session_factory, _account = _build_client()

    try:
        response = _start_link(client, password="not-the-password")

        assert response.status_code == 400
        assert "password" in response.json()["detail"].lower()
        assert "link_token" not in response.json()
    finally:
        _cleanup_overrides()


def test_link_refused_without_explicit_confirmation():
    client, _session_factory, _account = _build_client()

    try:
        missing = client.post(
            "/api/v1/auth/linked-identities/microsoft/start",
            json={"current_password": ACCOUNT_PASSWORD},
        )
        assert missing.status_code == 422

        declined = client.post(
            "/api/v1/auth/linked-identities/microsoft/start",
            json={"current_password": ACCOUNT_PASSWORD, "confirm": False},
        )
        assert declined.status_code == 422
    finally:
        _cleanup_overrides()


def test_link_binds_to_the_session_user_not_a_body_user_id(monkeypatch):
    """A user id in the request body is ignored; the session user is linked."""
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    db = session_factory()
    try:
        other = models.User(
            email="other@example.com",
            hashed_password=hash_password(ACCOUNT_PASSWORD),
            auth_provider="local",
            email_verified=True,
        )
        db.add(other)
        db.commit()
        other_id = other.id
    finally:
        db.close()

    try:
        start = _start_link(client, user_id=other_id)
        assert start.status_code == 200

        client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={start.json()['link_token']}",
            follow_redirects=False,
        )
        client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        db = session_factory()
        try:
            identity = db.query(models.UserLinkedIdentity).one()
            assert identity.user_id == account.id
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_link_refused_when_identity_belongs_to_another_account(monkeypatch):
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    db = session_factory()
    try:
        stranger = models.User(
            email="stranger@example.com",
            hashed_password=hash_password(ACCOUNT_PASSWORD),
            auth_provider="local",
            email_verified=True,
        )
        db.add(stranger)
        db.commit()
        db.add(
            models.UserLinkedIdentity(
                user_id=stranger.id,
                provider="microsoft",
                subject="ms-subject-owner",
            )
        )
        db.commit()
        stranger_id = stranger.id
    finally:
        db.close()

    try:
        start = _start_link(client)
        assert start.status_code == 200
        client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={start.json()['link_token']}",
            follow_redirects=False,
        )
        callback = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert callback.status_code in (302, 307)
        assert "link_error=identity_already_linked" in callback.headers["location"]

        db = session_factory()
        try:
            identities = db.query(models.UserLinkedIdentity).all()
            assert len(identities) == 1
            assert identities[0].user_id == stranger_id
            assert identities[0].user_id != account.id
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_link_refused_when_identity_is_an_existing_sso_account(monkeypatch):
    """The subject may also sit on a user row from an SSO-native signup."""
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    db = session_factory()
    try:
        db.add(
            models.User(
                email="sso-native@example.com",
                hashed_password=hash_password(ACCOUNT_PASSWORD),
                auth_provider="microsoft",
                provider_subject="ms-subject-owner",
                external_id="ms-subject-owner",
                email_verified=True,
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        start = _start_link(client)
        client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={start.json()['link_token']}",
            follow_redirects=False,
        )
        callback = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert "link_error=identity_already_linked" in callback.headers["location"]

        db = session_factory()
        try:
            assert db.query(models.UserLinkedIdentity).count() == 0
            owner = db.query(models.User).filter(models.User.id == account.id).one()
            assert owner.auth_provider == "local"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_authorize_leg_rejects_an_invalid_link_token(monkeypatch):
    client, session_factory, _account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    try:
        response = client.get(
            "/api/v1/auth/linked-identities/microsoft/authorize?link_token=not-a-token",
            follow_redirects=False,
        )
        assert response.status_code == 400

        # No link was armed, so a callback arriving afterwards falls back to
        # the ordinary sign-in rules and must not attach anything.
        callback = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )
        assert callback.status_code in (302, 307, 400)

        db = session_factory()
        try:
            assert db.query(models.UserLinkedIdentity).count() == 0
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_link_token_cannot_be_replayed(monkeypatch):
    client, _session_factory, _account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(monkeypatch, MS_CLAIMS)

    try:
        link_token = _start_link(client).json()["link_token"]

        first = client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={link_token}",
            follow_redirects=False,
        )
        assert first.status_code in (302, 307)

        replay = client.get(
            f"/api/v1/auth/linked-identities/microsoft/authorize?link_token={link_token}",
            follow_redirects=False,
        )
        assert replay.status_code == 400
    finally:
        _cleanup_overrides()


def test_link_refused_when_provider_is_not_configured(monkeypatch):
    client, _session_factory, _account = _build_client()
    monkeypatch.delenv("MICROSOFT_SSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("BING_CLIENT_ID", raising=False)

    try:
        assert _start_link(client).status_code == 503

        status_entry = next(
            item
            for item in client.get("/api/v1/auth/linked-identities").json()["identities"]
            if item["provider"] == "microsoft"
        )
        assert status_entry["configured"] is False
    finally:
        _cleanup_overrides()


def test_linked_identities_status_reports_provider_state():
    client, session_factory, account = _build_client()

    try:
        before = client.get("/api/v1/auth/linked-identities")
        assert before.status_code == 200
        entry = next(
            item for item in before.json()["identities"] if item["provider"] == "microsoft"
        )
        assert entry["configured"] is True
        assert entry["linked"] is False

        db = session_factory()
        try:
            db.add(
                models.UserLinkedIdentity(
                    user_id=account.id,
                    provider="microsoft",
                    subject="ms-subject-owner",
                )
            )
            db.commit()
        finally:
            db.close()

        after = client.get("/api/v1/auth/linked-identities")
        entry = next(item for item in after.json()["identities"] if item["provider"] == "microsoft")
        assert entry["linked"] is True
    finally:
        _cleanup_overrides()


# ---------------------------------------------------------------------------
# SIGV2-1239 must stay exactly as strict, and the refusal must now say what
# to do next instead of dead-ending.
# ---------------------------------------------------------------------------


def test_callback_still_refuses_to_auto_link_an_unverified_email(monkeypatch):
    client, session_factory, account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(
        monkeypatch,
        {
            "sub": "attacker-ms-subject",
            "preferred_username": "owner@example.com",
            "name": "Attacker",
        },
    )

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert response.status_code == 400

        db = session_factory()
        try:
            owner = db.query(models.User).filter(models.User.id == account.id).one()
            assert owner.auth_provider == "local"
            assert owner.provider_subject == "owner-local"
            assert db.query(models.UserLinkedIdentity).count() == 0
            assert db.query(models.User).count() == 1
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_auto_link_refusal_names_the_next_step(monkeypatch):
    client, _session_factory, _account = _build_client()
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    _install_fake_client(
        monkeypatch,
        {
            "sub": "attacker-ms-subject",
            "preferred_username": "owner@example.com",
            "name": "Attacker",
        },
    )

    try:
        response = client.get(
            "/api/v1/auth/microsoft/callback?code=provider-code",
            follow_redirects=False,
        )

        assert response.status_code == 400
        body = response.text.lower()
        assert "password" in body
        assert "account settings" in body
        assert "http://localhost:3000/login" in response.text
    finally:
        _cleanup_overrides()
