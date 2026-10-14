"""SIGV2-1268 / SIGV2-1273 / SIGV2-1274: ``_resolve_user_from_claims`` must be
read-only on the user row and must fail closed when the subject cannot be
resolved to a user id. Every access token is minted by
``AuthService.create_access_token`` with ``sub = str(user.id)``, so resolution
is a primary-key lookup, nothing else.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import jwt as pyjwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.token_verifier import JWT_ALGORITHM, JWT_SECRET_KEY
from core.password_hashing import hash_password
from database import Base
from main import app, get_db
from services.auth_service import AuthService


def _build_client(*users: models.User) -> tuple[TestClient, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()
    for user in users:
        db.add(user)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), db


def _user(email: str, **overrides) -> models.User:
    defaults = {
        "external_id": f"ext-{email}",
        "auth_provider": "local",
        "provider_subject": f"sub-{email}",
        "email": email,
        "hashed_password": hash_password("Password123!"),
        "role": "user",
        "email_verified": True,
    }
    defaults.update(overrides)
    return models.User(**defaults)


def _access_token(db: Session, user: models.User) -> str:
    return AuthService(db).create_access_token(user)


def _me(client: TestClient, token: str):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_provider_identity_columns_survive_an_authenticated_request():
    user = _user(
        "sso@example.com",
        auth_provider="microsoft",
        provider_subject="ms-sub-abc",
        external_id="ms-ext-abc",
    )
    client, db = _build_client(user)
    token = _access_token(db, user)
    try:
        assert _me(client, token).status_code == 200

        db.expire_all()
        stored = db.get(models.User, user.id)
        assert stored.provider_subject == "ms-sub-abc"
        assert stored.external_id == "ms-ext-abc"
        assert stored.auth_provider == "microsoft"
    finally:
        db.close()
        app.dependency_overrides.clear()


def test_stale_email_claim_does_not_overwrite_the_stored_email():
    user = _user("before@example.com")
    client, db = _build_client(user)
    token = _access_token(db, user)
    user.email = "after@example.com"
    db.commit()
    try:
        assert _me(client, token).status_code == 200

        db.expire_all()
        assert db.get(models.User, user.id).email == "after@example.com"
    finally:
        db.close()
        app.dependency_overrides.clear()


def test_token_for_a_deleted_user_is_rejected_and_recreates_nothing():
    user = _user("gone@example.com")
    client, db = _build_client(user)
    token = _access_token(db, user)
    db.delete(user)
    db.commit()
    try:
        assert _me(client, token).status_code == 401
        assert db.query(models.User).count() == 0
    finally:
        db.close()
        app.dependency_overrides.clear()


def test_unresolvable_subject_and_deleted_user_fail_identically():
    user = _user("gone@example.com")
    client, db = _build_client(user)
    deleted_token = _access_token(db, user)
    db.delete(user)
    db.commit()
    try:
        deleted_response = _me(client, deleted_token)

        phantom_token = pyjwt.encode(
            {
                "sub": "424242",
                "email": "ghost@example.com",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )
        phantom_response = _me(client, phantom_token)

        assert deleted_response.status_code == phantom_response.status_code == 401
        assert deleted_response.json() == phantom_response.json()
    finally:
        db.close()
        app.dependency_overrides.clear()


def test_intact_user_still_authenticates_with_role_and_permissions():
    user = _user("intact@example.com", role="admin")
    client, db = _build_client(user)
    token = _access_token(db, user)
    try:
        response = _me(client, token)
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "intact@example.com"
        assert body["role"] == "admin"
        assert body["permissions"] == ["*"]
    finally:
        db.close()
        app.dependency_overrides.clear()
