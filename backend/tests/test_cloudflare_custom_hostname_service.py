from __future__ import annotations

import pytest

from services.cloudflare_custom_hostname_service import (
    CloudflareCustomHostnameSnapshot,
    delete_cloudflare_custom_hostname,
    ensure_cloudflare_custom_hostname,
    find_cloudflare_custom_hostname,
    is_cloudflare_custom_hostname_configured,
    map_cloudflare_hostname_to_local_status,
)


def test_cloudflare_config_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_API_TOKEN",
        "token",
    )
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_ZONE_ID",
        "zone",
    )
    assert is_cloudflare_custom_hostname_configured() is True


def test_map_cloudflare_statuses_to_local_states() -> None:
    active = CloudflareCustomHostnameSnapshot(
        hostname_id="abc",
        hostname="audit.agency.example",
        status="active",
        ssl_status="active",
        verification_errors=[],
    )
    pending = CloudflareCustomHostnameSnapshot(
        hostname_id="def",
        hostname="audit.agency.example",
        status="pending_validation",
        ssl_status="pending_validation",
        verification_errors=[],
    )
    errored = CloudflareCustomHostnameSnapshot(
        hostname_id="ghi",
        hostname="audit.agency.example",
        status="deleted",
        ssl_status="deleted",
        verification_errors=["Ownership validation failed."],
    )

    assert map_cloudflare_hostname_to_local_status(active) == ("active", None)
    assert map_cloudflare_hostname_to_local_status(pending) == ("pending_ssl", None)
    assert map_cloudflare_hostname_to_local_status(errored) == (
        "error",
        "Ownership validation failed.",
    )


def test_hostname_active_but_ssl_pending_returns_pending_ssl() -> None:
    """BUG-1 regression: hostname active + SSL pending must be pending_ssl, not active."""
    snapshot = CloudflareCustomHostnameSnapshot(
        hostname_id="x1",
        hostname="audit.agency.example",
        status="active",
        ssl_status="pending_validation",
        verification_errors=[],
    )
    local_status, error = map_cloudflare_hostname_to_local_status(snapshot)
    assert local_status == "pending_ssl"
    assert error is None

    snapshot_redeploying = CloudflareCustomHostnameSnapshot(
        hostname_id="x2",
        hostname="audit.agency.example",
        status="active_redeploying",
        ssl_status="pending_issuance",
        verification_errors=[],
    )
    local_status2, error2 = map_cloudflare_hostname_to_local_status(snapshot_redeploying)
    assert local_status2 == "pending_ssl"
    assert error2 is None

    # Hostname pending + SSL active → still pending
    snapshot_pending_host = CloudflareCustomHostnameSnapshot(
        hostname_id="x3",
        hostname="audit.agency.example",
        status="pending",
        ssl_status="active",
        verification_errors=[],
    )
    local_status3, error3 = map_cloudflare_hostname_to_local_status(snapshot_pending_host)
    assert local_status3 == "pending_ssl"
    assert error3 is None


def test_find_create_patch_and_delete_custom_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_API_TOKEN",
        "token",
    )
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_ZONE_ID",
        "zone",
    )

    calls: list[tuple[str, str, dict | None, dict | None]] = []
    existing: dict[str, object] = {
        "id": "hostname-1",
        "hostname": "audit.agency.example",
        "status": "pending_validation",
        "ssl": {"status": "pending_validation"},
        "verification_errors": [],
    }

    def _fake_request_json(*, method: str, path: str, params=None, json_body=None, db=None):
        calls.append((method, path, params, json_body))
        if method == "GET":
            if params and params.get("hostname") == "audit.agency.example" and existing:
                return {"success": True, "result": [existing]}
            return {"success": True, "result": []}
        if method == "POST":
            created = {
                "id": "hostname-2",
                "hostname": json_body["hostname"],
                "status": "pending_validation",
                "ssl": {"status": "pending_validation"},
                "verification_errors": [],
            }
            return {"success": True, "result": created}
        if method == "PATCH":
            patched = {
                "id": "hostname-1",
                "hostname": "audit.agency.example",
                "status": "active",
                "ssl": {"status": "active"},
                "verification_errors": [],
            }
            return {"success": True, "result": patched}
        if method == "DELETE":
            return {"success": True, "result": {"id": "hostname-1"}}
        raise AssertionError(f"Unexpected call {method} {path}")

    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service._request_json",
        _fake_request_json,
    )

    found = find_cloudflare_custom_hostname("audit.agency.example")
    assert found is not None
    assert found.hostname_id == "hostname-1"

    patched = ensure_cloudflare_custom_hostname(
        hostname="audit.agency.example",
        workspace_id=7,
    )
    assert patched.hostname_id == "hostname-1"
    assert patched.status == "active"

    existing.clear()
    created = ensure_cloudflare_custom_hostname(
        hostname="audit.agency.example",
        workspace_id=7,
    )
    assert created.hostname_id == "hostname-2"

    existing.update(
        {
            "id": "hostname-1",
            "hostname": "audit.agency.example",
            "status": "active",
            "ssl": {"status": "active"},
            "verification_errors": [],
        }
    )
    delete_cloudflare_custom_hostname("audit.agency.example")

    methods = [method for method, _path, _params, _json in calls]
    assert methods.count("GET") >= 3
    assert "PATCH" in methods
    assert "POST" in methods
    assert "DELETE" in methods


def test_patch_includes_custom_metadata_and_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUG-2 regression: PATCH must include custom_metadata for workspace ownership."""
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_API_TOKEN",
        "token",
    )
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_ZONE_ID",
        "zone",
    )
    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service.settings.CLOUDFLARE_CUSTOM_ORIGIN_SERVER",
        "origin.example.com",
    )

    captured_patch_body: dict | None = None

    def _fake_request_json(*, method: str, path: str, params=None, json_body=None, db=None):
        nonlocal captured_patch_body
        if method == "GET":
            return {
                "success": True,
                "result": [
                    {
                        "id": "hostname-99",
                        "hostname": "audit.agency.example",
                        "status": "active",
                        "ssl": {"status": "active"},
                        "verification_errors": [],
                    }
                ],
            }
        if method == "PATCH":
            captured_patch_body = json_body
            return {
                "success": True,
                "result": {
                    "id": "hostname-99",
                    "hostname": "audit.agency.example",
                    "status": "active",
                    "ssl": {"status": "active"},
                    "verification_errors": [],
                },
            }
        raise AssertionError(f"Unexpected {method}")

    monkeypatch.setattr(
        "services.cloudflare_custom_hostname_service._request_json",
        _fake_request_json,
    )

    ensure_cloudflare_custom_hostname(
        hostname="audit.agency.example",
        workspace_id=42,
    )

    assert captured_patch_body is not None
    assert captured_patch_body["custom_metadata"] == {"workspace_id": "42"}
    assert captured_patch_body["custom_origin_server"] == "origin.example.com"
    assert "ssl" in captured_patch_body
