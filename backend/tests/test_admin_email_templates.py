"""Tests for TASK_ADMIN-10: Email Template Preview & Test Send endpoints."""

from __future__ import annotations

import models
from admin import get_db
from auth.token_verifier import get_current_staff_user
from database import Base
from main import app

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _build_client_with_db(admin_user: models.User):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_get_current_user
    return TestClient(app), db


def _cleanup(db):
    app.dependency_overrides.clear()
    db.close()


def _admin_user() -> models.User:
    return models.User(
        email="admin-templates@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )


# ---------------------------------------------------------------------------
# GET /admin/email-templates
# ---------------------------------------------------------------------------


def test_list_email_templates():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.get("/api/v1/admin/email-templates")
        assert response.status_code == 200
        data = response.json()

        assert "templates" in data
        assert "categories" in data
        assert "total" in data
        assert data["total"] > 0
        assert isinstance(data["templates"], list)
        assert isinstance(data["categories"], list)

        first = data["templates"][0]
        assert "key" in first
        assert "subject" in first
        assert "html_template" in first
        assert "category" in first
    finally:
        _cleanup(db)


def test_list_templates_contains_known_keys():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.get("/api/v1/admin/email-templates")
        data = response.json()
        keys = {t["key"] for t in data["templates"]}
        assert "auth.welcome" in keys
        assert "audit.completed" in keys
        assert "invoice.paid" in keys
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# GET /admin/email-templates/default-context
# ---------------------------------------------------------------------------


def test_default_context_returns_dict():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.get("/api/v1/admin/email-templates/default-context")
        assert response.status_code == 200
        data = response.json()
        assert "context" in data
        ctx = data["context"]
        assert isinstance(ctx, dict)
        assert "email" in ctx
        assert "user_name" in ctx
        assert "project_name" in ctx
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# POST /admin/email-templates/{key}/preview
# ---------------------------------------------------------------------------


def test_preview_known_template():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/auth.welcome/preview",
            json={"context": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "auth.welcome"
        assert "subject" in data
        assert "html" in data
        assert len(data["html"]) > 100
        assert "category" in data
    finally:
        _cleanup(db)


def test_preview_with_custom_context():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/auth.welcome/preview",
            json={"context": {"user_name": "Custom Test User"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "Custom Test User" in data["html"]
    finally:
        _cleanup(db)


def test_preview_unknown_template_404():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/nonexistent.template/preview",
            json={"context": {}},
        )
        assert response.status_code == 404
    finally:
        _cleanup(db)


def test_preview_empty_body_uses_defaults():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/invoice.paid/preview",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "billing"
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# POST /admin/email-templates/{key}/test-send
# ---------------------------------------------------------------------------


def test_test_send_queues_outbox_entry():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/auth.welcome/test-send",
            json={"to_email": "test@example.com", "context": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["to_email"] == "test@example.com"
        assert data["subject"].startswith("[TEST]")
        assert "outbox_id" in data

        outbox = db.query(models.EmailOutbox).filter_by(id=data["outbox_id"]).first()
        assert outbox is not None
        assert outbox.to_email == "test@example.com"
        assert outbox.subject.startswith("[TEST]")
        assert outbox.template_key == "auth.welcome"
        assert outbox.status == "pending"
        assert outbox.correlation_id.startswith("admin-test-")
    finally:
        _cleanup(db)


def test_test_send_logs_admin_action():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/audit.completed/test-send",
            json={"to_email": "qa@example.com"},
        )
        assert response.status_code == 200

        log = (
            db.query(models.AdminActionLog)
            .filter_by(action="email_test_send", target_type="email_template")
            .first()
        )
        assert log is not None
        assert log.target_id == "audit.completed"
        meta = log.metadata_json if isinstance(log.metadata_json, dict) else {}
        assert meta.get("to_email") == "qa@example.com"
    finally:
        _cleanup(db)


def test_test_send_unknown_template_404():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/fake.template/test-send",
            json={"to_email": "test@example.com"},
        )
        assert response.status_code == 404
    finally:
        _cleanup(db)


def test_test_send_invalid_email_422():
    admin = _admin_user()
    client, db = _build_client_with_db(admin)
    try:
        response = client.post(
            "/api/v1/admin/email-templates/auth.welcome/test-send",
            json={"to_email": "not-an-email"},
        )
        assert response.status_code == 422
    finally:
        _cleanup(db)
