"""Tests for the public (marketing site) guest audit contract.

Covers the three properties that make this surface different from the legacy
synchronous endpoint: it is submit plus poll, it is readable cross origin only
by configured marketing-site origins, and everything it returns to an
anonymous caller goes through an output allowlist.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import guest_audit_public  # noqa: E402

ALLOWED_ORIGIN = "https://www.preprod.qiko.ai"
DISALLOWED_ORIGIN = "https://evil.example.com"


class FakeRedis:
    """Enough of the Redis surface for the guest audit job store."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.counters: dict[str, int] = {}

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.hashes else 0

    async def get(self, key: str):
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


@pytest.fixture
def public_client(monkeypatch: pytest.MonkeyPatch):
    redis = FakeRedis()

    @contextlib.asynccontextmanager
    async def _fake_redis(**_kwargs):
        yield redis

    monkeypatch.setattr(guest_audit_public, "get_async_redis", _fake_redis)

    cors_module = importlib.import_module("core.public_site_cors")
    monkeypatch.setattr(cors_module, "resolve_public_site_origins", lambda: (ALLOWED_ORIGIN,))

    maintenance_module = importlib.import_module("middleware.maintenance")
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    main_mod = importlib.import_module("main")
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    yield client, redis
    main_mod.app.dependency_overrides.clear()


def _submit(client, **overrides):
    body = {"url": "https://example.com"}
    body.update(overrides)
    return client.post("/api/v1/public/guest-audit", json=body)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def test_submit_queues_a_job_and_never_runs_the_audit_inline(public_client):
    client, redis = public_client

    response = _submit(client)

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["job_id"]
    assert payload["poll_url"] == f"/api/v1/public/guest-audit/{payload['job_id']}"
    assert payload["poll_after_ms"] > 0

    queued = redis.lists[guest_audit_public.resolve_queue_name()]
    assert len(queued) == 1
    assert json.loads(queued[0])["target_url"] == "https://example.com"


def test_submit_hashes_the_client_ip_rather_than_storing_it(public_client):
    client, redis = public_client

    job_id = _submit(client).json()["job_id"]

    stored = redis.hashes[guest_audit_public.job_key(job_id)]
    assert stored["ip_hash"]
    assert "testclient" not in json.dumps(stored)


def test_repeat_submission_for_the_same_target_joins_the_running_job(public_client):
    client, redis = public_client

    first = _submit(client).json()
    second = _submit(client).json()

    assert second["job_id"] == first["job_id"]
    assert second["deduplicated"] is True
    # The point of the cooldown: the identical audit is not paid for twice.
    assert len(redis.lists[guest_audit_public.resolve_queue_name()]) == 1


def test_submit_is_refused_when_the_queue_is_at_capacity(public_client, monkeypatch):
    client, redis = public_client
    monkeypatch.setattr(guest_audit_public, "resolve_max_queue_depth", lambda: 1)
    redis.lists[guest_audit_public.resolve_queue_name()] = ["already-queued"]

    response = _submit(client, url="https://another-example.com")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"


def test_submit_rejects_a_body_with_unknown_fields(public_client):
    client, _redis = public_client

    response = client.post(
        "/api/v1/public/guest-audit",
        json={"url": "https://example.com", "tier": "deep_judgment"},
    )

    assert response.status_code == 422


def test_brand_submission_does_not_require_a_url(public_client):
    client, _redis = public_client

    response = client.post(
        "/api/v1/public/guest-audit",
        json={"audit_target_type": "brand", "target_name": "Acme Logistics"},
    )

    assert response.status_code == 202


# ---------------------------------------------------------------------------
# SSRF at the edge of the public contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5",
        "http://192.168.1.2",
        "http://172.16.0.10",
        "http://localhost:8000",
        "http://[::1]/",
        "file:///etc/passwd",
    ],
)
def test_submit_rejects_private_and_link_local_targets(public_client, blocked_url):
    client, redis = public_client

    response = client.post("/api/v1/public/guest-audit", json={"url": blocked_url})

    assert response.status_code == 400
    # No job is created, so a rejected target costs nothing.
    assert redis.lists == {}


def test_rejection_message_does_not_reveal_why_a_target_was_blocked(public_client):
    """A private address and a malformed string must look identical.

    Otherwise the endpoint answers "does 10.0.0.5 exist on your network"
    for anyone on the internet.
    """
    client, _redis = public_client

    private = client.post("/api/v1/public/guest-audit", json={"url": "http://10.0.0.5"})
    malformed = client.post("/api/v1/public/guest-audit", json={"url": "htp://nope"})

    assert private.status_code == malformed.status_code == 400
    assert private.json()["detail"] == malformed.json()["detail"]


# ---------------------------------------------------------------------------
# Poll
# ---------------------------------------------------------------------------


def test_status_reports_queued_then_running(public_client):
    client, redis = public_client
    job_id = _submit(client).json()["job_id"]

    assert client.get(f"/api/v1/public/guest-audit/{job_id}").json()["status"] == "queued"

    redis.hashes[guest_audit_public.job_key(job_id)]["status"] = "running"
    body = client.get(f"/api/v1/public/guest-audit/{job_id}").json()
    assert body["status"] == "running"
    assert body["poll_after_ms"] > 0
    assert "result" not in body


def test_status_returns_404_for_an_unknown_or_expired_job(public_client):
    client, _redis = public_client

    response = client.get("/api/v1/public/guest-audit/does-not-exist")

    assert response.status_code == 404


def test_status_reports_a_failed_job_with_a_stable_code(public_client):
    client, redis = public_client
    job_id = _submit(client).json()["job_id"]
    redis.hashes[guest_audit_public.job_key(job_id)].update(
        {"status": "failed", "error_code": guest_audit_public.ERROR_TARGET_BLOCKED}
    )

    body = client.get(f"/api/v1/public/guest-audit/{job_id}").json()

    assert body["status"] == "failed"
    assert body["error"]["code"] == "target_blocked"
    assert body["error"]["message"]


def test_a_job_stuck_past_the_timeout_is_reported_as_failed(public_client):
    client, redis = public_client
    job_id = _submit(client).json()["job_id"]
    redis.hashes[guest_audit_public.job_key(job_id)]["created_at"] = "1.0"

    body = client.get(f"/api/v1/public/guest-audit/{job_id}").json()

    assert body["status"] == "failed"
    assert body["error"]["code"] == "timeout"


def test_completed_job_returns_the_projected_result(public_client):
    client, redis = public_client
    job_id = _submit(client).json()["job_id"]
    stored = guest_audit_public.project_public_result(_internal_payload())
    redis.hashes[guest_audit_public.job_key(job_id)].update(
        {"status": "completed", "result": json.dumps(stored)}
    )

    body = client.get(f"/api/v1/public/guest-audit/{job_id}").json()

    assert body["status"] == "completed"
    assert body["poll_after_ms"] == 0
    assert body["result"]["scores"]["overall"] == 61
    assert body["result"]["claim_token"] == "claim-token-value"


def test_stored_result_is_filtered_again_on_read(public_client):
    """A field that is not in the allowlist cannot be served even if it is
    somehow present in the stored payload."""
    client, redis = public_client
    job_id = _submit(client).json()["job_id"]
    stored = guest_audit_public.project_public_result(_internal_payload())
    stored["performance"] = {"lighthouse": "internal"}
    redis.hashes[guest_audit_public.job_key(job_id)].update(
        {"status": "completed", "result": json.dumps(stored)}
    )

    body = client.get(f"/api/v1/public/guest-audit/{job_id}").json()

    assert "performance" not in body["result"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_configured_marketing_origin_may_read_the_response(public_client):
    client, _redis = public_client

    response = client.post(
        "/api/v1/public/guest-audit",
        json={"url": "https://example.com"},
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "access-control-allow-credentials" not in response.headers


def test_other_origins_cannot_read_the_response(public_client):
    client, _redis = public_client

    response = client.post(
        "/api/v1/public/guest-audit",
        json={"url": "https://example.com"},
        headers={"Origin": DISALLOWED_ORIGIN},
    )

    assert "access-control-allow-origin" not in response.headers


def test_a_rejected_target_is_still_readable_by_the_marketing_site(public_client):
    """A 400 with no CORS header is an opaque network error in the browser,
    so the visitor would see nothing instead of the validation message."""
    client, _redis = public_client

    response = client.post(
        "/api/v1/public/guest-audit",
        json={"url": "http://10.0.0.5"},
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_preflight_is_answered_for_configured_origins(public_client):
    client, _redis = public_client

    response = client.options(
        "/api/v1/public/guest-audit",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]


def test_preflight_grants_nothing_to_other_origins(public_client):
    client, _redis = public_client

    response = client.options(
        "/api/v1/public/guest-audit",
        headers={"Origin": DISALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Output allowlist
# ---------------------------------------------------------------------------


def _internal_payload() -> dict:
    return {
        "url": "https://example.com",
        "target": {"type": "website", "name": "Example", "url": "https://example.com"},
        "entity": "Example",
        "intelligence_summary": "Solid basics, weak answer formatting.",
        "insights": ["Performance is solid.", "HTTP/2 detected."],
        "scores": {
            "seo": 70,
            "geo": 55,
            "aeo": 58,
            "overall": 61,
            "seo_breakdown": {"components": {"secret": 1}},
        },
        "score_groups": [
            {"label": "Technical Setup", "score": 80},
            {"label": "SEO Health", "score": 70},
            {"label": "GEO Visibility", "score": 55, "locked": True},
            {"label": "AEO Readiness", "score": 58, "locked": True},
        ],
        "detailed_seo_recommendations": [
            {
                "source": "SEO Agent",
                "priority": "Critical",
                "title": "Missing meta description",
                "description": "Reduces click-through rate.",
                "implementation": "Add a 155 character meta description to /index.html.",
            }
        ],
        "performance": {"performance_score": 80, "seo_audits": [{"title": "internal"}]},
        "network": {"http_version": "HTTP/2"},
        "analysis_metadata": {"tools_used": [{"name": "Gemini Flash 2.5"}]},
        "structured_findings": {"seo_findings": [{"description": "raw finding"}]},
        "analysis": {
            "seo_findings": [{"description": "raw finding"}],
            "aeo_findings": [
                {
                    "title": "Answer blocks missing",
                    "description": "Key pages do not lead with a direct answer.",
                }
            ],
            "geo_findings": [
                {
                    "title": "Weak entity grounding",
                    "description": "The brand is not clearly identified as an entity.",
                }
            ],
        },
        "hallucination": {"claims": []},
        "competitors": [{"name": "Competitor A"}],
        "entities": [{"name": "Example", "type": "Organization"}],
        "request_id": "req-internal-123",
        "guest_audit_token": "claim-token-value",
        "degradation": {
            "fully_measured": False,
            "content_source": "fallback",
            "javascript_rendered": False,
            "screenshot_captured": False,
            "ai_analysis_available": True,
            "reasons": [{"code": "javascript_not_rendered", "message": "No JS."}],
        },
        "metadata": {
            "created_at": "2026-09-09T10:00:00+00:00Z",
            "plan": "guest",
            "target_metadata": {"industry": "logistics"},
            "locked_sections": {
                "geo": {
                    "is_locked": True,
                    "capability_key": "has_geo_analysis",
                    "required_plan": "plan_specialist",
                    "required_plan_label": "Specialist",
                    "detail": "4 GEO findings discovered.",
                    "lock_origin": "guest",
                }
            },
        },
    }


def test_projection_emits_exactly_the_allowlisted_top_level_fields():
    projected = guest_audit_public.project_public_result(_internal_payload())

    assert set(projected) == set(guest_audit_public.PUBLIC_RESULT_FIELDS)


@pytest.mark.parametrize(
    "leaked",
    [
        "performance",
        "network",
        "analysis",
        "analysis_metadata",
        "structured_findings",
        "hallucination",
        "competitors",
        "entities",
        "request_id",
        "entity",
        "seo_improvements",
    ],
)
def test_projection_drops_internal_sections(leaked):
    projected = guest_audit_public.project_public_result(_internal_payload())

    assert leaked not in projected


def test_projection_drops_the_remediation_steps_and_the_agent_name():
    projected = guest_audit_public.project_public_result(_internal_payload())

    recommendation = projected["recommendations"][0]
    assert set(recommendation) == set(guest_audit_public.PUBLIC_RECOMMENDATION_FIELDS)
    assert "implementation" not in recommendation
    assert "source" not in recommendation


def test_projection_exposes_a_single_aio_score_not_separate_geo_and_aeo():
    projected = guest_audit_public.project_public_result(_internal_payload())

    assert set(projected["scores"]) == {"overall", "seo", "aio"}
    # 55 + 58 -> 56.5 -> 57 (half-up, same as the canonical AIO view)
    assert projected["scores"]["aio"] == 57


def test_projection_prefers_the_canonical_aio_view_when_present():
    payload = _internal_payload()
    payload["metadata"]["aio"] = {"aio_score": 62}

    projected = guest_audit_public.project_public_result(payload)

    assert projected["scores"]["aio"] == 62


def test_projection_aio_is_none_when_no_component_scores_exist():
    payload = _internal_payload()
    payload["scores"] = {"overall": 40, "seo": 70}

    projected = guest_audit_public.project_public_result(payload)

    assert projected["scores"]["aio"] is None


def test_projection_collapses_geo_and_aeo_groups_into_one_aio_group():
    projected = guest_audit_public.project_public_result(_internal_payload())

    labels = [group["label"] for group in projected["score_groups"]]
    assert labels == ["Technical Setup", "SEO Health", "AIO"]
    aio_group = projected["score_groups"][2]
    assert aio_group["score"] == 57
    assert aio_group["locked"] is True


def test_projection_exposes_aio_insights_from_ai_visibility_findings():
    projected = guest_audit_public.project_public_result(_internal_payload())

    assert projected["aio_insights"] == [
        "Answer blocks missing. Key pages do not lead with a direct answer.",
        "Weak entity grounding. The brand is not clearly identified as an entity.",
    ]


def test_projection_aio_insights_falls_back_to_aeo_improvements():
    payload = _internal_payload()
    payload["analysis"]["aeo_findings"] = []
    payload["analysis"]["geo_findings"] = []
    payload["aeo_improvements"] = ["Lead each page with a direct answer."]

    projected = guest_audit_public.project_public_result(payload)

    assert projected["aio_insights"] == ["Lead each page with a direct answer."]


def test_projection_aio_insights_is_empty_without_ai_visibility_data():
    payload = _internal_payload()
    payload["analysis"]["aeo_findings"] = []
    payload["analysis"]["geo_findings"] = []
    payload.pop("aeo_improvements", None)

    projected = guest_audit_public.project_public_result(payload)

    assert projected["aio_insights"] == []


def test_projection_drops_internal_gating_identifiers():
    projected = guest_audit_public.project_public_result(_internal_payload())

    geo_lock = projected["locked_sections"]["geo"]
    assert set(geo_lock) == {"is_locked", "required_plan_label", "detail"}
    assert "capability_key" not in geo_lock
    assert "required_plan" not in geo_lock


def test_projection_keeps_what_the_site_actually_needs():
    projected = guest_audit_public.project_public_result(_internal_payload())

    assert projected["target"]["url"] == "https://example.com"
    assert projected["summary"].startswith("Solid basics")
    assert projected["scores"]["overall"] == 61
    assert projected["claim_token"] == "claim-token-value"
    assert projected["schema_version"] == guest_audit_public.PUBLIC_RESULT_SCHEMA_VERSION


def test_a_degraded_run_says_so_in_the_result():
    """A free audit is a first impression: a low score produced without
    JavaScript rendering must be labelled, not passed off as a measurement."""
    projected = guest_audit_public.project_public_result(_internal_payload())

    degradation = projected["degradation"]
    assert degradation["fully_measured"] is False
    assert degradation["javascript_rendered"] is False
    assert degradation["reasons"][0]["code"] == "javascript_not_rendered"


def test_a_clean_run_reports_no_degradation():
    payload = _internal_payload()
    payload["degradation"] = {
        "fully_measured": True,
        "content_source": "firecrawl",
        "javascript_rendered": True,
        "screenshot_captured": True,
        "ai_analysis_available": True,
        "reasons": [],
    }

    projected = guest_audit_public.project_public_result(payload)

    assert projected["degradation"]["fully_measured"] is True
    assert projected["degradation"]["reasons"] == []
