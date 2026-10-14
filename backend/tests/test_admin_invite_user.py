"""Tests for the admin "invite user" endpoint (POST /admin/users/invite)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from admin import AdminInviteUserRequest, get_db, invite_admin_user
from auth.token_verifier import get_current_user as base_get_current_user
from database import Base
from main import app
from services.email_service import EmailService


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine) -> None:
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _make_admin_user(db: Session) -> models.User:
    admin_user = models.User(
        email="admin-invite@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    return admin_user


def test_invite_admin_user_creates_user_queues_email_and_logs_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        admin_user = _make_admin_user(db)
        captured_email: dict[str, object] = {}

        async def _fake_send_password_reset_email(self, email, token, *, user_id=None):
            captured_email["email"] = email
            captured_email["token"] = token
            captured_email["user_id"] = user_id
            return SimpleNamespace(id=1)

        monkeypatch.setattr(
            EmailService,
            "send_password_reset_email",
            _fake_send_password_reset_email,
        )

        response = asyncio.run(
            invite_admin_user(
                payload=AdminInviteUserRequest(
                    email="New.Client@Example.com",
                    name="New Client",
                    role="user",
                ),
                admin_user=admin_user,
                db=db,
            )
        )

        created_user = (
            db.query(models.User).filter(models.User.email == "new.client@example.com").first()
        )
        assert created_user is not None
        assert created_user.role == "user"
        assert created_user.company_name == "New Client"
        # A random, unguessable password must be set - never the raw token or a
        # predictable value.
        assert created_user.hashed_password
        assert created_user.hashed_password != "x"

        assert response.user_id == created_user.id
        assert response.email == "new.client@example.com"
        assert response.role == "user"
        assert response.invited is True
        assert response.email_queued is True
        # The raw invitation link must never be returned when the email queued.
        assert response.invitation_url is None

        assert captured_email["email"] == "new.client@example.com"
        assert captured_email["user_id"] == created_user.id

        action_log = (
            db.query(models.AdminActionLog)
            .filter(models.AdminActionLog.action == "invite_user")
            .first()
        )
        assert action_log is not None
        assert action_log.target_type == "user"
        assert action_log.target_id == str(created_user.id)
        assert action_log.admin_user_id == admin_user.id
        assert action_log.metadata_json["email"] == "new.client@example.com"
        assert action_log.metadata_json["role"] == "user"
    finally:
        _cleanup(db, engine)


def test_invite_admin_user_returns_manual_link_when_email_not_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        admin_user = _make_admin_user(db)

        async def _fake_send_password_reset_email(self, email, token, *, user_id=None):
            return None

        monkeypatch.setattr(
            EmailService,
            "send_password_reset_email",
            _fake_send_password_reset_email,
        )

        response = asyncio.run(
            invite_admin_user(
                payload=AdminInviteUserRequest(email="manual-link@example.com"),
                admin_user=admin_user,
                db=db,
            )
        )

        assert response.email_queued is False
        assert response.invitation_url is not None
        assert "/reset-password?token=" in response.invitation_url
    finally:
        _cleanup(db, engine)


def test_invite_admin_user_duplicate_email_returns_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        admin_user = _make_admin_user(db)
        existing = models.User(
            email="existing@example.com",
            hashed_password="x",
            role="user",
        )
        db.add(existing)
        db.commit()

        async def _fake_send_password_reset_email(self, email, token, *, user_id=None):
            return SimpleNamespace(id=1)

        monkeypatch.setattr(
            EmailService,
            "send_password_reset_email",
            _fake_send_password_reset_email,
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                invite_admin_user(
                    payload=AdminInviteUserRequest(email="EXISTING@example.com"),
                    admin_user=admin_user,
                    db=db,
                )
            )

        assert exc_info.value.status_code == 409
    finally:
        _cleanup(db, engine)


def test_invite_admin_user_invalid_role_returns_400() -> None:
    db, engine = _build_db()
    try:
        admin_user = _make_admin_user(db)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                invite_admin_user(
                    payload=AdminInviteUserRequest(email="bad-role@example.com", role="superuser"),
                    admin_user=admin_user,
                    db=db,
                )
            )

        assert exc_info.value.status_code == 400
    finally:
        _cleanup(db, engine)


def _build_http_client(role: str):
    """Build a TestClient with the real ``get_current_admin_user`` role gate wired up.

    Mirrors the pattern used in ``test_moderator_role.py``: only the base
    ``get_current_user`` dependency is overridden so the admin-only role gate
    on the invite endpoint runs its real logic.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    user = models.User(
        email=f"{role}-caller@example.com",
        hashed_password="hashed",
        role=role,
        credits=100,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    setattr(user, "resolved_role", role)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_base_get_current_user() -> models.User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[base_get_current_user] = override_base_get_current_user

    return TestClient(app), db, engine


def test_invite_admin_user_endpoint_blocks_non_admin_caller() -> None:
    client, db, engine = _build_http_client("user")
    try:
        response = client.post(
            "/api/v1/admin/users/invite",
            json={"email": "someone@example.com"},
        )
        assert response.status_code == 403
    finally:
        client.close()
        _cleanup(db, engine)


def test_invite_admin_user_endpoint_blocks_moderator_caller() -> None:
    client, db, engine = _build_http_client("moderator")
    try:
        response = client.post(
            "/api/v1/admin/users/invite",
            json={"email": "someone-else@example.com"},
        )
        assert response.status_code == 403
    finally:
        client.close()
        _cleanup(db, engine)
