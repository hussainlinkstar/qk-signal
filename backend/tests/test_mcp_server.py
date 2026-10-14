"""SIGV2-1210: the Qiko Signal MCP server.

What these tests hold in place, in the order the risks matter:

1. **The plan gate is server-side.** Specialist and Executive only. The case
   that matters is the agency trial: it holds ``api_access``, so it clears the
   external API's own plan check and would reach the dispatcher if the MCP gate
   did not exist. Every assertion about it names the MCP refusal specifically,
   so the test cannot pass on some other plan's pre-existing refusal.
2. **Scope enforcement is per tool.** A key that lacks a tool's scope is
   refused at the dispatch, not shown an empty catalogue.
3. **Tenancy is resolved, not asserted.** A project, audit or job belonging to
   someone else is refused rather than substituted, and a foreign job reads as
   absent so the endpoint is not an existence oracle.
4. **Minimum disclosure.** A recommendation result carries the headline and
   not the recommendation body or the assignee.
5. **Exactly one tool spends, and it is hard to spend twice.**
   ``signal_run_audit`` holds the only write scope, says in its description
   that it consumes the scan allowance, and is advertised as not read-only so
   a client asks before calling it. The expensive failure modes are pinned
   directly: a retry must not start a second paid audit, an exhausted
   allowance must be refused in words a client stops on, and a foreign
   project id must buy nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from test_external_api import (  # noqa: E402  (test helper module, sets env on import)
    _build_client,
    _build_db,
    _cleanup_db,
    _fake_redis_ctx,
    _fake_sync_redis_ctx,
    _seed_api_key,
    _seed_user,
    _seed_workspace_and_project,
    FakeRedis,
)

import main  # noqa: E402
import models  # noqa: E402
from app.config.plans import CAPABILITY_MATRIX  # noqa: E402
from routers.external_api_router import _mcp_metadata  # noqa: E402
from services.mcp_server_service import (  # noqa: E402
    LATEST_PROTOCOL_VERSION,
    MCP_ERROR_FORBIDDEN,
    MCP_ERROR_NOT_FOUND,
    TOOL_REGISTRY,
    mcp_availability_sentence,
)

API_KEY = "stx_live_0123456789abcdef0123456789abcd"
MCP_URL = "/api/v1/mcp"
AUTH_HEADERS = {"X-API-Key": API_KEY, "Accept": "application/json, text/event-stream"}


def _patch_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Give both surfaces the same fake Redis and hand it back to the test.

    The MCP router is patched as well as the REST router because each resolves
    its own Redis factory and passes it into the shared audit launch path, so
    patching only one would let an audit started through MCP reach a real
    client. Returning the instance is what lets a test assert on the queue the
    launch actually wrote to.
    """
    fake = FakeRedis()
    monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
    monkeypatch.setattr("routers.external_api_router.get_async_redis", _fake_redis_ctx(fake))
    monkeypatch.setattr("routers.mcp_router.get_async_redis", _fake_redis_ctx(fake))
    return fake


def _rpc(client, method: str, params: dict | None = None, *, request_id: int | str = 1):
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(MCP_URL, headers=AUTH_HEADERS, json=body)


def _result(response) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def _error(response) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" in body, body
    return body["error"]


def _seed_audit(db: Session, *, user: models.User, project: models.Project) -> models.Audit:
    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        geo_score=70.0,
        seo_score=80.0,
        aeo_score=60.0,
        full_report={"scores": {"overall": 72.5}},
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _seed_task(db: Session, *, project: models.Project, user: models.User) -> models.ProjectTask:
    task = models.ProjectTask(
        project_id=project.id,
        title="Add FAQ schema to the pricing page",
        description="The full recommendation body, which must not be disclosed by the tool.",
        category="AEO",
        assigned_to_user_id=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _seed_job(
    db: Session,
    *,
    user: models.User,
    project: models.Project | None = None,
    job_id: str = "job-1210",
    source: str = "external",
) -> models.AuditJob:
    job = models.AuditJob(
        id=job_id,
        user_id=user.id,
        project_id=project.id if project is not None else None,
        status="queued",
        source=source,
        url="https://example.com",
        tier="fast",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# 1. The plan gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,params",
    [
        ("initialize", {"protocolVersion": LATEST_PROTOCOL_VERSION}),
        ("tools/list", {}),
        ("tools/call", {"name": "signal_list_projects", "arguments": {}}),
    ],
)
def test_agency_trial_is_refused_every_method(
    method: str, params: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate, proved on the plan that clears every other check.

    ``plan_agency_trial`` grants ``api_access`` and is ``trialing``, so
    ``resolve_external_plan`` admits it. The refusal asserted here is the MCP
    plan gate's own message, so this cannot pass on a different refusal.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(
            db,
            email="mcp-trial@example.com",
            plan_type="plan_agency_trial",
            subscription_status="trialing",
        )
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = _rpc(client, method, params)
        assert response.status_code == 403, response.text
        detail = response.json()["error"]
        assert detail["code"] == "PLAN_NOT_ELIGIBLE"
        assert detail["message"] == mcp_availability_sentence()
        assert "Specialist and Executive" in detail["message"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_a_plan_without_api_access_never_reaches_the_mcp_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer layer, named for what it actually proves.

    ``plan_standard`` has no ``api_access`` at all, so it is turned away by
    the external API's own plan check before the MCP gate is consulted. The
    assertion therefore names *that* refusal: an earlier version of this test
    asserted only ``PLAN_NOT_ELIGIBLE`` and still passed with the MCP gate
    deliberately removed, which made it look like gate coverage while proving
    nothing about the gate. The MCP gate itself is proved on the agency trial
    above, which is the only plan that clears this check and still must be
    refused.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(
            db,
            email="mcp-standard@example.com",
            plan_type="plan_standard",
            subscription_status="active",
        )
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = _rpc(client, "tools/call", {"name": "signal_list_projects", "arguments": {}})
        assert response.status_code == 403, response.text
        detail = response.json()["error"]
        assert detail["code"] == "PLAN_NOT_ELIGIBLE"
        # The API-access refusal, which is a different sentence from the MCP
        # gate's. Pinning it is what keeps this test from silently becoming a
        # false proof of the gate again.
        assert detail["message"] == (
            "External API access is available on Specialist and Executive plans."
        )
        assert detail["message"] != mcp_availability_sentence()
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


@pytest.mark.parametrize("plan", ["plan_specialist", "plan_executive"])
def test_eligible_plans_reach_the_tool_catalogue(
    plan: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email=f"mcp-{plan}@example.com", plan_type=plan)
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        tools = _result(_rpc(client, "tools/list"))["tools"]
        assert [tool["name"] for tool in tools] == [tool.name for tool in TOOL_REGISTRY]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# 2. Scope enforcement at dispatch
# ---------------------------------------------------------------------------


def test_a_tool_whose_scope_the_key_lacks_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-scope@example.com")
        _seed_api_key(db, user=user, scopes=["projects:read"])
        _workspace, project = _seed_workspace_and_project(db, user=user)
        _seed_audit(db, user=user, project=project)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_get_audit", "arguments": {"project_id": project.id}},
            )
        )
        assert refused["code"] == MCP_ERROR_FORBIDDEN
        assert "audit:read" in refused["message"]

        # The same key still reaches the tool whose scope it does hold.
        allowed = _result(_rpc(client, "tools/call", {"name": "signal_list_projects"}))
        assert allowed["isError"] is False
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_a_retired_stored_scope_does_not_open_a_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SIGV2-1213 normalizer governs MCP tools too, not a second copy."""
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-retired-scope@example.com")
        _seed_api_key(db, user=user, scopes=["tasks:read"])
        _seed_workspace_and_project(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        refused = _error(_rpc(client, "tools/call", {"name": "signal_list_projects"}))
        assert refused["code"] == MCP_ERROR_FORBIDDEN
        assert "projects:read" in refused["message"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# 3. Tenancy
# ---------------------------------------------------------------------------


def test_projects_are_scoped_to_the_keys_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        owner = _seed_user(db, email="mcp-owner@example.com")
        stranger = _seed_user(db, email="mcp-stranger@example.com")
        _seed_api_key(db, user=owner)
        _workspace, mine = _seed_workspace_and_project(db, user=owner, project_name="Mine")
        _other_ws, theirs = _seed_workspace_and_project(
            db, user=stranger, project_name="Theirs", domain_url="https://stranger.example"
        )
        client = _build_client(db, auth_user=owner, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        listed = _result(_rpc(client, "tools/call", {"name": "signal_list_projects"}))
        names = {project["name"] for project in listed["structuredContent"]["projects"]}
        assert names == {"Mine"}

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_list_recommendations", "arguments": {"project_id": theirs.id}},
            )
        )
        assert refused["code"] in {MCP_ERROR_FORBIDDEN, MCP_ERROR_NOT_FOUND}
        assert "Theirs" not in refused["message"]
        assert str(mine.id) not in refused["message"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_an_audit_id_from_another_project_is_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid-looking audit id must be resolved inside the named project."""
    db, engine = _build_db()
    try:
        owner = _seed_user(db, email="mcp-audit-scope@example.com")
        stranger = _seed_user(db, email="mcp-audit-stranger@example.com")
        _seed_api_key(db, user=owner)
        _ws, mine = _seed_workspace_and_project(db, user=owner, project_name="Mine")
        _other, theirs = _seed_workspace_and_project(
            db, user=stranger, project_name="Theirs", domain_url="https://stranger.example"
        )
        foreign_audit = _seed_audit(db, user=stranger, project=theirs)
        client = _build_client(db, auth_user=owner, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {
                    "name": "signal_get_audit",
                    "arguments": {"project_id": mine.id, "audit_id": foreign_audit.id},
                },
            )
        )
        assert refused["code"] == MCP_ERROR_NOT_FOUND
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_another_tenants_scan_job_reads_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        owner = _seed_user(db, email="mcp-job-owner@example.com")
        stranger = _seed_user(db, email="mcp-job-stranger@example.com")
        _seed_api_key(db, user=owner)
        _seed_workspace_and_project(db, user=owner)
        _seed_job(db, user=stranger, job_id="job-belongs-to-stranger")
        client = _build_client(db, auth_user=owner, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        foreign = _error(
            _rpc(
                client,
                "tools/call",
                {
                    "name": "signal_get_scan_status",
                    "arguments": {"job_id": "job-belongs-to-stranger"},
                },
            )
        )
        missing = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_get_scan_status", "arguments": {"job_id": "job-never-existed"}},
            )
        )
        # Identical answers: the endpoint cannot be used to prove a job exists.
        assert foreign == missing
        assert foreign["code"] == MCP_ERROR_NOT_FOUND
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_own_scan_status_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-own-job@example.com")
        _seed_api_key(db, user=user)
        _ws, project = _seed_workspace_and_project(db, user=user)
        _seed_job(db, user=user, project=project)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        payload = _result(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_get_scan_status", "arguments": {"job_id": "job-1210"}},
            )
        )["structuredContent"]
        assert payload["job_id"] == "job-1210"
        assert payload["status"] == "queued"
        assert payload["project_id"] == project.id
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# 4. Minimum disclosure
# ---------------------------------------------------------------------------


def test_recommendations_return_the_headline_not_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-recs@example.com")
        _seed_api_key(db, user=user)
        _ws, project = _seed_workspace_and_project(db, user=user)
        task = _seed_task(db, project=project, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = _rpc(
            client,
            "tools/call",
            {"name": "signal_list_recommendations", "arguments": {"project_id": project.id}},
        )
        result = _result(response)
        items = result["structuredContent"]["recommendations"]
        assert [item["title"] for item in items] == [task.title]
        assert set(items[0]) == {
            "recommendation_id",
            "project_id",
            "title",
            "category",
            "priority",
            "status",
            "created_at",
        }
        # Neither the body nor the assignee reaches the agent's context, in the
        # structured half or the text half of the result.
        assert "must not be disclosed" not in response.text
        assert "assigned_to_user_id" not in response.text
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_audit_scores_match_the_rest_api(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-audit@example.com")
        _seed_api_key(db, user=user)
        _ws, project = _seed_workspace_and_project(db, user=user)
        audit = _seed_audit(db, user=user, project=project)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        payload = _result(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_get_audit", "arguments": {"project_id": project.id}},
            )
        )["structuredContent"]
        assert payload["audit_id"] == audit.id
        # The overall score is the report's own number, not a recomputation.
        assert payload["scores"] == {"geo": 70.0, "seo": 80.0, "aeo": 60.0, "overall": 72.5}
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# 5. Nothing here can spend
# ---------------------------------------------------------------------------


def test_only_the_audit_tool_is_advertised_as_spending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The served catalogue must tell a client which call costs money.

    Read from ``tools/list`` rather than from the registry, because what
    protects the customer is what the client is actually told: a tool
    advertised as ``readOnlyHint`` is one many clients will call without
    asking anyone.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-spend-catalogue@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        tools = _result(_rpc(client, "tools/list"))["tools"]
        writers = [tool for tool in tools if tool["annotations"]["readOnlyHint"] is False]
        assert [tool["name"] for tool in writers] == ["signal_run_audit"]

        for tool in tools:
            assert tool["annotations"]["destructiveHint"] is False, tool["name"]

        audit_tool = writers[0]
        # The cost has to be legible in the description, because that is the
        # only part of this a model reads before deciding to call it.
        assert "consumes one scan" in audit_tool["description"]
        assert "scan allowance" in audit_tool["description"]
        assert audit_tool["annotations"]["idempotentHint"] is False
        # No url argument: the target is the project's own registered domain.
        assert set(audit_tool["inputSchema"]["properties"]) == {"project_id", "tier"}
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_the_served_instructions_do_not_claim_a_read_only_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initialize instructions become part of a model's standing context.

    They previously said the server "cannot start a scan, change a project or
    spend credits", which stopped being true the moment signal_run_audit
    landed. A model told that would have no reason to treat the audit tool as
    costly. Read from the live initialize result, because that is the string a
    client actually receives.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-instructions@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        text = _result(_rpc(client, "initialize", {"protocolVersion": "2025-06-18"}))[
            "instructions"
        ]

        assert "cannot start a scan" not in text
        assert "read-only" not in text
        # It has to name the tool that spends and say it costs money.
        assert "signal_run_audit" in text
        assert "consumes one scan" in text
        assert "costs them money" in text
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_running_an_audit_without_the_write_scope_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``audit:write`` is outside the default grant and is really required."""
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-audit-noscope@example.com")
        # Every read scope, which is what an omitted scope list would grant.
        _seed_api_key(db, user=user, scopes=["audit:read", "projects:read"])
        _workspace, project = _seed_workspace_and_project(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_run_audit", "arguments": {"project_id": project.id}},
            )
        )
        assert refused["code"] == MCP_ERROR_FORBIDDEN
        assert refused["message"].endswith("audit:write.")
        assert db.query(models.AuditJob).count() == 0
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_running_an_audit_queues_one_job_against_the_projects_own_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-audit-run@example.com")
        _seed_api_key(db, user=user, scopes=["audit:read", "audit:write", "projects:read"])
        _workspace, project = _seed_workspace_and_project(
            db, user=user, domain_url="https://example.com"
        )
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        fake = _patch_redis(monkeypatch)

        result = _result(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_run_audit", "arguments": {"project_id": project.id}},
            )
        )
        payload = result["structuredContent"]

        assert payload["status"] == "queued"
        assert payload["project_id"] == project.id
        assert payload["target_url"] == "https://example.com"
        assert payload["already_running"] is False
        # The id is returned so the agent polls instead of calling again.
        assert payload["job_id"]
        assert payload["poll_with"] == "signal_get_scan_status"

        jobs = db.query(models.AuditJob).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.project_id == project.id
        assert job.url == "https://example.com"
        # Counted as the customer's own scan by the shared launch path, which
        # is what makes it billable exactly once.
        assert job.scan_origin == models.SCAN_ORIGIN_CUSTOMER
        assert job.api_key_id is not None

        # It really reached a worker queue, not just the database.
        assert any(job.id in entry for entries in fake.lists.values() for entry in entries)

        # The allowance it just spent is reported back in the same answer.
        assert payload["scan_allowance"]["scans_used"] == 1
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_a_repeated_audit_call_does_not_start_a_second_paid_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry that would otherwise cost the customer twice.

    An autonomous client that reads a slow answer as a failure calls again.
    The derived idempotency key makes the second call replay the first job, so
    exactly one job exists and exactly one scan is consumed.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-audit-retry@example.com")
        _seed_api_key(db, user=user, scopes=["audit:read", "audit:write", "projects:read"])
        _workspace, project = _seed_workspace_and_project(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        call = {"name": "signal_run_audit", "arguments": {"project_id": project.id}}
        first = _result(_rpc(client, "tools/call", call))["structuredContent"]
        second_response = _rpc(client, "tools/call", call)

        body = second_response.json()
        if "error" in body:
            # Refused as already running: also acceptable, and also free.
            assert body["error"]["data"]["retryable"] is False
            assert "already running" in body["error"]["message"]
        else:
            second = body["result"]["structuredContent"]
            assert second["job_id"] == first["job_id"], "a second paid audit was started"

        assert db.query(models.AuditJob).count() == 1, "the retry created a second audit job"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_an_exhausted_scan_allowance_refuses_the_audit_legibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal an autonomous client has to be able to stop on.

    The allowance is exhausted for real, by filling the plan's rolling window
    with customer-origin jobs, so this exercises the shared
    ``scan_allowance_service`` counter rather than a stubbed limit. The
    assertions are about legibility: the message has to say the allowance is
    exhausted, that nothing was charged and when it resets, and the error data
    has to mark it non-retryable. An opaque refusal is what turns one failure
    into a hundred attempts.
    """
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-audit-allowance@example.com")
        _seed_api_key(db, user=user, scopes=["audit:read", "audit:write", "projects:read"])
        _workspace, project = _seed_workspace_and_project(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        limit = CAPABILITY_MATRIX["plan_specialist"]["max_audits"]
        assert isinstance(limit, int) and limit > 0
        db.bulk_save_objects(
            [
                models.AuditJob(
                    id=f"seeded-{index}",
                    user_id=user.id,
                    status="completed",
                    source="external",
                    url="https://example.com",
                    scan_origin=models.SCAN_ORIGIN_CUSTOMER,
                )
                for index in range(limit)
            ]
        )
        db.commit()

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_run_audit", "arguments": {"project_id": project.id}},
            )
        )

        assert refused["code"] == MCP_ERROR_FORBIDDEN
        message = refused["message"]
        assert "used all" in message and str(limit) in message
        assert "nothing was charged" in message
        assert "Do not retry" in message
        assert refused["data"]["reason"] == "scan_allowance_exhausted"
        assert refused["data"]["retryable"] is False
        assert refused["data"]["scans_limit"] == limit
        # The reset time has to be present so a client knows when to come back.
        assert refused["data"]["resets_at"]

        # Nothing was started: the refusal is before the job row, not after.
        assert db.query(models.AuditJob).count() == limit
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_the_audit_tool_cannot_be_aimed_at_another_tenants_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project id is resolved, so a foreign one buys nothing."""
    db, engine = _build_db()
    try:
        owner = _seed_user(db, email="mcp-audit-owner@example.com")
        stranger = _seed_user(db, email="mcp-audit-stranger@example.com")
        _seed_api_key(db, user=stranger, scopes=["audit:read", "audit:write", "projects:read"])
        _workspace, foreign_project = _seed_workspace_and_project(db, user=owner)
        client = _build_client(db, auth_user=stranger, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        refused = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_run_audit", "arguments": {"project_id": foreign_project.id}},
            )
        )
        assert refused["code"] in {MCP_ERROR_FORBIDDEN, MCP_ERROR_NOT_FOUND}
        assert db.query(models.AuditJob).count() == 0
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# 6. Protocol and transport
# ---------------------------------------------------------------------------


def test_initialize_negotiates_the_protocol_version(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-init@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        supported = _result(
            _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        )
        assert supported["protocolVersion"] == "2025-06-18"
        assert supported["serverInfo"]["name"] == "qiko-signal"
        assert supported["capabilities"] == {"tools": {"listChanged": False}}
        # The cost and remit wording is pinned by
        # test_the_served_instructions_do_not_claim_a_read_only_server; here it
        # is enough that instructions are served at all.
        assert supported["instructions"].startswith("Qiko Signal exposes")

        # An unknown revision is answered with the newest this server speaks,
        # which is what lets a future client fall back instead of failing.
        unknown = _result(_rpc(client, "initialize", {"protocolVersion": "1999-01-01"}))
        assert unknown["protocolVersion"] == LATEST_PROTOCOL_VERSION
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_notification_is_acknowledged_without_a_body(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-notify@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.post(
            MCP_URL,
            headers=AUTH_HEADERS,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert response.status_code == 202, response.text
        assert response.content == b""
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_malformed_and_unroutable_requests_are_answered_as_jsonrpc_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-malformed@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        malformed = client.post(MCP_URL, headers=AUTH_HEADERS, content=b"{not json")
        assert malformed.status_code == 400
        assert malformed.json()["error"]["code"] == -32700

        unknown_method = _error(_rpc(client, "resources/list"))
        assert unknown_method["code"] == -32601

        bad_args = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_get_audit", "arguments": {"project_id": "not-an-id"}},
            )
        )
        assert bad_args["code"] == -32602

        unexpected_argument = _error(
            _rpc(
                client,
                "tools/call",
                {"name": "signal_list_projects", "arguments": {"workspace_id": 7}},
            )
        )
        assert unexpected_argument["code"] == -32602
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_unsupported_protocol_version_header_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-version-header@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.post(
            MCP_URL,
            headers={**AUTH_HEADERS, "MCP-Protocol-Version": "2024-01-01"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_an_unauthenticated_call_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-anon@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.post(
            MCP_URL,
            headers={"Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 401, response.text
        assert response.headers["WWW-Authenticate"].startswith("Bearer")
        # No OAuth metadata is advertised, because there is no issuer to point at.
        assert "resource_metadata" not in response.headers["WWW-Authenticate"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_the_stream_and_session_halves_of_the_transport_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-methods@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        for request in (client.get(MCP_URL, headers=AUTH_HEADERS), client.delete(MCP_URL)):
            assert request.status_code == 405, request.text
            assert request.headers["Allow"] == "POST"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_a_batch_is_answered_message_for_message(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-batch@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.post(
            MCP_URL,
            headers=AUTH_HEADERS,
            json=[
                {"jsonrpc": "2.0", "id": "a", "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": "b", "method": "tools/list"},
            ],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [reply["id"] for reply in body] == ["a", "b"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_rate_limit_headers_are_carried_on_an_mcp_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-ratelimit@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = _rpc(client, "tools/list")
        assert response.status_code == 200, response.text
        assert response.headers["X-RateLimit-Limit"] == "60"
        assert "X-RateLimit-Remaining" in response.headers
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_sdk_metadata_publishes_the_endpoint_to_an_eligible_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-metadata@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.get("/api/v1/external/sdk-metadata", headers={"X-API-Key": API_KEY})
        assert response.status_code == 200, response.text
        mcp = response.json()["mcp"]
        assert mcp["enabled"] is True
        assert mcp["endpoint"] == MCP_URL
        assert mcp["required_plan"] == "plan_specialist"
        assert mcp["availability"] == mcp_availability_sentence()
        assert mcp["tools"] == [tool.name for tool in TOOL_REGISTRY]
        # The metadata names the tool that costs money instead of claiming a
        # read-only server, which stopped being true when signal_run_audit
        # landed. Derived from the registry, so it cannot fall out of date.
        assert mcp["tools_that_consume_a_scan"] == [
            tool.name for tool in TOOL_REGISTRY if tool.consumes_scan
        ]
        assert mcp["tools_that_consume_a_scan"] == ["signal_run_audit"]
        assert "audit:write" in mcp["scopes"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_sdk_metadata_withholds_the_endpoint_from_an_ineligible_plan() -> None:
    """The ineligible branch, exercised directly rather than left to inference.

    Only Specialist and Executive keys reach ``sdk-metadata`` today, because
    the plans below them lack ``api_access`` or have no external rate limit
    configured. The branch exists for the shape the agency trial already has,
    a plan holding ``api_access`` without ``mcp_access``, so it is asserted
    here rather than shipped untested.
    """
    trial_principal = SimpleNamespace(plan="plan_agency_trial")
    metadata = _mcp_metadata(trial_principal)
    assert metadata["enabled"] is False
    assert metadata["endpoint"] is None
    # It still says what the server is and which plan it needs.
    assert metadata["availability"] == mcp_availability_sentence()
    assert metadata["required_plan"] == "plan_specialist"


def test_an_event_stream_only_client_is_told_this_endpoint_answers_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="mcp-accept@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        _patch_redis(monkeypatch)

        response = client.post(
            MCP_URL,
            headers={"X-API-Key": API_KEY, "Accept": "text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert response.status_code == 406, response.text
        assert response.json()["error"]["code"] == "NOT_ACCEPTABLE"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)
