from __future__ import annotations

import asyncio
import gzip
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import routers.embed_router as embed_router_module
from database import Base, get_db
from routers.embed_router import get_current_user, router as embed_router, sitemap_crawler_service
from services import embed_service
from services.email_service import EmailService


class _FakePipeline:
    def __init__(self, redis_client: "_FakeRedis") -> None:
        self._redis = redis_client

    def delete(self, *keys: str) -> "_FakePipeline":
        for key in keys:
            self._redis._store.pop(key, None)
        return self

    def set(self, key: str, value: int | str, ex: int | None = None) -> "_FakePipeline":
        _ = ex
        self._redis._store[key] = str(value)
        return self

    def rpush(self, key: str, *values: str) -> "_FakePipeline":
        current = self._redis._store.get(key)
        if not isinstance(current, list):
            current = []
        current.extend([str(value) for value in values])
        self._redis._store[key] = current
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        _ = key
        _ = seconds
        return self

    async def execute(self) -> list[object]:
        return []


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, "0") or "0")
        current += 1
        self._store[key] = str(current)
        return current

    async def decr(self, key: str) -> int:
        current = int(self._store.get(key, "0") or "0")
        current -= 1
        self._store[key] = str(current)
        return current

    async def expire(self, key: str, seconds: int) -> bool:
        _ = key
        _ = seconds
        return True

    async def ttl(self, key: str) -> int:
        _ = key
        return 3600

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self._store[key] = dict(mapping)
        return len(mapping)

    async def rpush(self, key: str, value: str) -> int:
        current = self._store.get(key)
        if not isinstance(current, list):
            current = []
        current.append(str(value))
        self._store[key] = current
        return len(current)

    async def lpop(self, key: str) -> str | None:
        current = self._store.get(key)
        if not isinstance(current, list) or not current:
            return None
        return str(current.pop(0))

    async def llen(self, key: str) -> int:
        current = self._store.get(key)
        return len(current) if isinstance(current, list) else 0

    async def get(self, key: str) -> str | None:
        value = self._store.get(key)
        if isinstance(value, list):
            return None
        return str(value) if value is not None else None

    async def set(self, key: str, value: int | str, ex: int | None = None) -> bool:
        _ = ex
        self._store[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._store:
                deleted += 1
                self._store.pop(key, None)
        return deleted

    async def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _DummyHttpxResponse:
    def __init__(
        self, content: bytes, *, content_type: str = "application/xml", status_code: int = 200
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.is_redirect = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


@pytest.fixture
def embed_client(monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(embed_router)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    fake_redis = _FakeRedis()
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *args, **kwargs: fake_redis
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *args, **kwargs: fake_redis
    )

    async def _noop_lead_email(*args, **kwargs):
        return None

    async def _noop_crawl_email(*args, **kwargs):
        return None

    monkeypatch.setattr(EmailService, "send_lead_captured_email", _noop_lead_email)
    monkeypatch.setattr(EmailService, "send_sitemap_crawl_complete_email", _noop_crawl_email)

    def _seed_user(
        *, email: str = "owner@example.com", credits: int = 1000
    ) -> tuple[models.User, models.Workspace, models.Project]:
        user = models.User(
            email=email,
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
                stripe_customer_id=f"cus_{user.id}",
                stripe_subscription_id=f"sub_{user.id}",
                plan_type="plan_specialist",
                status="active",
            )
        )
        db.commit()

        workspace = models.Workspace(name="Agency Workspace", owner_id=user.id)
        db.add(workspace)
        db.commit()
        db.refresh(workspace)

        project = models.Project(
            workspace_id=workspace.id,
            name="Acme Project",
            domain_url="https://acme.test",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        return user, workspace, project

    state: dict[str, object] = {}

    def set_context(*, credits: int = 1000) -> tuple[models.User, models.Workspace, models.Project]:
        user, workspace, project = _seed_user(credits=credits)
        state["user"] = user
        state["workspace"] = workspace
        state["project"] = project
        return user, workspace, project

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return state["user"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)

    try:
        yield client, db, set_context, state, fake_redis
    finally:
        app.dependency_overrides.clear()
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def _create_embed_key(db, *, workspace_id: int, user_id: int, allowed_origins: list[str]) -> str:
    raw_key, key_hash, key_prefix, key_last_four = embed_service.generate_embed_api_key_material()
    db.add(
        models.EmbedApiKey(
            workspace_id=workspace_id,
            user_id=user_id,
            label="Homepage Widget",
            key_hash=key_hash,
            key_prefix=key_prefix,
            key_last_four=key_last_four,
            allowed_origins=allowed_origins,
            daily_limit=100,
            is_active=True,
            schema_version="1",
        )
    )
    db.commit()
    return raw_key


def test_embed_audit_rejects_unknown_origin(embed_client) -> None:
    client, db, set_context, state, _fake_redis = embed_client
    user, workspace, _project = set_context()
    raw_key = _create_embed_key(
        db, workspace_id=workspace.id, user_id=user.id, allowed_origins=["https://agency.test"]
    )

    response = client.post(
        "/api/v1/embed/audit",
        headers={"X-Embed-Key": raw_key, "Origin": "https://evil.test"},
        json={"url": "https://lead.example", "email": "lead@example.com"},
    )

    assert response.status_code == 403
    assert "Origin" in response.json()["detail"]


def test_embed_audit_creates_lead_and_job(embed_client) -> None:
    client, db, set_context, state, _fake_redis = embed_client
    user, workspace, _project = set_context()
    raw_key = _create_embed_key(
        db, workspace_id=workspace.id, user_id=user.id, allowed_origins=["https://agency.test"]
    )

    response = client.post(
        "/api/v1/embed/audit",
        headers={"X-Embed-Key": raw_key, "Origin": "https://agency.test"},
        json={"url": "https://lead.example", "email": "lead@example.com", "entity": "Acme"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["lead_id"] > 0
    assert payload["job_id"]
    assert payload["poll_url"].endswith(f"/embed/audit/{payload['job_id']}/status")

    lead = db.query(models.Lead).filter(models.Lead.id == payload["lead_id"]).first()
    assert lead is not None
    assert lead.status == "pending"
    assert lead.workspace_id == workspace.id

    audit_job = db.query(models.AuditJob).filter(models.AuditJob.id == payload["job_id"]).first()
    assert audit_job is not None
    assert audit_job.source == "embed"
    assert audit_job.embed_api_key_id is not None


def test_embed_audit_brand_mode_accepts_optional_url(embed_client) -> None:
    client, db, set_context, _state, _fake_redis = embed_client
    user, workspace, _project = set_context()
    raw_key = _create_embed_key(
        db, workspace_id=workspace.id, user_id=user.id, allowed_origins=["https://agency.test"]
    )

    response = client.post(
        "/api/v1/embed/audit",
        headers={"X-Embed-Key": raw_key, "Origin": "https://agency.test"},
        json={
            "audit_target_type": "brand",
            "email": "lead@example.com",
            "target_name": "Acme Logistics",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    audit_job = db.query(models.AuditJob).filter(models.AuditJob.id == payload["job_id"]).first()
    assert audit_job is not None
    assert str(audit_job.audit_target_type.value).lower() == "brand"
    assert audit_job.target_name == "Acme Logistics"
    assert audit_job.target_url is None
    assert audit_job.url == ""

    lead = db.query(models.Lead).filter(models.Lead.id == payload["lead_id"]).first()
    assert lead is not None
    assert lead.url == ""
    assert lead.entity == "Acme Logistics"


def test_embed_audit_requires_captcha_when_enabled(embed_client, monkeypatch) -> None:
    client, db, set_context, _state, _fake_redis = embed_client
    user, workspace, _project = set_context()
    raw_key = _create_embed_key(
        db, workspace_id=workspace.id, user_id=user.id, allowed_origins=["https://agency.test"]
    )

    monkeypatch.setattr(embed_router_module, "EMBED_CAPTCHA_REQUIRED", True)
    monkeypatch.setattr(embed_router_module, "EMBED_CAPTCHA_SECRET_KEY", "test-secret")

    response = client.post(
        "/api/v1/embed/audit",
        headers={"X-Embed-Key": raw_key, "Origin": "https://agency.test"},
        json={"url": "https://lead.example", "email": "lead@example.com"},
    )

    assert response.status_code == 400
    assert "Captcha" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sitemap_parser_supports_index_and_gzip(monkeypatch) -> None:
    index_xml = b"""<?xml version='1.0' encoding='UTF-8'?>\n<sitemapindex>\n  <sitemap><loc>https://example.test/nested.xml</loc></sitemap>\n  <sitemap><loc>https://example.test/nested.xml.gz</loc></sitemap>\n</sitemapindex>"""
    nested_xml = b"""<?xml version='1.0' encoding='UTF-8'?>\n<urlset>\n  <url><loc>https://example.test/a</loc></url>\n  <url><loc>https://example.test/b</loc></url>\n</urlset>"""
    nested_gzip_xml = gzip.compress(
        b"""<?xml version='1.0' encoding='UTF-8'?>\n<urlset>\n  <url><loc>https://example.test/c</loc></url>\n</urlset>"""
    )

    async def fake_request(self, method, url, *args, **kwargs):
        _ = method, args, kwargs
        if str(url).endswith("nested.xml"):
            return _DummyHttpxResponse(nested_xml)
        if str(url).endswith("nested.xml.gz"):
            return _DummyHttpxResponse(nested_gzip_xml, content_type="application/gzip")
        return _DummyHttpxResponse(index_xml)

    monkeypatch.setattr("services.sitemap_crawler_service.httpx.AsyncClient.request", fake_request)

    urls = await sitemap_crawler_service.parse_sitemap(
        "https://example.test/sitemap.xml", max_urls=500
    )

    assert urls == ["https://example.test/a", "https://example.test/b", "https://example.test/c"]


def test_sitemap_crawl_lifecycle_and_report(embed_client, monkeypatch) -> None:
    client, db, set_context, state, _fake_redis = embed_client
    _user, _workspace, project = set_context()

    async def fake_parse_sitemap(sitemap_url: str, max_urls: int = 500):
        _ = sitemap_url
        _ = max_urls
        return [
            "https://acme.test/page-a",
            "https://acme.test/page-b",
        ]

    monkeypatch.setattr(sitemap_crawler_service, "parse_sitemap", fake_parse_sitemap)

    response = client.post(
        f"/api/v1/projects/{project.id}/sitemap-crawl",
        json={"sitemap_url": "https://acme.test/sitemap.xml"},
    )
    assert response.status_code == 200
    payload = response.json()
    crawl_job_id = payload["job_id"]

    site = models.Site(user_id=state["user"].id, domain="acme.test", display_name="acme.test")
    db.add(site)
    db.commit()
    db.refresh(site)

    audit_jobs = (
        db.query(models.AuditJob)
        .filter(models.AuditJob.sitemap_crawl_job_id == crawl_job_id)
        .order_by(models.AuditJob.created_at.asc())
        .all()
    )
    assert len(audit_jobs) == 2

    for index, audit_job in enumerate(audit_jobs):
        audit_job.status = "succeeded"
        db.add(
            models.Audit(
                user_id=state["user"].id,
                site_id=site.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                audit_type=models.AuditType.FAST,
                url=audit_job.url,
                geo_score=70 + index,
                seo_score=75 + index,
                aeo_score=65 + index,
                full_report={"recommendations": [{"category": "technical"}]},
                request_id=audit_job.request_id,
            )
        )
    db.commit()

    asyncio.run(
        sitemap_crawler_service.record_page_outcome(
            db=db,
            crawl_job_id=crawl_job_id,
            success=True,
            consumed_credit_cost=1,
        )
    )
    asyncio.run(
        sitemap_crawler_service.record_page_outcome(
            db=db,
            crawl_job_id=crawl_job_id,
            success=True,
            consumed_credit_cost=1,
        )
    )

    status_response = client.get(f"/api/v1/sitemap-crawl/{crawl_job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    report_response = client.get(f"/api/v1/sitemap-crawl/{crawl_job_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()["report"]
    assert report["aggregated_scores"]["site_health"] is not None
    assert report["score_distribution"]["60_79"] >= 1
    assert report["top_issues"] == [{"category": "technical", "count": 2}]
    assert report["top_issues"][0]["category"] == "technical"


def test_get_latest_sitemap_crawl_returns_most_recent_job(embed_client) -> None:
    client, db, set_context, state, _fake_redis = embed_client
    user, _workspace, project = set_context()

    now = datetime.now(timezone.utc)
    older_job = models.SitemapCrawlJob(
        id=str(uuid4()),
        project_id=project.id,
        user_id=user.id,
        sitemap_url="https://acme.test/sitemap-old.xml",
        status="completed",
        total_urls=5,
        completed_urls=5,
        failed_urls=0,
        credits_consumed=5,
        created_at=now - timedelta(hours=1),
        completed_at=now - timedelta(minutes=30),
    )
    newer_job = models.SitemapCrawlJob(
        id=str(uuid4()),
        project_id=project.id,
        user_id=user.id,
        sitemap_url="https://acme.test/sitemap-new.xml",
        status="running",
        total_urls=10,
        completed_urls=3,
        failed_urls=0,
        credits_consumed=3,
        created_at=now,
    )
    db.add_all([older_job, newer_job])
    db.commit()

    response = client.get(f"/api/v1/projects/{project.id}/sitemap-crawl/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == newer_job.id
    assert payload["status"] == "running"
    assert payload["sitemap_url"] == "https://acme.test/sitemap-new.xml"


def test_get_latest_sitemap_crawl_returns_404_when_none_exists(embed_client) -> None:
    client, _db, set_context, _state, _fake_redis = embed_client
    _user, _workspace, project = set_context()

    response = client.get(f"/api/v1/projects/{project.id}/sitemap-crawl/latest")
    assert response.status_code == 404
    assert response.json()["detail"] == "No sitemap crawl found for this project."


def test_get_latest_sitemap_crawl_denies_other_tenant_project(embed_client) -> None:
    client, db, set_context, _state, _fake_redis = embed_client
    set_context()

    other_user = models.User(
        email="owner-b@example.com",
        hashed_password="x",
        role="user",
        credits=1000,
        notifications_enabled=True,
    )
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    other_workspace = models.Workspace(name="Other Workspace", owner_id=other_user.id)
    db.add(other_workspace)
    db.commit()
    db.refresh(other_workspace)

    other_project = models.Project(
        workspace_id=other_workspace.id,
        name="Other Project",
        domain_url="https://other.test",
    )
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    crawl_job = models.SitemapCrawlJob(
        id=str(uuid4()),
        project_id=other_project.id,
        user_id=other_user.id,
        sitemap_url="https://other.test/sitemap.xml",
        status="completed",
        total_urls=1,
        completed_urls=1,
        failed_urls=0,
        credits_consumed=1,
    )
    db.add(crawl_job)
    db.commit()

    response = client.get(f"/api/v1/projects/{other_project.id}/sitemap-crawl/latest")
    assert response.status_code == 403
