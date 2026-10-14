"""Tests for the passkey has-credentials endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with patched dependencies."""
    with patch("routers.passkeys_router.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])

        from main import app

        yield TestClient(app), mock_db


class TestPasskeyHasCredentials:
    """Tests for GET /api/v1/auth/passkeys/has-credentials."""

    @patch("routers.passkeys_router.user_has_passkeys")
    def test_returns_true_when_user_has_passkeys(self, mock_has, client):
        test_client, _ = client
        mock_has.return_value = True

        resp = test_client.get(
            "/api/v1/auth/passkeys/has-credentials",
            params={"email": "user@example.com"},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {"has_passkeys": True}
        mock_has.assert_called_once()

    @patch("routers.passkeys_router.user_has_passkeys")
    def test_returns_false_when_user_has_no_passkeys(self, mock_has, client):
        test_client, _ = client
        mock_has.return_value = False

        resp = test_client.get(
            "/api/v1/auth/passkeys/has-credentials",
            params={"email": "new@example.com"},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {"has_passkeys": False}

    @patch("routers.passkeys_router.user_has_passkeys")
    def test_returns_false_for_unknown_email(self, mock_has, client):
        test_client, _ = client
        mock_has.return_value = False

        resp = test_client.get(
            "/api/v1/auth/passkeys/has-credentials",
            params={"email": "nonexistent@example.com"},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {"has_passkeys": False}

    def test_rejects_missing_email_param(self, client):
        test_client, _ = client

        resp = test_client.get("/api/v1/auth/passkeys/has-credentials")

        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
