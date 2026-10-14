import sys
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from auth import token_verifier


class _FakeDB:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refresh_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, _user) -> None:
        self.refresh_calls += 1


def test_apply_admin_promotion_uses_stored_email_when_claim_missing(monkeypatch):
    # The allowlist is read from the Settings singleton (built at import), not
    # live env, so patch the settings attribute directly.
    monkeypatch.setattr(token_verifier.settings, "ADMIN_EMAILS", "admin@example.com", raising=False)

    user = SimpleNamespace(email="admin@example.com", role="user")
    db = _FakeDB()

    updated_user = token_verifier.apply_admin_promotion(user, email=None, db=db)

    assert updated_user.role == "admin"
    assert db.commit_calls == 1
    assert db.refresh_calls == 1


def test_extract_bearer_token_rejects_missing_authorization():
    try:
        token_verifier.extract_bearer_token(None)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("Expected missing authorization to fail")


def test_decode_access_token_validates_token_type(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "dev-secret")
    payload = {"sub": "123", "type": "refresh"}
    token = jwt.encode(payload, "dev-secret", algorithm="HS256")

    try:
        token_verifier.decode_access_token(token)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("Expected refresh token to be rejected as access token")


def test_extract_role_permissions_uses_claim_permissions():
    user = SimpleNamespace(role="user")
    role, permissions = token_verifier.extract_role_permissions(
        {"role": "admin", "permissions": ["audit:run", "admin:users"]},
        user,
    )

    assert role == "user"
    assert permissions == ["audit:read", "audit:run", "profile:read", "profile:update"]


def test_extract_role_permissions_uses_claim_permissions_when_role_matches():
    user = SimpleNamespace(role="admin")
    role, permissions = token_verifier.extract_role_permissions(
        {"role": "admin", "permissions": ["audit:run", "admin:users"]},
        user,
    )

    assert role == "admin"
    assert permissions == ["admin:users", "audit:run"]


def test_extract_role_permissions_uses_promoted_database_role_over_stale_claims(monkeypatch):
    monkeypatch.setattr(token_verifier.settings, "ADMIN_EMAILS", "admin@example.com", raising=False)

    user = SimpleNamespace(email="admin@example.com", role="user")
    db = _FakeDB()

    promoted_user = token_verifier.apply_admin_promotion(user, email=None, db=db)
    role, permissions = token_verifier.extract_role_permissions(
        {"role": "user", "permissions": ["audit:run"]},
        promoted_user,
    )

    assert promoted_user.role == "admin"
    assert role == "admin"
    assert permissions == ["*"]


def _make_db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import models as _models
    from database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session, _models


def test_resolve_user_from_claims_returns_the_normalized_email_claim():
    """SIGV2-1268: resolution is by numeric sub only; the email claim is still
    returned, normalized to lowercase, for apply_admin_promotion and logging."""
    testing_session, models = _make_db_session()
    db = testing_session()
    try:
        existing = models.User(
            email="alice@example.com",
            hashed_password="x",
            auth_provider="google",
            provider_subject="other-subject",
            external_id="other-subject",
        )
        db.add(existing)
        db.commit()

        user, email = token_verifier._resolve_user_from_claims(
            db, {"sub": str(existing.id), "email": "Alice@Example.com"}
        )

        assert user.id == existing.id
        assert email == "alice@example.com"
        assert db.query(models.User).count() == 1
        assert user.email == "alice@example.com"
    finally:
        db.close()


def test_resolve_user_from_claims_rejects_non_numeric_subject():
    """SIGV2-1268: a non-numeric sub fails closed even when the email claim
    matches a stored user; the email fallback was an identity-confusion path."""
    testing_session, models = _make_db_session()
    db = testing_session()
    try:
        existing = models.User(
            email="alice@example.com",
            hashed_password="x",
            auth_provider="google",
            provider_subject="other-subject",
            external_id="other-subject",
        )
        db.add(existing)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            token_verifier._resolve_user_from_claims(
                db, {"sub": "new-subject-1", "email": "Alice@Example.com"}
            )
        assert exc_info.value.status_code == 401
        assert db.query(models.User).count() == 1
    finally:
        db.close()
