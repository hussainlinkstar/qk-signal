from datetime import datetime, timedelta, timezone

import models
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin import get_db
from auth.token_verifier import get_current_staff_user
from database import Base
from main import app


def _build_client_with_db() -> tuple[TestClient, sessionmaker, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    admin_user = models.User(
        email="admin-audits@example.com",
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

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_get_current_user
    return TestClient(app), db, engine


def _cleanup(client: TestClient, db, engine) -> None:
    client.close()
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed_audits(db) -> dict[str, int]:
    fallback_user = models.User(
        email="fallback-user@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    shadow_user = models.User(
        email="shadow-user@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    neutral_user = models.User(
        email="neutral-user@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add_all([fallback_user, shadow_user, neutral_user])
    db.commit()
    for user in (fallback_user, shadow_user, neutral_user):
        db.refresh(user)

    now = datetime.now(timezone.utc)
    fallback_audit = models.Audit(
        user_id=fallback_user.id,
        url="https://fallback.example.com",
        geo_score=61,
        seo_score=62,
        aeo_score=63,
        created_at=now - timedelta(hours=2),
        full_report={
            "metadata": {
                "model": "gemini-2.5-pro",
                "tier": "smart",
                "requested_tier": "deep_judgment",
                "grounding_profile": "single_track_fallback",
                "dual_track_grounding_enabled": False,
                "fallback_reason": "unified_truth_context_unavailable",
                "integrity_certificate_summary": {
                    "track_a_claim_count": 0,
                    "track_b_claim_count": 0,
                },
                "dual_track_grounding": {
                    "rollout_mode": "disabled",
                    "effective_execution_mode": "disabled",
                },
            }
        },
    )
    shadow_brand_audit = models.Audit(
        user_id=shadow_user.id,
        audit_target_type=models.AuditTargetType.BRAND,
        target_name="Acme Analytics",
        target_url=None,
        url="https://brand.example.com",
        geo_score=82,
        seo_score=80,
        aeo_score=84,
        created_at=now - timedelta(hours=1),
        full_report={
            "metadata": {
                "model": "gpt-5.4",
                "tier": "deep_judgment",
                "requested_tier": "deep_judgment",
                "grounding_profile": "shadow_dual_track",
                "dual_track_grounding_enabled": True,
                "track_a_claim_count": 3,
                "track_b_claim_count": 2,
                "dual_track_grounding": {
                    "rollout_mode": "allowlist_enabled",
                    "effective_execution_mode": "shadow",
                },
            }
        },
    )
    neutral_audit = models.Audit(
        user_id=neutral_user.id,
        url="https://neutral.example.com",
        geo_score=70,
        seo_score=71,
        aeo_score=72,
        created_at=now - timedelta(hours=3),
        full_report={
            "metadata": {
                "model": "gpt-5.4-mini",
                "tier": "fast",
                "requested_tier": "fast",
            }
        },
    )
    db.add_all([fallback_audit, shadow_brand_audit, neutral_audit])
    db.commit()
    for audit in (fallback_audit, shadow_brand_audit, neutral_audit):
        db.refresh(audit)

    return {
        "fallback_audit_id": fallback_audit.id,
        "shadow_brand_audit_id": shadow_brand_audit.id,
        "neutral_audit_id": neutral_audit.id,
    }


def test_admin_audits_list_includes_dual_track_runtime_metadata() -> None:
    client, db, engine = _build_client_with_db()
    try:
        seeded = _seed_audits(db)

        response = client.get("/api/v1/admin/audits")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 3
        assert [audit["id"] for audit in payload["audits"]] == [
            seeded["shadow_brand_audit_id"],
            seeded["fallback_audit_id"],
            seeded["neutral_audit_id"],
        ]

        brand_entry = payload["audits"][0]
        assert brand_entry["audit_target_type"] == "brand"
        assert brand_entry["target_name"] == "Acme Analytics"
        assert brand_entry["target_url"] == "https://brand.example.com"
        assert brand_entry["requested_tier"] == "deep_judgment"
        assert brand_entry["grounding_profile"] == "shadow_dual_track"
        assert brand_entry["dual_track_grounding_enabled"] is True
        assert brand_entry["track_a_claim_count"] == 3
        assert brand_entry["track_b_claim_count"] == 2
        assert brand_entry["dual_track_rollout_mode"] == "allowlist_enabled"
        assert brand_entry["dual_track_execution_mode"] == "shadow"

        detail_response = client.get(f"/api/v1/admin/audits/{seeded['fallback_audit_id']}")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["requested_tier"] == "deep_judgment"
        assert detail_payload["grounding_profile"] == "single_track_fallback"
        assert detail_payload["dual_track_grounding_enabled"] is False
        assert detail_payload["fallback_reason"] == "unified_truth_context_unavailable"
        assert detail_payload["track_a_claim_count"] == 0
        assert detail_payload["track_b_claim_count"] == 0
        assert detail_payload["dual_track_rollout_mode"] == "disabled"
        assert detail_payload["dual_track_execution_mode"] == "disabled"
    finally:
        _cleanup(client, db, engine)


def test_admin_audits_filters_grounding_profile_and_dual_track_enabled() -> None:
    client, db, engine = _build_client_with_db()
    try:
        seeded = _seed_audits(db)

        profile_response = client.get(
            "/api/v1/admin/audits",
            params={"grounding_profile": "single_track_fallback"},
        )
        assert profile_response.status_code == 200
        profile_payload = profile_response.json()
        assert profile_payload["total"] == 1
        assert [audit["id"] for audit in profile_payload["audits"]] == [seeded["fallback_audit_id"]]

        dual_track_response = client.get(
            "/api/v1/admin/audits",
            params={"dual_track_grounding_enabled": "true"},
        )
        assert dual_track_response.status_code == 200
        dual_track_payload = dual_track_response.json()
        assert dual_track_payload["total"] == 1
        assert [audit["id"] for audit in dual_track_payload["audits"]] == [
            seeded["shadow_brand_audit_id"]
        ]
    finally:
        _cleanup(client, db, engine)


def test_admin_audits_filters_fallback_reason_by_substring() -> None:
    client, db, engine = _build_client_with_db()
    try:
        seeded = _seed_audits(db)

        response = client.get(
            "/api/v1/admin/audits",
            params={"fallback_reason": "truth_context"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert [audit["id"] for audit in payload["audits"]] == [seeded["fallback_audit_id"]]
        assert payload["audits"][0]["fallback_reason"] == "unified_truth_context_unavailable"
    finally:
        _cleanup(client, db, engine)
