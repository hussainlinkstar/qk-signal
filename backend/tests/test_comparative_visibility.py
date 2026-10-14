"""Tests for comparative (brand vs competitor) visibility features."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.project_visibility_service import ProjectVisibilityService

try:
    from main import app, get_current_user, get_db
except Exception:
    app = None
    get_current_user = None
    get_db = None


# ── Helpers ───────────────────────────────────────────────────────────────


# SIGV2-1216: Executive is the default because its roster is the only one that
# contains every offered engine, so these tests stay about comparative
# mechanics (averaging, Share of Voice, freshness) rather than about which
# engines a plan measures. The fixtures record their cells on ``google``, and
# an engine outside the project's plan roster is no longer counted by any
# aggregate, so on Specialist they would have been measuring the filter instead
# of the maths. The tests that are genuinely about a plan still name theirs.
def _build_context(plan_type: str = "plan_executive"):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email=f"comp-vis-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    sub = models.Subscription(
        user_id=user.id,
        stripe_customer_id=f"cus_{plan_type}",
        stripe_subscription_id=f"sub_{plan_type}",
        plan_type=plan_type,
        status="active",
    )
    db.add(sub)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Comp Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Brand Project",
        domain_url="brand.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return db, user, project


def _add_competitor(db, project, domain, display_name):
    comp = models.ProjectCompetitor(
        project_id=project.id,
        target_url=f"https://{domain}",
        normalized_domain=domain,
        display_name=display_name,
    )
    db.add(comp)
    db.commit()
    return comp


def _add_query(db, project, text, providers=None):
    q = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text=text,
        query_type="aeo",
        providers=providers or ["google", "openai"],
        is_active=True,
    )
    db.add(q)
    db.commit()
    return q


def _add_batch(db, project_id, topic, provider, target_domain, score, *, days_ago=0):
    batch = models.VisibilityRunBatch(
        project_id=project_id,
        topic=topic,
        provider=provider,
        target_domain=target_domain,
        schedule_key=f"{project_id}:{topic}:{provider}:{target_domain}",
        status="succeeded",
        score=score,
        started_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        completed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(batch)
    db.commit()
    return batch


# ── build_comparative_summary tests ──────────────────────────────────────


class TestBuildComparativeSummary:
    def test_includes_primary_and_competitors(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Competitor 1")
        _add_competitor(db, project, "comp2.example", "Competitor 2")
        _add_query(db, project, "best seo tool")

        _add_batch(db, project.id, "best seo tool", "google", "brand.example", 75.0)
        _add_batch(db, project.id, "best seo tool", "google", "comp1.example", 45.0)
        _add_batch(db, project.id, "best seo tool", "google", "comp2.example", 30.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        assert "brand.example" in result["domains"]
        assert "comp1.example" in result["domains"]
        assert "comp2.example" in result["domains"]
        assert result["domains"]["brand.example"]["is_primary"] is True
        assert result["domains"]["comp1.example"]["is_primary"] is False

    def test_no_competitors_returns_primary_only(self):
        db, user, project = _build_context()
        _add_query(db, project, "best seo tool")
        _add_batch(db, project.id, "best seo tool", "google", "brand.example", 80.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        assert len(result["domains"]) == 1
        assert "brand.example" in result["domains"]

    def test_no_queries_returns_empty(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp")

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        assert result["domains"] == {}

    def test_provider_scores_averaged(self):
        db, user, project = _build_context()
        _add_query(db, project, "query a")
        _add_query(db, project, "query b")
        _add_batch(db, project.id, "query a", "google", "brand.example", 60.0)
        _add_batch(db, project.id, "query b", "google", "brand.example", 80.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        google_stats = result["domains"]["brand.example"]["providers"]["google"]
        assert google_stats["visibility_score"] == 70.0  # (60+80)/2
        assert google_stats["total_checks"] == 2

    def test_existing_build_summary_unchanged(self):
        """Verify that the original build_summary still returns primary-only."""
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp")
        _add_query(db, project, "test query", providers=["google"])
        _add_batch(db, project.id, "test query", "google", "brand.example", 70.0)
        _add_batch(db, project.id, "test query", "google", "comp1.example", 50.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        summary = service.build_summary(project=project)

        # Original summary should NOT include competitor data
        assert summary["visibility_score"] is not None
        # The primary-only score should be ~70, not blended with competitor
        assert abs(summary["visibility_score"] - 70.0) < 5.0


# ── Freshness: the surface must be able to say how old the numbers are ───


class TestComparativeFreshness:
    """SIGV2-1208: a measurement surface states the age of its numbers.

    The comparative payload is the only surface fed by scheduled competitor
    cells, so each domain carries the time it was last measured and the policy
    cadence that paces it. Without that a figure from three weeks ago reads
    exactly like one from this morning.
    """

    def test_each_domain_reports_when_it_was_last_measured(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Competitor 1")
        _add_query(db, project, "best seo tool")
        _add_batch(db, project.id, "best seo tool", "google", "brand.example", 75.0, days_ago=1)
        _add_batch(db, project.id, "best seo tool", "google", "comp1.example", 45.0, days_ago=9)
        # An older competitor batch must not win: the freshest one is the age.
        _add_batch(db, project.id, "best seo tool", "google", "comp1.example", 40.0, days_ago=20)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        brand_measured = result["domains"]["brand.example"]["last_measured_at"]
        comp_measured = result["domains"]["comp1.example"]["last_measured_at"]
        assert brand_measured is not None
        assert comp_measured is not None
        brand_age = datetime.now(timezone.utc) - datetime.fromisoformat(brand_measured)
        comp_age = datetime.now(timezone.utc) - datetime.fromisoformat(comp_measured)
        assert 0 <= brand_age.total_seconds() - 86400 < 3600
        assert 0 <= comp_age.total_seconds() - 9 * 86400 < 3600

    def test_an_unmeasured_competitor_reports_no_timestamp_rather_than_now(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Competitor 1")
        _add_query(db, project, "best seo tool")
        _add_batch(db, project.id, "best seo tool", "google", "brand.example", 75.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        assert result["domains"]["comp1.example"]["last_measured_at"] is None

    def test_the_summary_carries_the_plan_competitor_cadence(self):
        from services.project_visibility_service import VISIBILITY_SWEEP_WEEKLY_SECONDS

        db, user, project = _build_context(plan_type="plan_specialist")
        _add_query(db, project, "best seo tool")
        _add_batch(db, project.id, "best seo tool", "google", "brand.example", 75.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        assert result["plan"] == "plan_specialist"
        assert result["competitor_sweep_interval_seconds"] == VISIBILITY_SWEEP_WEEKLY_SECONDS


# ── build_comparative_trends tests ───────────────────────────────────────


class TestBuildComparativeTrends:
    def test_returns_daily_series_per_domain(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp 1")
        _add_query(db, project, "test query")
        _add_batch(db, project.id, "test query", "google", "brand.example", 60.0, days_ago=2)
        _add_batch(db, project.id, "test query", "google", "brand.example", 70.0, days_ago=1)
        _add_batch(db, project.id, "test query", "google", "comp1.example", 40.0, days_ago=2)
        _add_batch(db, project.id, "test query", "google", "comp1.example", 50.0, days_ago=1)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_trends(project=project, days=30)

        assert "brand.example" in result["domains"]
        assert "comp1.example" in result["domains"]
        assert result["domains"]["brand.example"]["is_primary"] is True
        assert len(result["domains"]["brand.example"]["trend"]) >= 2
        assert len(result["domains"]["comp1.example"]["trend"]) >= 2

    def test_no_queries_returns_empty(self):
        db, user, project = _build_context()
        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_trends(project=project, days=30)
        assert result["domains"] == {}

    def test_domains_with_no_batches_included_empty(self):
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp 1")
        _add_query(db, project, "test query")
        _add_batch(db, project.id, "test query", "google", "brand.example", 80.0, days_ago=1)
        # No batches for comp1.example

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_trends(project=project, days=30)

        assert "comp1.example" in result["domains"]
        assert result["domains"]["comp1.example"]["trend"] == []


# ── Share-of-Voice tests ─────────────────────────────────────────────────


class TestShareOfVoice:
    def test_sov_calculation(self):
        """brand=5 citations, comp=3, comp2=2 → SoV=50%"""
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp 1")
        _add_competitor(db, project, "comp2.example", "Comp 2")
        _add_query(db, project, "test query")

        # Create batches with runs that have citations
        for i in range(5):
            b = _add_batch(db, project.id, "test query", "google", "brand.example", 80.0)
            run = models.VisibilityRun(
                batch_id=b.id,
                topic="test query",
                provider="google",
                target_domain="brand.example",
                prompt_template="",
                prompt="",
                raw_response="x",
                valid_citations=["https://brand.example/page"],
                score=80.0,
                status="succeeded",
                started_at=b.started_at,
                completed_at=b.completed_at,
                created_at=b.created_at,
            )
            db.add(run)
        for i in range(3):
            b = _add_batch(db, project.id, "test query", "google", "comp1.example", 50.0)
            run = models.VisibilityRun(
                batch_id=b.id,
                topic="test query",
                provider="google",
                target_domain="comp1.example",
                prompt_template="",
                prompt="",
                raw_response="x",
                valid_citations=["https://comp1.example/page"],
                score=50.0,
                status="succeeded",
                started_at=b.started_at,
                completed_at=b.completed_at,
                created_at=b.created_at,
            )
            db.add(run)
        for i in range(2):
            b = _add_batch(db, project.id, "test query", "google", "comp2.example", 30.0)
            run = models.VisibilityRun(
                batch_id=b.id,
                topic="test query",
                provider="google",
                target_domain="comp2.example",
                prompt_template="",
                prompt="",
                raw_response="x",
                valid_citations=["https://comp2.example/page"],
                score=30.0,
                status="succeeded",
                started_at=b.started_at,
                completed_at=b.completed_at,
                created_at=b.created_at,
            )
            db.add(run)
        db.commit()

        db.refresh(project)
        service = ProjectVisibilityService(db)
        summary = service.build_comparative_summary(project=project, days=30)

        # Cited counts: brand=5, comp1=3, comp2=2, total=10
        brand_cited = summary["domains"]["brand.example"]["providers"]["google"]["cited_count"]
        comp1_cited = summary["domains"]["comp1.example"]["providers"]["google"]["cited_count"]
        comp2_cited = summary["domains"]["comp2.example"]["providers"]["google"]["cited_count"]

        assert brand_cited == 5
        assert comp1_cited == 3
        assert comp2_cited == 2

    def test_batch_citing_only_other_domains_is_not_counted(self):
        """A run that cites only competitors must not count as a citation of the target."""
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp 1")
        _add_query(db, project, "test query")

        # Brand batch whose response cites only the competitor, never the brand.
        b = _add_batch(db, project.id, "test query", "google", "brand.example", 40.0)
        db.add(
            models.VisibilityRun(
                batch_id=b.id,
                topic="test query",
                provider="google",
                target_domain="brand.example",
                prompt_template="",
                prompt="",
                raw_response="x",
                valid_citations=["https://comp1.example/page", "https://other.example/x"],
                score=40.0,
                status="succeeded",
                started_at=b.started_at,
                completed_at=b.completed_at,
                created_at=b.created_at,
            )
        )
        # Competitor batch that genuinely cites the competitor.
        b2 = _add_batch(db, project.id, "test query", "google", "comp1.example", 60.0)
        db.add(
            models.VisibilityRun(
                batch_id=b2.id,
                topic="test query",
                provider="google",
                target_domain="comp1.example",
                prompt_template="",
                prompt="",
                raw_response="x",
                valid_citations=["https://comp1.example/page"],
                score=60.0,
                status="succeeded",
                started_at=b2.started_at,
                completed_at=b2.completed_at,
                created_at=b2.created_at,
            )
        )
        db.commit()

        db.refresh(project)
        service = ProjectVisibilityService(db)
        summary = service.build_comparative_summary(project=project, days=30)

        brand_cited = summary["domains"]["brand.example"]["providers"]["google"]["cited_count"]
        comp1_cited = summary["domains"]["comp1.example"]["providers"]["google"]["cited_count"]

        assert brand_cited == 0
        assert comp1_cited == 1

    def test_sov_zero_total_no_division_error(self):
        """Zero citations total → no crash."""
        db, user, project = _build_context()
        _add_competitor(db, project, "comp1.example", "Comp 1")
        _add_query(db, project, "test query")
        _add_batch(db, project.id, "test query", "google", "brand.example", 0.0)
        _add_batch(db, project.id, "test query", "google", "comp1.example", 0.0)

        db.refresh(project)
        service = ProjectVisibilityService(db)
        result = service.build_comparative_summary(project=project, days=30)

        # Should complete without division by zero
        assert "brand.example" in result["domains"]
        assert "comp1.example" in result["domains"]


# ── Endpoint tests ───────────────────────────────────────────────────────


class TestComparativeEndpoint:
    def _build_client(self, plan_type="plan_executive"):
        from fastapi.testclient import TestClient

        if app is None or get_db is None or get_current_user is None:
            pytest.skip("main app import unavailable")

        db, user, project = _build_context(plan_type=plan_type)

        def override_get_db():
            try:
                yield db
            finally:
                pass

        def override_get_current_user():
            return user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        return TestClient(app), db, user, project

    def test_returns_200_for_plan_specialist(self):
        client, db, user, project = self._build_client("plan_specialist")
        _add_query(db, project, "test query")
        _add_batch(db, project.id, "test query", "google", "brand.example", 70.0)
        db.refresh(project)

        resp = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-comparative?days=30"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "domains" in data
        app.dependency_overrides.clear()

    def test_exposes_the_freshness_of_the_competitor_rows(self):
        from services.project_visibility_service import VISIBILITY_SWEEP_WEEKLY_SECONDS

        # Executive, because the cells are recorded on an engine Specialist no
        # longer measures (SIGV2-1216) and this test is about freshness, not
        # about the roster. The Specialist competitor cadence is asserted by
        # ``test_the_summary_carries_the_plan_competitor_cadence``.
        client, db, user, project = self._build_client("plan_executive")
        _add_competitor(db, project, "comp1.example", "Competitor 1")
        _add_query(db, project, "test query")
        _add_batch(db, project.id, "test query", "google", "brand.example", 70.0)
        _add_batch(db, project.id, "test query", "google", "comp1.example", 50.0, days_ago=9)
        db.refresh(project)

        resp = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-comparative?days=30"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["competitor_sweep_interval_seconds"] == VISIBILITY_SWEEP_WEEKLY_SECONDS
        # The header figure is the oldest-safe one: the freshest competitor
        # measurement, never the brand's own fresher run.
        competitors_measured = data["competitors_last_measured_at"]
        assert competitors_measured is not None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(competitors_measured)
        assert 0 <= age.total_seconds() - 9 * 86400 < 3600
        assert data["domains"]["comp1.example"]["last_measured_at"] == competitors_measured
        assert data["domains"]["brand.example"]["last_measured_at"] is not None
        app.dependency_overrides.clear()

    def test_returns_402_for_plan_standard(self):
        client, db, user, project = self._build_client("plan_standard")
        resp = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-comparative?days=30"
        )
        assert resp.status_code == 402
        app.dependency_overrides.clear()
