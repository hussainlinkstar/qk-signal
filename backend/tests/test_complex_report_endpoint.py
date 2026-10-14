import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base
from middleware import maintenance as maintenance_module


class FakeRedisClient:
    def __init__(self, queued_payloads: list[dict[str, object]], store: dict | None = None):
        self._queued_payloads = queued_payloads
        self._store = store if store is not None else {}

    async def rpush(self, key: str, value: str):
        self._queued_payloads.append(
            {
                "queue_name": key,
                "job_payload": json.loads(value),
            }
        )
        return len(self._queued_payloads)

    async def get(self, key: str):
        record = self._store.get(key)
        return record[0] if record else None

    async def setex(self, key: str, ttl, value: str):
        seconds = int(ttl.total_seconds() if hasattr(ttl, "total_seconds") else ttl)
        if seconds > 0:
            self._store[key] = (value, seconds)
        return True

    async def delete(self, key: str):
        return int(self._store.pop(key, None) is not None)

    async def close(self):
        return None

    async def aclose(self):
        return None


def _assert_single_queued_job(client: TestClient) -> dict[str, object]:
    queued_jobs = client.app.state.queued_pdf_jobs
    assert len(queued_jobs) == 1
    return queued_jobs[0]


@pytest.fixture
def client_with_report_data(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="reports@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_reports_{user.id}",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name="Report Ops", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Alpha Project",
        domain_url="https://alpha.example.com",
        target_country="US",
        language="en",
        icp_roles=["CMO", "SEO Lead"],
        usp="Evidence-backed GEO growth",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    site_a = models.Site(user_id=user.id, domain="alpha.example.com", display_name="Alpha")
    site_b = models.Site(user_id=user.id, domain="beta.example.com", display_name="Beta")
    site_c = models.Site(user_id=user.id, domain="gamma.example.com", display_name="Gamma")
    db.add_all([site_a, site_b, site_c])
    db.commit()
    db.refresh(site_a)
    db.refresh(site_b)
    db.refresh(site_c)

    now = datetime.now(timezone.utc)
    audits = [
        models.Audit(
            user_id=user.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            site_id=site_a.id,
            url="https://alpha.example.com/page-1",
            geo_score=80,
            seo_score=82,
            aeo_score=79,
            full_report={
                "metadata": {"title": "alpha"},
                "geo": {"score": 80},
                "seo": {"score": 82},
                "aeo": {"score": 79},
                "performance": {"lcp": 2.1},
                "competitors": {"count": 1},
            },
            created_at=now,
        ),
        models.Audit(
            user_id=user.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            site_id=site_a.id,
            url="https://alpha.example.com/page-2",
            geo_score=84,
            seo_score=85,
            aeo_score=83,
            full_report={
                "metadata": {"title": "alpha-older"},
                "geo": {"score": 84},
                "seo": {"score": 85},
                "aeo": {"score": 83},
            },
            created_at=now - timedelta(days=10),
        ),
        models.Audit(
            user_id=user.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            site_id=site_b.id,
            url="https://beta.example.com/page-1",
            geo_score=70,
            seo_score=71,
            aeo_score=72,
            full_report={
                "metadata": {"title": "beta"},
                "geo": {"score": 70},
                "seo": {"score": 71},
                "aeo": {"score": 72},
                "ai": {"summary": "beta ai"},
            },
            created_at=now - timedelta(days=40),
        ),
        models.Audit(
            user_id=user.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            site_id=site_c.id,
            url="https://gamma.example.com/page-1",
            geo_score=60,
            seo_score=61,
            aeo_score=62,
            full_report={
                "metadata": {"title": "gamma"},
                "geo": {"score": 60},
                "seo": {"score": 61},
                "aeo": {"score": 62},
            },
            created_at=now - timedelta(days=5),
        ),
    ]
    db.add_all(audits)
    db.commit()
    for audit in audits:
        db.refresh(audit)

    tracked_competitor = models.ProjectCompetitor(
        project_id=project.id,
        target_url="https://beta.example.com",
        normalized_domain="beta.example.com",
        display_name="Beta",
    )
    db.add(tracked_competitor)
    db.commit()
    db.refresh(tracked_competitor)

    db.add(
        models.ProjectCompetitorSnapshot(
            project_id=project.id,
            competitor_id=tracked_competitor.id,
            source_audit_id=audits[0].id,
            competitor_audit_id=audits[2].id,
            status="succeeded",
            geo_score=audits[2].geo_score,
            seo_score=audits[2].seo_score,
            aeo_score=audits[2].aeo_score,
            captured_at=audits[0].created_at,
        )
    )
    db.commit()

    queued_pdf_jobs: list[dict[str, object]] = []
    redis_store: dict = {}

    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(queued_pdf_jobs, redis_store),
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(queued_pdf_jobs, redis_store),
    )
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    test_client = TestClient(main.app)
    test_client.app.state.queued_pdf_jobs = queued_pdf_jobs
    test_client.app.state.redis_store = redis_store
    test_client.app.state.test_db = db
    try:
        yield test_client, audits, [site_a, site_b, site_c]
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_generate_complex_report_queues_aggregated_site_selection(client_with_report_data):
    client, audits, sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "site_id": sites[0].id,
            "report_options": {
                "mode": "aggregated",
                "sections": ["overview", "geo"],
                "competitors": [],
                "primary_color": "#0EA5E9",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["audit_count"] == 2
    assert payload["aggregate"] is None
    assert payload["download_url"] is None

    queued_job = _assert_single_queued_job(client)
    assert queued_job["queue_name"] == "pdf_jobs"
    job_payload = queued_job["job_payload"]
    assert job_payload["template_type"] == "Executive"
    assert job_payload["audit_ids"] == [audits[1].id, audits[0].id]
    assert job_payload["options"]["mode"] == "aggregated"
    assert job_payload["options"]["sections"] == ["overview", "geo"]
    assert job_payload["options"]["primary_color"] == "#0EA5E9"
    assert job_payload["export_manifest"]["template_type"] == "Executive"
    assert job_payload["export_manifest"]["hide_credit_cost"] is True


def test_generate_complex_report_persists_queued_job_status(client_with_report_data):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "competitors": [],
                "primary_color": "#0EA5E9",
            },
        },
    )

    assert response.status_code == 200
    report_id = response.json()["report_id"]

    job = (
        client.app.state.test_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == report_id)
        .first()
    )
    assert job is not None
    assert job.status == "queued"
    assert job.file_path is None

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["audit_ids"] == [audits[0].id]


def test_generate_complex_report_freezes_the_library_name_and_period(client_with_report_data):
    """SIGV2-1130: the library row's name and period are written at enqueue.

    The requested interval used to reach this endpoint, pick the audits and
    then be discarded, so the library had nothing to show in its PERIOD column
    and no name to show at all.
    """
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "date_from": "2026-04-01T00:00:00Z",
            "date_to": "2026-06-30T23:59:59Z",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "competitors": [],
            },
        },
    )

    assert response.status_code == 200
    job = (
        client.app.state.test_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == response.json()["report_id"])
        .first()
    )
    assert job is not None
    assert job.name == "Executive report - 1 Apr 2026 to 30 Jun 2026"
    assert job.period_start is not None and job.period_start.year == 2026
    assert job.period_end is not None and job.period_end.month == 6


def test_generate_complex_report_without_a_period_names_from_the_generation_date(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "competitors": [],
            },
        },
    )

    assert response.status_code == 200
    job = (
        client.app.state.test_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == response.json()["report_id"])
        .first()
    )
    assert job is not None
    # No interval was requested, so the row records none and the name says so
    # rather than borrowing the span of the audits that happened to be picked.
    assert job.period_start is None
    assert job.period_end is None
    assert job.name is not None
    assert job.name.startswith("Executive report - all time, ")


def test_generate_complex_report_project_export_uses_selected_audit_history_without_explicit_site_id(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo", "seo", "aeo"],
                "report_kind": "project",
                "branding_mode": "platform",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["audit_count"] == 2

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["export_manifest"]["report_kind"] == "project"
    assert queued_job["audit_ids"] == [audits[1].id, audits[0].id]


def test_generate_complex_report_project_export_honors_custom_range(client_with_report_data):
    client, audits, _sites = client_with_report_data
    latest_created_at = audits[0].created_at
    assert latest_created_at is not None

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "date_from": (latest_created_at - timedelta(days=2)).isoformat(),
            "date_to": latest_created_at.isoformat(),
            "report_options": {
                "mode": "aggregated",
                "sections": ["overview", "geo", "seo", "aeo"],
                "report_kind": "project",
                "branding_mode": "platform",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["audit_count"] == 1

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["audit_ids"] == [audits[0].id]


def test_generate_complex_report_queues_comparative_primary_and_competitor_selection(
    client_with_report_data,
):
    client, audits, sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id for audit in audits],
            "template_type": "Comparative",
            "site_id": sites[0].id,
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2100-01-01T00:00:00Z",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [sites[1].id],
                "primary_color": "#112233",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["audit_count"] == 3

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["template_type"] == "Comparative"
    assert queued_job["primary_audit_id"] == audits[0].id
    assert queued_job["competitor_audit_ids"] == [audits[2].id]
    assert set(queued_job["audit_ids"]) == {audits[0].id, audits[1].id, audits[2].id}
    assert queued_job["options"]["competitors"] == [sites[1].id]
    assert queued_job["options"]["primary_color"] == "#112233"


def test_generate_complex_report_comparative_supports_two_competitors(client_with_report_data):
    client, audits, sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id for audit in audits],
            "template_type": "Comparative",
            "site_id": sites[0].id,
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2100-01-01T00:00:00Z",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [sites[1].id, sites[2].id],
                "primary_color": "#0EA5E9",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["audit_count"] == 4

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["primary_audit_id"] == audits[0].id
    assert queued_job["competitor_audit_ids"] == [audits[2].id, audits[3].id]
    assert set(queued_job["audit_ids"]) == {audits[0].id, audits[1].id, audits[2].id, audits[3].id}


def test_generate_complex_report_comparative_aggregated_uses_site_pool_for_competitors(
    client_with_report_data,
):
    client, audits, sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Comparative",
            "site_id": sites[0].id,
            "report_options": {
                "mode": "aggregated",
                "sections": ["overview", "geo"],
                "competitors": [sites[1].id],
                "primary_color": "#0EA5E9",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["audit_count"] == 3

    queued_job = _assert_single_queued_job(client)["job_payload"]
    assert queued_job["template_type"] == "Comparative"
    assert queued_job["primary_audit_id"] == audits[0].id
    assert queued_job["competitor_audit_ids"] == [audits[2].id]
    assert set(queued_job["audit_ids"]) == {audits[0].id, audits[1].id, audits[2].id}
    assert queued_job["options"]["competitors"] == [sites[1].id]


def test_generate_complex_report_comparative_missing_competitor_audit_in_interval(
    client_with_report_data,
):
    client, audits, sites = client_with_report_data
    date_to = audits[0].created_at
    assert date_to is not None
    date_from = date_to - timedelta(days=30)

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id for audit in audits],
            "template_type": "Comparative",
            "site_id": sites[0].id,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [sites[1].id],
                "primary_color": "#0EA5E9",
            },
        },
    )

    assert response.status_code == 400
    assert "Missing competitor audit in selected interval" in response.json()["detail"]


def test_generate_complex_report_rejects_project_export_without_project_backing(
    client_with_report_data,
):
    client, _audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user = db.query(models.User).first()
    assert user is not None

    detached_audit = models.Audit(
        user_id=user.id,
        site_id=None,
        project_id=None,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://standalone.example.com",
        geo_score=61,
        seo_score=60,
        aeo_score=62,
        full_report={"metadata": {"title": "standalone"}},
        created_at=datetime.now(timezone.utc),
    )
    db.add(detached_audit)
    db.commit()
    db.refresh(detached_audit)

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [detached_audit.id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "report_kind": "project",
                "branding_mode": "platform",
            },
        },
    )

    assert response.status_code == 400
    assert "project-backed, site-linked audit" in response.json()["detail"]


def test_generate_complex_report_rejects_financial_export_without_project_backing(
    client_with_report_data,
):
    client, _audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user = db.query(models.User).first()
    assert user is not None

    detached_audit = models.Audit(
        user_id=user.id,
        site_id=None,
        project_id=None,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://financial.example.com",
        geo_score=61,
        seo_score=60,
        aeo_score=62,
        full_report={"metadata": {"title": "financial-standalone"}},
        created_at=datetime.now(timezone.utc),
    )
    db.add(detached_audit)
    db.commit()
    db.refresh(detached_audit)

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [detached_audit.id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "report_kind": "financial",
                "branding_mode": "platform",
            },
        },
    )

    assert response.status_code == 400
    assert "Financial report exports require a project-backed audit" in response.json()["detail"]


def test_generate_complex_report_rejects_competitor_trend_without_tracked_selection(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Comparative",
            "report_options": {
                "mode": "aggregated",
                "sections": ["overview", "geo"],
                "report_kind": "competitors",
                "branding_mode": "platform",
                "competitor_mode": "trend",
                "competitors": [],
            },
        },
    )

    assert response.status_code == 400
    assert "tracked competitor selection" in response.json()["detail"]


def test_generate_complex_report_rejects_competitor_trend_for_untracked_site(
    client_with_report_data,
):
    client, audits, sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Comparative",
            "report_options": {
                "mode": "aggregated",
                "sections": ["overview", "geo"],
                "report_kind": "competitors",
                "branding_mode": "platform",
                "competitor_mode": "trend",
                "competitors": [sites[2].id],
            },
        },
    )

    assert response.status_code == 400
    assert "Unsupported competitor site_id" in response.json()["detail"]


def test_generate_complex_report_option_validations(client_with_report_data):
    client, audits, _sites = client_with_report_data

    invalid_color = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "competitors": [],
                "primary_color": "blue",
            },
        },
    )
    assert invalid_color.status_code == 422

    too_many_competitors = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id for audit in audits],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "competitors": [1, 2, 3, 4],
                "primary_color": "#123456",
            },
        },
    )
    assert too_many_competitors.status_code == 422


def test_generate_complex_report_uses_persisted_branding_defaults_in_queue_payload(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data

    branding_response = client.put(
        "/api/v1/users/me/branding",
        json={
            "company_name": "Persisted Co",
            "primary_color": "#123456",
            "secondary_color": "#654321",
        },
    )
    assert branding_response.status_code == 200

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [],
            },
        },
    )

    assert response.status_code == 200
    queued_job = _assert_single_queued_job(client)["job_payload"]
    branding = queued_job["branding_config"]
    assert branding["company_name"] == "Persisted Co"
    assert branding["primary_color"] == "#123456"
    assert branding["secondary_color"] == "#654321"


def _set_user_plan(db, user_id: int, plan_type: str) -> None:
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user_id).first()
    )
    subscription.plan_type = plan_type
    db.commit()


def test_generate_complex_report_denies_competitor_export_after_downgrade(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user_id = audits[0].user_id
    _set_user_plan(db, user_id, "plan_starter")

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Comparative",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [],
            },
        },
    )

    assert response.status_code == 402
    assert response.json()["detail"] == (
        "Battle PDF reports are available on plans with competitor analysis."
    )
    assert client.app.state.queued_pdf_jobs == []
    assert (
        db.query(models.ComplexReportJob).filter(models.ComplexReportJob.user_id == user_id).count()
        == 0
    )


def test_generate_complex_report_enqueue_persists_export_manifest(client_with_report_data):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audits[0].id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview", "geo"],
                "competitors": [],
            },
        },
    )
    assert response.status_code == 200
    report_id = response.json()["report_id"]

    job = db.query(models.ComplexReportJob).filter(models.ComplexReportJob.id == report_id).one()
    queued_manifest = client.app.state.queued_pdf_jobs[0]["job_payload"]["export_manifest"]
    assert job.export_manifest == queued_manifest
    assert job.export_manifest["report_kind"] == "executive"


def test_white_label_denied_request_leaves_no_phantom_job(client_with_report_data):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user_id = audits[0].user_id

    response = client.post(
        "/api/v1/reports/white-label/pdf",
        json={"audit_id": audits[0].id, "report_type": "whitelabel"},
    )

    assert response.status_code == 402
    assert response.json()["detail"] == (
        "White-label PDF reports are available on plans with PDF white-label access."
    )
    assert (
        db.query(models.ComplexReportJob).filter(models.ComplexReportJob.user_id == user_id).count()
        == 0
    )


def test_download_complex_report_denies_after_downgrade(client_with_report_data, monkeypatch):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user_id = audits[0].user_id

    job = models.ComplexReportJob(
        id="battle-report-1",
        user_id=user_id,
        status="succeeded",
        file_path="local://reports/battle.pdf",
        completed_at=datetime.now(timezone.utc),
        export_manifest={
            "report_kind": "competitors",
            "branding_mode": "platform",
            "render_report_type": "battle",
        },
    )
    db.add(job)
    db.commit()

    from unittest.mock import MagicMock

    mock_gcs = MagicMock()
    mock_gcs.download_file.return_value = b"%PDF-fake"
    mock_gcs.filename_from_uri.return_value = "battle.pdf"

    import routers.api_router as api_router_module

    monkeypatch.setattr(api_router_module, "get_storage_service", lambda: mock_gcs)

    # Downgrade after the artifact was legitimately rendered.
    _set_user_plan(db, user_id, "plan_starter")

    denied = client.get("/api/v1/reports/complex/battle-report-1/download")
    assert denied.status_code == 402
    assert denied.json()["detail"] == (
        "Battle PDF reports are available on plans with competitor analysis."
    )
    mock_gcs.download_file.assert_not_called()

    # Entitled plan can still download the same artifact.
    _set_user_plan(db, user_id, "plan_specialist")
    allowed = client.get("/api/v1/reports/complex/battle-report-1/download")
    assert allowed.status_code == 200
    assert allowed.content == b"%PDF-fake"


def test_complex_report_status_and_download_return_404_for_foreign_user(
    client_with_report_data,
):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    owner_id = audits[0].user_id

    other_user = models.User(
        email="foreign@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        notifications_enabled=True,
    )
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    job = models.ComplexReportJob(
        id="foreign-job-1",
        user_id=owner_id,
        status="succeeded",
        file_path="local://reports/x.pdf",
        export_manifest={"report_kind": "standard"},
    )
    db.add(job)
    db.commit()

    main.app.dependency_overrides[main.get_current_user] = lambda: other_user
    try:
        status_response = client.get("/api/v1/reports/complex/foreign-job-1/status")
        download_response = client.get("/api/v1/reports/complex/foreign-job-1/download")
    finally:
        main.app.dependency_overrides[main.get_current_user] = lambda: db.query(models.User).get(
            owner_id
        )

    assert status_response.status_code == 404
    assert download_response.status_code == 404


def test_white_label_project_kind_leaves_no_phantom_job(client_with_report_data):
    """A rejected project-kind white-label request must not persist a
    permanently queued ComplexReportJob row (pre-existing phantom)."""
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    user_id = audits[0].user_id

    response = client.post(
        "/api/v1/reports/white-label/pdf",
        json={"audit_id": audits[0].id, "report_kind": "project"},
    )

    assert response.status_code == 400
    assert (
        db.query(models.ComplexReportJob).filter(models.ComplexReportJob.user_id == user_id).count()
        == 0
    )


def _complex_report_request(audit_id: int, **options):
    return {
        "audit_ids": [audit_id],
        "template_type": "Executive",
        "report_options": options or {"sections": ["overview", "geo"]},
    }


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_generate_complex_report_accepts_new_report_kinds(client_with_report_data, kind):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id, report_kind=kind),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    queued_job = _assert_single_queued_job(client)
    assert queued_job["job_payload"]["export_manifest"]["report_kind"] == kind
    job_row = (
        client.app.state.test_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == response.json()["report_id"])
        .one()
    )
    assert job_row.export_manifest["report_kind"] == kind


def test_generate_complex_report_rejects_unknown_report_kind(client_with_report_data):
    client, audits, _sites = client_with_report_data

    response = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id, report_kind="aiox"),
    )

    assert response.status_code == 422
    assert not client.app.state.queued_pdf_jobs


def test_generate_complex_report_idempotent_within_window(client_with_report_data):
    client, audits, _sites = client_with_report_data
    body = _complex_report_request(audits[0].id, report_kind="aio")

    first = client.post("/api/v1/reports/generate-complex", json=body)
    second = client.post("/api/v1/reports/generate-complex", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["report_id"] == first.json()["report_id"]
    assert len(client.app.state.queued_pdf_jobs) == 1
    assert (
        client.app.state.test_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.user_id == audits[0].user_id)
        .count()
        == 1
    )


def test_generate_complex_report_new_job_after_window(client_with_report_data):
    client, audits, _sites = client_with_report_data
    body = _complex_report_request(audits[0].id, report_kind="seo")

    first = client.post("/api/v1/reports/generate-complex", json=body)
    assert first.status_code == 200

    # The stored key carried the configured TTL; simulate the window lapsing.
    assert any(key.startswith("complex_report_idem:") for key in client.app.state.redis_store)
    client.app.state.redis_store.clear()

    second = client.post("/api/v1/reports/generate-complex", json=body)
    assert second.status_code == 200
    assert second.json()["report_id"] != first.json()["report_id"]
    assert len(client.app.state.queued_pdf_jobs) == 2


def test_generate_complex_report_idempotency_uses_configured_window(
    client_with_report_data,
):
    from routers import api_router as api_router_module

    client, audits, _sites = client_with_report_data
    response = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id),
    )
    assert response.status_code == 200
    ttls = {
        ttl
        for key, (_value, ttl) in client.app.state.redis_store.items()
        if key.startswith("complex_report_idem:")
    }
    assert ttls == {api_router_module.settings.COMPLEX_REPORT_IDEMPOTENCY_WINDOW_SECONDS}
    assert api_router_module.settings.COMPLEX_REPORT_IDEMPOTENCY_WINDOW_SECONDS == 60


def test_generate_complex_report_failed_job_does_not_replay(client_with_report_data):
    """A terminal-failure job inside the window must not be handed back:
    the user who upgrades after a 1019 entitlement failure gets a new job."""
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    body = _complex_report_request(audits[0].id, report_kind="aio")

    first = client.post("/api/v1/reports/generate-complex", json=body)
    assert first.status_code == 200
    job = (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == first.json()["report_id"])
        .one()
    )
    job.status = "failed"
    db.commit()

    second = client.post("/api/v1/reports/generate-complex", json=body)
    assert second.status_code == 200
    assert second.json()["report_id"] != first.json()["report_id"]
    assert len(client.app.state.queued_pdf_jobs) == 2
    # The stale key is cleared, so a third identical request replays the NEW job.
    third = client.post("/api/v1/reports/generate-complex", json=body)
    assert third.status_code == 200
    assert third.json()["report_id"] == second.json()["report_id"]
    assert len(client.app.state.queued_pdf_jobs) == 2


@pytest.mark.parametrize("status", ["queued", "running", "succeeded"])
def test_generate_complex_report_replayable_states_still_replay(client_with_report_data, status):
    client, audits, _sites = client_with_report_data
    db = client.app.state.test_db
    body = _complex_report_request(audits[0].id)

    first = client.post("/api/v1/reports/generate-complex", json=body)
    assert first.status_code == 200
    job = (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == first.json()["report_id"])
        .one()
    )
    job.status = status
    db.commit()

    second = client.post("/api/v1/reports/generate-complex", json=body)
    assert second.status_code == 200
    assert second.json()["report_id"] == first.json()["report_id"]
    assert second.json()["status"] == status
    assert len(client.app.state.queued_pdf_jobs) == 1


def test_generate_complex_report_new_job_when_fingerprint_differs(client_with_report_data):
    client, audits, _sites = client_with_report_data

    first = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id, report_kind="aio", sections=["overview", "geo"]),
    )
    second = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id, report_kind="aio", sections=["overview", "seo"]),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["report_id"] != first.json()["report_id"]
    assert len(client.app.state.queued_pdf_jobs) == 2


class _IdempotencyFlakyRedis:
    """Queue push works; idempotency get/setex fail (Redis partially down)."""

    def __init__(self, queued_payloads):
        self._queued_payloads = queued_payloads

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def rpush(self, key: str, value: str):
        self._queued_payloads.append({"queue_name": key, "job_payload": json.loads(value)})
        return len(self._queued_payloads)

    async def get(self, key: str):
        raise ConnectionError("redis down")

    async def setex(self, key: str, ttl, value: str):
        raise ConnectionError("redis down")


def test_generate_complex_report_fails_open_when_idempotency_redis_unavailable(
    client_with_report_data, monkeypatch
):
    client, audits, _sites = client_with_report_data
    flaky = _IdempotencyFlakyRedis(client.app.state.queued_pdf_jobs)
    monkeypatch.setattr("routers.api_router.get_async_redis", lambda: flaky)

    response = client.post(
        "/api/v1/reports/generate-complex",
        json=_complex_report_request(audits[0].id, report_kind="aio"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert len(client.app.state.queued_pdf_jobs) == 1
