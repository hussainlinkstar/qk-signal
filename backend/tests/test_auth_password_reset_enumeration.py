from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

from database import Base
import models
from routers.auth import forgot_password, reset_password
from schemas.auth import ForgotPasswordRequest, PasswordReset
from services.auth_service import AuthService


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.asyncio
async def test_forgot_password_is_non_enumerating_for_unknown_email(db_session) -> None:
    response = await forgot_password(
        payload=ForgotPasswordRequest(email="unknown@example.com"),
        db=db_session,
    )

    assert response["message"] == "If the email exists, password reset instructions have been sent"


@pytest.mark.asyncio
async def test_reset_password_masks_missing_user_as_invalid_token(db_session) -> None:
    from services.auth_service import JWT_ALGORITHM, JWT_SECRET_KEY

    token = jwt.encode(
        {
            "sub": "missing@example.com",
            "type": "password_reset",
            "credential_version": "invalid",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(HTTPException) as exc_info:
        await reset_password(
            reset_data=PasswordReset(
                token=token,
                password="Passw0rd!",
            ),
            db=db_session,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired reset token"


@pytest.mark.asyncio
async def test_password_reset_token_is_invalid_after_first_success(db_session) -> None:
    user = models.User(
        email="reset@example.com",
        hashed_password="$2b$12$initial-password-hash",
        role="user",
        credits=0,
    )
    db_session.add(user)
    db_session.commit()
    service = AuthService(db_session)
    token = service.create_password_reset_token(user.email)

    response = await reset_password(
        reset_data=PasswordReset(token=token, password="NewPassw0rd!"),
        db=db_session,
    )
    assert response["message"] == "Password has been reset successfully"

    with pytest.raises(HTTPException) as exc_info:
        await reset_password(
            reset_data=PasswordReset(token=token, password="OtherPassw0rd!"),
            db=db_session,
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired reset token"


def test_legacy_password_reset_token_without_credential_version_is_rejected(db_session) -> None:
    from services.auth_service import JWT_ALGORITHM, JWT_SECRET_KEY

    user = models.User(
        email="legacy@example.com",
        hashed_password="existing-hash",
        role="user",
        credits=0,
    )
    db_session.add(user)
    db_session.commit()
    token = jwt.encode(
        {
            "sub": user.email,
            "type": "password_reset",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    assert AuthService(db_session).verify_password_reset_token(token) is None
