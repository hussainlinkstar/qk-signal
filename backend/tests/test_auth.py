from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
import jwt
from core.password_hashing import hash_password
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base, get_db as database_get_db
from main import app, get_db as api_get_db
import main
from middleware import maintenance as maintenance_module
from services.auth_service import JWT_ALGORITHM, JWT_REFRESH_SECRET_KEY, JWT_SECRET_KEY


@pytest.fixture(autouse=True)
def _isolate_app_middleware(monkeypatch: pytest.MonkeyPatch):
    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)


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
    return TestClient(app), testing_session


def _cleanup_overrides() -> None:
    app.dependency_overrides.clear()


def test_register_user():
    client, session_factory = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "Test12345!",
                "name": "Test User",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert (
            payload["message"]
            == "If this email is not already registered, a verification link has been sent."
        )

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "test@example.com").first()
            assert user is not None
            # SIGV2-1157: the company entered at sign-up must be persisted, it is
            # what names the owner's first workspace.
            assert user.company_name == "Test User"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_register_user_persists_signup_company_name():
    client, session_factory = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@raizn.example",
                "password": "Test12345!",
                "name": "  Raizn  ",
            },
        )

        assert response.status_code == 200

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "owner@raizn.example").first()
            assert user is not None
            assert user.company_name == "Raizn"

            from routers.workspace_router import _default_workspace_name

            assert _default_workspace_name(user) == "Raizn Workspace"
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_register_user_without_a_company_name_is_accepted():
    client, session_factory = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "nameless@example.com",
                "password": "Test12345!",
                "name": "   ",
            },
        )

        assert response.status_code == 200

        db = session_factory()
        try:
            user = db.query(models.User).filter(models.User.email == "nameless@example.com").first()
            assert user is not None
            assert user.company_name is None
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_register_user_rejects_an_overlong_company_name():
    client, _ = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "overlong@example.com",
                "password": "Test12345!",
                "name": "R" * 121,
            },
        )

        assert response.status_code == 422
    finally:
        _cleanup_overrides()


def test_profile_update_rejects_an_overlong_company_name():
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            db.add(
                models.User(
                    email="profile-overlong@example.com",
                    hashed_password=hash_password("Test12345!"),
                    role="user",
                    auth_provider="local",
                    provider_subject="local-profile-overlong",
                    external_id="local-profile-overlong",
                    email_verified=True,
                )
            )
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "profile-overlong@example.com", "password": "Test12345!"},
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]

        response = client.patch(
            "/api/v1/users/me",
            json={"name": "N" * 121},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422
    finally:
        _cleanup_overrides()


def test_login_success_and_auth_me():
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="test@example.com",
                hashed_password=hash_password("Test12345!"),
                role="user",
                auth_provider="local",
                provider_subject="local-test-user",
                external_id="local-test-user",
                email_verified=True,
            )
            db.add(user)
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@example.com", "password": "Test12345!"},
        )
        assert login_response.status_code == 200
        login_payload = login_response.json()
        assert "access_token" in login_payload
        assert "refresh_token" in login_payload
        assert login_payload["token_type"] == "bearer"

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login_payload['access_token']}"},
        )
        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["email"] == "test@example.com"
        assert me_payload["role"] == "user"
        assert "audit:run" in me_payload["permissions"]
    finally:
        _cleanup_overrides()


def test_login_invalid_credentials():
    client, _session_factory = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "missing@example.com", "password": "wrongpassword"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password"
    finally:
        _cleanup_overrides()


def test_refresh_token():
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="refresh@example.com",
                hashed_password=hash_password("Refresh123!"),
                role="user",
                auth_provider="local",
                provider_subject="local-refresh-user",
                external_id="local-refresh-user",
                email_verified=True,
            )
            db.add(user)
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "refresh@example.com", "password": "Refresh123!"},
        )
        assert login_response.status_code == 200

        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": login_response.json()["refresh_token"]},
        )
        assert refresh_response.status_code == 200
        refresh_payload = refresh_response.json()
        assert "access_token" in refresh_payload
        assert "refresh_token" in refresh_payload
    finally:
        _cleanup_overrides()


def test_refresh_token_rotates_session_and_denies_reuse():
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="rotate@example.com",
                hashed_password=hash_password("Rotate123!"),
                role="user",
                auth_provider="local",
                provider_subject="local-rotate-user",
                external_id="local-rotate-user",
                email_verified=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "rotate@example.com", "password": "Rotate123!"},
        )
        assert login_response.status_code == 200
        original_refresh_token = login_response.json()["refresh_token"]
        original_refresh_claims = jwt.decode(
            original_refresh_token,
            JWT_REFRESH_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )
        assert refresh_response.status_code == 200
        rotated_refresh_token = refresh_response.json()["refresh_token"]
        rotated_refresh_claims = jwt.decode(
            rotated_refresh_token,
            JWT_REFRESH_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        assert rotated_refresh_claims["jti"] != original_refresh_claims["jti"]

        db = session_factory()
        try:
            original_session = (
                db.query(models.UserSession)
                .filter(models.UserSession.token_jti == original_refresh_claims["jti"])
                .first()
            )
            rotated_session = (
                db.query(models.UserSession)
                .filter(models.UserSession.token_jti == rotated_refresh_claims["jti"])
                .first()
            )
            assert original_session is not None
            assert rotated_session is not None
            assert original_session.is_active is False
            assert rotated_session.is_active is True
        finally:
            db.close()

        reuse_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )
        assert reuse_response.status_code == 401
        assert reuse_response.json()["detail"] in {
            "Token has been revoked",
            "Session has been revoked or expired",
        }
    finally:
        _cleanup_overrides()


def test_logout_deactivates_current_session():
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="logout@example.com",
                hashed_password=hash_password("Logout123!"),
                role="user",
                auth_provider="local",
                provider_subject="local-logout-user",
                external_id="local-logout-user",
                email_verified=True,
            )
            db.add(user)
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "logout@example.com", "password": "Logout123!"},
        )
        assert login_response.status_code == 200
        payload = login_response.json()
        access_claims = jwt.decode(
            payload["access_token"],
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        logout_response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": payload["refresh_token"]},
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert logout_response.status_code == 200

        db = session_factory()
        try:
            session = (
                db.query(models.UserSession)
                .filter(models.UserSession.token_jti == access_claims["jti"])
                .first()
            )
            assert session is not None
            assert session.is_active is False
        finally:
            db.close()
    finally:
        _cleanup_overrides()


def test_login_remember_me_sets_refresh_token_claim() -> None:
    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="remember@example.com",
                hashed_password=hash_password("Remember123!"),
                role="user",
                auth_provider="local",
                provider_subject="local-remember-user",
                external_id="local-remember-user",
                email_verified=True,
            )
            db.add(user)
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "remember@example.com",
                "password": "Remember123!",
                "remember_me": "true",
            },
        )
        assert login_response.status_code == 200

        payload = login_response.json()
        decoded_refresh = jwt.decode(
            payload["refresh_token"],
            JWT_REFRESH_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        assert decoded_refresh.get("remember_me") is True
    finally:
        _cleanup_overrides()
