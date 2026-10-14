"""GET /api/v1/audit/tier-durations (SIGV2-1177).

The endpoint is the only place the product gets a per-depth duration from, so
the contract that matters is what it does with too little data: it must serve an
empty ``tiers`` map rather than a zero, a null-filled entry or a borrowed
figure. The frontend renders nothing from an absent entry, which only works if
absence is what the API actually returns.
"""

from __future__ import annotations

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
from services import tier_duration_stats_service as service


class _LazyModuleProxy:
    """Deferred import so env-vars are settled before the app module loads."""

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


main = _LazyModuleProxy("main")

ENDPOINT = "/api/v1/audit/tier-durations"


class FakeRedisClient:
    def __init__(self):
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)

    async def aclose(self):
        pass

    async def close(self):
        pass


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    user = models.User(email="tier-durations@example.com", hashed_password="x", role="user")
    db.add(user)
    db.commit()
    db.refresh(user)

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

    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    yield {"client": TestClient(main.app), "db": db, "user": user}

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _publish(db, *, tier: str, p25: float, p50: float, p75: float, sample_size: int) -> None:
    db.add(
        models.AuditTierDurationStat(
            tier=tier,
            sample_size=sample_size,
            window_days=service.WINDOW_DAYS,
            min_sample_size=service.MIN_SAMPLE_SIZE,
            p25_seconds=p25,
            p50_seconds=p50,
            p75_seconds=p75,
            computed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def test_serves_the_measured_range_per_tier(context):
    _publish(
        context["db"],
        tier="smart",
        p25=420.0,
        p50=640.0,
        p75=900.0,
        sample_size=37,
    )

    response = context["client"].get(ENDPOINT)

    assert response.status_code == 200
    payload = response.json()
    assert payload["statistic"] == "p25_p75_minutes"
    assert payload["min_sample_size"] == service.MIN_SAMPLE_SIZE
    assert payload["window_days"] == service.WINDOW_DAYS
    assert set(payload["tiers"]) == {"smart"}
    assert payload["tiers"]["smart"]["low_minutes"] == 7
    assert payload["tiers"]["smart"]["high_minutes"] == 15
    assert payload["tiers"]["smart"]["sample_size"] == 37


def test_serves_an_empty_map_when_nothing_is_measured(context):
    response = context["client"].get(ENDPOINT)

    assert response.status_code == 200
    payload = response.json()
    # Not a zero, not a null-filled entry, not another tier's figure: nothing.
    assert payload["tiers"] == {}


def test_a_below_threshold_tier_is_absent_rather_than_zeroed(context):
    db = context["db"]
    # What the sweep writes for a tier with too few runs: the real sample size,
    # no quartiles.
    db.add(
        models.AuditTierDurationStat(
            tier="deep_judgment",
            sample_size=4,
            window_days=service.WINDOW_DAYS,
            min_sample_size=service.MIN_SAMPLE_SIZE,
            p25_seconds=None,
            p50_seconds=None,
            p75_seconds=None,
            computed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    payload = context["client"].get(ENDPOINT).json()

    assert payload["tiers"] == {}


def test_a_stale_row_is_not_served(context):
    db = context["db"]
    db.add(
        models.AuditTierDurationStat(
            tier="fast",
            sample_size=120,
            window_days=service.WINDOW_DAYS,
            min_sample_size=service.MIN_SAMPLE_SIZE,
            p25_seconds=180.0,
            p50_seconds=240.0,
            p75_seconds=300.0,
            computed_at=datetime.now(timezone.utc) - timedelta(days=service.MAX_STAT_AGE_DAYS + 1),
        )
    )
    db.commit()

    payload = context["client"].get(ENDPOINT).json()

    assert payload["tiers"] == {}


def test_reports_only_tiers_that_cleared_the_threshold(context):
    db = context["db"]
    _publish(db, tier="fast", p25=120.0, p50=180.0, p75=260.0, sample_size=90)
    db.add(
        models.AuditTierDurationStat(
            tier="smart",
            sample_size=2,
            window_days=service.WINDOW_DAYS,
            min_sample_size=service.MIN_SAMPLE_SIZE,
            computed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    payload = context["client"].get(ENDPOINT).json()

    assert set(payload["tiers"]) == {"fast"}
    assert payload["tiers"]["fast"]["low_minutes"] == 2
    assert payload["tiers"]["fast"]["high_minutes"] == 5


def test_requires_authentication(context):
    # The identity is used for nothing but the gate, so the assertion is simply
    # that the gate exists: a dashboard-only figure is not served anonymously.
    main.app.dependency_overrides.pop(main.get_current_user, None)

    response = context["client"].get(ENDPOINT)

    assert response.status_code in (401, 403)


def test_the_figure_is_derived_from_recorded_jobs_not_a_constant(context):
    """End to end: rows in ``audit_jobs`` become the served figure.

    This is the whole point of the ticket, so it is asserted through the real
    recompute rather than a hand-written stats row: insert completed runs, run
    the sweep's own function, read the endpoint.
    """
    db = context["db"]
    now = datetime.now(timezone.utc)
    for index in range(service.MIN_SAMPLE_SIZE):
        completed = now - timedelta(hours=index + 1)
        db.add(
            models.AuditJob(
                id=str(uuid.uuid4()),
                user_id=context["user"].id,
                status="succeeded",
                url="https://example.com",
                audit_target_type=models.AuditTargetType.WEBSITE,
                tier="smart",
                started_at=completed - timedelta(seconds=480),
                completed_at=completed,
            )
        )
    db.commit()

    service.recompute_tier_duration_stats(db, now=now)
    db.commit()

    payload = context["client"].get(ENDPOINT).json()

    assert payload["tiers"]["smart"]["sample_size"] == service.MIN_SAMPLE_SIZE
    assert payload["tiers"]["smart"]["low_minutes"] == 8
    assert payload["tiers"]["smart"]["high_minutes"] == 8
