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
from database import Base, get_db as database_get_db
from main import app, get_db as api_get_db
import middleware.maintenance as maintenance_module


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
        external_id="onboarding-user",
        auth_provider="local",
        provider_subject="onboarding-user",
        email="onboarding@example.com",
        hashed_password=hash_password("Password123!"),
        role="user",
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

    app.dependency_overrides[database_get_db] = override_get_db
    app.dependency_overrides[api_get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), db


def test_onboarding_state_roundtrip(monkeypatch):
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    client, db = _build_client()
    try:
        initial = client.get("/api/v1/users/me/onboarding")
        assert initial.status_code == 200
        assert initial.json() == {
            "completed_steps": [],
            "started_at": None,
            "dismissed_at": None,
            "updated_at": None,
        }

        update = client.patch(
            "/api/v1/users/me/onboarding",
            json={
                "started": True,
                "add_completed_steps": ["workspace_named", "first_project", "unknown_step"],
            },
        )
        assert update.status_code == 200
        update_payload = update.json()
        assert update_payload["completed_steps"] == ["workspace_named", "first_project"]
        assert update_payload["started_at"] is not None
        assert update_payload["dismissed_at"] is None
        assert update_payload["updated_at"] is not None

        refreshed = client.get("/api/v1/users/me/onboarding")
        assert refreshed.status_code == 200
        assert refreshed.json()["completed_steps"] == ["workspace_named", "first_project"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_onboarding_state_dismiss_toggle(monkeypatch):
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    client, db = _build_client()
    try:
        dismiss = client.patch("/api/v1/users/me/onboarding", json={"dismissed": True})
        assert dismiss.status_code == 200
        assert dismiss.json()["dismissed_at"] is not None

        restore = client.patch("/api/v1/users/me/onboarding", json={"dismissed": False})
        assert restore.status_code == 200
        assert restore.json()["dismissed_at"] is None
    finally:
        app.dependency_overrides.clear()
        db.close()
