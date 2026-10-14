import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from main import app, get_current_user, get_db
from services.competitors.benchmark_service import CompetitorBenchmarkService


def _setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local()


def _seed_users_and_sites(db):
    user = models.User(
        email="semantic-owner@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    other_user = models.User(
        email="semantic-rival@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add_all([user, other_user])
    db.commit()
    db.refresh(user)
    db.refresh(other_user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_semantic_owner",
            stripe_subscription_id="sub_semantic_owner",
            plan_type="plan_specialist",
            status="active",
            cancel_at_period_end=False,
        )
    )
    db.commit()

    base_site = models.Site(user_id=user.id, domain="base-semantic.com", display_name="Base")
    comp_site = models.Site(user_id=other_user.id, domain="comp-semantic.com", display_name="Comp")
    db.add_all([base_site, comp_site])
    db.commit()
    db.refresh(base_site)
    db.refresh(comp_site)
    base_site.competitors.append(comp_site)
    db.commit()

    return user, base_site, comp_site


def test_compare_semantic_footprint_happy_path_sorted_by_importance():
    db = _setup_db()
    _, base_site, comp_site = _seed_users_and_sites(db)
    service = CompetitorBenchmarkService()
    now = datetime.now(timezone.utc)

    db.add_all(
        [
            models.Audit(
                user_id=base_site.user_id,
                site_id=base_site.id,
                url="https://base-semantic.com",
                geo_score=70,
                seo_score=70,
                aeo_score=70,
                full_report={
                    "entities": ["CRM"],
                    "aeo": {"answer_relevance": 40},
                    "geo_visibility": {
                        "results": [
                            {"query": "crm software", "brand_cited": True, "answer_relevance": 45}
                        ]
                    },
                },
                created_at=now,
            ),
            models.Audit(
                user_id=comp_site.user_id,
                site_id=comp_site.id,
                url="https://comp-semantic.com",
                geo_score=80,
                seo_score=80,
                aeo_score=80,
                full_report={
                    "entities": [
                        {"name": "AI CRM", "relevance": 0.9},
                        {"name": "Lead Nurturing", "relevance": 0.6},
                    ],
                    "aeo": {"answer_relevance": 88},
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best ai crm for saas",
                                "brand_cited": True,
                                "answer_relevance": 90,
                            },
                            {
                                "query": "lead nurturing strategies",
                                "brand_cited": False,
                                "answer_relevance_score": 70,
                            },
                        ]
                    },
                },
                created_at=now,
            ),
            models.Audit(
                user_id=comp_site.user_id,
                site_id=comp_site.id,
                url="https://comp-semantic.com/history",
                geo_score=79,
                seo_score=78,
                aeo_score=79,
                full_report={
                    "analysis": {"entities": [{"entity": "AI CRM", "score": 0.8}]},
                    "aeo": {"answer_relevance": 82},
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "ai crm examples",
                                "brand_cited": True,
                                "answer_relevance": 85,
                            }
                        ]
                    },
                },
                created_at=now,
            ),
        ]
    )
    db.commit()

    payload = service.compare_semantic_footprint(
        site_id_1=base_site.id, site_id_2=comp_site.id, db=db
    )

    assert payload["base_site_id"] == base_site.id
    assert payload["comp_site_id"] == comp_site.id
    assert [item["entity"] for item in payload["missing_entities"]] == ["AI CRM", "Lead Nurturing"]
    assert (
        payload["missing_entities"][0]["importance"]["ai_importance"]
        >= payload["missing_entities"][1]["importance"]["ai_importance"]
    )
    assert payload["missing_entities"][0]["evidence_queries"] == [
        "ai crm examples",
        "best ai crm for saas",
    ]

    db.close()


def test_compare_semantic_footprint_raises_when_missing_audits():
    db = _setup_db()
    _, base_site, comp_site = _seed_users_and_sites(db)
    service = CompetitorBenchmarkService()

    with pytest.raises(ValueError, match="No audits found for base site"):
        service.compare_semantic_footprint(site_id_1=base_site.id, site_id_2=comp_site.id, db=db)

    db.add(
        models.Audit(
            user_id=base_site.user_id,
            site_id=base_site.id,
            url="https://base-semantic.com",
            geo_score=60,
            seo_score=60,
            aeo_score=60,
            full_report={"entities": ["crm"]},
        )
    )
    db.commit()

    with pytest.raises(ValueError, match="No audits found for competitor site"):
        service.compare_semantic_footprint(site_id_1=base_site.id, site_id_2=comp_site.id, db=db)

    db.close()


def test_compare_semantic_footprint_returns_empty_list_when_no_gap():
    db = _setup_db()
    _, base_site, comp_site = _seed_users_and_sites(db)
    service = CompetitorBenchmarkService()

    db.add_all(
        [
            models.Audit(
                user_id=base_site.user_id,
                site_id=base_site.id,
                url="https://base-semantic.com",
                geo_score=60,
                seo_score=60,
                aeo_score=60,
                full_report={"entities": ["crm", "automation"]},
            ),
            models.Audit(
                user_id=comp_site.user_id,
                site_id=comp_site.id,
                url="https://comp-semantic.com",
                geo_score=65,
                seo_score=65,
                aeo_score=65,
                full_report={"entities": ["crm"]},
            ),
        ]
    )
    db.commit()

    payload = service.compare_semantic_footprint(
        site_id_1=base_site.id, site_id_2=comp_site.id, db=db
    )

    assert payload["missing_entities"] == []
    db.close()


def test_compare_semantic_footprint_handles_incomplete_full_report():
    db = _setup_db()
    _, base_site, comp_site = _seed_users_and_sites(db)
    service = CompetitorBenchmarkService()

    db.add_all(
        [
            models.Audit(
                user_id=base_site.user_id,
                site_id=base_site.id,
                url="https://base-semantic.com",
                geo_score=55,
                seo_score=55,
                aeo_score=55,
                full_report={"analysis": {"entities": []}},
            ),
            models.Audit(
                user_id=comp_site.user_id,
                site_id=comp_site.id,
                url="https://comp-semantic.com",
                geo_score=75,
                seo_score=75,
                aeo_score=75,
                full_report={
                    "entities": [{"label": "Knowledge Graph"}],
                    "geo_visibility": {
                        "results": [{"query": "knowledge graph seo", "brand_cited": True}]
                    },
                },
            ),
        ]
    )
    db.commit()

    payload = service.compare_semantic_footprint(
        site_id_1=base_site.id, site_id_2=comp_site.id, db=db
    )

    assert len(payload["missing_entities"]) == 1
    assert payload["missing_entities"][0]["entity"] == "Knowledge Graph"
    assert payload["missing_entities"][0]["importance"]["avg_answer_relevance"] == 0.0

    db.close()


def test_semantic_gap_endpoint_returns_payload():
    db = _setup_db()
    user, base_site, comp_site = _seed_users_and_sites(db)

    db.add_all(
        [
            models.Audit(
                user_id=base_site.user_id,
                site_id=base_site.id,
                url="https://base-semantic.com",
                geo_score=60,
                seo_score=60,
                aeo_score=60,
                full_report={"entities": ["crm"]},
            ),
            models.Audit(
                user_id=comp_site.user_id,
                site_id=comp_site.id,
                url="https://comp-semantic.com",
                geo_score=80,
                seo_score=80,
                aeo_score=80,
                full_report={
                    "entities": [{"name": "entity gap", "relevance": 0.6}],
                    "geo_visibility": {
                        "results": [{"query": "entity gap query", "brand_cited": True}]
                    },
                },
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
        f"/api/v1/competitors/semantic-gap?base_site_id={base_site.id}&comp_site_id={comp_site.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_site_id"] == base_site.id
    assert payload["missing_entities"][0]["entity"] == "entity gap"

    app.dependency_overrides.clear()
    db.close()
