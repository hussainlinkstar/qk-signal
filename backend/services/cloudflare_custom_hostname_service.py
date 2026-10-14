from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from core.config import settings

DEFAULT_API_BASE_URL = "https://api.cloudflare.com/client/v4"
LOCAL_STATUS_ACTIVE = "active"
LOCAL_STATUS_PENDING = "pending_ssl"
LOCAL_STATUS_ERROR = "error"
ACTIVE_HOSTNAME_STATUSES = {"active", "active_redeploying"}
PENDING_HOSTNAME_STATUSES = {
    "pending",
    "initializing",
    "pending_validation",
    "pending_issuance",
    "pending_deployment",
}


def normalize_host(value: str | None) -> str:
    host = str(value or "").strip().lower()
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    return host


@dataclass(slots=True)
class CloudflareCustomHostnameSnapshot:
    hostname_id: str | None
    hostname: str
    status: str | None
    ssl_status: str | None
    verification_errors: list[str]


def _cf_setting(env_key: str, db=None, default: str = "") -> str:
    """Resolve a Cloudflare setting: DB cloudflare_config section → env/Settings default."""
    if db is not None:
        try:
            from services.configuration_service import configuration_service

            value = configuration_service.resolve_value(env_key, db=db, default=default)
            if value is not None and str(value).strip():
                return str(value).strip()
        except Exception:
            pass
    return str(getattr(settings, env_key, default) or default).strip()


def is_cloudflare_custom_hostname_configured(db=None) -> bool:
    return bool(_cf_setting("CLOUDFLARE_API_TOKEN", db) and _cf_setting("CLOUDFLARE_ZONE_ID", db))


def _api_base_url() -> str:
    return str(
        getattr(settings, "CLOUDFLARE_API_BASE_URL", DEFAULT_API_BASE_URL) or DEFAULT_API_BASE_URL
    ).rstrip("/")


def _request_headers(db=None) -> dict[str, str]:
    token = _cf_setting("CLOUDFLARE_API_TOKEN", db)
    if not token:
        raise HTTPException(
            status_code=503, detail="Cloudflare custom hostname integration is not configured."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request_json(
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    db=None,
) -> dict[str, Any]:
    zone_id = _cf_setting("CLOUDFLARE_ZONE_ID", db)
    if not zone_id:
        raise HTTPException(status_code=503, detail="Cloudflare zone ID is not configured.")

    url = f"{_api_base_url()}/zones/{zone_id}{path}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(
                method,
                url,
                headers=_request_headers(db),
                params=params,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Cloudflare API request failed: {exc}"
        ) from exc

    payload = response.json() if response.content else {}
    if response.status_code >= 400 or not payload.get("success", False):
        errors = payload.get("errors") or []
        message = "Cloudflare custom hostname request failed."
        if errors:
            message = (
                "; ".join(
                    str(item.get("message") or item.get("code") or "Unknown Cloudflare error")
                    for item in errors
                    if isinstance(item, dict)
                )
                or message
            )
        raise HTTPException(status_code=502, detail=message)
    return payload


def _snapshot_from_result(
    result: dict[str, Any], *, fallback_hostname: str
) -> CloudflareCustomHostnameSnapshot:
    hostname = normalize_host(result.get("hostname")) or fallback_hostname
    ssl = result.get("ssl") if isinstance(result.get("ssl"), dict) else {}
    verification_errors = [
        str(item).strip() for item in (result.get("verification_errors") or []) if str(item).strip()
    ]
    return CloudflareCustomHostnameSnapshot(
        hostname_id=str(result.get("id") or "") or None,
        hostname=hostname,
        status=str(result.get("status") or "").strip().lower() or None,
        ssl_status=str(ssl.get("status") or "").strip().lower() or None,
        verification_errors=verification_errors,
    )


def _hostname_payload(*, hostname: str, workspace_id: int, db=None) -> dict[str, Any]:
    validation_method = (
        str(getattr(settings, "CLOUDFLARE_CUSTOM_HOSTNAME_VALIDATION_METHOD", "http") or "http")
        .strip()
        .lower()
    )
    payload: dict[str, Any] = {
        "hostname": hostname,
        "ssl": {
            "method": validation_method,
            "type": "dv",
        },
        "custom_metadata": {
            "workspace_id": str(workspace_id),
        },
    }
    custom_origin_server = normalize_host(_cf_setting("CLOUDFLARE_CUSTOM_ORIGIN_SERVER", db))
    if custom_origin_server:
        payload["custom_origin_server"] = custom_origin_server
    return payload


def find_cloudflare_custom_hostname(
    hostname: str, db=None
) -> CloudflareCustomHostnameSnapshot | None:
    normalized = normalize_host(hostname)
    if not normalized or not is_cloudflare_custom_hostname_configured(db):
        return None
    payload = _request_json(
        method="GET",
        path="/custom_hostnames",
        params={"hostname": normalized, "per_page": 20},
        db=db,
    )
    results = payload.get("result") or []
    if not isinstance(results, list):
        return None
    for item in results:
        if not isinstance(item, dict):
            continue
        if normalize_host(item.get("hostname")) == normalized:
            return _snapshot_from_result(item, fallback_hostname=normalized)
    return None


def ensure_cloudflare_custom_hostname(
    *,
    hostname: str,
    workspace_id: int,
    db=None,
) -> CloudflareCustomHostnameSnapshot:
    normalized = normalize_host(hostname)
    if not normalized:
        raise HTTPException(status_code=400, detail="Custom hostname is invalid.")
    if not is_cloudflare_custom_hostname_configured(db):
        raise HTTPException(
            status_code=503, detail="Cloudflare custom hostname integration is not configured."
        )

    existing = find_cloudflare_custom_hostname(normalized, db=db)
    payload = _hostname_payload(hostname=normalized, workspace_id=workspace_id, db=db)
    if existing and existing.hostname_id:
        patch_body: dict[str, Any] = {
            "ssl": payload["ssl"],
            "custom_metadata": payload["custom_metadata"],
        }
        if "custom_origin_server" in payload:
            patch_body["custom_origin_server"] = payload["custom_origin_server"]
        refreshed = _request_json(
            method="PATCH",
            path=f"/custom_hostnames/{existing.hostname_id}",
            json_body=patch_body,
            db=db,
        )
        return _snapshot_from_result(refreshed.get("result") or {}, fallback_hostname=normalized)

    created = _request_json(
        method="POST",
        path="/custom_hostnames",
        json_body=payload,
        db=db,
    )
    return _snapshot_from_result(created.get("result") or {}, fallback_hostname=normalized)


def delete_cloudflare_custom_hostname(hostname: str, db=None) -> None:
    existing = find_cloudflare_custom_hostname(hostname, db=db)
    if existing is None or not existing.hostname_id:
        return
    _request_json(
        method="DELETE",
        path=f"/custom_hostnames/{existing.hostname_id}",
        db=db,
    )


def map_cloudflare_hostname_to_local_status(
    snapshot: CloudflareCustomHostnameSnapshot,
) -> tuple[str, str | None]:
    hostname_status = (snapshot.status or "").strip().lower()
    ssl_status = (snapshot.ssl_status or "").strip().lower()
    ok_statuses = ACTIVE_HOSTNAME_STATUSES | PENDING_HOSTNAME_STATUSES

    # Both hostname and SSL must be active for the domain to serve traffic.
    if hostname_status in ACTIVE_HOSTNAME_STATUSES and ssl_status in ACTIVE_HOSTNAME_STATUSES:
        return LOCAL_STATUS_ACTIVE, None

    # Either side still progressing → pending.
    if hostname_status in ok_statuses and ssl_status in ok_statuses:
        return LOCAL_STATUS_PENDING, None

    if snapshot.verification_errors:
        return LOCAL_STATUS_ERROR, "; ".join(snapshot.verification_errors)
    effective = hostname_status or ssl_status
    if effective:
        return (
            LOCAL_STATUS_ERROR,
            f"Cloudflare hostname status: {hostname_status}, ssl: {ssl_status}.",
        )
    return LOCAL_STATUS_ERROR, "Cloudflare did not return a hostname activation status."
