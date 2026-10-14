import json
from types import SimpleNamespace

import models
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.encrypted_types as encrypted_types
from admin import get_db, router as admin_router
from auth.token_verifier import get_current_staff_user
from core.encrypted_types import reset_encryption_state
from database import Base


def _configure_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        encrypted_types,
        "settings",
        SimpleNamespace(
            OAUTH_TOKEN_ENCRYPTION_KEY="debate-trace-secret",
            JWT_SECRET_KEY="jwt-signing-secret",
            JWT_SECRET=None,
            is_production=False,
            ALLOW_LEGACY_PLAINTEXT_SECRETS=False,
        ),
    )
    reset_encryption_state()


def _build_client_with_db() -> tuple[FastAPI, TestClient, sessionmaker, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    admin_user = models.User(
        email="admin-debate@example.com",
        hashed_password="x",
        role="admin",
        credits=100,
        notifications_enabled=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    test_app = FastAPI()
    test_app.include_router(admin_router, prefix="/api/v1")
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_staff_user] = override_get_current_user
    return test_app, TestClient(test_app), db, engine


def _cleanup(test_app: FastAPI, client: TestClient, db, engine) -> None:
    client.close()
    test_app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed_trace_audit(db) -> int:
    user = models.User(
        email="trace-user@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit = models.Audit(
        user_id=user.id,
        url="https://trace.example.com",
        geo_score=81,
        seo_score=79,
        aeo_score=83,
        full_report={
            "metadata": {
                "debate": {
                    "enabled": True,
                    "pipeline_type": "delta_flow",
                }
            }
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    db.add_all(
        [
            models.DebateTrace(
                audit_id=audit.id,
                agent_role="seo_generator",
                agent_layer=1,
                pipeline_type="delta_flow",
                provider="google",
                model="gemini-2.5-pro",
                input_payload_hash="a" * 64,
                input_payload_chars=1200,
                input_summary="generator input",
                input_payload_raw=json.dumps(
                    {"system_prompt": "SEO", "user_prompt": ['{"claim_id":"seo-01"}']}
                ),
                output_raw=json.dumps(
                    {
                        "claim_ledger": [
                            {
                                "claim_id": "seo-01",
                                "domain": "seo",
                                "claim_text": "Faceted URLs are wasting crawl budget.",
                                "confidence": 0.91,
                                "recommended_action": "Block crawl traps.",
                            }
                        ]
                    }
                ),
                output_claim_ledger={
                    "claim_ledger": [
                        {
                            "claim_id": "seo-01",
                            "domain": "seo",
                            "claim_text": "Faceted URLs are wasting crawl budget.",
                            "confidence": 0.91,
                            "recommended_action": "Block crawl traps.",
                        }
                    ]
                },
                latency_ms=2100,
                cost_usd=0.12,
                prompt_tokens=1000,
                completion_tokens=400,
                status="completed",
            ),
            models.DebateTrace(
                audit_id=audit.id,
                agent_role="seo_critic",
                agent_layer=2,
                pipeline_type="delta_flow",
                provider="openai",
                model="gpt-5.4",
                input_payload_hash="b" * 64,
                input_payload_chars=900,
                input_summary="critic input",
                input_payload_raw=json.dumps(
                    {"system_prompt": "Critic", "user_prompt": ["seo-01"]}
                ),
                output_raw=json.dumps(
                    {
                        "challenge_ledger": [
                            {
                                "claim_id": "challenge-01",
                                "target_claim": "Faceted URLs are wasting crawl budget.",
                                "counter_argument": "The crawl sample is narrow.",
                                "severity": "moderate",
                                "suggested_disposition": "downgrade",
                            }
                        ]
                    }
                ),
                output_claim_ledger={
                    "challenge_ledger": [
                        {
                            "claim_id": "challenge-01",
                            "target_claim": "Faceted URLs are wasting crawl budget.",
                            "counter_argument": "The crawl sample is narrow.",
                            "severity": "moderate",
                            "suggested_disposition": "downgrade",
                        }
                    ]
                },
                latency_ms=1800,
                cost_usd=0.09,
                prompt_tokens=800,
                completion_tokens=300,
                status="completed",
            ),
            models.DebateTrace(
                audit_id=audit.id,
                agent_role="consolidator",
                agent_layer=3,
                pipeline_type="delta_flow",
                provider="openai",
                model="gpt-5.4",
                input_payload_hash="c" * 64,
                input_payload_chars=1500,
                input_summary="consolidator input",
                input_payload_raw=json.dumps(
                    {"system_prompt": "Consolidator", "user_prompt": ["seo-01"]}
                ),
                output_raw=json.dumps(
                    {
                        "synthesis_reasoning": "The claim needs additional crawl evidence.",
                        "consolidated_claim_disposition": [
                            {
                                "claim_id": "seo-01",
                                "domain": "seo",
                                "disposition": "needs_manual_review",
                                "critique_reference": "seo.challenge_01",
                                "post_critique_confidence": 0.66,
                            }
                        ],
                    }
                ),
                output_claim_ledger={
                    "consolidated_claim_disposition": [
                        {
                            "claim_id": "seo-01",
                            "domain": "seo",
                            "disposition": "needs_manual_review",
                            "critique_reference": "seo.challenge_01",
                            "post_critique_confidence": 0.66,
                        }
                    ],
                    "dedup_count": 0,
                    "domain_summaries": {},
                    "cross_domain_conflicts": [],
                    "dedup_details": [],
                },
                latency_ms=2400,
                cost_usd=0.14,
                prompt_tokens=1200,
                completion_tokens=350,
                status="completed",
            ),
            models.DebateTrace(
                audit_id=audit.id,
                agent_role="global_magistrate",
                agent_layer=4,
                pipeline_type="delta_flow",
                provider="anthropic",
                model="claude-opus-4-6",
                input_payload_hash="d" * 64,
                input_payload_chars=1600,
                input_summary="magistrate input",
                input_payload_raw=json.dumps({"system_prompt": "Judge", "user_prompt": ["seo-01"]}),
                output_raw=json.dumps(
                    {"judge_summary": {"accepted_claims": 0, "unresolved_disputes": 1}}
                ),
                output_claim_ledger={
                    "judge_summary": {"accepted_claims": 0, "unresolved_disputes": 1}
                },
                latency_ms=2600,
                cost_usd=0.18,
                prompt_tokens=1400,
                completion_tokens=420,
                status="completed",
            ),
        ]
    )
    db.commit()
    return audit.id


def test_admin_debate_trace_endpoints_return_timeline_output_and_claim_journey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_encryption(monkeypatch)
    test_app, client, db, engine = _build_client_with_db()
    try:
        audit_id = _seed_trace_audit(db)

        timeline_response = client.get(f"/api/v1/admin/audits/{audit_id}/debate-trace")
        assert timeline_response.status_code == 200
        timeline_payload = timeline_response.json()
        assert timeline_payload["pipeline_type"] == "delta_flow"
        assert timeline_payload["total_agents"] == 4
        assert timeline_payload["layers"][0]["name"] == "Specialized Generation"
        assert timeline_payload["layers"][0]["traces"][0]["claim_count"] == 1

        output_response = client.get(
            f"/api/v1/admin/audits/{audit_id}/debate-trace/seo_generator/output"
        )
        assert output_response.status_code == 200
        output_payload = output_response.json()
        assert output_payload["agent_role"] == "seo_generator"
        assert output_payload["input_payload"]["system_prompt"] == "SEO"
        assert output_payload["output_claim_ledger"]["claim_ledger"][0]["claim_id"] == "seo-01"

        journey_response = client.get(
            f"/api/v1/admin/audits/{audit_id}/debate-trace/claim/seo-01/journey"
        )
        assert journey_response.status_code == 200
        journey_payload = journey_response.json()
        assert journey_payload["claim_id"] == "seo-01"
        assert journey_payload["claim_text"] == "Faceted URLs are wasting crawl budget."
        assert [step["action"] for step in journey_payload["journey"]] == [
            "generated",
            "challenged",
            "consolidated",
            "reviewed",
        ]
        assert journey_payload["journey"][1]["critique"] == "The crawl sample is narrow."
        assert journey_payload["journey"][2]["disposition"] == "needs_manual_review"
    finally:
        _cleanup(test_app, client, db, engine)


def test_delta_flow_layer_names_match_orchestrator():
    """BUG-044: debate_trace_service layer config must match debate_orchestrator naming."""
    from services.debate_trace_service import _PIPELINE_LAYER_CONFIG

    delta = _PIPELINE_LAYER_CONFIG["delta_flow"]
    assert (
        delta[2][0] == "Domain Critique"
    ), f"Layer 2 should be 'Domain Critique' but got '{delta[2][0]}'"
    assert delta[1][0] == "Specialized Generation"
    assert delta[3][0] == "Consolidation"
    assert delta[4][0] == "Global Magistrate"
