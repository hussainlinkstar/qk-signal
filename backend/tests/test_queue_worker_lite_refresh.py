import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
import queue_worker
from database import Base
from job_models import AuditJobPayload


class _FakeRedis:
    def __init__(self):
        self.hset_calls: list[tuple[str, dict]] = []
        self.rpush_calls: list[tuple[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []

    async def hset(self, key: str, mapping: dict):
        self.hset_calls.append((key, mapping))

    async def rpush(self, key: str, value: str):
        self.rpush_calls.append((key, value))

    async def expire(self, key: str, ttl: int):
        self.expire_calls.append((key, ttl))
        return True


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.asyncio
async def test_enqueue_competitor_lite_refresh_launches_top_3(db_session):
    user = models.User(email="owner@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source_site = models.Site(user_id=user.id, domain="source.example.com", display_name="source")
    competitors = [
        models.Site(user_id=user.id, domain="comp-a.example.com", display_name="a"),
        models.Site(user_id=user.id, domain="comp-b.example.com", display_name="b"),
        models.Site(user_id=user.id, domain="comp-c.example.com", display_name="c"),
        models.Site(user_id=user.id, domain="comp-d.example.com", display_name="d"),
    ]
    db_session.add(source_site)
    db_session.add_all(competitors)
    db_session.commit()
    db_session.refresh(source_site)
    for competitor in competitors:
        db_session.refresh(competitor)
        source_site.competitors.append(competitor)
    db_session.commit()

    scores = [20.0, 90.0, 70.0, 10.0]
    for competitor, score in zip(competitors, scores, strict=True):
        db_session.add(
            models.Audit(
                user_id=user.id,
                site_id=competitor.id,
                url=f"https://{competitor.domain}",
                geo_score=score,
                seo_score=score,
                aeo_score=score,
                full_report={"metadata": {}},
                request_id=f"main:{competitor.id}",
            )
        )
    source_audit = models.Audit(
        user_id=user.id,
        site_id=source_site.id,
        url="https://source.example.com",
        geo_score=60,
        seo_score=60,
        aeo_score=60,
        full_report={"metadata": {}},
        request_id="main:source",
    )
    db_session.add(source_audit)
    db_session.commit()
    db_session.refresh(source_audit)

    job = AuditJobPayload(
        job_id="job-main",
        request_id="req-main",
        user_id=user.id,
        url=source_audit.url,
        provider="openai",
        tier="starter",
    )
    redis_client = _FakeRedis()

    result = await queue_worker._enqueue_competitor_lite_refresh_jobs(
        redis_client=redis_client,
        db=db_session,
        source_job=job,
        source_audit=source_audit,
    )

    assert result["status"] == "queued"
    assert result["enqueued_count"] == 3
    queued_domains = [entry["target_domain"] for entry in result["enqueued_jobs"]]
    assert queued_domains == ["comp-b.example.com", "comp-c.example.com", "comp-a.example.com"]
    assert len(redis_client.rpush_calls) == 3


@pytest.mark.asyncio
async def test_enqueue_competitor_lite_refresh_skips_when_no_competitors(db_session):
    user = models.User(email="owner2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source_site = models.Site(user_id=user.id, domain="solo.example.com", display_name="solo")
    source_audit = models.Audit(
        user_id=user.id,
        site_id=1,
        url="https://solo.example.com",
        geo_score=50,
        seo_score=50,
        aeo_score=50,
        full_report={"metadata": {}},
        request_id="main:solo",
    )
    db_session.add(source_site)
    db_session.commit()
    db_session.refresh(source_site)
    source_audit.site_id = source_site.id
    db_session.add(source_audit)
    db_session.commit()
    db_session.refresh(source_audit)

    job = AuditJobPayload(
        job_id="job-main-2",
        request_id="req-main-2",
        user_id=user.id,
        url=source_audit.url,
        provider="openai",
        tier="starter",
    )
    redis_client = _FakeRedis()

    result = await queue_worker._enqueue_competitor_lite_refresh_jobs(
        redis_client=redis_client,
        db=db_session,
        source_job=job,
        source_audit=source_audit,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_competitors"
    assert redis_client.rpush_calls == []


@pytest.mark.asyncio
async def test_enqueue_competitor_lite_refresh_skips_sites_in_cooldown(db_session):
    user = models.User(email="owner3@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source_site = models.Site(
        user_id=user.id, domain="source-3.example.com", display_name="source3"
    )
    competitor = models.Site(user_id=user.id, domain="comp-3.example.com", display_name="c3")
    db_session.add_all([source_site, competitor])
    db_session.commit()
    db_session.refresh(source_site)
    db_session.refresh(competitor)
    source_site.competitors.append(competitor)
    db_session.commit()

    source_audit = models.Audit(
        user_id=user.id,
        site_id=source_site.id,
        url="https://source-3.example.com",
        geo_score=50,
        seo_score=50,
        aeo_score=50,
        full_report={"metadata": {}},
        request_id="main:source3",
    )
    recent_lite_audit = models.Audit(
        user_id=user.id,
        site_id=competitor.id,
        url="https://comp-3.example.com",
        geo_score=20,
        seo_score=20,
        aeo_score=20,
        full_report={"metadata": {}},
        request_id=f"{queue_worker.LITE_AUDIT_REQUEST_PREFIX}:old",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([source_audit, recent_lite_audit])
    db_session.commit()
    db_session.refresh(source_audit)

    job = AuditJobPayload(
        job_id="job-main-3",
        request_id="req-main-3",
        user_id=user.id,
        url=source_audit.url,
        provider="openai",
        tier="starter",
    )
    redis_client = _FakeRedis()

    result = await queue_worker._enqueue_competitor_lite_refresh_jobs(
        redis_client=redis_client,
        db=db_session,
        source_job=job,
        source_audit=source_audit,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "cooldown"
    assert result["enqueued_count"] == 0
    assert result["skipped_sites"][0]["reason"] == "cooldown"
    assert redis_client.rpush_calls == []
