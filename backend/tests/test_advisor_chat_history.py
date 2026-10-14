"""Tests for persisted advisor-chat history — Phase 8 follow-up (F3).

Sync sqlite ``TestClient`` harness (mirrors ``test_advisor_chat_api``). The LLM
is NEVER reached: ``advisor_chat_service.answer`` is patched so no Bedrock/model
call happens. Covers:

* a chat POST persists BOTH the user turn and the assistant reply (+citations);
* a 2nd POST replays the prior persisted turns as context (``answer`` receives
  non-empty history);
* GET history returns turns in chronological order;
* cross-user / cross-audit isolation (no leakage of another user's history);
* the plan gate (402) still blocks chat + history;
* the LLM is never really invoked.
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

    owner = models.User(email="owner@example.com", hashed_password="x", role="user")
    free_user = models.User(email="free@example.com", hashed_password="x", role="user")
    other = models.User(email="other@example.com", hashed_password="x", role="user")
    db.add_all([owner, free_user, other])
    db.commit()
    for u in (owner, free_user, other):
        db.refresh(u)

    db.add_all(
        [
            _make_subscription(owner.id, "plan_standard", "owner"),
            _make_subscription(free_user.id, "plan_starter", "free"),
            _make_subscription(other.id, "plan_standard", "other"),
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
    # A second audit owned by `other` for cross-audit isolation.
    other_audit = models.Audit(
        user_id=other.id,
        geo_score=10,
        seo_score=10,
        aeo_score=10,
        url="https://other.example.com",
        full_report=report,
    )
    db.add_all([audit, other_audit])
    db.commit()
    db.refresh(audit)
    db.refresh(other_audit)

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
    return client, db, state, owner, free_user, other, audit, other_audit


def _chat_url(audit_id: int) -> str:
    return f"/api/v1/audits/{audit_id}/advisor-chat"


def _history_url(audit_id: int) -> str:
    return f"/api/v1/audits/{audit_id}/advisor-chat/history"


def test_chat_persists_user_and_assistant_turns():
    client, db, state, owner, _free, _other, audit, _oa = _build_harness()
    try:
        state["user"] = owner
        fake = {"reply": "You have no FAQ schema.", "citations": ["aeo.no_faq_schema"]}
        with patch("services.advisor_chat_service.answer", return_value=fake) as mock_answer:
            resp = client.post(_chat_url(audit.id), json={"message": "Why losing answers?"})
        assert resp.status_code == 200, resp.text
        assert mock_answer.called

        rows = (
            db.query(models.AdvisorChatMessage)
            .filter(models.AdvisorChatMessage.audit_id == audit.id)
            .order_by(models.AdvisorChatMessage.id)
            .all()
        )
        assert [r.role for r in rows] == ["user", "assistant"]
        assert rows[0].content == "Why losing answers?"
        assert rows[1].content == "You have no FAQ schema."
        assert rows[1].citations == ["aeo.no_faq_schema"]
        assert rows[0].user_id == owner.id
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_second_post_receives_prior_history_as_context():
    client, db, state, owner, _free, _other, audit, _oa = _build_harness()
    try:
        state["user"] = owner
        fake = {"reply": "First reply.", "citations": []}
        with patch("services.advisor_chat_service.answer", return_value=fake) as mock_answer:
            client.post(_chat_url(audit.id), json={"message": "First question"})
            # Second turn: the handler should load persisted history and pass it.
            client.post(_chat_url(audit.id), json={"message": "Follow-up question"})

        # Inspect the history passed into the 2nd call.
        assert mock_answer.call_count == 2
        second_call_history = mock_answer.call_args_list[1].args[2]
        assert isinstance(second_call_history, list)
        assert len(second_call_history) == 2  # prior user + assistant turn
        roles = [turn["role"] for turn in second_call_history]
        assert roles == ["user", "assistant"]
        assert second_call_history[0]["content"] == "First question"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_get_history_returns_turns_in_order():
    client, db, state, owner, _free, _other, audit, _oa = _build_harness()
    try:
        state["user"] = owner
        fake = {"reply": "An answer.", "citations": []}
        with patch("services.advisor_chat_service.answer", return_value=fake):
            client.post(_chat_url(audit.id), json={"message": "Q1"})
            client.post(_chat_url(audit.id), json={"message": "Q2"})

        resp = client.get(_history_url(audit.id))
        assert resp.status_code == 200, resp.text
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert contents == ["Q1", "An answer.", "Q2", "An answer."]
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cross_user_history_isolation():
    client, db, state, owner, _free, other, audit, _oa = _build_harness()
    try:
        # Owner builds some history.
        state["user"] = owner
        fake = {"reply": "Owner reply.", "citations": []}
        with patch("services.advisor_chat_service.answer", return_value=fake):
            client.post(_chat_url(audit.id), json={"message": "Owner secret question"})

        # `other` cannot read the owner's audit history (not the audit owner).
        state["user"] = other
        resp = client.get(_history_url(audit.id))
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cross_audit_history_isolation():
    client, db, state, owner, _free, other, audit, other_audit = _build_harness()
    try:
        state["user"] = owner
        fake = {"reply": "Owner reply.", "citations": []}
        with patch("services.advisor_chat_service.answer", return_value=fake):
            client.post(_chat_url(audit.id), json={"message": "Owner question"})

        # `other` reads THEIR OWN audit history — empty, no leakage from `audit`.
        state["user"] = other
        resp = client.get(_history_url(other_audit.id))
        assert resp.status_code == 200, resp.text
        assert resp.json()["messages"] == []
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_plan_gate_blocks_chat_and_history_without_persisting():
    client, db, state, _owner, free_user, _other, audit, _oa = _build_harness()
    try:
        # free_user owns the audit but lacks the capability → 402, no LLM, no rows.
        audit.user_id = free_user.id
        db.commit()
        state["user"] = free_user
        with patch("services.advisor_chat_service.answer") as mock_answer:
            chat_resp = client.post(_chat_url(audit.id), json={"message": "hi"})
            hist_resp = client.get(_history_url(audit.id))
        assert chat_resp.status_code == 402, chat_resp.text
        assert hist_resp.status_code == 402, hist_resp.text
        assert not mock_answer.called
        count = (
            db.query(models.AdvisorChatMessage)
            .filter(models.AdvisorChatMessage.audit_id == audit.id)
            .count()
        )
        assert count == 0
    finally:
        app.dependency_overrides.clear()
        db.close()
