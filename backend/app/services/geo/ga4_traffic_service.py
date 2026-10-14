"""GA4 LLM Referral Traffic Detection Service.

Connects to the Google Analytics 4 Data API to pull session data from AI engine
referrers (ChatGPT, Gemini, Copilot, Claude, Perplexity, DeepSeek, Grok, Meta AI,
Mistral, You.com, Poe, Phind, Brave Search) and persists daily snapshots.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

# Known AI/LLM referral sources to track
LLM_REFERRAL_SOURCES = [
    # Tier 1, Major platforms
    "chatgpt.com",
    "gemini.google.com",
    "copilot.microsoft.com",
    "claude.ai",
    "perplexity.ai",
    # Tier 2, Growing platforms
    "deepseek.com",
    "chat.deepseek.com",
    "grok.com",
    "meta.ai",
    # Tier 3, Niche platforms
    "chat.mistral.ai",
    "you.com",
    "poe.com",
    "phind.com",
    "search.brave.com",
    # Mobile apps
    "android-app://com.openai.chatgpt",
    "android-app://com.google.android.apps.bard",
]

# Platform family grouping: maps individual sources to a family key
PLATFORM_FAMILIES: dict[str, str] = {
    "chatgpt.com": "openai",
    "android-app://com.openai.chatgpt": "openai",
    "gemini.google.com": "google",
    "android-app://com.google.android.apps.bard": "google",
    "copilot.microsoft.com": "microsoft",
    "claude.ai": "anthropic",
    "perplexity.ai": "perplexity",
    "deepseek.com": "deepseek",
    "chat.deepseek.com": "deepseek",
    "grok.com": "xai",
    "meta.ai": "meta",
    "chat.mistral.ai": "mistral",
    "you.com": "you",
    "poe.com": "poe",
    "phind.com": "phind",
    "search.brave.com": "brave",
}

PLATFORM_FAMILY_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "google": "Google",
    "microsoft": "Microsoft",
    "anthropic": "Anthropic",
    "perplexity": "Perplexity",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "meta": "Meta",
    "mistral": "Mistral",
    "you": "You.com",
    "poe": "Poe",
    "phind": "Phind",
    "brave": "Brave",
}

# GA4 Data API endpoint
GA4_DATA_API_BASE = "https://analyticsdata.googleapis.com/v1beta"

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


class GA4AuthError(Exception):
    """Raised when GA4 authentication fails."""


class GA4RateLimitError(Exception):
    """Raised when GA4 API rate limit is hit after all retries."""


class GA4TrafficService:
    """Fetches AI-referral traffic from GA4 and stores snapshots."""

    def __init__(
        self,
        service_account_json_path: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        self._service_account_json_path = service_account_json_path
        # A caller-supplied bearer (customer OAuth token) takes precedence over
        # service-account auth. It cannot self-refresh; the caller owns refresh.
        self._access_token: Optional[str] = access_token
        self._token_expiry: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _load_service_account_credentials(self) -> dict[str, Any]:
        """Load and validate service account JSON file."""
        if not self._service_account_json_path:
            raise GA4AuthError("GA4_SERVICE_ACCOUNT_JSON_PATH is not configured.")

        path = Path(self._service_account_json_path)
        if not path.exists():
            raise GA4AuthError(f"Service account file not found: {path}")

        with open(path, "r") as f:
            creds = json.load(f)

        required_fields = ["client_email", "private_key", "token_uri"]
        for field in required_fields:
            if field not in creds:
                raise GA4AuthError(f"Service account JSON missing required field: {field}")

        return creds

    def _get_access_token(self) -> str:
        """Get a valid OAuth2 access token using service account credentials.

        Uses a JWT-based token exchange (RFC 7523) to obtain short-lived access
        tokens from Google's OAuth2 token endpoint.
        """
        now = datetime.now(timezone.utc)
        if self._access_token:
            if self._token_expiry is None or self._token_expiry > now:
                return self._access_token

        if not self._service_account_json_path:
            raise GA4AuthError(
                "Caller-supplied GA4 access token was rejected; reconnect the "
                "data source to refresh it."
            )

        import jwt as pyjwt  # PyJWT already in requirements

        creds = self._load_service_account_credentials()

        iat = int(now.timestamp())
        exp = iat + 3600  # 1 hour validity

        payload = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
            "aud": creds["token_uri"],
            "iat": iat,
            "exp": exp,
        }

        assertion = pyjwt.encode(payload, creds["private_key"], algorithm="RS256")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                creds["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )

        if response.status_code != 200:
            raise GA4AuthError(
                f"Token exchange failed (HTTP {response.status_code}): {response.text}"
            )

        token_data = response.json()
        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self._token_expiry = now + timedelta(seconds=expires_in - 60)  # 1 min buffer

        return self._access_token

    # ------------------------------------------------------------------
    # GA4 Data API calls
    # ------------------------------------------------------------------

    def _build_report_request(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Build the GA4 Data API runReport request body."""
        return {
            "dateRanges": [
                {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                }
            ],
            "dimensions": [
                {"name": "sessionSource"},
                {"name": "date"},
            ],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "screenPageViews"},
                {"name": "averageSessionDuration"},
                {"name": "bounceRate"},
            ],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "sessionSource",
                    "inListFilter": {
                        "values": LLM_REFERRAL_SOURCES,
                    },
                }
            },
            "keepEmptyRows": False,
        }

    def _call_ga4_api(
        self,
        property_id: str,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the GA4 Data API with retry logic."""
        access_token = self._get_access_token()
        url = f"{GA4_DATA_API_BASE}/{property_id}:runReport"

        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        url,
                        json=request_body,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                    )

                if response.status_code == 200:
                    return response.json()

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "GA4 API returned %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue

                if response.status_code == 401:
                    # Token might have expired, force refresh and retry once
                    self._access_token = None
                    if attempt == 0:
                        access_token = self._get_access_token()
                        continue
                    raise GA4AuthError(
                        f"GA4 authentication failed after token refresh: {response.text}"
                    )

                if response.status_code == 429:
                    raise GA4RateLimitError(
                        f"GA4 API rate limit exceeded after {MAX_RETRIES} retries"
                    )

                response.raise_for_status()

            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "GA4 API request error: %s, retrying in %.1fs (attempt %d/%d)",
                        exc,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise

        raise GA4RateLimitError("GA4 API exhausted all retries")

    # ------------------------------------------------------------------
    # Parsing & persistence
    # ------------------------------------------------------------------

    def _parse_report_rows(
        self,
        report_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Parse GA4 runReport response into structured records."""
        rows = report_data.get("rows", [])
        dimension_headers = [h.get("name", "") for h in report_data.get("dimensionHeaders", [])]
        metric_headers = [h.get("name", "") for h in report_data.get("metricHeaders", [])]

        parsed: list[dict[str, Any]] = []
        for row in rows:
            dim_values = [v.get("value", "") for v in row.get("dimensionValues", [])]
            metric_values = [v.get("value", "0") for v in row.get("metricValues", [])]

            dim_map = dict(zip(dimension_headers, dim_values))
            metric_map = dict(zip(metric_headers, metric_values))

            source = dim_map.get("sessionSource", "")
            date_str = dim_map.get("date", "")

            if not source or not date_str:
                continue

            try:
                snapshot_date = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                logger.warning("Skipping GA4 row with invalid date: %s", date_str)
                continue

            parsed.append(
                {
                    "source": source,
                    "snapshot_date": snapshot_date,
                    "sessions": int(metric_map.get("sessions", 0)),
                    "users": int(metric_map.get("totalUsers", 0)),
                    "page_views": int(metric_map.get("screenPageViews", 0)),
                    "avg_session_duration_seconds": float(
                        metric_map.get("averageSessionDuration", 0)
                    ),
                    "bounce_rate": float(metric_map.get("bounceRate", 0)),
                }
            )

        return parsed

    def _upsert_snapshots(
        self,
        db: Session,
        project_id: int,
        parsed_rows: list[dict[str, Any]],
    ) -> int:
        """Upsert LLMTrafficSnapshot rows; returns count of rows written."""
        count = 0
        for row_data in parsed_rows:
            existing = (
                db.query(models.LLMTrafficSnapshot)
                .filter(
                    models.LLMTrafficSnapshot.project_id == project_id,
                    models.LLMTrafficSnapshot.source == row_data["source"],
                    models.LLMTrafficSnapshot.snapshot_date == row_data["snapshot_date"],
                )
                .first()
            )
            if existing:
                existing.sessions = row_data["sessions"]
                existing.users = row_data["users"]
                existing.page_views = row_data["page_views"]
                existing.avg_session_duration_seconds = row_data["avg_session_duration_seconds"]
                existing.bounce_rate = row_data["bounce_rate"]
            else:
                snapshot = models.LLMTrafficSnapshot(
                    project_id=project_id,
                    source=row_data["source"],
                    snapshot_date=row_data["snapshot_date"],
                    sessions=row_data["sessions"],
                    users=row_data["users"],
                    page_views=row_data["page_views"],
                    avg_session_duration_seconds=row_data["avg_session_duration_seconds"],
                    bounce_rate=row_data["bounce_rate"],
                )
                db.add(snapshot)
            count += 1

        return count

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sync_traffic(
        self,
        db: Session,
        project_id: int,
        property_id: str,
        lookback_days: int = 30,
    ) -> int:
        """Pull LLM referral traffic from GA4 for the last N days and persist.

        Returns:
            Number of snapshot rows upserted.
        """
        end = date.today()
        start = end - timedelta(days=lookback_days)

        logger.info(
            "Syncing GA4 LLM traffic for project=%d property=%s range=%s..%s",
            project_id,
            property_id,
            start,
            end,
        )

        request_body = self._build_report_request(start, end)
        report_data = self._call_ga4_api(property_id, request_body)
        parsed_rows = self._parse_report_rows(report_data)

        count = self._upsert_snapshots(db, project_id, parsed_rows)
        db.commit()

        # Update last_synced_at on the GA4 config
        ga4_config = (
            db.query(models.ProjectGA4Config)
            .filter(models.ProjectGA4Config.project_id == project_id)
            .first()
        )
        if ga4_config:
            ga4_config.last_synced_at = datetime.now(timezone.utc)
            db.commit()

        logger.info(
            "GA4 sync complete for project=%d: %d snapshot rows upserted",
            project_id,
            count,
        )
        return count
