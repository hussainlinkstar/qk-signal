import asyncio
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base


class FakeRedisClient:
    async def get(self, _key: str):
        return None

    async def set(self, _key: str, _value: str, ex: int | None = None):
        return None

    async def setex(self, _key: str, _ttl: int, _value: str):
        return None

    async def expire(self, _key: str, _ttl: int):
        return True

    async def delete(self, *_keys: str):
        return 0

    async def close(self):
        return None

    async def aclose(self):
        return None


@pytest.fixture
def concurrency_context(monkeypatch: pytest.MonkeyPatch):
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    engine = create_engine(
        f"sqlite:///{db_file.name}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    seed_db = testing_session_local()
    user = models.User(
        email="audit-concurrency@example.com",
        hashed_password="x",
        role="user",
        credits=3,
        notifications_enabled=True,
    )
    seed_db.add(user)
    seed_db.commit()
    seed_db.refresh(user)
    user_id = user.id

    # Each parallel request targets a distinct domain, which would otherwise
    # create a new tracked Site per audit and trip the plan_starter max_sites=1
    # cap (returning 403 and masking the credit-overdraw behavior under test).
    # Grant an unlimited-sites plan (plan_executive: max_sites=-1); credits are
    # still consumed (should_decrement_credits is plan-independent), so the
    # 3-credit overdraw protection remains exercised.
    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id=f"cus_concurrency_{user.id}",
        plan_type="plan_executive",
        status="active",
    )
    seed_db.add(subscription)
    seed_db.commit()

    # project_id is strictly required on AuditRequest, so seed a workspace +
    # project the user owns and reuse it across all parallel requests.
    workspace = models.Workspace(name="Concurrency Workspace", owner_id=user.id)
    seed_db.add(workspace)
    seed_db.commit()
    seed_db.refresh(workspace)
    project = models.Project(
        workspace_id=workspace.id,
        name="Concurrency Project",
        domain_url="https://example-concurrency.com",
        language="en",
    )
    seed_db.add(project)
    seed_db.commit()
    seed_db.refresh(project)
    project_id = project.id
    seed_db.close()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user(db: Session = Depends(main.get_db)):
        return db.query(models.User).filter(models.User.id == user_id).first()

    async def noop_enforce_authenticated_audit_limit(*_args, **_kwargs):
        return None

    async def fake_perform_audit(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return (
            {"analysis": {"seo_score": 90, "geo_score": 90, "aeo_score": 90}},
            {"seo": 90.0, "geo": 90.0, "aeo": 90.0, "overall": 90.0},
        )

    monkeypatch.setattr(main.api_module, "perform_audit", fake_perform_audit)
    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *_args, **_kwargs: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *_args, **_kwargs: FakeRedisClient()
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    client = TestClient(main.app)
    yield {
        "client": client,
        "session_factory": testing_session_local,
        "user_id": user_id,
        "project_id": project_id,
        "initial_credits": 3,
    }

    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_create_audit_parallel_requests_do_not_block_on_wallet(concurrency_context):
    client = concurrency_context["client"]
    initial_credits = concurrency_context["initial_credits"]
    project_id = concurrency_context["project_id"]

    def make_request(index: int):
        return client.post(
            "/api/v1/audit",
            headers={"X-Request-ID": f"req-concurrency-{index}"},
            json={
                "url": f"https://example-{index}.com",
                "provider": "google",
                "tier": "fast",
                "project_id": project_id,
            },
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(make_request, range(8)))

    statuses = [response.status_code for response in responses]
    # SIGV2-1024: the internal wallet is a soft limit, so every request is
    # accepted and the balance may go negative; it no longer caps launches.
    assert set(statuses) == {200}

    session = concurrency_context["session_factory"]()
    try:
        user = (
            session.query(models.User)
            .filter(models.User.id == concurrency_context["user_id"])
            .first()
        )
        audits_count = (
            session.query(models.Audit)
            .filter(models.Audit.user_id == concurrency_context["user_id"])
            .count()
        )
    finally:
        session.close()

    assert user is not None
    assert user.credits < initial_credits
    assert audits_count == len(responses)
    # Guard against a raw DB IntegrityError (or its underlying UNIQUE-constraint
    # message) leaking into a response body. A bare "integrity" check is too
    # broad now that successful audit reports legitimately include an
    # "integrity_certificate" section, so match the actual error signatures.
    for response in responses:
        body = (response.text or "").lower()
        assert "integrityerror" not in body
        assert "unique constraint failed" not in body
