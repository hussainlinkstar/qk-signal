"""Bing Webmaster Tools OAuth and metrics ingestion (SIGV2-1082).

A real Bing Webmaster connection, separate from the Microsoft Entra ``bing``
client used for SSO. Authorization-code flow against
``www.bing.com/webmasters/oauth`` plus token refresh, and ingestion of the
three stat endpoints (site, query, page) into ``project_bing_metrics``.

Unconfigured deployments stay inert: with no client id/secret, connecting and
refreshing fail with explicit reason codes, never silently.

Position correctness: Bing's reference types ``AvgClickPosition`` and
``AvgImpressionPosition`` as ``int`` and never documents the scale, so the
raw integer is persisted verbatim (``avg_click_position_raw`` /
``avg_impression_position_raw``) and every payload reports position as
unavailable rather than guessing a factor.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    import models

logger = logging.getLogger(__name__)

BING_AUTHORIZE_URL = "https://www.bing.com/webmasters/oauth/authorize"
BING_TOKEN_URL = "https://www.bing.com/webmasters/oauth/token"
BING_API_BASE = "https://ssl.bing.com/webmaster/api.svc/json"

# Bing exposes a fixed recent window, not an arbitrary range; the response is
# authoritative about which dates it actually covers.
BING_SCOPE = "webmaster.manage"

# Reason codes surfaced to API consumers.
REASON_NOT_CONFIGURED = "bing_webmaster_oauth_not_configured"
POSITION_UNAVAILABLE_REASON = "bing_position_scale_unverified"

TOKEN_EXPIRY_BUFFER = timedelta(seconds=60)

_DOTNET_DATE_RE = re.compile(r"^/Date\((-?\d+)([+-]\d{4})?\)/$")


class BingWebmasterConfigError(Exception):
    """The deployment has no Bing Webmaster OAuth client configured."""


class BingWebmasterTokenError(Exception):
    """Token exchange or refresh failed. Reason codes only; no secrets."""


class BingWebmasterConnectionError(Exception):
    """A data source has no usable OAuth connection or token."""


class BingWebmasterApiError(Exception):
    """A Webmaster API call failed."""


def bing_webmaster_oauth_configured() -> bool:
    from core.config import settings

    return bool(
        str(settings.BING_WEBMASTER_CLIENT_ID or "").strip()
        and str(settings.BING_WEBMASTER_CLIENT_SECRET or "").strip()
    )


def _client_credentials() -> tuple[str, str]:
    from core.config import settings

    client_id = str(settings.BING_WEBMASTER_CLIENT_ID or "").strip()
    client_secret = str(settings.BING_WEBMASTER_CLIENT_SECRET or "").strip()
    if not client_id or not client_secret:
        raise BingWebmasterConfigError(REASON_NOT_CONFIGURED)
    return client_id, client_secret


def _post_token_request(data: dict[str, str]) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                BING_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise BingWebmasterTokenError("token_request_failed") from exc
    if response.status_code >= 400:
        raise BingWebmasterTokenError(f"token_failed_http_{response.status_code}")
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise BingWebmasterTokenError("token_response_invalid")
    return payload


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code (5-minute lifetime) for tokens."""
    client_id, client_secret = _client_credentials()
    payload = _post_token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    )
    if not str(payload.get("access_token") or "").strip():
        raise BingWebmasterTokenError("token_access_token_missing")
    return payload


def derive_expires_at(token_payload: dict[str, Any]) -> datetime | None:
    """Expiry instant from a Bing token response (``expires_in`` or ``expires_at``)."""
    expires_at_value = token_payload.get("expires_at")
    if isinstance(expires_at_value, (int, float)):
        return datetime.fromtimestamp(float(expires_at_value), tz=timezone.utc)
    expires_in_value = token_payload.get("expires_in")
    if isinstance(expires_in_value, (int, float)):
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_value))
    return None


def refresh_bing_oauth_connection(
    db: Session,
    connection: "models.OAuthConnection | models.ProjectOAuthConnection",
) -> "models.OAuthConnection | models.ProjectOAuthConnection":
    """Refresh a stored Bing Webmaster token set and persist the result.

    Bing refresh tokens remain valid until the user revokes access. Raises
    ``BingWebmasterTokenError`` / ``BingWebmasterConfigError`` with reason
    codes only; token material never appears in error text.
    """
    import models as _models

    provider = getattr(connection, "provider", None)
    provider_value = provider.value if isinstance(provider, _models.OAuthProvider) else provider
    if provider_value != _models.OAuthProvider.BING.value:
        raise BingWebmasterTokenError(f"provider_not_bing:{provider_value}")

    refresh_token = str(connection.refresh_token or "").strip()
    if not refresh_token:
        raise BingWebmasterTokenError("refresh_token_missing")

    client_id, client_secret = _client_credentials()
    payload = _post_token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise BingWebmasterTokenError("refresh_access_token_missing")

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


def bing_connection_for_source(
    source: "models.ProjectDataSource",
) -> "models.OAuthConnection | models.ProjectOAuthConnection | None":
    """The OAuth connection a Bing data source binds to, project-level first."""
    connection = getattr(source, "project_oauth_connection", None)
    if connection is not None:
        return connection
    return getattr(source, "oauth_connection", None)


def bing_access_token(db: Session, source: "models.ProjectDataSource") -> str:
    """A valid Webmaster token for the source's OAuth connection.

    Returns the stored access token while valid; otherwise refreshes and
    persists the rotated set. Errors are reason codes only.
    """
    connection = bing_connection_for_source(source)
    if connection is None:
        raise BingWebmasterConnectionError("no_oauth_connection")

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
        raise BingWebmasterTokenError("refresh_token_missing")

    try:
        connection = refresh_bing_oauth_connection(db, connection)
    except BingWebmasterTokenError:
        raise
    new_token = str(connection.access_token or "").strip()
    if not new_token:
        raise BingWebmasterTokenError("refresh_access_token_missing")
    return new_token


def parse_bing_dotnet_date(value: object) -> date | None:
    """Parse ``/Date(<epoch_ms><±HHMM>)/`` to a UTC ``date``.

    The milliseconds are .NET epoch ticks in the serialized offset; the
    instant is epoch_ms in UTC terms and the trailing offset describes the
    serializer's zone. We take the calendar day in that declared offset so the
    day Bing meant is the day we store, then return it as a plain UTC date.
    """
    if not isinstance(value, str):
        return None
    match = _DOTNET_DATE_RE.match(value.strip())
    if not match:
        return None
    epoch_ms = int(match.group(1))
    offset_raw = match.group(2)
    if offset_raw:
        sign = 1 if offset_raw[0] == "+" else -1
        offset = timedelta(hours=int(offset_raw[1:3]), minutes=int(offset_raw[3:5])) * sign
    else:
        offset = timedelta(0)
    instant = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return (instant + offset).date()


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def normalize_stats_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """One Bing stats row to a storage-shaped dict, or None if undatable.

    Clicks and impressions pass through as floats. Position is never
    reinterpreted: the raw provider integers ride along under
    ``avg_click_position_raw`` / ``avg_impression_position_raw`` and no
    ``position`` field is produced.
    """
    row_date = parse_bing_dotnet_date(row.get("Date")) or (
        row.get("date") if isinstance(row.get("date"), date) else None
    )
    if row_date is None:
        return None
    return {
        "date": row_date,
        "clicks": float(row.get("Clicks") or 0.0),
        "impressions": float(row.get("Impressions") or 0.0),
        "avg_click_position_raw": _int_or_none(row.get("AvgClickPosition")),
        "avg_impression_position_raw": _int_or_none(row.get("AvgImpressionPosition")),
    }


def position_payload(row: dict[str, Any] | "models.ProjectBingMetric") -> dict[str, Any]:
    """Honest position representation: always unavailable, raw value retained.

    ``raw_provider_value`` is the provider-reported integer with an unverified
    scale, exposed so the raw figure stays inspectable without being rendered
    as a position.
    """

    def _first(*values):
        for value in values:
            if value is not None:
                return value
        return None

    raw = _first(
        getattr(row, "avg_click_position_raw", None)
        if not isinstance(row, dict)
        else row.get("avg_click_position_raw"),
        getattr(row, "avg_impression_position_raw", None)
        if not isinstance(row, dict)
        else row.get("avg_impression_position_raw"),
    )
    return {
        "status": "unavailable",
        "reason": POSITION_UNAVAILABLE_REASON,
        "raw_provider_value": raw,
    }


class BingWebmasterService:
    """Thin client over the Webmaster API. All calls are mockable via _get."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    f"{BING_API_BASE}/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
        except httpx.RequestError as exc:
            raise BingWebmasterApiError("api_request_failed") from exc
        if response.status_code == 429:
            raise BingWebmasterApiError("rate_limited")
        if response.status_code in (401, 403):
            raise BingWebmasterApiError(f"auth_failed_http_{response.status_code}")
        if response.status_code >= 400:
            raise BingWebmasterApiError(f"api_failed_http_{response.status_code}")
        return response.json() if response.content else {}

    @staticmethod
    def _result_list(payload: Any) -> list[dict[str, Any]]:
        candidates: Any = payload
        if isinstance(payload, dict):
            container = payload.get("d")
            candidates = container if isinstance(container, dict) else payload
        if isinstance(candidates, dict):
            for key in ("Results", "results", "Rows", "rows", "Sites", "sites"):
                value = candidates.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            for value in candidates.values():
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return list(value)
            return []
        if isinstance(candidates, list):
            return [item for item in candidates if isinstance(item, dict)]
        return []

    def get_user_sites(self) -> list[str]:
        """Site URLs the connected account can see. A site not listed is not
        owned by the caller and must be refused."""
        payload = self._get("GetUserSites", {})
        sites: list[str] = []
        for item in self._result_list(payload):
            url = str(
                item.get("Url")
                or item.get("url")
                or item.get("SiteUrl")
                or item.get("siteUrl")
                or ""
            ).strip()
            if url:
                sites.append(url)
        return sites

    def get_rank_and_traffic_stats(self, site_url: str) -> list[dict[str, Any]]:
        """Site-level daily clicks/impressions for Bing's fixed recent window."""
        payload = self._get("GetRankAndTrafficStats", {"siteUrl": site_url})
        return self._result_list(payload)

    def get_query_stats(self, site_url: str) -> list[dict[str, Any]]:
        """Query-level stats for the same fixed window."""
        payload = self._get("GetQueryStats", {"siteUrl": site_url})
        return self._result_list(payload)

    def get_page_stats(self, site_url: str) -> list[dict[str, Any]]:
        """Page-level stats for the same fixed window."""
        payload = self._get("GetPageStats", {"siteUrl": site_url})
        return self._result_list(payload)


def sync_bing_metrics(
    db: Session,
    project_id: int,
    site_url: str,
    rows: list[dict[str, Any]],
    *,
    dimension_type: str,
    dimension_getter=lambda row: "",
) -> int:
    """Upsert normalized Bing rows; returns rows written. Idempotent.

    ``dimension`` is "" for site-level rows, the query text for GetQueryStats
    rows, and the page URL for GetPageStats rows. Position stays as the raw
    provider integers only.
    """
    import models as _models

    written = 0
    for raw_row in rows:
        row = normalize_stats_row(raw_row)
        if row is None:
            continue
        dimension = str(dimension_getter(raw_row) or "").strip()
        existing = (
            db.query(_models.ProjectBingMetric)
            .filter(
                _models.ProjectBingMetric.project_id == project_id,
                _models.ProjectBingMetric.site_url == site_url,
                _models.ProjectBingMetric.dimension_type == dimension_type,
                _models.ProjectBingMetric.dimension == dimension,
                _models.ProjectBingMetric.date == row["date"],
            )
            .first()
        )
        fields = {
            "clicks": row["clicks"],
            "impressions": row["impressions"],
            "avg_click_position_raw": row["avg_click_position_raw"],
            "avg_impression_position_raw": row["avg_impression_position_raw"],
        }
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
        else:
            db.add(
                _models.ProjectBingMetric(
                    project_id=project_id,
                    site_url=site_url,
                    dimension_type=dimension_type,
                    dimension=dimension,
                    date=row["date"],
                    **fields,
                )
            )
        written += 1
    db.commit()
    return written


@dataclass(frozen=True)
class BingSyncResult:
    """Outcome of one ingestion pass over one Bing binding.

    ``status`` and ``availability`` use the same vocabulary the monitoring
    endpoint reports, so the endpoint can hand the result straight back and the
    scheduled worker can log the same outcomes.
    """

    status: str
    availability: str
    site_url: str | None = None
    rows_written: int = 0
    reason: str | None = None


def _mark_binding(
    db: Session,
    source: "models.ProjectDataSource",
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Record a retrieval outcome on the binding (same shape as the router)."""
    source.last_status = status
    source.last_error = (error or "")[:500] or None
    if status in ("success", "fresh"):
        source.last_sync_at = datetime.now(timezone.utc)
    db.commit()


def sync_project_bing_source(
    db: Session,
    source: "models.ProjectDataSource",
) -> BingSyncResult:
    """Fetch and store Bing metrics for one binding (SIGV2-1265).

    The single ingestion path: the monitoring endpoint and the scheduled
    monitoring worker both call this, so a bound Bing site ingests on the
    worker's cadence instead of only when somebody loads a page. A site the
    connected account does not own is refused before any stats call.
    """
    site_url = str(source.source_id or "").strip()
    if not site_url:
        _mark_binding(db, source, status="error", error="missing_site_url")
        return BingSyncResult(
            status="provider_error",
            availability="unavailable",
            reason="missing_site_url",
        )

    try:
        token = bing_access_token(db, source)
    except BingWebmasterConfigError as exc:
        # A deployment without Bing credentials is not a binding failure, so the
        # binding's own status is left as it was.
        return BingSyncResult(
            status="unavailable",
            availability="unavailable",
            site_url=site_url,
            reason=str(exc),
        )
    except (BingWebmasterConnectionError, BingWebmasterTokenError) as exc:
        _mark_binding(db, source, status="auth_error", error=str(exc)[:200])
        return BingSyncResult(
            status="revoked",
            availability="unavailable",
            site_url=site_url,
            reason=str(exc),
        )

    service = BingWebmasterService(access_token=token)
    try:
        owned_sites = service.get_user_sites()
    except BingWebmasterApiError as exc:
        _mark_binding(db, source, status="error", error=str(exc)[:200])
        return BingSyncResult(
            status="provider_error",
            availability="unavailable",
            site_url=site_url,
            reason=str(exc),
        )

    if site_url not in owned_sites:
        _mark_binding(db, source, status="auth_error", error="site_not_owned")
        return BingSyncResult(
            status="site_not_owned",
            availability="unavailable",
            site_url=site_url,
            reason="site_not_in_account",
        )

    try:
        site_rows = service.get_rank_and_traffic_stats(site_url)
        query_rows = service.get_query_stats(site_url)
        page_rows = service.get_page_stats(site_url)
    except BingWebmasterApiError as exc:
        _mark_binding(db, source, status="error", error=str(exc)[:200])
        return BingSyncResult(
            status="provider_error",
            availability="unavailable",
            site_url=site_url,
            reason=str(exc),
        )

    project_id = int(source.project_id)
    written = sync_bing_metrics(db, project_id, site_url, site_rows, dimension_type="site")
    written += sync_bing_metrics(
        db,
        project_id,
        site_url,
        query_rows,
        dimension_type="query",
        dimension_getter=lambda row: row.get("Query") or row.get("query") or "",
    )
    written += sync_bing_metrics(
        db,
        project_id,
        site_url,
        page_rows,
        dimension_type="page",
        dimension_getter=lambda row: row.get("Url") or row.get("url") or "",
    )

    has_stored = bool(
        stored_bing_rows(db, project_id, site_url, dimension_type="site")
        or stored_bing_rows(db, project_id, site_url, dimension_type="query")
        or stored_bing_rows(db, project_id, site_url, dimension_type="page")
    )
    _mark_binding(db, source, status="fresh" if has_stored else "connected_no_data")
    return BingSyncResult(
        status="ok",
        availability="ok",
        site_url=site_url,
        rows_written=written,
    )


def active_bing_bindings(db: Session) -> list["models.ProjectDataSource"]:
    """Every active Bing Webmaster binding, for the scheduled worker."""
    import models as _models

    return (
        db.query(_models.ProjectDataSource)
        .filter(
            _models.ProjectDataSource.source_type == _models.ProjectDataSourceType.BING_WEBMASTER,
            _models.ProjectDataSource.is_active.is_(True),
        )
        .all()
    )


def stored_bing_rows(
    db: Session,
    project_id: int,
    site_url: str,
    *,
    dimension_type: str,
) -> list["models.ProjectBingMetric"]:
    import models as _models

    return (
        db.query(_models.ProjectBingMetric)
        .filter(
            _models.ProjectBingMetric.project_id == project_id,
            _models.ProjectBingMetric.site_url == site_url,
            _models.ProjectBingMetric.dimension_type == dimension_type,
        )
        .order_by(_models.ProjectBingMetric.date.asc(), _models.ProjectBingMetric.dimension.asc())
        .all()
    )


def serialize_metric_row(row: "models.ProjectBingMetric") -> dict[str, Any]:
    return {
        "date": row.date.isoformat() if isinstance(row.date, date) else str(row.date),
        "dimension": row.dimension,
        "clicks": row.clicks,
        "impressions": row.impressions,
        "position": position_payload(row),
    }


def covered_period(
    rows: list[dict[str, Any] | "models.ProjectBingMetric"],
) -> dict[str, str | None]:
    """The period the rows actually cover; never the period that was asked for."""
    dates: list[date] = []
    for row in rows:
        value = row.get("date") if isinstance(row, dict) else getattr(row, "date", None)
        if isinstance(value, datetime):
            dates.append(value.date())
        elif isinstance(value, date):
            dates.append(value)
    if not dates:
        return {"start": None, "end": None}
    return {"start": min(dates).isoformat(), "end": max(dates).isoformat()}
