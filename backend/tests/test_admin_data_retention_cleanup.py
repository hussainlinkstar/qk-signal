from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from admin import get_current_user, get_db
from database import Base
from main import app


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
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), db, admin_user


def _seed_audit(
    db,
    user_id: int,
    *,
    url: str,
    days_ago: int,
    screenshot: str | None = None,
):
    audit = models.Audit(
        user_id=user_id,
        url=url,
        geo_score=50,
        full_report={"screenshot_base64": screenshot, "metadata": {"tier": "fast"}},
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def test_cleanup_data_retention_deletes_old_audits_when_retention_days_set(monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "30")
    monkeypatch.delenv("AUDIT_STRIP_SCREENSHOTS_AFTER_DAYS", raising=False)

    admin_user = models.User(
        email="admin-retention@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db, _ = _build_client_with_db(admin_user)

    _seed_audit(db, admin_user.id, url="https://old.example.com", days_ago=45)
    kept = _seed_audit(db, admin_user.id, url="https://new.example.com", days_ago=5)

    response = client.post("/api/v1/admin/data-retention/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audits_deleted"] == 1
    assert payload["screenshots_redacted"] == 0

    assert (
        db.query(models.Audit).filter(models.Audit.url == "https://old.example.com").first() is None
    )
    assert db.query(models.Audit).filter(models.Audit.id == kept.id).first() is not None

    app.dependency_overrides.clear()
    db.close()


def test_cleanup_data_retention_redacts_screenshots_when_strip_days_set(monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_STRIP_SCREENSHOTS_AFTER_DAYS", "10")
    monkeypatch.delenv("AUDIT_RETENTION_DAYS", raising=False)

    admin_user = models.User(
        email="admin-strip@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db, _ = _build_client_with_db(admin_user)

    old_with_screenshot = _seed_audit(
        db,
        admin_user.id,
        url="https://strip.example.com",
        days_ago=20,
        screenshot="abc123",
    )

    response = client.post("/api/v1/admin/data-retention/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audits_deleted"] == 0
    assert payload["screenshots_redacted"] == 1

    db.refresh(old_with_screenshot)
    assert old_with_screenshot.full_report["screenshot_base64"] is None
    assert old_with_screenshot.sanitized_at is not None

    app.dependency_overrides.clear()
    db.close()


def test_cleanup_data_retention_deletes_and_redacts_when_both_settings_set(monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "30")
    monkeypatch.setenv("AUDIT_STRIP_SCREENSHOTS_AFTER_DAYS", "10")

    admin_user = models.User(
        email="admin-both@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db, _ = _build_client_with_db(admin_user)

    _seed_audit(
        db,
        admin_user.id,
        url="https://deleted.example.com",
        days_ago=45,
        screenshot="to-delete",
    )
    redacted_only = _seed_audit(
        db,
        admin_user.id,
        url="https://redacted.example.com",
        days_ago=15,
        screenshot="to-redact",
    )
    kept = _seed_audit(
        db,
        admin_user.id,
        url="https://kept.example.com",
        days_ago=5,
        screenshot="keep",
    )

    response = client.post("/api/v1/admin/data-retention/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audits_deleted"] == 1
    assert payload["screenshots_redacted"] == 1
    assert payload["retention_days"] == 30
    assert payload["strip_screenshots_after_days"] == 10

    assert (
        db.query(models.Audit).filter(models.Audit.url == "https://deleted.example.com").first()
        is None
    )

    db.refresh(redacted_only)
    assert redacted_only.full_report["screenshot_base64"] is None
    assert redacted_only.sanitized_at is not None

    db.refresh(kept)
    assert kept.full_report["screenshot_base64"] == "keep"
    assert kept.sanitized_at is None

    app.dependency_overrides.clear()
    db.close()


def test_cleanup_data_retention_noop_when_settings_missing_or_non_positive(monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "0")
    monkeypatch.setenv("AUDIT_STRIP_SCREENSHOTS_AFTER_DAYS", "-5")

    admin_user = models.User(
        email="admin-noop@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db, _ = _build_client_with_db(admin_user)

    existing = _seed_audit(
        db,
        admin_user.id,
        url="https://noop.example.com",
        days_ago=365,
        screenshot="still-there",
    )

    response = client.post("/api/v1/admin/data-retention/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audits_deleted"] == 0
    assert payload["screenshots_redacted"] == 0
    assert payload["retention_days"] is None
    assert payload["strip_screenshots_after_days"] is None

    db.refresh(existing)
    assert existing.full_report["screenshot_base64"] == "still-there"
    assert existing.sanitized_at is None

    app.dependency_overrides.clear()
    db.close()


def test_cleanup_data_retention_blocks_non_admin_access() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        raise HTTPException(status_code=403, detail="Admin access required.")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    response = client.post("/api/v1/admin/data-retention/cleanup")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."

    app.dependency_overrides.clear()
    db.close()
