"""SIGV2-1182: adding a prompt has to start the measurement it implies.

Jake added prompts and the project overview's "Why AI recommends / ignores your
website" cards still said "No prompt data yet". Two defects produced that:

1. Creating a ``ProjectVisibilityQuery`` enqueued nothing. The only producer for
   the ``visibility_index_jobs`` queue was ``visibility_index_worker``'s own
   hourly loop (``VISIBILITY_SCHEDULE_SECONDS``, 3600s), so the prompt went
   unmeasured for up to an hour and nothing on screen said a run was coming.
2. The project-scoped audit endpoints the overview reads
   (``/projects/{id}/audits/latest`` and friends) never passed
   ``search_type_measurements`` into ``build_normalized_audit_report``, so those
   five cards reported "unmeasured" even for a project whose prompts HAD been
   measured.

Every test here fails on the pre-fix code: the enqueue ones because nothing was
queued at all, the pending ones because there was no third state to report, and
the serialization one because the measurements never reached the response.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import models
from database import Base
from services import project_visibility_service as visibility_module
from services import visibility_refresh_service
from services.project_visibility_service import (
    ProjectVisibilityService,
    compute_search_type_measurements,
)
from services.query_taxonomy import (
    SEARCH_TYPE_CATEGORY,
    SEARCH_TYPE_COMPARISON,
    SOURCE_PENDING,
    SOURCE_UNMEASURED,
    aggregate_search_types,
)
from services.visibility_refresh_service import (
    REFRESH_JOB_KIND,
    VISIBILITY_QUEUE_NAME,
    enqueue_project_visibility_refresh,
    refresh_lease_key,
    visibility_refresh_in_flight,
)


class FakeRedis:
    """The five calls the refresh path makes, with real SET NX semantics."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.queues: dict[str, list[str]] = {}
        self.rpush_calls = 0

    def set(self, key, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.keys:
            return None
        self.keys[key] = str(value)
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def exists(self, key) -> int:
        return 1 if key in self.keys else 0

    def delete(self, key) -> int:
        return 1 if self.keys.pop(key, None) is not None else 0

    def ttl(self, key) -> int:
        return int(self.ttls.get(key, -1)) if key in self.keys else -2

    def scan_iter(self, match: str | None = None):
        pattern = str(match) if match is not None else "*"
        return [key for key in list(self.keys) if fnmatch.fnmatch(key, pattern)]

    def rpush(self, queue, *values) -> int:
        self.rpush_calls += 1
        self.queues.setdefault(queue, []).extend(str(value) for value in values)
        return len(self.queues[queue])

    # Helpers for the assertions below.
    def payloads(self) -> list[dict]:
        return [json.loads(raw) for raw in self.queues.get(VISIBILITY_QUEUE_NAME, [])]


class BrokenRedis(FakeRedis):
    def set(self, *_args, **_kwargs):
        raise RuntimeError("redis is down")


class RedisThatCannotPush(FakeRedis):
    def rpush(self, *_args, **_kwargs):
        raise RuntimeError("queue write refused")


def _install_fake_redis(monkeypatch, client: FakeRedis) -> None:
    """Point both ends of the refresh service at one fake client."""

    class _Ctx:
        def __enter__(self):
            return client

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(visibility_refresh_service, "get_sync_redis", lambda **_kwargs: _Ctx())


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db, *, plan_type: str = "plan_specialist", credits: int = 40):
    user = models.User(
        email="prompt-enqueue@example.com",
        hashed_password="x",
        role="user",
        credits=credits,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_prompt_enqueue",
            stripe_subscription_id="sub_prompt_enqueue",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    workspace = models.Workspace(name="WS", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Proj",
        domain_url="https://example.com",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return user, project


# ---------------------------------------------------------------------------
# 1. Creating a prompt enqueues exactly one run
# ---------------------------------------------------------------------------


def test_creating_a_prompt_enqueues_exactly_one_refresh(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)

        created = service.create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity", "openai"],
        )

        assert created.id is not None
        payloads = redis.payloads()
        assert len(payloads) == 1
        assert payloads[0]["kind"] == REFRESH_JOB_KIND
        assert payloads[0]["project_id"] == project.id
        # One job for the project, not one per prompt+provider cell: the worker
        # enumerates the cells when the refresh starts.
        assert redis.rpush_calls == 1
        assert refresh_lease_key(project.id) in redis.keys
    finally:
        db.close()


def test_a_prompt_on_the_existing_queue_name_is_the_only_queue_used(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        ProjectVisibilityService(db).create_query(
            project=project,
            query_text="payroll tools",
            query_type="aeo",
            providers=["perplexity"],
        )
        # The visibility worker's own queue, no second queueing scheme.
        assert list(redis.queues) == [VISIBILITY_QUEUE_NAME]
        assert VISIBILITY_QUEUE_NAME == "visibility_index_jobs"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. A burst of additions does not stack runs
# ---------------------------------------------------------------------------


def test_five_prompts_in_quick_succession_do_not_stack_runs(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)

        for index in range(5):
            service.create_query(
                project=project,
                query_text=f"payroll prompt {index}",
                query_type="aeo",
                providers=["perplexity"],
            )

        assert len(service.list_queries(project_id=project.id)) == 5
        # Five additions, one run.
        assert len(redis.payloads()) == 1
    finally:
        db.close()


def test_prompt_added_while_a_refresh_is_in_flight_does_not_enqueue_again(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)
        first = service.create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity"],
        )
        assert first.id is not None
        assert len(redis.payloads()) == 1
        # A refresh is now queued or running for this project.
        assert redis.exists(refresh_lease_key(project.id)) == 1

        result = service.request_visibility_refresh(project)

        assert result.enqueued is False
        assert result.coalesced is True
        assert result.reason == "already_in_flight"
        assert len(redis.payloads()) == 1
    finally:
        db.close()


def test_the_lease_carries_a_ttl_so_a_dead_worker_cannot_block_refreshes(monkeypatch) -> None:
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    enqueue_project_visibility_refresh(project_id=7)
    assert redis.ttls[refresh_lease_key(7)] == visibility_refresh_service.REFRESH_LEASE_SECONDS


# ---------------------------------------------------------------------------
# 2b. SIGV2-1194: editing a prompt's wording is a new question
#
# The runs already recorded answered the old wording, so they are evidence for
# a different question and are deliberately left untouched: an edit applies to
# future scans. What the edit does owe the customer is a measurement of what
# they now asked, enqueued through the same SIGV2-1182 refresh, not a second
# mechanism.
# ---------------------------------------------------------------------------


def _seed_prompt(db, project, *, query_text: str, search_type: str | None = None):
    """A prompt written straight to the table, so nothing is queued yet."""
    prompt = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text=query_text,
        query_type="aeo",
        search_type=search_type,
        providers=["perplexity"],
        is_active=True,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def test_editing_a_prompts_wording_enqueues_a_fresh_measurement(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="best payroll software")
        assert redis.payloads() == []

        updated = ProjectVisibilityService(db).update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=None,
            query_type=None,
            query_text="best payroll software for dental clinics",
        )

        assert updated.query_text == "best payroll software for dental clinics"
        payloads = redis.payloads()
        assert len(payloads) == 1
        assert payloads[0]["kind"] == REFRESH_JOB_KIND
        assert payloads[0]["project_id"] == project.id
        # Signal started this run, exactly as for an added prompt.
        assert payloads[0]["charge_credits"] is False
        assert redis.rpush_calls == 1
    finally:
        db.close()


def test_an_edit_that_does_not_change_the_wording_queues_nothing(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="best payroll software")

        service = ProjectVisibilityService(db)
        # The same words, and the same words with the padding creation would
        # have stripped: neither is a change.
        service.update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=None,
            query_type=None,
            query_text="best payroll software",
        )
        service.update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=None,
            query_type=None,
            query_text="  best   payroll   software  ",
        )
        # ... and neither is dropping an engine: nothing new needs measuring.
        service.update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=["perplexity"],
            query_type=None,
        )

        assert redis.payloads() == []
        assert redis.rpush_calls == 0
    finally:
        db.close()


def test_adding_an_engine_to_a_prompt_enqueues_a_measurement(monkeypatch) -> None:
    """A prompt/engine pair that has never been measured needs a run.

    Until this, a provider edit queued nothing, so the row named the new
    engine at once and stayed blank until the plan's cadence came round: two
    days on Specialist, a week on Starter. That is indistinguishable from the
    edit having failed, and it is the repair path for a prompt stranded on an
    engine its plan stopped measuring, so the repair has to measure.
    """
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="best payroll software")

        updated = ProjectVisibilityService(db).update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=["perplexity", "openai"],
            query_type=None,
        )

        # Stored in canonical engine order, not the order they were sent.
        assert updated.providers == ["openai", "perplexity"]
        payloads = redis.payloads()
        assert len(payloads) == 1
        assert payloads[0]["kind"] == REFRESH_JOB_KIND
        assert payloads[0]["project_id"] == project.id
        # Signal started this run, so the customer is not charged for it.
        assert payloads[0]["charge_credits"] is False
    finally:
        db.close()


def test_repointing_a_stranded_prompt_enqueues_a_measurement(monkeypatch) -> None:
    """The exact repair for a prompt left on an engine the plan dropped.

    A prompt stored against Gemini on Specialist measures nothing at all, so
    moving it onto an engine the plan does measure must produce a measurement
    rather than another silent wait.
    """
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="best payroll software")
        # Straight to the table: the plan does not allow Gemini, so the edit
        # path would refuse to put it there in the first place.
        prompt.providers = ["google"]
        db.commit()

        updated = ProjectVisibilityService(db).update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=["openai"],
            query_type=None,
        )

        assert updated.providers == ["openai"]
        assert len(redis.payloads()) == 1
    finally:
        db.close()


def test_reactivating_a_prompt_enqueues_a_measurement(monkeypatch) -> None:
    """Returning a prompt to the measured set is the same event as adding one.

    The create path already refreshes when it reactivates a duplicate, so the
    two routes back to active behave the same way.
    """
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="best payroll software")
        prompt.is_active = False
        db.commit()

        service = ProjectVisibilityService(db)
        service.update_query(
            project=project,
            query_id=prompt.id,
            is_active=True,
            providers=None,
            query_type=None,
        )
        assert len(redis.payloads()) == 1

        # Already active: re-asserting it is not a new event.
        service.update_query(
            project=project,
            query_id=prompt.id,
            is_active=True,
            providers=None,
            query_type=None,
        )
        assert len(redis.payloads()) == 1
    finally:
        db.close()


def test_an_unchanged_wording_leaves_an_inferred_type_alone(monkeypatch) -> None:
    db = _make_session()
    _install_fake_redis(monkeypatch, FakeRedis())
    try:
        _user, project = _seed_project(db)
        # NULL type, so it is inferred on read; the words suggest "category".
        prompt = _seed_prompt(db, project, query_text="acme for dental clinics")

        updated = ProjectVisibilityService(db).update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=None,
            query_type=None,
            query_text="acme for dental clinics",
        )

        assert updated.search_type is None
    finally:
        db.close()


def test_editing_a_prompt_keeps_the_measurements_already_recorded(monkeypatch) -> None:
    db = _make_session()
    _install_fake_redis(monkeypatch, FakeRedis())
    try:
        _user, project = _seed_project(db)
        prompt = _seed_prompt(db, project, query_text="nike vs adidas comparison")
        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="nike vs adidas comparison",
            provider="perplexity",
            target_domain="example.com",
            schedule_key="already-measured",
            status="succeeded",
            score=72.0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        db.add(
            models.VisibilityRun(
                batch_id=batch.id,
                topic=batch.topic,
                provider="perplexity",
                target_domain="example.com",
                prompt_template="default",
                prompt=batch.topic,
                raw_response={"answer": "example.com leads."},
                parsed_citations=["https://example.com/shoes"],
                valid_citations=["https://example.com/shoes"],
                status="succeeded",
                score=72.0,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        ProjectVisibilityService(db).update_query(
            project=project,
            query_id=prompt.id,
            is_active=None,
            providers=None,
            query_type=None,
            query_text="nike vs puma comparison",
        )

        batches = db.query(models.VisibilityRunBatch).all()
        runs = db.query(models.VisibilityRun).all()
        assert [row.topic for row in batches] == ["nike vs adidas comparison"]
        assert [row.score for row in batches] == [72.0]
        assert [row.topic for row in runs] == ["nike vs adidas comparison"]
        assert [row.valid_citations for row in runs] == [["https://example.com/shoes"]]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. Cost and allowance: Signal started this run, the customer does not pay
# ---------------------------------------------------------------------------


def test_the_refresh_charges_nothing_and_creates_no_scan(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        user, project = _seed_project(db, credits=40)
        ProjectVisibilityService(db).create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity"],
        )

        payload = redis.payloads()[0]
        # SIGV2-1128's rule, applied to a Signal-initiated refresh: the hourly
        # sweep passes charge_credits=True with the workspace owner's id, this
        # path must not.
        assert payload["charge_credits"] is False
        assert "charge_user_id" not in payload

        db.refresh(user)
        assert user.credits == 40
        assert db.query(models.UserCreditAdjustment).count() == 0
        # No AuditJob, so the 30-day scan allowance cannot see this at all.
        assert db.query(models.AuditJob).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. Queueing must never cost the customer the prompt they just saved
# ---------------------------------------------------------------------------


def test_a_redis_outage_does_not_lose_the_prompt(monkeypatch) -> None:
    db = _make_session()
    _install_fake_redis(monkeypatch, BrokenRedis())
    try:
        _user, project = _seed_project(db)
        created = ProjectVisibilityService(db).create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity"],
        )
        assert created.id is not None
        assert created.is_active is True
    finally:
        db.close()


def test_a_failed_queue_push_releases_the_lease(monkeypatch) -> None:
    redis = RedisThatCannotPush()
    _install_fake_redis(monkeypatch, redis)

    result = enqueue_project_visibility_refresh(project_id=11)

    assert result.enqueued is False
    assert result.reason == "queue_unavailable"
    # Otherwise the next prompt would coalesce into a refresh nobody queued.
    assert refresh_lease_key(11) not in redis.keys


def test_an_unreachable_lease_reports_not_pending(monkeypatch) -> None:
    _install_fake_redis(monkeypatch, BrokenRedis())
    assert visibility_refresh_in_flight(3) is False


def test_a_project_with_no_active_prompts_queues_nothing(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        result = ProjectVisibilityService(db).request_visibility_refresh(project)
        assert result.reason == "no_active_prompts"
        assert result.pending is False
        assert redis.payloads() == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. The surface says a run is in progress, not that there is no data
# ---------------------------------------------------------------------------


def test_the_cards_report_in_progress_once_a_run_is_queued(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        ProjectVisibilityService(db).create_query(
            project=project,
            # Classifies onto the "comparison" canonical search type.
            query_text="nike vs adidas comparison",
            query_type="aeo",
            providers=["perplexity"],
        )

        measurements = compute_search_type_measurements(db, project.id)
        assert measurements[SEARCH_TYPE_COMPARISON]["pending"] is True
        assert measurements[SEARCH_TYPE_COMPARISON]["score"] is None
        # A type nobody tracks has no run coming, so it keeps saying so.
        assert measurements[SEARCH_TYPE_CATEGORY]["pending"] is False

        by_id = {entry["id"]: entry for entry in aggregate_search_types(measurements)}
        assert by_id[SEARCH_TYPE_COMPARISON]["source"] == SOURCE_PENDING
        assert by_id[SEARCH_TYPE_COMPARISON]["score"] is None
        assert "Measuring" in by_id[SEARCH_TYPE_COMPARISON]["insight"]
        assert by_id[SEARCH_TYPE_CATEGORY]["source"] == SOURCE_UNMEASURED
    finally:
        db.close()


def test_without_a_queued_run_the_cards_keep_the_unmeasured_state(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="nike vs adidas comparison",
                query_type="aeo",
                providers=["perplexity"],
                is_active=True,
            )
        )
        db.commit()

        measurements = compute_search_type_measurements(db, project.id)
        assert measurements[SEARCH_TYPE_COMPARISON]["pending"] is False
        by_id = {entry["id"]: entry for entry in aggregate_search_types(measurements)}
        assert by_id[SEARCH_TYPE_COMPARISON]["source"] == SOURCE_UNMEASURED
    finally:
        db.close()


def test_a_measured_type_is_never_reported_as_pending(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        ProjectVisibilityService(db).create_query(
            project=project,
            query_text="nike vs adidas comparison",
            query_type="aeo",
            providers=["perplexity"],
        )
        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="nike vs adidas comparison",
            provider="perplexity",
            target_domain="example.com",
            schedule_key="queued",
            status="succeeded",
            score=72.0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        db.add(
            models.VisibilityRun(
                batch_id=batch.id,
                topic=batch.topic,
                provider="perplexity",
                target_domain="example.com",
                prompt_template="default",
                prompt=batch.topic,
                raw_response={"answer": "example.com leads."},
                parsed_citations=["https://example.com/shoes"],
                valid_citations=["https://example.com/shoes"],
                status="succeeded",
                score=72.0,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        # The lease is still held (the refresh has not been released yet), but
        # this type already has its answer.
        assert visibility_refresh_in_flight(project.id) is True
        measurements = compute_search_type_measurements(db, project.id)
        assert measurements[SEARCH_TYPE_COMPARISON]["pending"] is False
        assert measurements[SEARCH_TYPE_COMPARISON]["score"] == 72.0
    finally:
        db.close()


def test_pending_never_asks_redis_when_every_tracked_type_is_measured(monkeypatch) -> None:
    """A measured project must not pay a Redis round trip per report render."""
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    calls: list[int] = []

    def _tracking_in_flight(project_id, **_kwargs):
        calls.append(project_id)
        return True

    monkeypatch.setattr(visibility_module, "visibility_refresh_in_flight", _tracking_in_flight)
    try:
        _user, project = _seed_project(db)
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="nike vs adidas comparison",
                query_type="aeo",
                providers=["perplexity"],
                is_active=True,
            )
        )
        db.commit()
        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="nike vs adidas comparison",
            provider="perplexity",
            target_domain="example.com",
            schedule_key="queued",
            status="succeeded",
            score=50.0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        db.add(
            models.VisibilityRun(
                batch_id=batch.id,
                topic=batch.topic,
                provider="perplexity",
                target_domain="example.com",
                prompt_template="default",
                prompt=batch.topic,
                raw_response={"answer": "An answer."},
                parsed_citations=[],
                valid_citations=[],
                status="succeeded",
                score=50.0,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        compute_search_type_measurements(db, project.id)
        assert calls == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. The response the overview cards are rendered from carries the measurements
# ---------------------------------------------------------------------------


def _create_audit(db, *, user_id: int, project_id: int) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        seo_score=62,
        geo_score=55,
        aeo_score=40,
        full_report={
            "metadata": {"audit_outcome": "completed"},
            "analysis": {"seo_score": 62, "geo_score": 55, "aeo_score": 40},
            "geo_score": 55,
            "seo_score": 62,
            "aeo_score": 40,
        },
        created_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def test_project_latest_audit_reports_the_queued_measurement(monkeypatch) -> None:
    """The exact surface Jake read.

    Fails against pre-fix code twice over: nothing was queued, and
    ``_normalize_project_audit_report`` never passed the measurements, so this
    response said "unmeasured" for all five types whatever the project's
    prompts had done.
    """
    from routers.workspace_router import get_project_latest_audit

    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        user, project = _seed_project(db)
        _create_audit(db, user_id=user.id, project_id=project.id)
        ProjectVisibilityService(db).create_query(
            project=project,
            query_text="nike vs adidas comparison",
            query_type="aeo",
            providers=["perplexity"],
        )

        entry = get_project_latest_audit(
            project_id=project.id,
            user=user,
            db=db,
            include_full_report=True,
            audit_type=None,
        )

        assert entry is not None
        search_types = entry["full_report"]["metadata"]["search_types"]
        by_id = {item["id"]: item for item in search_types}
        assert by_id[SEARCH_TYPE_COMPARISON]["source"] == SOURCE_PENDING
        assert by_id[SEARCH_TYPE_CATEGORY]["source"] == SOURCE_UNMEASURED
    finally:
        db.close()


def test_project_latest_audit_reports_a_completed_measurement(monkeypatch) -> None:
    """The other half of the same defect: a measured project read as unmeasured."""
    from routers.workspace_router import get_project_latest_audit

    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        user, project = _seed_project(db)
        _create_audit(db, user_id=user.id, project_id=project.id)
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="nike vs adidas comparison",
                query_type="aeo",
                providers=["perplexity"],
                is_active=True,
            )
        )
        db.commit()
        batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="nike vs adidas comparison",
            provider="perplexity",
            target_domain="example.com",
            schedule_key="queued",
            status="succeeded",
            score=64.0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        db.add(
            models.VisibilityRun(
                batch_id=batch.id,
                topic=batch.topic,
                provider="perplexity",
                target_domain="example.com",
                prompt_template="default",
                prompt=batch.topic,
                raw_response={"answer": "example.com leads."},
                parsed_citations=["https://example.com/shoes"],
                valid_citations=["https://example.com/shoes"],
                status="succeeded",
                score=64.0,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        entry = get_project_latest_audit(
            project_id=project.id,
            user=user,
            db=db,
            include_full_report=True,
            audit_type=None,
        )

        by_id = {item["id"]: item for item in entry["full_report"]["metadata"]["search_types"]}
        assert by_id[SEARCH_TYPE_COMPARISON]["source"] == "measured"
        assert by_id[SEARCH_TYPE_COMPARISON]["score"] == 64
        assert by_id[SEARCH_TYPE_COMPARISON]["answer_ratio"] == {"present": 1, "measured": 1}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. The worker end: one refresh job measures the project's prompts
# ---------------------------------------------------------------------------


def test_the_worker_measures_every_prompt_of_the_project_and_frees_the_lease(monkeypatch) -> None:
    import visibility_index_worker as worker

    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)
        service.create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity", "openai"],
        )
        # Added while the refresh was still on the queue: the same run measures
        # it, because the prompts are enumerated when the job starts.
        service.create_query(
            project=project,
            query_text="payroll software pricing",
            query_type="aeo",
            providers=["perplexity"],
        )
        assert len(redis.payloads()) == 1
        payload = redis.payloads()[0]

        other_db = _make_session()
        try:
            monkeypatch.setattr(worker, "SessionLocal", lambda: db)

            executed: list[dict] = []

            async def _fake_run_batch_for(**kwargs):
                executed.append(kwargs)

            monkeypatch.setattr(worker, "_run_batch_for", _fake_run_batch_for)

            class AsyncRedis:
                def __init__(self, backing: FakeRedis) -> None:
                    self.backing = backing

                async def delete(self, key):
                    return self.backing.delete(key)

            async_redis = AsyncRedis(redis)
            assert redis.exists(refresh_lease_key(project.id)) == 1

            executed_count = asyncio.run(
                worker._run_project_refresh(
                    project_id=int(payload["project_id"]),
                    schedule_key=str(payload["schedule_key"]),
                    lease_key=str(payload["lease_key"]),
                    redis_client=async_redis,
                )
            )

            assert executed_count == 3
            assert {(call["topic"], call["provider"]) for call in executed} == {
                ("best payroll software", "perplexity"),
                ("best payroll software", "openai"),
                ("payroll software pricing", "perplexity"),
            }
            assert all(call["charge_credits"] is False for call in executed)
            assert all(call["charge_user_id"] is None for call in executed)
            assert all(call["target_domain"] == "example.com" for call in executed)
            # Released, so the next prompt addition starts a run immediately
            # instead of waiting out the lease TTL.
            assert redis.exists(refresh_lease_key(project.id)) == 0
        finally:
            other_db.close()
    finally:
        db.close()


def test_the_worker_refuses_to_delete_a_lease_key_it_does_not_own(monkeypatch) -> None:
    import visibility_index_worker as worker

    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        monkeypatch.setattr(worker, "SessionLocal", lambda: db)

        async def _fake_run_batch_for(**_kwargs):
            return None

        monkeypatch.setattr(worker, "_run_batch_for", _fake_run_batch_for)

        foreign_key = refresh_lease_key(project.id + 999)
        redis.set(foreign_key, "1", nx=True, ex=900)

        class AsyncRedis:
            def __init__(self, backing: FakeRedis) -> None:
                self.backing = backing

            async def delete(self, key):
                return self.backing.delete(key)

        asyncio.run(
            worker._run_project_refresh(
                project_id=project.id,
                schedule_key="queued",
                lease_key=foreign_key,
                redis_client=AsyncRedis(redis),
            )
        )

        assert redis.exists(foreign_key) == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. SIGV2-1234: a lease outlives the work it was taken for
#
# The lease's TTL is a backstop for a worker that dies mid-refresh, but a
# restart between "lease acquired" and "job popped off the queue" (or mid-job)
# leaves nothing behind it: no visibility_run_batches row at all. Every scan
# attempt for that project was refused for up to REFRESH_LEASE_SECONDS with no
# explanation. Startup reconciliation detects and releases exactly that state;
# the coalesced refusal also now says when the lease frees.
# ---------------------------------------------------------------------------


def test_reconcile_releases_a_lease_with_no_matching_in_flight_batch(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        redis.set(refresh_lease_key(project.id), "1", ex=900)
        assert refresh_lease_key(project.id) in redis.keys

        released = visibility_refresh_service.reconcile_orphaned_refresh_leases(db)

        assert released == [project.id]
        assert refresh_lease_key(project.id) not in redis.keys
    finally:
        db.close()


def test_reconcile_leaves_a_lease_with_an_in_flight_batch_alone(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        redis.set(refresh_lease_key(project.id), "1", ex=900)
        db.add(
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="seo",
                provider="openai",
                schedule_key="queued",
                status="running",
            )
        )
        db.commit()

        released = visibility_refresh_service.reconcile_orphaned_refresh_leases(db)

        assert released == []
        assert redis.exists(refresh_lease_key(project.id)) == 1
    finally:
        db.close()


def test_reconcile_leaves_a_lease_with_a_still_queued_batch_alone(monkeypatch) -> None:
    """A batch that has not started yet is still in flight, not orphaned."""
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        redis.set(refresh_lease_key(project.id), "1", ex=900)
        db.add(
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="seo",
                provider="openai",
                schedule_key="queued",
                status="queued",
            )
        )
        db.commit()

        released = visibility_refresh_service.reconcile_orphaned_refresh_leases(db)

        assert released == []
        assert redis.exists(refresh_lease_key(project.id)) == 1
    finally:
        db.close()


def test_reconcile_ignores_lease_keys_for_other_projects(monkeypatch) -> None:
    db = _make_session()
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    try:
        _user, project = _seed_project(db)
        other_lease = refresh_lease_key(project.id + 500)
        redis.set(other_lease, "1", ex=900)
        db.add(
            models.VisibilityRunBatch(
                project_id=project.id + 500,
                topic="seo",
                provider="openai",
                schedule_key="queued",
                status="running",
            )
        )
        db.commit()

        released = visibility_refresh_service.reconcile_orphaned_refresh_leases(db)

        assert released == []
        assert redis.exists(other_lease) == 1
    finally:
        db.close()


def test_coalesced_refusal_reports_when_the_lease_frees(monkeypatch) -> None:
    redis = FakeRedis()
    _install_fake_redis(monkeypatch, redis)

    first = enqueue_project_visibility_refresh(project_id=42)
    assert first.enqueued is True

    second = enqueue_project_visibility_refresh(project_id=42)

    assert second.coalesced is True
    assert second.reason == "already_in_flight"
    assert second.retry_after_seconds == visibility_refresh_service.REFRESH_LEASE_SECONDS
    assert second.message is not None
    assert "progress" in second.message
    assert str(visibility_refresh_service.REFRESH_LEASE_SECONDS) in second.message


# ---------------------------------------------------------------------------
# The missing producer for visibility_run_batches.audit_job_id.
# ---------------------------------------------------------------------------


def test_a_refresh_can_be_attributed_to_the_scan_that_asked_for_it(monkeypatch) -> None:
    """`audit_job_id` had consumers on every side and no producer.

    The column, the `?audit_job_id=` summary filter and the scan-scoped PDF
    engine rows all existed, but nothing ever set the value, so every
    scan-scoped surface could only return nothing. The enqueue carries it
    when a scan asks, and omits it otherwise.
    """
    from services.visibility_refresh_service import enqueue_project_visibility_refresh

    redis = FakeRedis()

    result = enqueue_project_visibility_refresh(
        project_id=7, redis_client=redis, audit_job_id="job-abc"
    )
    assert result.enqueued is True
    payload = redis.payloads()[0]
    assert payload["audit_job_id"] == "job-abc"
    assert payload["kind"] == REFRESH_JOB_KIND
    # Still Signal-initiated, so still not billed.
    assert payload["charge_credits"] is False


def test_an_ordinary_prompt_refresh_carries_no_scan_attribution(monkeypatch) -> None:
    """A prompt-driven refresh belongs to the project, not to any scan.

    Attributing it to a scan would make project-wide measurements show up as
    that scan's evidence, which is the confusion the audit link exists to
    prevent.
    """
    from services.visibility_refresh_service import enqueue_project_visibility_refresh

    redis = FakeRedis()

    enqueue_project_visibility_refresh(project_id=7, redis_client=redis)

    assert "audit_job_id" not in redis.payloads()[0]
