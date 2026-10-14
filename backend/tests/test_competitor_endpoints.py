import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import app, get_current_user


class _FakeDiscoveryService:
    async def discover_competitors(self, site_url: str, category: str, market: str):
        return {
            "site": "example.com",
            "category": category,
            "market": market,
            "cached": False,
            "competitors": [
                {"name": "Atlas Dental", "source": "Places", "confidence_score": 0.84},
                {"name": "City Dental", "source": "SERP", "confidence_score": 0.78},
            ],
        }


class _FakeBenchmarkService:
    def build_benchmark_table(self, *, target, competitors):
        return {
            "columns": [
                {"key": "rank", "label": "Rank", "type": "number"},
                {"key": "name", "label": "Brand", "type": "text"},
                {"key": "geo_visibility", "label": "GEO Visibility", "type": "score"},
                {"key": "aeo_score", "label": "AEO Score", "type": "score"},
                {"key": "entity_strength", "label": "Entity Strength", "type": "score"},
                {"key": "overall_score", "label": "Overall", "type": "score"},
            ],
            "rows": [
                {
                    "rank": 1,
                    "name": target["name"],
                    "is_target": True,
                    "geo_visibility": target["geo_visibility"],
                    "aeo_score": target["aeo_score"],
                    "entity_strength": target["entity_strength"],
                    "overall_score": 70.0,
                    "deltas_vs_target": {
                        "geo_visibility": 0.0,
                        "aeo_score": 0.0,
                        "entity_strength": 0.0,
                    },
                }
            ],
            "summary": {
                "target": target["name"],
                "competitor_count": len(competitors),
                "target_rank": 1,
            },
        }


def _override_user():
    return SimpleNamespace(
        id=1,
        email="user@example.com",
        role="user",
        trial_plan="plan_specialist",
        subscription=None,
    )


def test_competitor_discovery_endpoint_success(monkeypatch):
    from routers import api_router as api_module

    monkeypatch.setattr(api_module, "competitor_discovery_service", _FakeDiscoveryService())
    app.dependency_overrides[get_current_user] = _override_user

    client = TestClient(app)
    response = client.post(
        "/api/v1/competitors/discovery",
        json={"site_url": "https://example.com", "category": "dental clinic", "market": "austin"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["site"] == "example.com"
    assert len(payload["competitors"]) == 2
    assert payload["competitors"][0]["source"] == "Places"

    app.dependency_overrides.clear()


def test_competitor_discovery_endpoint_validation_error():
    app.dependency_overrides[get_current_user] = _override_user
    client = TestClient(app)

    response = client.post(
        "/api/v1/competitors/discovery",
        json={"site_url": "https://example.com", "category": "", "market": "austin"},
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_competitor_benchmark_endpoint_success(monkeypatch):
    from routers import api_router as api_module

    monkeypatch.setattr(api_module, "competitor_benchmark_service", _FakeBenchmarkService())
    app.dependency_overrides[get_current_user] = _override_user

    client = TestClient(app)
    response = client.post(
        "/api/v1/competitors/benchmark",
        json={
            "target": {
                "name": "Acme",
                "geo_visibility": 70,
                "aeo_score": 68,
                "entity_strength": 72,
            },
            "competitors": [
                {"name": "Rival", "geo_visibility": 65, "aeo_score": 64, "entity_strength": 63}
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"target": "Acme", "competitor_count": 1, "target_rank": 1}
    assert payload["rows"][0]["is_target"] is True

    app.dependency_overrides.clear()


def test_competitor_benchmark_endpoint_validation_error():
    app.dependency_overrides[get_current_user] = _override_user
    client = TestClient(app)

    response = client.post(
        "/api/v1/competitors/benchmark",
        json={
            "target": {"name": "", "geo_visibility": 70, "aeo_score": 68, "entity_strength": 72},
            "competitors": [],
        },
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_competitor_endpoints_require_authentication():
    # Force explicit auth failure regardless of runtime environment.
    from fastapi import HTTPException

    def _unauthorized_user():
        raise HTTPException(status_code=401, detail="Authorization token missing.")

    app.dependency_overrides[get_current_user] = _unauthorized_user
    client = TestClient(app)

    discovery_response = client.post(
        "/api/v1/competitors/discovery",
        json={"site_url": "https://example.com", "category": "dental clinic", "market": "austin"},
    )
    benchmark_response = client.post(
        "/api/v1/competitors/benchmark",
        json={
            "target": {
                "name": "Acme",
                "geo_visibility": 70,
                "aeo_score": 68,
                "entity_strength": 72,
            },
            "competitors": [],
        },
    )

    assert discovery_response.status_code == 401
    assert benchmark_response.status_code == 401

    app.dependency_overrides.clear()


def test_competitor_benchmark_maps_service_error_to_bad_request(monkeypatch):
    from routers import api_router as api_module

    class _ErrorBenchmarkService:
        def build_benchmark_table(self, *, target, competitors):
            raise ValueError("Missing required metrics: entity_strength")

    monkeypatch.setattr(api_module, "competitor_benchmark_service", _ErrorBenchmarkService())
    app.dependency_overrides[get_current_user] = _override_user

    client = TestClient(app)
    response = client.post(
        "/api/v1/competitors/benchmark",
        json={
            "target": {
                "name": "Acme",
                "geo_visibility": 70,
                "aeo_score": 68,
                "entity_strength": 72,
            },
            "competitors": [
                {"name": "Rival", "geo_visibility": 65, "aeo_score": 64, "entity_strength": 63}
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid competitor benchmark request."

    app.dependency_overrides.clear()


from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from main import get_db


def _setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local()


def test_competitor_compare_success_with_complete_scores() -> None:
    db = _setup_db()
    user = models.User(
        email="compare-full@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
        trial_plan="plan_specialist",
    )
    other_user = models.User(
        email="compare-rival@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    owned_site = models.Site(user_id=user.id, domain="owned.com", display_name="Owned")
    competitor_site = models.Site(
        user_id=other_user.id,
        domain="competitor.com",
        display_name="Competitor",
    )
    db.add_all([owned_site, competitor_site])
    db.commit()
    db.refresh(owned_site)
    db.refresh(competitor_site)
    owned_site.competitors.append(competitor_site)

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            models.Audit(
                user_id=user.id,
                site_id=owned_site.id,
                url="https://owned.com",
                geo_score=77,
                seo_score=81,
                aeo_score=73,
                full_report={
                    "performance": {"performance_score": 66},
                    "entities": ["dentist", "bucharest"],
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best dentist in bucharest",
                                "brand_cited": False,
                                "provider_citations": [],
                            }
                        ]
                    },
                },
                created_at=now,
            ),
            models.Audit(
                user_id=other_user.id,
                site_id=competitor_site.id,
                url="https://competitor.com",
                geo_score=68,
                seo_score=72,
                aeo_score=64,
                full_report={
                    "performance": {"performance_score": 59},
                    "entities": ["dentist", "bucharest"],
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best dentist in bucharest",
                                "brand_cited": True,
                                "provider_citations": ["https://shared.com", "https://b-only.com"],
                            }
                        ]
                    },
                },
                created_at=now - timedelta(minutes=5),
            ),
        ]
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    response = client.get(
        f"/api/v1/competitors/compare?base_site_id={owned_site.id}&comp_site_id={competitor_site.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["labels"] == ["SEO", "AEO", "GEO", "Speed"]
    assert payload["site_scores"] == [81.0, 73.0, 77.0, 66.0]
    assert payload["comp_scores"] == [72.0, 64.0, 68.0, 59.0]
    assert payload["base_site"] == "owned.com"
    assert payload["comp_site"] == "competitor.com"
    assert len(payload["audit_timestamps"]) == 2
    assert payload["common_entities"] == [
        {"entity": "bucharest", "site_citations": 0, "comp_citations": 2},
        {"entity": "dentist", "site_citations": 0, "comp_citations": 2},
    ]
    assert payload["missing_answers"] == [
        {"query": "best dentist in bucharest", "competitor_citations": ["shared.com", "b-only.com"]}
    ]

    app.dependency_overrides.clear()
    db.close()


def test_competitor_compare_returns_not_found_when_one_audit_is_missing() -> None:
    db = _setup_db()
    user = models.User(
        email="compare-missing@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
        trial_plan="plan_specialist",
    )
    other_user = models.User(
        email="compare-missing-rival@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    owned_site = models.Site(user_id=user.id, domain="missing-owned.com", display_name="Owned")
    competitor_site = models.Site(
        user_id=other_user.id,
        domain="missing-competitor.com",
        display_name="Competitor",
    )
    db.add_all([owned_site, competitor_site])
    db.commit()
    db.refresh(owned_site)
    db.refresh(competitor_site)
    owned_site.competitors.append(competitor_site)

    db.add(
        models.Audit(
            user_id=user.id,
            site_id=owned_site.id,
            url="https://missing-owned.com",
            geo_score=70,
            seo_score=70,
            aeo_score=70,
            full_report={"analysis": {"performance_score": 70}},
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    response = client.get(
        f"/api/v1/competitors/compare?base_site_id={owned_site.id}&comp_site_id={competitor_site.id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No audits found for competitor site."

    app.dependency_overrides.clear()
    db.close()


def test_competitor_compare_requires_owner_or_linked_competitor_access() -> None:
    db = _setup_db()
    user = models.User(
        email="compare-access@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
        trial_plan="plan_specialist",
    )
    other_user = models.User(
        email="compare-access-rival@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    owned_site = models.Site(user_id=user.id, domain="access-owned.com", display_name="Owned")
    competitor_site = models.Site(
        user_id=other_user.id,
        domain="access-competitor.com",
        display_name="Competitor",
    )
    db.add_all([owned_site, competitor_site])
    db.commit()
    db.refresh(owned_site)
    db.refresh(competitor_site)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    response = client.get(
        f"/api/v1/competitors/compare?base_site_id={owned_site.id}&comp_site_id={competitor_site.id}"
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()
    db.close()


def test_competitor_compare_rejects_unlinked_competitor_even_with_access() -> None:
    db = _setup_db()
    user = models.User(
        email="compare-unlinked@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
        trial_plan="plan_specialist",
    )
    other_user = models.User(
        email="compare-unlinked-rival@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    base_site = models.Site(user_id=user.id, domain="base-owned.com", display_name="Base")
    access_anchor_site = models.Site(
        user_id=user.id,
        domain="access-anchor.com",
        display_name="Access Anchor",
    )
    competitor_site = models.Site(
        user_id=other_user.id,
        domain="unlinked-competitor.com",
        display_name="Competitor",
    )
    db.add_all([base_site, access_anchor_site, competitor_site])
    db.commit()
    db.refresh(base_site)
    db.refresh(access_anchor_site)
    db.refresh(competitor_site)

    # Gives user access to competitor through monitoring, without linking it to base_site.
    access_anchor_site.competitors.append(competitor_site)

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            models.Audit(
                user_id=user.id,
                site_id=base_site.id,
                url="https://base-owned.com",
                geo_score=74,
                seo_score=76,
                aeo_score=71,
                full_report={},
                created_at=now,
            ),
            models.Audit(
                user_id=other_user.id,
                site_id=competitor_site.id,
                url="https://unlinked-competitor.com",
                geo_score=69,
                seo_score=70,
                aeo_score=68,
                full_report={},
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    response = client.get(
        f"/api/v1/competitors/compare?base_site_id={base_site.id}&comp_site_id={competitor_site.id}"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Competitor is not linked to this project"

    app.dependency_overrides.clear()
    db.close()
