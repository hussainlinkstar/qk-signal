import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from unittest.mock import patch

from database import Base
from main import app, get_current_user, get_db


def _setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local()


@patch("routers.api_router.plan_validator.has_feature", return_value=True)
def test_geo_compare_endpoint_returns_gap_overlap_and_dominance(mock_has_feature) -> None:
    db = _setup_db()
    user = models.User(
        email="compare@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    site_a = models.Site(user_id=user.id, domain="alpha.com", display_name="Alpha")
    site_b = models.Site(user_id=user.id, domain="beta.com", display_name="Beta")
    db.add_all([site_a, site_b])
    db.commit()
    db.refresh(site_a)
    db.refresh(site_b)

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            models.Audit(
                user_id=user.id,
                site_id=site_a.id,
                url="https://alpha.com",
                geo_score=70,
                seo_score=60,
                aeo_score=50,
                full_report={
                    "geo": {
                        "citations": 8,
                        "citation_sources": ["https://shared.com", "https://a-only.com"],
                    },
                    "hallucination": {
                        "claims": [
                            {
                                "claim_id": "c1",
                                "claim_text": "Starter price is $99.",
                                "hallucination": True,
                                "discrepancy_type": "pricing_mismatch",
                                "severity": "high",
                            }
                        ]
                    },
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best dentist in bucharest",
                                "brand_cited": True,
                                "provider_citations": ["https://shared.com/path"],
                            }
                        ]
                    },
                },
                created_at=now - timedelta(days=1),
            ),
            models.Audit(
                user_id=user.id,
                site_id=site_b.id,
                url="https://beta.com",
                geo_score=65,
                seo_score=60,
                aeo_score=50,
                full_report={
                    "analysis": {"citation_share": {"score": 3}},
                    "hallucination": {
                        "claims": [
                            {
                                "claim_id": "c2",
                                "claim_text": "Free cancellation for all plans.",
                                "hallucination": True,
                                "discrepancy_type": "policy_mismatch",
                                "severity": "critical",
                            }
                        ]
                    },
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best dentist in bucharest",
                                "brand_cited": False,
                                "provider_citations": ["https://shared.com"],
                            },
                            {
                                "query": "how to choose a clinic",
                                "brand_cited": True,
                                "provider_citations": ["https://b-only.com"],
                            },
                        ]
                    },
                },
                created_at=now - timedelta(days=2),
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
    response = client.get(f"/api/v1/geo/compare?site_a_id={site_a.id}&site_b_id={site_b.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["citation_gap"]["site_a_citations"] == 8.0
    assert payload["citation_gap"]["site_b_citations"] == 3.0
    assert payload["source_overlap"]["domains"] == ["shared.com"]
    assert payload["high_risk_discrepancies"]["site_a_total"] == 1
    assert payload["high_risk_discrepancies"]["site_b_total"] == 1
    assert any(
        item["discrepancy_type"] == "pricing_mismatch"
        for item in payload["high_risk_discrepancies"]["items"]
    )
    assert any(
        item["category"] == "local" and item["dominant_site"] == "alpha.com"
        for item in payload["keyword_dominance"]
    )

    app.dependency_overrides.clear()
    db.close()


@patch("routers.api_router.plan_validator.has_feature", return_value=True)
def test_geo_compare_allows_linked_competitor_site(mock_has_feature) -> None:
    db = _setup_db()
    user = models.User(
        email="compare2@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    other_user = models.User(
        email="other@example.com",
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
    db.commit()

    db.add(
        models.Audit(
            user_id=other_user.id,
            site_id=competitor_site.id,
            url="https://competitor.com",
            geo_score=55,
            seo_score=50,
            aeo_score=45,
            full_report={"geo": {"citations": 4}},
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
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
        f"/api/v1/geo/compare?site_a_id={owned_site.id}&site_b_id={competitor_site.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["site_a"]["audit_count"] == 0
    assert payload["site_b"]["audit_count"] == 1
    assert payload["citation_gap"]["site_b_citations"] > 0

    app.dependency_overrides.clear()
    db.close()


@patch("routers.api_router.plan_validator.has_feature", return_value=True)
def test_geo_compare_rejects_unlinked_competitor_even_if_audit_payload_mentions_it(
    mock_has_feature,
) -> None:
    db = _setup_db()
    user = models.User(
        email="compare3@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    other_user = models.User(
        email="other2@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    owned_site = models.Site(user_id=user.id, domain="owned2.com", display_name="Owned2")
    competitor_site = models.Site(
        user_id=other_user.id,
        domain="competitor2.com",
        display_name="Competitor2",
    )
    db.add_all([owned_site, competitor_site])
    db.commit()
    db.refresh(owned_site)
    db.refresh(competitor_site)

    db.add(
        models.Audit(
            user_id=user.id,
            site_id=owned_site.id,
            url="https://owned2.com",
            geo_score=70,
            seo_score=60,
            aeo_score=50,
            full_report={
                "competitors": [{"name": "competitor2.com"}],
                "geo": {"citations": 1},
            },
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
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
        f"/api/v1/geo/compare?site_a_id={owned_site.id}&site_b_id={competitor_site.id}"
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()
    db.close()
