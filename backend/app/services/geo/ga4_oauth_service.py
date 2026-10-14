"""GA4 OAuth connection resolution and token management.

Public, importable service holding the single token-handling path for the
customer-OAuth GA4 integration (SIGV2-1001, absorbing the SIGNAL-1061 work that
previously lived as private functions in ``monitoring_worker.py``).

The customer's own OAuth token authorizes every GA4 read for a bound
``ProjectDataSource``; expired tokens are refreshed through the shared Google
primitive in ``app.services.google_oauth_service`` and the rotated token set is
persisted on the connection row.

No token, refresh token or client secret may appear in raised errors, return
values other than the access token itself, or log output.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    import models

logger = logging.getLogger(__name__)

# Tokens inside this buffer are treated as expired so a token is never handed
# to GA4 moments before it stops being valid.
TOKEN_EXPIRY_BUFFER = timedelta(seconds=60)


class GA4ConnectionError(Exception):
    """Raised when a data source has no usable OAuth connection."""


class GA4TokenRefreshError(Exception):
    """Raised when refreshing a stored OAuth token fails."""


def ga4_connection_for_source(
    source: "models.ProjectDataSource",
) -> "models.OAuthConnection | models.ProjectOAuthConnection | None":
    """The OAuth connection a data source binds to, project-level first.

    Project-level connections take precedence over the workspace-level
    connection, matching the binding contract in
    ``docs/ga4-reporting-contract.md`` section 1.
    """
    connection = getattr(source, "project_oauth_connection", None)
    if connection is not None:
        return connection
    return getattr(source, "oauth_connection", None)


def ga4_access_token(
    db: Session,
    source: "models.ProjectDataSource",
) -> str:
    """A valid analytics.readonly token for the source's OAuth connection.

    Returns the stored access token while it is valid; otherwise refreshes
    against Google's token endpoint, persists the rotated token (and rotated
    refresh token, when Google returns one) and returns the fresh token.

    Raises:
        GA4ConnectionError: the data source has no bound OAuth connection.
        GA4TokenRefreshError: no refresh token, missing client config, or the
            refresh call failed. Error messages are reason codes only; token
            material never appears in them.
    """
    connection = ga4_connection_for_source(source)
    if connection is None:
        raise GA4ConnectionError("no_oauth_connection")

    access_token = str(connection.access_token or "").strip()
    expires_at = getattr(connection, "expires_at", None)
    if access_token:
        if expires_at is None:
            return access_token
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc) + TOKEN_EXPIRY_BUFFER:
            return access_token

    if not str(connection.refresh_token or "").strip():
        raise GA4TokenRefreshError("refresh_token_missing")

    from app.services.google_oauth_service import (
        GoogleOAuthRefreshError,
        refresh_google_oauth_connection,
    )

    try:
        connection = refresh_google_oauth_connection(db, connection)
    except GoogleOAuthRefreshError as exc:
        raise GA4TokenRefreshError(str(exc)) from exc

    new_token = str(connection.access_token or "").strip()
    if not new_token:
        raise GA4TokenRefreshError("refresh_access_token_missing")
    return new_token
