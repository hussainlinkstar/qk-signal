import os
import sys
import types
from pathlib import Path

os.environ.setdefault("SSM_ENABLED", "false")


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException
from core.password_hashing import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

email_service_stub = types.ModuleType("services.email_service")


class _NoopEmailService:
    def __init__(self, *_args, **_kwargs):
        return None

    async def send_verification_email(self, *_args, **_kwargs):
        return None

    async def send_password_reset_email(self, *_args, **_kwargs):
        return None

    async def send_welcome_email(self, *_args, **_kwargs):
        return None


email_service_stub.EmailService = _NoopEmailService
sys.modules.setdefault("services.email_service", email_service_stub)

import models
from core.config import settings
from database import Base
import services.auth_service as auth_service_module
from services.auth_service import (
    AuthService,
    create_linkedin_oauth_state,
    verify_linkedin_oauth_state,
)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise auth_service_module.httpx.HTTPStatusError(
                "request failed",
                request=auth_service_module.httpx.Request("GET", "https://example.com"),
                response=auth_service_module.httpx.Response(self.status_code, json=self._payload),
            )


class _FakeAsyncClient:
    def __init__(self, token_payload: dict, profile_payload: dict):
        self._token_payload = token_payload
        self._profile_payload = profile_payload
        self.post_calls = []
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, data=None, timeout=None):
        self.post_calls.append({"url": url, "data": data, "timeout": timeout})
        return _FakeResponse(self._token_payload)

    async def get(self, url, *, headers=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse(self._profile_payload)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def linkedin_settings(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_CLIENT_ID", "linkedin-client-id", raising=False)
    monkeypatch.setattr(settings, "LINKEDIN_CLIENT_SECRET", "linkedin-client-secret", raising=False)
    monkeypatch.setattr(
        settings, "LINKEDIN_REDIRECT_URI", "http://localhost:3000/auth/callback", raising=False
    )


@pytest.mark.asyncio
async def test_process_linkedin_login_registers_new_user(monkeypatch, db_session):
    fake_client = _FakeAsyncClient(
        token_payload={"access_token": "linkedin-access-token"},
        profile_payload={
            "sub": "linkedin-sub-123",
            "email": "new-linkedin-user@example.com",
            "name": "LinkedIn New User",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        auth_service_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    service = AuthService(db_session)
    tokens = await service.process_linkedin_login("auth-code-123")

    assert tokens["token_type"] == "bearer"
    created_user = (
        db_session.query(models.User)
        .filter(models.User.email == "new-linkedin-user@example.com")
        .one()
    )
    assert created_user.auth_provider == "linkedin"
    assert created_user.provider_subject == "linkedin-sub-123"
    assert created_user.external_id == "linkedin-sub-123"
    assert created_user.company_name == "LinkedIn New User"
    assert created_user.hashed_password.startswith("$2")
    assert str(service.verify_token(tokens["access_token"])) == str(created_user.id)
    assert str(service.verify_token(tokens["refresh_token"], is_refresh=True)) == str(
        created_user.id
    )
    assert fake_client.post_calls[0]["url"] == "https://www.linkedin.com/oauth/v2/accessToken"
    assert (
        fake_client.post_calls[0]["data"]["redirect_uri"] == "http://localhost:3000/auth/callback"
    )
    assert fake_client.get_calls[0]["url"] == "https://api.linkedin.com/v2/userinfo"
    assert fake_client.get_calls[0]["headers"]["Authorization"] == "Bearer linkedin-access-token"


@pytest.mark.asyncio
async def test_process_linkedin_login_links_existing_user(monkeypatch, db_session):
    existing_user = models.User(
        email="existing-user@example.com",
        hashed_password=hash_password("StrongPass1!"),
        company_name="Existing Company",
    )
    db_session.add(existing_user)
    db_session.commit()

    fake_client = _FakeAsyncClient(
        token_payload={"access_token": "existing-linkedin-access-token"},
        profile_payload={
            "sub": "linkedin-sub-existing",
            "email": "existing-user@example.com",
            "name": "Existing Company",
            "email_verified": "true",
        },
    )
    monkeypatch.setattr(
        auth_service_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    service = AuthService(db_session)
    tokens = await service.process_linkedin_login("auth-code-existing")

    db_session.refresh(existing_user)
    assert db_session.query(models.User).count() == 1
    assert existing_user.auth_provider == "linkedin"
    assert existing_user.provider_subject == "linkedin-sub-existing"
    assert existing_user.external_id == "linkedin-sub-existing"
    assert existing_user.company_name == "Existing Company"
    assert tokens["token_type"] == "bearer"
    assert str(service.verify_token(tokens["access_token"])) == str(existing_user.id)


def test_verify_linkedin_oauth_state_rejects_invalid_token():
    valid_state = create_linkedin_oauth_state()
    verify_linkedin_oauth_state(valid_state)

    with pytest.raises(HTTPException) as exc:
        verify_linkedin_oauth_state("invalid-state-token")

    assert exc.value.status_code == 401
    assert "LinkedIn OAuth state" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_get_or_create_oauth_user_links_existing_user_case_insensitive(
    db_session,
):
    """SIGV2-1248: a differently-cased provider email links to the stored
    lowercase account instead of creating a duplicate."""
    existing_user = models.User(
        email="alice@example.com",
        hashed_password=hash_password("StrongPass1!"),
        email_verified=True,
    )
    db_session.add(existing_user)
    db_session.commit()

    service = AuthService(db_session)
    user = await service.get_or_create_oauth_user(
        provider="google",
        subject="google-sub-alice",
        email="Alice@Example.com",
        name="Alice",
        provider_email_verified=True,
    )

    db_session.refresh(existing_user)
    assert user.id == existing_user.id
    assert db_session.query(models.User).count() == 1
    assert existing_user.auth_provider == "google"
    assert existing_user.provider_subject == "google-sub-alice"
