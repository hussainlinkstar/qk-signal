"""SIGV2-1241: MFA enrollment must bind only the server-minted TOTP secret."""

from __future__ import annotations

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
import pyotp
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base, get_db
from main import app


def _build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        external_id="mfa-enroll-user",
        auth_provider="local",
        provider_subject="mfa-enroll-user",
        email="mfa-enroll@example.com",
        hashed_password=hash_password("Password123"),
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


def test_enable_mfa_rejects_client_supplied_secret_without_setup_token():
    client, db, user = _build_client()
    try:
        attacker_secret = pyotp.random_base32()
        response = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "secret": attacker_secret,
                "otp_code": pyotp.TOTP(attacker_secret).now(),
            },
        )

        assert 400 <= response.status_code < 500

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_mfa_rejects_client_secret_with_invalid_setup_token():
    client, db, user = _build_client()
    try:
        attacker_secret = pyotp.random_base32()
        response = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "secret": attacker_secret,
                "setup_token": "not-a-valid-setup-token",
                "otp_code": pyotp.TOTP(attacker_secret).now(),
            },
        )

        assert 400 <= response.status_code < 500

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_mfa_ignores_client_secret_and_binds_server_minted_secret():
    client, db, user = _build_client()
    try:
        setup_response = client.post("/api/v1/users/me/mfa/setup")
        assert setup_response.status_code == 200
        setup_payload = setup_response.json()
        server_secret = setup_payload["secret"]
        attacker_secret = pyotp.random_base32()

        response = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "secret": attacker_secret,
                "setup_token": setup_payload["setup_token"],
                "otp_code": pyotp.TOTP(server_secret).now(),
            },
        )

        assert response.status_code == 200
        assert response.json()["enabled"] is True

        db.refresh(user)
        assert user.mfa_secret == server_secret
        assert user.mfa_secret != attacker_secret
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_mfa_rejects_otp_generated_from_client_secret():
    client, db, user = _build_client()
    try:
        setup_response = client.post("/api/v1/users/me/mfa/setup")
        assert setup_response.status_code == 200
        setup_payload = setup_response.json()
        attacker_secret = pyotp.random_base32()

        response = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "secret": attacker_secret,
                "setup_token": setup_payload["setup_token"],
                "otp_code": pyotp.TOTP(attacker_secret).now(),
            },
        )

        assert response.status_code == 400

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()
