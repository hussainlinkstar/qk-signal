"""API tests for the advisor-chat endpoint — Phase 8, Task 8.2.

Sync sqlite ``TestClient`` harness (mirrors ``test_audit_response_advisor`` /
``test_learnings_api``). The LLM is never reached: we patch
``advisor_chat_service.answer`` so no model/Bedrock call happens. Covers auth,
tenant ownership (403), tier gating (402), and the happy path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from main import app, get_current_user, get_db


def _make_subscription(user_id: int, plan_type: str, suffix: str) -> models.Subscription:
    return models.Subscription(
        user_id=user_id,
        stripe_customer_id=f"cus_{suffix}",
        plan_type=plan_type,
        status="active",
    )


def _build_harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    # Standard plan → has_advisor_recommendations True.
    owner = models.User(email="owner@example.com", hashed_password="x", role="user")
    # Starter plan → has_advisor_recommendations False.
    free_user = models.User(email="free@example.com", hashed_password="x", role="user")
    # Standard plan but does NOT own the audit (cross-tenant).
    outsider = models.User(email="outsider@example.com", hashed_password="x", role="user")
    db.add_all([owner, free_user, outsider])
    db.commit()
    for u in (owner, free_user, outsider):
        db.refresh(u)

    db.add_all(
        [
            _make_subscription(owner.id, "plan_standard", "owner"),
            _make_subscription(free_user.id, "plan_starter", "free"),
            _make_subscription(outsider.id, "plan_standard", "outsider"),
        ]
    )
    db.commit()

    report = {
        "analysis": {
            "aeo_findings": [
                {
                    "id": "aeo.no_faq_schema",
                    "description": "No FAQPage structured data on the pricing page.",
                    "severity": "critical",
                    "category": "structured_data",
                }
            ]
        },
        "geo_score": 55,
        "seo_score": 62,
        "aeo_score": 40,
    }
    audit = models.Audit(
        user_id=owner.id,
        geo_score=55,
        seo_score=62,
        aeo_score=40,
        url="https://example.com",
        full_report=report,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    state = {"user": owner}

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
    return client, db, state, owner, free_user, outsider, audit


def _url(audit_id: int) -> str:
    return f"/api/v1/audits/{audit_id}/advisor-chat"


def test_requires_authentication():
    client, db, state, owner, _free, _outsider, audit = _build_harness()
    try:
        app.dependency_overrides.pop(get_current_user, None)  # restore real auth
        resp = client.post(_url(audit.id), json={"message": "hi"})
        assert resp.status_code in (401, 403), resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_happy_path_returns_reply_and_citations():
    client, db, state, owner, _free, _outsider, audit = _build_harness()
    try:
        state["user"] = owner
        fake = {"reply": "You have no FAQ schema.", "citations": ["aeo.no_faq_schema"]}
        with patch("services.advisor_chat_service.answer", return_value=fake) as mock_answer:
            resp = client.post(
                _url(audit.id),
                json={"message": "Why am I losing AI answers?"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reply"] == fake["reply"]
        assert body["citations"] == ["aeo.no_faq_schema"]
        assert mock_answer.called
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cross_tenant_access_denied():
    client, db, state, _owner, _free, outsider, audit = _build_harness()
    try:
        state["user"] = outsider
        with patch("services.advisor_chat_service.answer") as mock_answer:
            resp = client.post(_url(audit.id), json={"message": "hi"})
        assert resp.status_code == 403, resp.text
        assert not mock_answer.called
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_plan_without_advisor_recommendations_is_payment_required():
    client, db, state, _owner, free_user, _outsider, audit = _build_harness()
    try:
        state["user"] = free_user
        # free_user does not own the audit; make them own it to isolate the
        # gating check from the ownership check.
        audit.user_id = free_user.id
        db.commit()
        with patch("services.advisor_chat_service.answer") as mock_answer:
            resp = client.post(_url(audit.id), json={"message": "hi"})
        assert resp.status_code == 402, resp.text
        assert not mock_answer.called
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_unknown_audit_returns_404():
    client, db, state, owner, _free, _outsider, _audit = _build_harness()
    try:
        state["user"] = owner
        resp = client.post(_url(999999), json={"message": "hi"})
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()
