"""SIGV2-1240: password reset and password change must revoke existing sessions.

A refresh token issued before the credential change stays valid for up to 30
days unless the user's ``UserSession`` rows are deactivated and their JTIs
deny-listed. These tests prove a pre-change refresh token is rejected
immediately afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from core.password_hashing import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db
from services.auth_service import AuthService


def _build_client(email: str = "revoke@example.com", password: str = "OldPassword123"):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        external_id="revoke-user",
        auth_provider="local",
        provider_subject="revoke-user",
        email=email,
        hashed_password=hash_password(password),
        role="user",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), db, user


def _issue_tokens(db, user) -> dict:
    return AuthService(db).build_token_response(user)


def _cleanup_overrides() -> None:
    app.dependency_overrides.clear()


def test_refresh_token_is_rejected_after_password_reset():
    client, db, user = _build_client()
    try:
        tokens = _issue_tokens(db, user)
        reset_token = AuthService(db).create_password_reset_token(user.email)

        reset_response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "password": "NewPassword123!"},
        )
        assert reset_response.status_code == 200

        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refresh_response.status_code == 401
    finally:
        _cleanup_overrides()


def test_refresh_token_is_rejected_after_password_change():
    client, db, user = _build_client()
    try:
        tokens = _issue_tokens(db, user)

        change_response = client.post(
            "/api/v1/users/me/password",
            json={"current_password": "OldPassword123", "new_password": "NewPassword123"},
        )
        assert change_response.status_code == 200

        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refresh_response.status_code == 401

        db.expire_all()
        sessions = db.query(models.UserSession).filter(models.UserSession.user_id == user.id).all()
        assert sessions
        assert all(session.is_active is not True for session in sessions)
    finally:
        _cleanup_overrides()


@pytest.mark.asyncio
async def test_revoke_session_jtis_counts_only_successes(monkeypatch):
    """revoked_sessions must reflect real Redis writes, not attempts."""
    import middleware.session_checker as session_checker

    async def _flaky(jti: str, *args, **kwargs) -> bool:
        return jti != "failing-jti"

    monkeypatch.setattr(session_checker, "revoke_session_jti", _flaky)

    revoked = await session_checker.revoke_session_jtis(["jti-1", "failing-jti", "jti-2"])

    assert revoked == 2
