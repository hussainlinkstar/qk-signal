"""Tests for SIGV2-1021 resumable audit stage progress.

Covers the public stage allowlist, deterministic reconstruction from retained
events, Redis-expiry "unknown" behaviour, consistent failure attribution,
and the regression that no credit/cost field reaches public payloads.
"""

import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.audit_job_event_service import (
    AUDIT_STAGE_IDS,
    append_stage_progress_event,
    normalize_stage_progress_event,
    project_audit_stage_states,
)


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name):
        return getattr(self._load(), name)


main = _LazyModuleProxy("main")


class FakeRedisClient:
    def __init__(self):
        self._store: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def hset(self, key, mapping):
        self._store[key] = dict(mapping)

    async def hgetall(self, key):
        value = self._store.get(key)
        return dict(value) if isinstance(value, dict) else {}

    async def rpush(self, key, value):
        existing = self._store.get(key)
        if isinstance(existing, list):
            existing.append(value)
        elif existing is None:
            self._store[key] = [value]
        else:
            self._store[key] = [existing, value]

    async def expire(self, key, _seconds):
        return 1

    async def lrange(self, key, start, end):
        value = self._store.get(key)
        items = list(value) if isinstance(value, list) else []
        normalized_end = None if end == -1 else end + 1
        return items[start:normalized_end]

    async def delete(self, *keys):
        for key in keys:
            self._store.pop(key, None)

    async def aclose(self):
        pass

    async def close(self):
        pass


def _build_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    user = models.User(
        email="stage-progress-test@example.com",
        hashed_password="x",
        role="user",
        credits=10,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return engine, db, user


def _make_audit_job(db, *, user_id, status="running"):
    now = datetime.now(timezone.utc)
    job_id = str(uuid.uuid4())
    job = models.AuditJob(
        id=job_id,
        user_id=user_id,
        status=status,
        url="https://example.com",
        audit_target_type=models.AuditTargetType.WEBSITE,
        target_name="example.com",
        target_url="https://example.com",
        tier="fast",
        created_at=now - timedelta(minutes=5),
        started_at=now - timedelta(minutes=4),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job_id


@pytest.fixture
def test_context(monkeypatch: pytest.MonkeyPatch):
    engine, db, user = _build_test_session()
    maintenance_module = importlib.import_module("middleware.maintenance")
    from services.ai_routing_policy import provider_runtime_state_service

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        db.refresh(user)
        return user

    async def noop_enforce_authenticated_audit_limit(*_args, **_kwargs):
        return None

    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    monkeypatch.setattr(
        main.api_module,
        "enforce_authenticated_audit_limit",
        noop_enforce_authenticated_audit_limit,
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    shared_redis = FakeRedisClient()
    import core.redis_client as _redis_client

    monkeypatch.setattr(_redis_client.async_redis_lib, "from_url", lambda *a, **kw: shared_redis)
    monkeypatch.setattr(_redis_client.sync_redis_lib, "from_url", lambda *a, **kw: shared_redis)
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    client = TestClient(main.app)
    yield {"client": client, "db": db, "user": user, "redis": shared_redis}

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Normalization allowlist (AC5)
# ---------------------------------------------------------------------------


def test_stage_event_normalization_allowlist_drops_unlisted_fields():
    normalized = normalize_stage_progress_event(
        {
            "event": "stage_started",
            "stage": "measurement",
            "attempt": 2,
            "reason": "provider_timeout",
            "prompt": "SECRET PROMPT TEXT",
            "stack_trace": "Traceback (most recent call last)...",
            "raw_response": {"provider": "openai"},
            "total_cost_usd": 0.42,
            "estimated_credit_cost": 5,
            "provider_usd": 0.11,
            "credits": 9,
        }
    )
    assert normalized is not None
    assert normalized["type"] == "stage_started"
    assert normalized["stage"] == "measurement"
    assert normalized["attempt"] == 2
    assert normalized["reason"] == "provider_timeout"
    assert isinstance(normalized["occurred_at"], str)
    leaked = set(normalized)
    assert leaked <= {"type", "stage", "occurred_at", "attempt", "reason"}
    for forbidden in (
        "prompt",
        "stack_trace",
        "raw_response",
        "total_cost_usd",
        "estimated_credit_cost",
        "provider_usd",
        "credits",
    ):
        assert forbidden not in normalized


def test_stage_event_normalization_rejects_unknown_stage_and_event():
    assert normalize_stage_progress_event({"event": "stage_started", "stage": "hacking"}) is None
    assert normalize_stage_progress_event({"event": "rm_rf", "stage": "measurement"}) is None
    assert normalize_stage_progress_event({"stage": "measurement"}) is None
    assert normalize_stage_progress_event(None) is None
    assert normalize_stage_progress_event("stage_started") is None


def test_stage_event_degraded_outcome_only_on_completed():
    degraded = normalize_stage_progress_event(
        {"event": "stage_completed", "stage": "measurement", "outcome": "degraded"}
    )
    assert degraded is not None and degraded["outcome"] == "degraded"
    ignored = normalize_stage_progress_event(
        {"event": "stage_started", "stage": "measurement", "outcome": "degraded"}
    )
    assert ignored is not None and "outcome" not in ignored


# ---------------------------------------------------------------------------
# Deterministic projection (AC2, AC3, AC4)
# ---------------------------------------------------------------------------


def _ts(offset_seconds: int) -> str:
    return (
        datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


def _ev(event_type, stage=None, *, attempt=None, reason=None, outcome=None, t=0):
    ev = {"type": event_type, "occurred_at": _ts(t)}
    if stage is not None:
        ev["stage"] = stage
    if attempt is not None:
        ev["attempt"] = attempt
    if reason is not None:
        ev["reason"] = reason
    if outcome is not None:
        ev["outcome"] = outcome
    return ev


def _by_id(stages):
    return {stage["id"]: stage for stage in stages}


def test_projection_success_sequence_all_stages_completed():
    events = [
        _ev("stage_started", "signal_collection", attempt=1, t=0),
        _ev("stage_completed", "signal_collection", attempt=1, t=5),
        _ev("stage_completed", "measurement", attempt=1, t=10),
        _ev("pipeline_started", t=11),
        _ev("debate_finished", t=20),
        _ev("stage_started", "report", attempt=1, t=21),
        _ev("stage_completed", "report", attempt=1, t=25),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="succeeded"))
    for stage_id in AUDIT_STAGE_IDS:
        assert stages[stage_id]["status"] == "completed", stage_id
    assert stages["signal_collection"]["started_at"] == _ts(0)
    assert stages["signal_collection"]["completed_at"] == _ts(5)
    assert stages["report"]["completed_at"] == _ts(25)


def test_projection_brand_target_signal_collection_skipped():
    events = [
        _ev("stage_skipped", "signal_collection", reason="brand_target", attempt=1, t=0),
        _ev("stage_completed", "measurement", attempt=1, t=4),
        _ev("stage_completed", "analysis", attempt=1, t=9),
        _ev("stage_completed", "report", attempt=1, t=12),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="succeeded"))
    assert stages["signal_collection"]["status"] == "skipped"
    assert stages["signal_collection"]["reason"] == "brand_target"
    assert stages["measurement"]["status"] == "completed"


def test_projection_partial_provider_failure_is_degraded_not_failed():
    events = [
        _ev("stage_completed", "signal_collection", attempt=1, t=3),
        _ev(
            "stage_completed",
            "measurement",
            outcome="degraded",
            reason="partial_measurement_failure",
            attempt=1,
            t=8,
        ),
        _ev("stage_completed", "analysis", attempt=1, t=15),
        _ev("stage_completed", "report", attempt=1, t=18),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="succeeded"))
    assert stages["measurement"]["status"] == "degraded"
    assert stages["measurement"]["reason"] == "partial_measurement_failure"
    # A degraded stage must not make a valid audit look fully failed.
    assert stages["analysis"]["status"] == "completed"
    assert stages["report"]["status"] == "completed"


def test_projection_failed_job_attributes_to_in_flight_stage():
    events = [
        _ev("stage_completed", "signal_collection", attempt=1, t=3),
        _ev("stage_completed", "measurement", attempt=1, t=8),
        _ev("stage_started", "analysis", attempt=1, t=9),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="failed"))
    # Consistent attribution: the stage still running when the job died is
    # the failed stage; completed stages stay completed (AC4).
    assert stages["analysis"]["status"] == "failed"
    assert stages["analysis"]["reason"] == "job_failed"
    assert stages["signal_collection"]["status"] == "completed"
    assert stages["measurement"]["status"] == "completed"
    assert stages["report"]["status"] == "unknown"


def test_projection_explicit_stage_failure_wins_over_inferred():
    events = [
        _ev("stage_completed", "signal_collection", t=3),
        _ev("stage_failed", "analysis", reason="ai_service_unavailable", t=9),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="failed"))
    assert stages["analysis"]["status"] == "failed"
    assert stages["analysis"]["reason"] == "ai_service_unavailable"


def test_projection_retry_attempt_distinguishable():
    events = [
        _ev("stage_started", "analysis", attempt=1, t=5),
        _ev("stage_failed", "analysis", attempt=1, reason="timeout", t=8),
        _ev("stage_started", "analysis", attempt=2, t=40),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="running"))
    assert stages["analysis"]["status"] == "running"
    assert stages["analysis"]["attempt"] == 2
    assert stages["analysis"]["started_at"] == _ts(40)


def test_projection_duplicate_events_deterministic():
    events = [
        _ev("stage_completed", "signal_collection", t=3),
        _ev("stage_completed", "signal_collection", t=3),
        _ev("stage_completed", "measurement", t=8),
        _ev("stage_completed", "analysis", t=12),
        _ev("stage_completed", "report", t=15),
    ]
    first = project_audit_stage_states(events, job_status="succeeded")
    second = project_audit_stage_states(list(reversed(events)) + events, job_status="succeeded")
    # Out-of-order and duplicated events resolve deterministically: the last
    # terminal transition wins regardless of replay position.
    assert [s["status"] for s in first] == ["completed"] * 4
    assert [s["status"] for s in second] == ["completed"] * 4


def test_projection_redis_expiry_unknown_never_fabricated():
    # Evidence list expired: job status survives (job hash TTL), events do not.
    for status in ("succeeded", "failed"):
        stages = _by_id(project_audit_stage_states([], job_status=status))
        for stage_id in AUDIT_STAGE_IDS:
            assert stages[stage_id]["status"] == "unknown", (status, stage_id)
    # A queued job with no events truthfully reports pending.
    queued = _by_id(project_audit_stage_states([], job_status="queued"))
    assert all(s["status"] == "pending" for s in queued.values())
    running = _by_id(project_audit_stage_states([], job_status="running"))
    assert all(s["status"] == "pending" for s in running.values())


def test_projection_partial_evidence_terminal_job_marks_silent_stages_unknown():
    events = [_ev("stage_completed", "signal_collection", t=3)]
    stages = _by_id(project_audit_stage_states(events, job_status="succeeded"))
    assert stages["signal_collection"]["status"] == "completed"
    assert stages["measurement"]["status"] == "unknown"
    assert stages["analysis"]["status"] == "unknown"
    assert stages["report"]["status"] == "unknown"


def test_projection_running_job_shows_pending_for_future_stages():
    events = [
        _ev("stage_completed", "signal_collection", t=3),
        _ev("stage_completed", "measurement", t=8),
        _ev("stage_started", "analysis", t=9),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="running"))
    assert stages["analysis"]["status"] == "running"
    assert stages["report"]["status"] == "pending"


def test_projection_debate_finished_completes_analysis_while_report_waits():
    """SIGV2-1162: the shape every successful scan passes through.

    ``analysis`` completes when the debate returns (audit_runner emits
    ``stage_completed analysis`` right after ``generate_audit``), and
    ``report`` only starts once the post-analysis work is done (queue_worker
    emits ``stage_started report`` after ``perform_audit`` returns). The
    projection is deliberately truthful here: the debate is finished and
    report assembly has not started. Any consumer merging the two stages into
    one row must read that pair as in progress, never as queued.
    """
    events = [
        _ev("stage_completed", "signal_collection", t=3),
        _ev("stage_completed", "measurement", t=8),
        _ev("pipeline_started", t=9),
        _ev("step_completed", t=10),
        _ev("debate_finished", t=12),
    ]
    stages = _by_id(project_audit_stage_states(events, job_status="running"))
    assert stages["analysis"]["status"] == "completed"
    assert stages["report"]["status"] == "pending"


# ---------------------------------------------------------------------------
# Append + TTL (AC3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_stage_event_sets_expiry_and_persists():
    redis_client = FakeRedisClient()
    appended = await append_stage_progress_event(
        redis_client,
        job_id="job-ttl",
        payload={"event": "stage_started", "stage": "report", "attempt": 1},
    )
    assert appended is not None
    stored = redis_client._store["audit:job:job-ttl:events"]
    assert len(stored) == 1
    assert "stage_started" in stored[0]


# ---------------------------------------------------------------------------
# Endpoint: stages on polling payload, foreign job refused, payload hygiene
# ---------------------------------------------------------------------------


def test_status_endpoint_returns_stage_projection(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user = test_context["user"]
    redis_client = test_context["redis"]
    job_id = _make_audit_job(db, user_id=user.id, status="running")

    redis_client._store[f"audit:job:{job_id}"] = {
        "status": "running",
        "request_id": "req-1",
    }

    import asyncio

    async def _seed():
        await append_stage_progress_event(
            redis_client,
            job_id=job_id,
            payload={"event": "stage_completed", "stage": "signal_collection"},
        )
        await append_stage_progress_event(
            redis_client,
            job_id=job_id,
            payload={"event": "stage_started", "stage": "measurement"},
        )

    asyncio.run(_seed())

    response = client.get(f"/api/v1/audit/jobs/{job_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    stages = {s["id"]: s for s in body["stages"]}
    assert stages["signal_collection"]["status"] == "completed"
    assert stages["measurement"]["status"] == "running"
    assert stages["analysis"]["status"] == "pending"
    assert stages["report"]["status"] == "pending"


def test_status_endpoint_expired_events_reports_unknown(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user = test_context["user"]
    redis_client = test_context["redis"]
    job_id = _make_audit_job(db, user_id=user.id, status="succeeded")

    # Job hash survives; the events list has expired (absent from the store).
    redis_client._store[f"audit:job:{job_id}"] = {"status": "succeeded"}

    response = client.get(f"/api/v1/audit/jobs/{job_id}")
    assert response.status_code == 200, response.text
    stages = {s["id"]: s for s in response.json()["stages"]}
    assert all(s["status"] == "unknown" for s in stages.values())


def test_status_endpoint_foreign_job_refused(test_context):
    client = test_context["client"]
    db = test_context["db"]
    job_id = _make_audit_job(db, user_id=999999, status="running")
    response = client.get(f"/api/v1/audit/jobs/{job_id}")
    assert response.status_code == 404


def test_status_and_sse_payloads_carry_no_credit_or_cost_fields(test_context):
    """AC5 regression: no credit or provider-USD field can reach the public
    polling payload, stage events, or the SSE stream."""
    client = test_context["client"]
    db = test_context["db"]
    user = test_context["user"]
    redis_client = test_context["redis"]
    job_id = _make_audit_job(db, user_id=user.id, status="running")

    # Worker job hash legitimately carries internal credit accounting (SIGV2-1024).
    redis_client._store[f"audit:job:{job_id}"] = {
        "status": "running",
        "request_id": "req-2",
        "estimated_credit_cost": "5",
        "consumed_credit_cost": "0",
        "remaining_credits": "9",
    }

    import asyncio

    async def _seed():
        await append_stage_progress_event(
            redis_client,
            job_id=job_id,
            payload={
                "event": "stage_started",
                "stage": "signal_collection",
                "attempt": 1,
                "total_cost_usd": 1.23,
                "estimated_credit_cost": 5,
                "credits": 9,
            },
        )

    asyncio.run(_seed())

    response = client.get(f"/api/v1/audit/jobs/{job_id}")
    assert response.status_code == 200, response.text
    forbidden_fragments = ("credit", "cost", "usd", "price", "billing")
    serialized = response.text.lower()
    for fragment in forbidden_fragments:
        assert fragment not in serialized, f"public payload leaked '{fragment}': {serialized}"


# ---------------------------------------------------------------------------
# SIGV2-1292. Edward: "a scan jumps from queued straight to finished with no
# sign of progress."
#
# Settled with a real scan on preprod rather than by reading. It ran 44.3
# seconds and recorded 21 events, with the four stages well spread:
#
#   +0.0s   stage_started    signal_collection
#   +3.5s   stage_completed  signal_collection
#   +10.8s  stage_completed  measurement
#   +11.2s  stage_started    analysis
#   +29.0s  stage_completed  analysis
#   +43.3s  stage_started    report
#   +44.3s  stage_completed  report
#
# So the machinery is correct and the data is complete. What is missing is in
# that list: `measurement` has a completion and no start. It only ever emitted
# `stage_completed` or `stage_skipped`, so its row could never read as
# running. It sat queued for 7.3 seconds, the second longest window in the
# run, while it was working.
#
# A stage that cannot say it has begun is a stage the customer watches do
# nothing and then be finished, which is most of what was reported.
# ---------------------------------------------------------------------------


def test_every_canonical_stage_can_announce_that_it_started():
    """Each stage has a `stage_started` emission somewhere in the pipeline.

    Read off the source, because the gap was an absence: no test that drives a
    scan can fail on an event that is never sent, and the projection happily
    renders a stage that only ever completes.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / name).read_text() for name in ("audit_runner.py", "queue_worker.py")
    )

    missing = [
        stage
        for stage in AUDIT_STAGE_IDS
        if f'"stage_started", "{stage}"' not in sources
        and f'"event": "stage_started", "stage": "{stage}"' not in sources
    ]
    assert missing == [], f"these stages never announce a start: {missing}"


def test_a_stage_that_only_completes_reads_as_queued_until_it_is_done():
    """Why the missing emission mattered, in the projection's own terms."""
    events = [
        {
            "type": "stage_started",
            "stage": "signal_collection",
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        {
            "type": "stage_completed",
            "stage": "signal_collection",
            "occurred_at": "2026-01-01T00:00:03Z",
        },
    ]
    stages = {
        s["id"]: s["status"] for s in project_audit_stage_states(events, job_status="running")
    }

    # signal_collection announced both, so it is done.
    assert stages["signal_collection"] == "completed"
    # measurement is the one that was working and silent. Before the fix this
    # is the state it stayed in for 7.3 seconds of a 44 second run.
    assert stages["measurement"] in {"pending", "running"}
