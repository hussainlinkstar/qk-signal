import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.services.entity.site_map_service import SiteMapService
from database import Base
from services.competitors.benchmark_service import CompetitorBenchmarkService
from services.site_entity_facts import SiteEntityFactService


def _setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local()


def test_replace_audit_facts_builds_rows_with_geo_aeo_signals() -> None:
    db = _setup_db()
    service = SiteEntityFactService()

    user = models.User(email="facts@example.com", hashed_password="x", role="user", credits=5)
    db.add(user)
    db.commit()
    db.refresh(user)

    site = models.Site(user_id=user.id, domain="example.com", display_name="Example")
    db.add(site)
    db.commit()
    db.refresh(site)

    audit = models.Audit(
        user_id=user.id,
        site_id=site.id,
        url="https://example.com",
        geo_score=70,
        seo_score=60,
        aeo_score=50,
        full_report={"analysis": {}},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    report = {
        "entities": [
            {"name": "OpenAI", "type": "ORG", "relevance_score": 80},
            "ChatGPT",
        ],
        "aeo": {
            "answer_excerpt": "OpenAI and ChatGPT are referenced.",
            "answer_relevance": 75,
        },
        "geo_visibility": {
            "results": [
                {"query": "openai assistants", "brand_cited": True},
                {"query": "chatgpt tools", "brand_cited": False},
            ]
        },
    }

    inserted = service.replace_audit_facts(
        db=db,
        site_id=site.id,
        audit_id=audit.id,
        report=report,
        created_at=audit.created_at,
    )
    db.commit()

    assert inserted == 2
    facts = db.query(models.SiteEntityFact).filter(models.SiteEntityFact.audit_id == audit.id).all()
    assert len(facts) == 2

    by_key = {item.entity_key: item for item in facts}
    assert by_key["openai"].entity_category == "Org"
    assert by_key["openai"].relevance_score == 80.0
    assert by_key["openai"].ai_importance is not None and by_key["openai"].ai_importance > 0

    assert by_key["chatgpt"].entity_name == "ChatGPT"
    assert by_key["chatgpt"].ai_importance is not None and by_key["chatgpt"].ai_importance > 0

    db.close()


def test_site_map_prefers_site_entity_facts() -> None:
    db = _setup_db()
    service = SiteMapService()

    user = models.User(email="mapfacts@example.com", hashed_password="x", role="user", credits=5)
    db.add(user)
    db.commit()
    db.refresh(user)

    site = models.Site(user_id=user.id, domain="example.net", display_name="Example")
    db.add(site)
    db.commit()
    db.refresh(site)

    audit = models.Audit(
        user_id=user.id,
        site_id=site.id,
        url="https://example.net",
        geo_score=1,
        seo_score=1,
        aeo_score=1,
        full_report={"entities": []},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    db.add(
        models.SiteEntityFact(
            site_id=site.id,
            audit_id=audit.id,
            entity_name="Preferred Fact",
            entity_key="preferred fact",
            entity_category="Concept",
            relevance_score=91,
            ai_importance=92,
            source="full_report.entities",
            created_at=audit.created_at,
        )
    )
    db.commit()

    payload = service.build_site_map(db=db, site_id=site.id)
    assert payload["audit_count"] == 1
    assert payload["entities"][0]["normalized_key"] == "preferred fact"
    assert payload["entities"][0]["avg_relevance_score"] == 91.0

    db.close()


def test_competitor_benchmark_entity_extraction_prefers_facts() -> None:
    audit = models.Audit(
        id=1,
        user_id=1,
        site_id=1,
        url="https://example.org",
        geo_score=0,
        seo_score=0,
        aeo_score=0,
        full_report={"entities": ["Legacy"]},
    )
    audit.entity_facts = [
        models.SiteEntityFact(entity_name="High", entity_key="high", ai_importance=99),
        models.SiteEntityFact(entity_name="Low", entity_key="low", ai_importance=10),
    ]

    entities = CompetitorBenchmarkService._extract_entities(audit)
    assert entities == ["High", "Low"]
