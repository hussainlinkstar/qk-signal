"""GET /api/v1/maintenance-notice, the banner-facing maintenance endpoint.

The in-app MaintenanceBanner is mounted for every logged-in user, so it cannot
call the admin-only maintenance endpoint: that returns 403 for ordinary users
and the browser logs a failed request on every page load. This endpoint serves
the same warning to any authenticated user while exposing nothing else from the
operational settings row.
"""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
import system_checks
from auth.security import get_current_user
from operational_settings import build_maintenance_notice

app = FastAPI()
app.include_router(system_checks.router, prefix="/api/v1")

SCHEDULED_START = datetime(2026, 9, 20, 22, 0, tzinfo=timezone.utc)
SCHEDULED_END = datetime(2026, 9, 20, 23, 30, tzinfo=timezone.utc)
BYPASS_EMAIL = "admin-bypass@example.com"


def _operational_settings() -> models.OperationalSetting:
    return models.OperationalSetting(
        maintenance_mode=True,
        maintenance_message="Signal will be briefly unavailable.",
        maintenance_allowed_ips=[BYPASS_EMAIL],
        maintenance_scheduled_start=SCHEDULED_START,
        maintenance_scheduled_end=SCHEDULED_END,
        admin_settings_payload={"feature_switches": {"audits_enabled": False}},
    )


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self, result):
        self._result = result

    def query(self, _model):
        return _FakeQuery(self._result)


def _override_db(result):
    def _get_db():
        yield _FakeDb(result)

    return _get_db


def _ordinary_user() -> models.User:
    return models.User(
        email="member@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )


client = TestClient(app)


def _reset_overrides() -> None:
    app.dependency_overrides = {}


def test_ordinary_user_gets_only_the_two_banner_fields() -> None:
    settings_row = _operational_settings()
    app.dependency_overrides[system_checks.get_db] = _override_db(settings_row)
    app.dependency_overrides[get_current_user] = _ordinary_user

    try:
        response = client.get("/api/v1/maintenance-notice")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "maintenance": {
            "scheduled_start": SCHEDULED_START.isoformat(),
            "message": "Signal will be briefly unavailable.",
        }
    }
    assert set(payload) == {"maintenance"}
    assert set(payload["maintenance"]) == {"scheduled_start", "message"}


def test_no_admin_only_maintenance_state_leaks_into_the_payload() -> None:
    settings_row = _operational_settings()
    app.dependency_overrides[system_checks.get_db] = _override_db(settings_row)
    app.dependency_overrides[get_current_user] = _ordinary_user

    try:
        response = client.get("/api/v1/maintenance-notice")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    notice = response.json()["maintenance"]
    for admin_only_field in ("enabled", "allowed_emails", "scheduled_end", "feature_switches"):
        assert admin_only_field not in notice

    raw_body = response.text
    assert BYPASS_EMAIL not in raw_body
    assert "feature_switches" not in raw_body
    assert "audits_enabled" not in raw_body
    assert SCHEDULED_END.isoformat() not in raw_body


def test_payload_matches_the_shared_maintenance_source_of_truth() -> None:
    """The admin view and this endpoint build their scheduled-maintenance
    fields from the same helper, so they can never drift apart."""
    settings_row = _operational_settings()
    app.dependency_overrides[system_checks.get_db] = _override_db(settings_row)
    app.dependency_overrides[get_current_user] = _ordinary_user

    try:
        response = client.get("/api/v1/maintenance-notice")
    finally:
        _reset_overrides()

    assert response.json()["maintenance"] == build_maintenance_notice(settings_row)


def test_notice_is_empty_when_no_maintenance_is_scheduled() -> None:
    settings_row = models.OperationalSetting(
        maintenance_mode=False,
        maintenance_message=None,
        maintenance_scheduled_start=None,
    )
    app.dependency_overrides[system_checks.get_db] = _override_db(settings_row)
    app.dependency_overrides[get_current_user] = _ordinary_user

    try:
        response = client.get("/api/v1/maintenance-notice")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    assert response.json() == {"maintenance": {"scheduled_start": None, "message": ""}}


def test_unauthenticated_request_is_rejected() -> None:
    settings_row = _operational_settings()
    app.dependency_overrides[system_checks.get_db] = _override_db(settings_row)

    try:
        response = client.get("/api/v1/maintenance-notice")
    finally:
        _reset_overrides()

    assert response.status_code == 401
