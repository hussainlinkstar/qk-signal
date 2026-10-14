"""SIGV2-1213: the advertised, enforced and documented API key scopes must agree.

Every set here is derived from the real source it describes, never restated:

* the allow-list is ``services.external_api_service.API_KEY_SCOPES``
* the advertised set comes from the live ``GET /external/sdk-metadata`` response
* the enforced set is read back off the mounted routes, from the marker
  ``require_api_key_scope`` leaves on each dependency it builds
* the documented set is parsed out of ``docs/api.md``

A scope that is published but gates nothing invites a false assumption about
least privilege, so the agreement is pinned rather than reviewed by eye.

SIGV2-1210 added a second surface that enforces these scopes: the MCP server,
where one endpoint dispatches several tools and the scope is chosen per tool
rather than per route. Its tools are covered here, in the same derive-both-sides
way, rather than in a parallel test that could agree with itself while
disagreeing with this file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from test_external_api import (  # noqa: E402  (test helper module, sets env on import)
    _build_client,
    _build_db,
    _cleanup_db,
    _fake_redis_ctx,
    _fake_sync_redis_ctx,
    _seed_api_key,
    _seed_user,
    FakeRedis,
)

import main  # noqa: E402
import models  # noqa: E402
from routers.internal_signal_router import SIGNAL_KEY_SCOPES  # noqa: E402
from services.external_api_service import (  # noqa: E402
    API_KEY_SCOPES,
    DEFAULT_API_KEY_SCOPES,
)
from services.mcp_server_service import TOOL_REGISTRY  # noqa: E402

API_KEY = "stx_live_0123456789abcdef0123456789abcd"
API_DOC = Path(__file__).resolve().parents[2] / "docs" / "api.md"
_DOC_ENDPOINT = re.compile(r"^- `([A-Z]+) (/api/v1/external/[^`]*)`\s*$")
_DOC_SCOPE = re.compile(r"^\s+- auth: API key with `([^`]+)`\s*$")
_DOC_MCP_TOOL = re.compile(r"^- `(signal_[a-z_]+)`\s*$")
_DOC_MCP_SCOPE = re.compile(r"^\s+- scope: `([^`]+)`\s*$")


def _dependant_scopes(dependant) -> set[str]:
    """Collect the scopes a route actually enforces, via the dependency tree."""
    found: set[str] = set()
    pending = [dependant]
    while pending:
        current = pending.pop()
        scope = getattr(current.call, "api_key_scope", None)
        if scope:
            found.add(str(scope))
        pending.extend(current.dependencies)
    return found


def _enforced_scopes_by_route() -> dict[tuple[str, str], set[str]]:
    enforced: dict[tuple[str, str], set[str]] = {}
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or "/external/" not in route.path:
            continue
        scopes = _dependant_scopes(route.dependant)
        for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
            enforced[(method, route.path)] = scopes
    return enforced


def _documented_scopes_by_route() -> dict[tuple[str, str], str]:
    documented: dict[tuple[str, str], str] = {}
    endpoint: tuple[str, str] | None = None
    for line in API_DOC.read_text(encoding="utf-8").splitlines():
        endpoint_match = _DOC_ENDPOINT.match(line)
        if endpoint_match:
            endpoint = (endpoint_match.group(1), endpoint_match.group(2))
            continue
        scope_match = _DOC_SCOPE.match(line)
        if scope_match and endpoint is not None:
            documented[endpoint] = scope_match.group(1)
            endpoint = None
    return documented


def _documented_mcp_tool_scopes() -> dict[str, str]:
    """The scope ``docs/api.md`` publishes for each MCP tool."""
    documented: dict[str, str] = {}
    tool: str | None = None
    for line in API_DOC.read_text(encoding="utf-8").splitlines():
        tool_match = _DOC_MCP_TOOL.match(line)
        if tool_match:
            tool = tool_match.group(1)
            continue
        scope_match = _DOC_MCP_SCOPE.match(line)
        if scope_match and tool is not None:
            documented[tool] = scope_match.group(1)
            tool = None
    return documented


def _advertised_mcp_tools(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The tool catalogue a real eligible key is served by ``tools/list``."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="mcp-catalogue-scopes@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )
        response = client.post(
            "/api/v1/mcp",
            headers={"X-API-Key": API_KEY},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 200, response.text
        return list(response.json()["result"]["tools"])
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def _advertised_scopes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="sdk-metadata-scopes@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )
        response = client.get("/api/v1/external/sdk-metadata", headers={"X-API-Key": API_KEY})
        assert response.status_code == 200, response.text
        return list(response.json()["available_scopes"])
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_advertised_scopes_match_the_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    advertised = _advertised_scopes(monkeypatch)
    assert advertised == list(API_KEY_SCOPES)
    assert len(advertised) == len(set(advertised))


def test_every_allowed_scope_is_enforced_by_at_least_one_route() -> None:
    enforced = set().union(*_enforced_scopes_by_route().values())
    assert enforced, "no external route reported an API key scope"
    assert sorted(enforced) == sorted(API_KEY_SCOPES)


def test_documented_scopes_match_the_enforced_scopes() -> None:
    enforced = _enforced_scopes_by_route()
    documented = _documented_scopes_by_route()
    assert documented, "docs/api.md documented no external endpoint scopes"
    for endpoint, scope in documented.items():
        assert (
            scope in API_KEY_SCOPES
        ), f"docs/api.md publishes unknown scope {scope} for {endpoint}"
        assert (
            endpoint in enforced
        ), f"docs/api.md documents a route that does not exist: {endpoint}"
        assert enforced[endpoint] == {scope}, (
            f"docs/api.md says {endpoint} needs {scope}, "
            f"the route enforces {sorted(enforced[endpoint])}"
        )


def test_task_endpoints_are_covered_by_projects_read() -> None:
    enforced = _enforced_scopes_by_route()
    assert enforced[("GET", "/api/v1/external/projects/{project_id}/tasks")] == {"projects:read"}
    assert enforced[("GET", "/api/v1/external/projects/{project_id}/tasks/{task_id}")] == {
        "projects:read"
    }
    assert "tasks:read" not in API_KEY_SCOPES


def test_signal_provisioning_scopes_stay_inside_the_allow_list() -> None:
    assert set(SIGNAL_KEY_SCOPES) <= set(API_KEY_SCOPES)


# ---------------------------------------------------------------------------
# The MCP surface (SIGV2-1210)
# ---------------------------------------------------------------------------


def test_mcp_tool_scopes_stay_inside_the_allow_list() -> None:
    assert TOOL_REGISTRY, "the MCP server advertises no tools"
    assert {tool.scope for tool in TOOL_REGISTRY} <= set(API_KEY_SCOPES)


def test_read_tools_stay_inside_the_default_grant() -> None:
    """A tool that only reads must be satisfiable by a default-scoped key."""
    for tool in TOOL_REGISTRY:
        if tool.consumes_scan:
            continue
        assert tool.scope in DEFAULT_API_KEY_SCOPES, (
            f"{tool.name} needs {tool.scope}, which is outside the default read-only grant, "
            "so a key created without an explicit scope list cannot call it"
        )
        annotations = tool.descriptor()["annotations"]
        assert annotations["readOnlyHint"] is True, tool.name
        assert annotations["destructiveHint"] is False, tool.name


def test_every_spending_tool_is_outside_the_default_grant() -> None:
    """A tool that costs the customer money can never be granted by omission.

    This is the invariant that replaced "no MCP tool can spend" when
    ``signal_run_audit`` landed. The point was never that the server must stay
    read-only; it is that spending must be chosen. A key created with no scope
    list gets read scopes only, so if a spending tool's scope ever appeared in
    that default set, every such key would silently be able to charge the
    customer. This also pins the honesty of what the tool tells a client: it
    must not describe itself as a read, and its cost must be in its
    description rather than discoverable only by calling it.
    """
    spending = [tool for tool in TOOL_REGISTRY if tool.consumes_scan]
    assert spending, "the audit-triggering tool is missing from the registry"
    for tool in spending:
        assert tool.scope.endswith(
            ":write"
        ), f"{tool.name} spends but holds {tool.scope}, a read scope"
        assert tool.scope not in DEFAULT_API_KEY_SCOPES, (
            f"{tool.name} spends and its scope {tool.scope} is in the default grant, so a "
            "key created without an explicit scope list could charge the customer"
        )
        assert "scan allowance" in tool.description, (
            f"{tool.name} does not state in its description that it consumes the scan " "allowance"
        )
        annotations = tool.descriptor()["annotations"]
        assert annotations["readOnlyHint"] is False, tool.name
        assert annotations["idempotentHint"] is False, tool.name


def test_documented_mcp_tools_match_the_served_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advertised = _advertised_mcp_tools(monkeypatch)
    documented = _documented_mcp_tool_scopes()
    assert documented, "docs/api.md documented no MCP tools"
    assert sorted(tool["name"] for tool in advertised) == sorted(documented)
    assert sorted(tool.name for tool in TOOL_REGISTRY) == sorted(documented)


def test_documented_mcp_tool_scopes_match_the_enforced_scopes() -> None:
    enforced = {tool.name: tool.scope for tool in TOOL_REGISTRY}
    for name, scope in _documented_mcp_tool_scopes().items():
        assert scope in API_KEY_SCOPES, f"docs/api.md publishes unknown scope {scope} for {name}"
        assert name in enforced, f"docs/api.md documents an MCP tool that does not exist: {name}"
        assert (
            enforced[name] == scope
        ), f"docs/api.md says {name} needs {scope}, the tool enforces {enforced[name]}"


@pytest.mark.parametrize("tool", TOOL_REGISTRY, ids=lambda tool: tool.name)
def test_each_mcp_tool_scope_is_enforced_at_dispatch(tool, monkeypatch: pytest.MonkeyPatch) -> None:
    """The enforcement side, derived by calling rather than by inspection.

    The key is issued every allowed scope except the one tool under test needs,
    so the refusal can only come from that tool's own check. No arguments are
    sent: authorization runs before argument validation, so a caller who may
    not use a tool is refused without being told what the tool takes.
    """
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email=f"mcp-scope-{tool.name}@example.com")
        _seed_api_key(
            db,
            user=user,
            scopes=[scope for scope in API_KEY_SCOPES if scope != tool.scope],
        )
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        response = client.post(
            "/api/v1/mcp",
            headers={"X-API-Key": API_KEY},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool.name},
            },
        )
        assert response.status_code == 200, response.text
        error = response.json()["error"]
        assert error["message"].endswith(f"{tool.scope}.")
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_default_scopes_grant_no_write_and_never_spend() -> None:
    assert set(DEFAULT_API_KEY_SCOPES) <= set(API_KEY_SCOPES)
    assert DEFAULT_API_KEY_SCOPES, "an empty default would lock every omitted-scope key out"
    assert [scope for scope in DEFAULT_API_KEY_SCOPES if not scope.endswith(":read")] == []
    assert "audit:write" not in DEFAULT_API_KEY_SCOPES


def test_created_key_without_scopes_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="default-scopes@example.com")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        response = client.post("/api/v1/settings/api-keys", json={"name": "Warehouse Export"})
        assert response.status_code == 201, response.text
        scopes = response.json()["item"]["scopes"]
        assert scopes == list(DEFAULT_API_KEY_SCOPES)
        assert "audit:write" not in scopes

        stored = db.query(models.ApiKey).filter(models.ApiKey.user_id == user.id).one()
        assert list(stored.scopes) == list(DEFAULT_API_KEY_SCOPES)
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


@pytest.mark.parametrize("scope", ["tasks:read", "credits:read", "audit:*", "admin"])
def test_created_key_rejects_scopes_outside_the_allow_list(
    scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="unknown-scope@example.com")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        response = client.post(
            "/api/v1/settings/api-keys",
            json={"name": "Warehouse Export", "scopes": ["audit:read", scope]},
        )
        assert response.status_code == 422, response.text
        assert db.query(models.ApiKey).filter(models.ApiKey.user_id == user.id).count() == 0
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_created_key_keeps_the_scopes_the_caller_chose(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="chosen-scopes@example.com")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        response = client.post(
            "/api/v1/settings/api-keys",
            json={"name": "Audit Runner", "scopes": ["Audit:Read", " audit:write "]},
        )
        assert response.status_code == 201, response.text
        assert response.json()["item"]["scopes"] == ["audit:read", "audit:write"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_stored_retired_scope_is_dropped_without_widening_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key issued before SIGV2-1213 may still carry `tasks:read` in storage."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="retired-scope@example.com")
        _seed_api_key(db, user=user, scopes=["projects:read", "tasks:read"])
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        listed = client.get("/api/v1/settings/api-keys")
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["scopes"] == ["projects:read"]

        projects = client.get("/api/v1/external/projects", headers={"X-API-Key": API_KEY})
        assert projects.status_code == 200, projects.text
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_key_left_with_no_recognised_scope_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dropping a retired scope must not fall back to the default grant."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="only-retired-scope@example.com")
        _seed_api_key(db, user=user, scopes=["tasks:read"])
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        projects = client.get("/api/v1/external/projects", headers={"X-API-Key": API_KEY})
        assert projects.status_code == 403, projects.text
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)
