from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.services.advisor_view import attach_advisor_view
from database import Base
from main import app, get_current_user, get_db
from middleware import maintenance as maintenance_module


def _roi(action: dict) -> int:
    impact = {"high": 3, "medium": 2, "low": 1}.get(action.get("impact"), 2)
    effort = {"low": 1, "medium": 2, "high": 3}.get(action.get("effort"), 2)
    return impact * 10 - effort


def test_attach_advisor_view_orders_actions_by_roi() -> None:
    report = {
        "recommendations": {
            "items": [
                {
                    "action": "Rewrite long-form pillar copy across the site",
                    "estimated_effort": "high",
                    "expected_score_impact": {"seo": 2},
                    "grounded_by_findings": ["seo.thin_content"],
                    "derived_from": ["analysis.seo"],
                },
                {
                    "action": "Add FAQPage schema to the pricing page",
                    "estimated_effort": "low",
                    "expected_score_impact": {"aeo": 15},
                    "grounded_by_findings": ["aeo.no_faq_schema"],
                    "derived_from": ["analysis.answerability"],
                },
            ]
        }
    }

    result = attach_advisor_view(report)

    advisor = result["metadata"]["advisor"]
    actions = advisor["actions"]
    assert isinstance(actions, list)
    assert len(actions) >= 2
    # ROI-ordered: first action's ROI >= last action's ROI.
    assert _roi(actions[0]) >= _roi(actions[-1])
    # Highest-impact / lowest-effort win ranks first.
    assert actions[0]["action"] == "Add FAQPage schema to the pricing page"


def test_attach_advisor_view_no_suggestions_yields_empty_actions() -> None:
    report = {"analysis": {"summary": "no recommendations here"}}
    result = attach_advisor_view(report)
    assert result["metadata"]["advisor"]["actions"] == []


def test_attach_advisor_view_is_idempotent() -> None:
    report = {
        "recommendations": {
            "items": [
                {
                    "action": "Add FAQPage schema to the pricing page",
                    "estimated_effort": "low",
                    "expected_score_impact": {"aeo": 15},
                    "grounded_by_findings": ["aeo.no_faq_schema"],
                }
            ]
        }
    }
    first = attach_advisor_view(report)["metadata"]["advisor"]
    second = attach_advisor_view(report)["metadata"]["advisor"]
    assert first == second


def test_audit_response_exposes_advisor_plan_in_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="advisor@example.com",
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
        url="https://advisor.example.com/",
        geo_score=60,
        seo_score=70,
        aeo_score=40,
        full_report={
            "analysis": {
                "seo_score": 70,
                "geo_score": 60,
                "aeo_score": 40,
                "summary": "advisor target",
            },
            "suggestions": [
                {
                    "action": "Add FAQPage schema to the pricing page",
                    "estimated_effort": "low",
                    "expected_score_impact": {"aeo": 15},
                    "grounded_by_findings": ["aeo.no_faq_schema"],
                    "derived_from": ["analysis.answerability"],
                },
                {
                    "action": "Rewrite long-form pillar copy across the site",
                    "estimated_effort": "high",
                    "expected_score_impact": {"seo": 2},
                    "grounded_by_findings": ["seo.thin_content"],
                    "derived_from": ["analysis.seo"],
                },
            ],
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
        advisor = payload["full_report"]["metadata"]["advisor"]
        actions = advisor["actions"]
        assert isinstance(actions, list)
        assert len(actions) >= 1
        assert _roi(actions[0]) >= _roi(actions[-1])
    finally:
        maintenance_module._get_maintenance_state = original_get_maintenance_state
        app.dependency_overrides.clear()
        db.close()
