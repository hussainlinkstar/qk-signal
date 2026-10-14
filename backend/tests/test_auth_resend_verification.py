from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db as database_get_db
from main import app, get_db as api_get_db
import routers.auth as auth_router_module
import middleware.maintenance as maintenance_module
from services.auth_service import AuthService


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


async def _allow_resend(*_args, **_kwargs) -> bool:
    return True


async def _deny_resend(*_args, **_kwargs) -> bool:
    return False


def test_resend_verification_sends_generic_success_and_queues_email(monkeypatch) -> None:
    monkeypatch.setattr(auth_router_module, "_acquire_resend_verification_slot", _allow_resend)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    send_mock = AsyncMock()
    monkeypatch.setattr(AuthService, "send_verification_email_if_available", send_mock)

    client, session_factory = _build_client()
    try:
        db = session_factory()
        try:
            user = models.User(
                email="resend@example.com",
                hashed_password=hash_password("Password123!"),
                auth_provider="local",
                provider_subject="resend-user",
                external_id="resend-user",
                role="user",
            )
            db.add(user)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "resend@example.com"},
        )

        assert response.status_code == 200
        assert (
            response.json()["message"] == "If the email exists, a verification link has been sent."
        )
        assert send_mock.await_count == 1
    finally:
        _cleanup_overrides()


def test_resend_verification_rate_limit_returns_429(monkeypatch) -> None:
    monkeypatch.setattr(auth_router_module, "_acquire_resend_verification_slot", _deny_resend)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    client, _session_factory = _build_client()
    try:
        response = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "resend@example.com"},
        )
        assert response.status_code == 429
        assert (
            response.json()["detail"]
            == "Please wait 60 seconds before requesting another verification email."
        )
    finally:
        _cleanup_overrides()
