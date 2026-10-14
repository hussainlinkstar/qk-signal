"""Shared Google OAuth refresh primitive (SIGV2-1025).

The single Google token-refresh implementation. Both the GA4 data-access path
(``app.services.geo.ga4_oauth_service``) and the workspace data-source catalog
path delegate here. Error messages are reason codes only: no token, refresh
token or client secret may appear in them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    import models

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthRefreshError(Exception):
    """Raised when refreshing a stored Google OAuth connection fails."""


def derive_expires_at(token_payload: dict) -> datetime | None:
    """Expiry instant from a Google token response.

    Handles both ``expires_at`` (epoch seconds) and ``expires_in`` (seconds
    from now), the two shapes Google and persisted payloads produce.
    """
    expires_at_value = token_payload.get("expires_at")
    if isinstance(expires_at_value, (int, float)):
        return datetime.fromtimestamp(float(expires_at_value), tz=timezone.utc)

    expires_in_value = token_payload.get("expires_in")
    if isinstance(expires_in_value, (int, float)):
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_value))

    return None


def refresh_google_oauth_connection(
    db: Session,
    connection: "models.OAuthConnection | models.ProjectOAuthConnection",
) -> "models.OAuthConnection | models.ProjectOAuthConnection":
    """Refresh the connection's access token and persist the full token set.

    Persists ``access_token``, ``refresh_token`` (when Google rotates it),
    ``token_type``, ``scope`` and ``expires_at``. Raises
    ``GoogleOAuthRefreshError`` with a reason code only.
    """
    import models as _models
    from core.config import settings

    provider = getattr(connection, "provider", None)
    provider_value = provider.value if isinstance(provider, _models.OAuthProvider) else provider
    if provider_value != _models.OAuthProvider.GOOGLE.value:
        raise GoogleOAuthRefreshError(f"provider_not_google:{provider_value}")

    refresh_token = str(connection.refresh_token or "").strip()
    if not refresh_token:
        raise GoogleOAuthRefreshError("refresh_token_missing")

    client_id = str(settings.GOOGLE_CLIENT_ID or "").strip()
    client_secret = str(settings.GOOGLE_CLIENT_SECRET or "").strip()
    if not client_id or not client_secret:
        raise GoogleOAuthRefreshError("google_oauth_client_not_configured")

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise GoogleOAuthRefreshError("refresh_request_failed") from exc

    if response.status_code >= 400:
        raise GoogleOAuthRefreshError(f"refresh_failed_http_{response.status_code}")

    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise GoogleOAuthRefreshError("refresh_access_token_missing")

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise GoogleOAuthRefreshError("refresh_access_token_missing")

    new_refresh = str(payload.get("refresh_token") or "").strip()
    connection.access_token = access_token
    if new_refresh:
        connection.refresh_token = new_refresh
    token_type = str(payload.get("token_type") or "").strip()
    if token_type:
        connection.token_type = token_type
    scope = str(payload.get("scope") or "").strip()
    if scope:
        connection.scope = scope
    expires_at = derive_expires_at(payload)
    if expires_at is not None:
        connection.expires_at = expires_at

    db.commit()
    return connection
