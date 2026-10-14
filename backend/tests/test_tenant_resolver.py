from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import Request
from fastapi.responses import PlainTextResponse

from database import get_db
from middleware import tenant_resolver


def _make_request(*, host: str | None = None, forwarded_host: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if host is not None:
        headers.append((b"host", host.encode("utf-8")))
    if forwarded_host is not None:
        headers.append((b"x-forwarded-host", forwarded_host.encode("utf-8")))

    app = SimpleNamespace(dependency_overrides={})
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "scheme": "http",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": app,
    }
    return Request(scope)


def test_extract_request_host_prefers_forwarded_host_and_first_proxy_hop() -> None:
    request = _make_request(
        host="ignored.example.com",
        forwarded_host="agency.example.com, edge.proxy.local",
    )

    assert tenant_resolver._extract_request_host(request) == "agency.example.com"


def test_allowed_system_host_accepts_platform_hosts_and_dev_defaults(monkeypatch) -> None:
    monkeypatch.setattr(tenant_resolver.settings, "ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setattr(tenant_resolver.settings, "DOMAIN", "thothgraph.com")
    monkeypatch.setattr(tenant_resolver.settings, "APP_BASE_URL", "https://thothgraph.com")
    monkeypatch.setattr(tenant_resolver.settings, "FRONTEND_URL", "https://app.thothgraph.com")
    monkeypatch.setattr(
        tenant_resolver.settings, "BACKEND_PUBLIC_URL", "https://api.thothgraph.com"
    )
    monkeypatch.setattr(tenant_resolver.settings, "ENVIRONMENT", "development")

    assert tenant_resolver._is_allowed_system_host("api.example.com") is True
    assert tenant_resolver._is_allowed_system_host("www.thothgraph.com") is True
    assert tenant_resolver._is_allowed_system_host("testserver") is True
    assert tenant_resolver._is_allowed_system_host("evil.example.com") is False


def test_allowed_system_host_supports_wildcard_subdomains(monkeypatch) -> None:
    monkeypatch.setattr(tenant_resolver.settings, "ALLOWED_HOSTS", "*.trusted.example")
    monkeypatch.setattr(tenant_resolver.settings, "DOMAIN", "")
    monkeypatch.setattr(tenant_resolver.settings, "APP_BASE_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "FRONTEND_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "BACKEND_PUBLIC_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "ENVIRONMENT", "production")

    assert tenant_resolver._is_allowed_system_host("edge.trusted.example") is True
    assert tenant_resolver._is_allowed_system_host("nested.edge.trusted.example") is True
    assert tenant_resolver._is_allowed_system_host("trusted.example") is False


def test_tenant_resolver_rejects_unknown_host(monkeypatch) -> None:
    request = _make_request(host="unknown.example.com")

    def db_override():
        yield object()

    request.app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(tenant_resolver.settings, "ALLOWED_HOSTS", "")
    monkeypatch.setattr(tenant_resolver.settings, "DOMAIN", "")
    monkeypatch.setattr(tenant_resolver.settings, "APP_BASE_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "FRONTEND_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "BACKEND_PUBLIC_URL", "")
    monkeypatch.setattr(tenant_resolver.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        tenant_resolver,
        "resolve_workspace_by_host",
        lambda _db, *, host: (None, None),
    )

    async def call_next(_request: Request):
        raise AssertionError("call_next should not execute for an invalid host")

    response = asyncio.run(tenant_resolver.tenant_resolver_middleware(request, call_next))

    assert response.status_code == 400
    assert response.body == b'{"detail":"Invalid host header."}'


def test_tenant_resolver_allows_verified_custom_domains(monkeypatch) -> None:
    request = _make_request(host="client.agency.example")

    def db_override():
        yield object()

    request.app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(tenant_resolver.settings, "ALLOWED_HOSTS", "")
    monkeypatch.setattr(tenant_resolver.settings, "DOMAIN", "thothgraph.com")
    monkeypatch.setattr(tenant_resolver.settings, "APP_BASE_URL", "https://thothgraph.com")
    monkeypatch.setattr(tenant_resolver.settings, "FRONTEND_URL", "https://thothgraph.com")
    monkeypatch.setattr(
        tenant_resolver.settings, "BACKEND_PUBLIC_URL", "https://api.thothgraph.com"
    )
    monkeypatch.setattr(tenant_resolver.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        tenant_resolver,
        "resolve_workspace_by_host",
        lambda _db, *, host: (
            SimpleNamespace(id=42),
            SimpleNamespace(domain=host),
        ),
    )

    seen_state: dict[str, object | None] = {}

    async def call_next(passed_request: Request):
        seen_state["workspace_id"] = getattr(passed_request.state, "tenant_workspace_id", None)
        seen_state["tenant_domain"] = getattr(passed_request.state, "tenant_domain", None)
        return PlainTextResponse("ok")

    response = asyncio.run(tenant_resolver.tenant_resolver_middleware(request, call_next))

    assert response.status_code == 200
    assert response.body == b"ok"
    assert seen_state == {"workspace_id": 42, "tenant_domain": "client.agency.example"}
