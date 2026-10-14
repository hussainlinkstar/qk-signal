import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import database
import main
import models
from core.config import settings
from database import Base
from services.external_api_service import hash_api_key

PROVISION_URL = "/api/v1/internal/signal/provision-key"
SECRET = "super-secret-service-token"


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _build_client(db: Session) -> TestClient:
    def override_get_db():
        yield db

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    return TestClient(main.app)


def test_provision_disabled_returns_503_without_configured_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNAL_PROVISION_SECRET", None)
    db, engine = _build_db()
    try:
        client = _build_client(db)
        resp = client.post(
            PROVISION_URL,
            json={"tenant_ref": "agent-uuid-1"},
            headers={"X-Signal-Service-Secret": "anything"},
        )
        assert resp.status_code == 503
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_provision_rejects_missing_or_wrong_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNAL_PROVISION_SECRET", SECRET)
    db, engine = _build_db()
    try:
        client = _build_client(db)
        assert client.post(PROVISION_URL, json={"tenant_ref": "a"}).status_code == 401
        assert (
            client.post(
                PROVISION_URL,
                json={"tenant_ref": "a"},
                headers={"X-Signal-Service-Secret": "wrong"},
            ).status_code
            == 401
        )
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_provision_creates_tenant_user_and_mints_scoped_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNAL_PROVISION_SECRET", SECRET)
    monkeypatch.setattr(settings, "SIGNAL_PROVISION_DEFAULT_CREDITS", 7)
    db, engine = _build_db()
    try:
        client = _build_client(db)
        resp = client.post(
            PROVISION_URL,
            json={"tenant_ref": "agent-uuid-1", "name": "Acme Signal"},
            headers={"X-Signal-Service-Secret": SECRET},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["api_key"].startswith("stx_live_")
        assert body["user_created"] is True
        assert body["tenant_ref"] == "agent-uuid-1"
        assert body["scopes"] == ["audit:read", "audit:write", "projects:read"]

        user = db.query(models.User).filter(models.User.external_id == "agent-uuid-1").first()
        assert user is not None
        assert user.auth_provider == "signal_tenant"
        assert user.credits == 7
        assert user.id == body["user_id"]

        api_key = db.query(models.ApiKey).filter(models.ApiKey.id == body["key_id"]).first()
        assert api_key is not None
        assert api_key.user_id == user.id
        assert api_key.scopes == ["audit:read", "audit:write", "projects:read"]
        # The raw key returned must hash to the stored hash (and never be stored raw).
        assert api_key.key_hash == hash_api_key(body["api_key"])

        # A real engine project (in a workspace the tenant admins) is created so
        # audits bind to it and project-buckets read real data.
        assert body["project_id"] > 0 and body["workspace_id"] > 0
        project = db.query(models.Project).filter(models.Project.id == body["project_id"]).first()
        assert project is not None and project.workspace_id == body["workspace_id"]
        workspace = (
            db.query(models.Workspace).filter(models.Workspace.id == body["workspace_id"]).first()
        )
        assert workspace is not None and workspace.owner_id == user.id
        membership = (
            db.query(models.WorkspaceUser)
            .filter(
                models.WorkspaceUser.workspace_id == workspace.id,
                models.WorkspaceUser.user_id == user.id,
            )
            .first()
        )
        assert membership is not None and membership.role == models.WorkspaceRole.ADMIN
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_provision_is_idempotent_on_user_and_mints_a_fresh_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNAL_PROVISION_SECRET", SECRET)
    db, engine = _build_db()
    try:
        client = _build_client(db)
        first = client.post(
            PROVISION_URL,
            json={"tenant_ref": "agent-uuid-2"},
            headers={"X-Signal-Service-Secret": SECRET},
        ).json()
        second = client.post(
            PROVISION_URL,
            json={"tenant_ref": "agent-uuid-2"},
            headers={"X-Signal-Service-Secret": SECRET},
        ).json()

        assert first["user_created"] is True
        assert second["user_created"] is False
        assert first["user_id"] == second["user_id"]
        # Stable project across calls (find-or-create), fresh key each call.
        assert first["project_id"] == second["project_id"]
        assert first["key_id"] != second["key_id"]
        assert first["api_key"] != second["api_key"]
        assert db.query(models.User).filter(models.User.external_id == "agent-uuid-2").count() == 1
        assert (
            db.query(models.Project).filter(models.Project.id == first["project_id"]).count() == 1
        )
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
