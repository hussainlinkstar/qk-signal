from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from core.password_hashing import hash_password, verify_password
import pyotp
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
        external_id="settings-user",
        auth_provider="local",
        provider_subject="settings-user",
        email="settings@example.com",
        hashed_password=hash_password("OldPassword123"),
        role="user",
        company_name="Initial Name",
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


def test_account_settings_profile_password_and_mfa_flow():
    client, db, user = _build_client()

    profile_response = client.get("/api/v1/users/me/profile")
    assert profile_response.status_code == 200
    assert profile_response.json()["name"] == "Initial Name"
    assert profile_response.json()["mfa_enabled"] is False

    update_profile_response = client.patch(
        "/api/v1/users/me",
        json={
            "name": "Updated Name",
            "company_legal_name": "Updated Name LLC",
            "company_registration_number": "J22/999/2026",
            "company_vat_number": "RO99999999",
            "billing_email": "billing@example.com",
            "billing_phone": "+40 700 000 000",
            "billing_address_line1": "Main Street 10",
            "billing_city": "Iasi",
            "billing_state": "Iasi",
            "billing_postal_code": "700001",
            "billing_country": "RO",
            "billing_website_url": "https://example.com",
            "billing_tax_exempt": True,
        },
    )
    assert update_profile_response.status_code == 200
    assert update_profile_response.json()["name"] == "Updated Name"
    assert update_profile_response.json()["company_legal_name"] == "Updated Name LLC"
    assert update_profile_response.json()["billing_email"] == "billing@example.com"
    assert update_profile_response.json()["billing_country"] == "RO"
    assert update_profile_response.json()["billing_tax_exempt"] is True

    wrong_password_response = client.post(
        "/api/v1/users/me/password",
        json={"current_password": "wrong-password", "new_password": "NewPassword123"},
    )
    assert wrong_password_response.status_code == 400
    assert wrong_password_response.json()["detail"] == "Current password is incorrect."

    change_password_response = client.post(
        "/api/v1/users/me/password",
        json={"current_password": "OldPassword123", "new_password": "NewPassword123"},
    )
    assert change_password_response.status_code == 200
    assert change_password_response.json()["message"] == "Password updated successfully."

    db.refresh(user)
    assert verify_password("NewPassword123", user.hashed_password)

    mfa_setup_response = client.post("/api/v1/users/me/mfa/setup")
    assert mfa_setup_response.status_code == 200
    setup_payload = mfa_setup_response.json()
    assert setup_payload["issuer"]
    assert setup_payload["secret"]
    assert setup_payload["setup_token"]
    assert setup_payload["otpauth_uri"].startswith("otpauth://totp/")

    setup_totp = pyotp.TOTP(setup_payload["secret"])
    enable_mfa_response = client.post(
        "/api/v1/users/me/mfa/enable",
        json={
            "setup_token": setup_payload["setup_token"],
            "otp_code": setup_totp.now(),
        },
    )
    assert enable_mfa_response.status_code == 200
    assert enable_mfa_response.json()["enabled"] is True

    mfa_status_response = client.get("/api/v1/users/me/mfa/status")
    assert mfa_status_response.status_code == 200
    assert mfa_status_response.json()["enabled"] is True

    db.refresh(user)
    assert user.mfa_secret is not None
    # SIGV2-1258: the enrollment code above is spent, so disabling needs the
    # next timestep's code (still inside the +/- 1 acceptance window).
    disable_totp = pyotp.TOTP(user.mfa_secret)
    disable_mfa_response = client.post(
        "/api/v1/users/me/mfa/disable",
        json={"otp_code": disable_totp.at(int(time.time()) + 30)},
    )
    assert disable_mfa_response.status_code == 200
    assert disable_mfa_response.json()["enabled"] is False

    db.refresh(user)
    assert user.mfa_secret is None

    app.dependency_overrides.clear()
    db.close()
