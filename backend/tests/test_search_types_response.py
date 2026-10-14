from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.services.search_types_view import attach_search_types
from database import Base
from main import app, get_current_user, get_db
from middleware import maintenance as maintenance_module
from services.query_taxonomy import CANONICAL_SEARCH_TYPES, aggregate_search_types


def test_aggregate_search_types_returns_all_five_ids_in_order() -> None:
    measurements = {
        "brand": {"score": 80, "answer_ratio": {"present": 4, "measured": 5}},
        "category": {"score": 40, "answer_ratio": None},
        "problem": {"score": 55, "answer_ratio": None},
        "feature": {"score": 70, "answer_ratio": None},
        "comparison": {"score": 30, "answer_ratio": None},
    }

    result = aggregate_search_types(measurements=measurements)

    assert [entry["id"] for entry in result] == CANONICAL_SEARCH_TYPES
    by_id = {entry["id"]: entry for entry in result}
    assert by_id["brand"]["score"] == 80
    assert by_id["brand"]["answer_ratio"] == {"present": 4, "measured": 5}
    assert by_id["category"]["score"] == 40
    assert by_id["problem"]["score"] == 55
    assert by_id["feature"]["score"] == 70
    assert by_id["comparison"]["score"] == 30


def test_aggregate_search_types_flags_only_comparison_as_premium() -> None:
    result = aggregate_search_types(measurements={"feature": {"score": 50}})
    by_id = {entry["id"]: entry for entry in result}
    assert by_id["comparison"]["premium"] is True
    for non_premium in ("brand", "category", "problem", "feature"):
        assert by_id[non_premium]["premium"] is False


def test_aggregate_search_types_yields_null_scores_when_no_data() -> None:
    result = aggregate_search_types(measurements={})
    assert len(result) == 5
    for entry in result:
        assert entry["id"] in CANONICAL_SEARCH_TYPES
        assert entry["score"] is None
        assert entry["answer_ratio"] is None
        assert entry["source"] == "unmeasured"
        assert entry["trend"] is None
        assert isinstance(entry["insight"], str) and entry["insight"]
        assert isinstance(entry["label"], str) and entry["label"]


def test_aggregate_search_types_handles_malformed_measurements() -> None:
    # Must never raise on garbage input.
    for bad in (None, [], "nope", 42, {"brand": "broken"}):
        result = aggregate_search_types(measurements=bad)
        assert [entry["id"] for entry in result] == CANONICAL_SEARCH_TYPES


def test_attach_search_types_is_idempotent_and_guarded() -> None:
    report = {"scores": {"aeo": 40, "geo": 60, "seo": 70}}
    measurements = {"brand": {"score": 61, "answer_ratio": {"present": 3, "measured": 4}}}
    first = attach_search_types(report, measurements=measurements)["metadata"]["search_types"]
    second = attach_search_types(report, measurements=measurements)["metadata"]["search_types"]
    assert first == second
    assert len(first) == 5

    # Guarded against non-dict reports.
    assert attach_search_types(None) is None
    assert attach_search_types("nope") == "nope"


def test_attach_search_types_never_derives_a_score_from_the_report() -> None:
    # The report carries every field the retired heuristic used to read.
    report = {
        "scores": {"seo": 70, "geo": 60, "aeo": 40},
        "metadata": {
            "entity_analysis": {"brand_trust_score": 80},
            "geo_signals": {"topical_depth_score": 55, "competitor_overlap_score": 30},
        },
    }

    search_types = attach_search_types(report)["metadata"]["search_types"]

    assert all(entry["score"] is None for entry in search_types)
    assert all(entry["source"] == "unmeasured" for entry in search_types)


def test_audit_response_exposes_search_types_in_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="searchtypes@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit = models.Audit(
        user_id=user.id,
        url="https://searchtypes.example.com/",
        geo_score=60,
        seo_score=70,
        aeo_score=40,
        full_report={
            "analysis": {
                "seo_score": 70,
                "geo_score": 60,
                "aeo_score": 40,
                "summary": "search types target",
                "entity_analysis": {"brand_trust_score": 80},
                "geo_signals": {"topical_depth_score": 55, "competitor_overlap_score": 30},
            },
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
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
    original_get_maintenance_state = maintenance_module._get_maintenance_state
    maintenance_module._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }

    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/audits/{audit.id}")

        assert response.status_code == 200
        payload = response.json()
        search_types = payload["full_report"]["metadata"]["search_types"]
        assert [entry["id"] for entry in search_types] == CANONICAL_SEARCH_TYPES
        by_id = {entry["id"]: entry for entry in search_types}
        assert by_id["comparison"]["premium"] is True
        # The audit has no project and therefore no visibility runs, so every
        # type reports the unmeasured state rather than an estimate taken off
        # the audit's own sub-scores (SIGV2-1105).
        assert by_id["brand"]["score"] is None
        assert by_id["brand"]["source"] == "unmeasured"
        assert by_id["brand"]["answer_ratio"] is None
    finally:
        maintenance_module._get_maintenance_state = original_get_maintenance_state
        app.dependency_overrides.clear()
        db.close()
