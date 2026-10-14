from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db


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
        external_id="role-mode-user",
        auth_provider="local",
        provider_subject="role-mode-user",
        email="role-mode@example.com",
        hashed_password=hash_password("OldPassword123"),
        role="user",
        company_name="Role Mode Co",
        notifications_enabled=True,
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


def test_patch_and_get_role_mode():
    client, db, _user = _build_client()
    try:
        patch_response = client.patch(
            "/api/v1/workspaces/current",
            json={"role_mode": "enterprise"},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["role_mode"] == "enterprise"

        get_response = client.get("/api/v1/workspaces/current")
        assert get_response.status_code == 200
        assert get_response.json()["role_mode"] == "enterprise"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_patch_role_mode_rejects_invalid():
    client, db, _user = _build_client()
    try:
        response = client.patch(
            "/api/v1/workspaces/current",
            json={"role_mode": "wizard"},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()
