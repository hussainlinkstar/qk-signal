import models
import routers.admin_observability as admin_observability
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from datetime import datetime, timedelta, timezone


def _build_client_with_db(admin_user: models.User):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
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

    app = FastAPI()
    app.include_router(admin_observability.router, prefix="/api/v1")
    app.dependency_overrides[admin_observability.get_db] = override_get_db
    app.dependency_overrides[admin_observability.get_current_staff_user] = override_get_current_user
    return TestClient(app), db


def test_admin_observability_dual_track_snapshot_reports_canonical_runtime(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-observability@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setattr(
        admin_observability,
        "_collect_dual_track_grounding_metrics",
        lambda: {
            "claims_observed": 0,
            "reason_codes_observed": 0,
            "fallbacks_observed": 0,
            "claim_dispositions": {},
            "reason_codes": {},
            "fallback_reasons": {},
            "top_reason_codes": [],
        },
    )

    response = client.get("/api/v1/admin/observability/dual-track-grounding")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "canonical_deep_judgment"
    assert payload["effective_scope"] == "deep_judgment_only"
    assert payload["source"] == "canonical"
    assert payload["metrics"]["claims_observed"] == 0
    assert payload["metrics"]["fallback_reasons"] == {}

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_prompt_quality_gate_snapshot_aggregates_recent_failures() -> None:
    admin_user = models.User(
        email="admin-observability-quality@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    passing_audit = models.Audit(
        user_id=admin_user.id,
        url="https://example.com",
        geo_score=70,
        seo_score=72,
        aeo_score=74,
        full_report={
            "debate": {
                "requested_tier": "smart",
                "pipeline_type": "smart_5step",
                "quality_gate": {
                    "schema_version": "orchestra-v3-qg-1",
                    "requested_tier": "smart",
                    "pipeline_type": "smart_5step",
                    "passed": True,
                    "violations": [],
                },
            }
        },
    )
    failing_audit = models.Audit(
        user_id=admin_user.id,
        url="https://example.org",
        geo_score=60,
        seo_score=61,
        aeo_score=62,
        full_report={
            "debate": {
                "requested_tier": "deep_judgment",
                "pipeline_type": "delta_flow",
                "quality_gate": {
                    "schema_version": "orchestra-v3-qg-1",
                    "requested_tier": "deep_judgment",
                    "pipeline_type": "delta_flow",
                    "passed": False,
                    "violations": [
                        {"code": "magistrate_over_flagging"},
                        {"code": "generator_grounding_rate_low"},
                    ],
                },
            }
        },
    )
    db.add_all([passing_audit, failing_audit])
    db.commit()

    response = client.get("/api/v1/admin/observability/prompt-quality-gate?days=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "orchestra-v3-qg-1"
    assert payload["audits_checked"] == 2
    assert payload["audits_failed"] == 1
    assert payload["top_violations"][0]["code"] == "generator_grounding_rate_low"
    assert payload["tier_summary"]["deep_judgment"]["audits_failed"] == 1
    assert payload["recent_failures"][0]["pipeline_type"] == "delta_flow"

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_prompt_quality_gate_snapshot_includes_previous_window_comparison() -> (
    None
):
    admin_user = models.User(
        email="admin-observability-quality-trend@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)
    now = datetime.now(timezone.utc)

    current_failing_audit = models.Audit(
        user_id=admin_user.id,
        url="https://trend-current.example.com",
        geo_score=60,
        seo_score=61,
        aeo_score=62,
        created_at=now - timedelta(days=1),
        full_report={
            "debate": {
                "requested_tier": "deep_judgment",
                "pipeline_type": "delta_flow",
                "quality_gate": {
                    "schema_version": "orchestra-v3-qg-1",
                    "requested_tier": "deep_judgment",
                    "pipeline_type": "delta_flow",
                    "passed": False,
                    "violations": [{"code": "magistrate_over_flagging"}],
                },
            }
        },
    )
    previous_passing_audit = models.Audit(
        user_id=admin_user.id,
        url="https://trend-previous.example.com",
        geo_score=75,
        seo_score=76,
        aeo_score=77,
        created_at=now - timedelta(days=8),
        full_report={
            "debate": {
                "requested_tier": "smart",
                "pipeline_type": "smart_5step",
                "quality_gate": {
                    "schema_version": "orchestra-v3-qg-1",
                    "requested_tier": "smart",
                    "pipeline_type": "smart_5step",
                    "passed": True,
                    "violations": [],
                },
            }
        },
    )
    db.add_all([current_failing_audit, previous_passing_audit])
    db.commit()

    response = client.get("/api/v1/admin/observability/prompt-quality-gate?days=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["failure_rate"] == 1.0
    assert payload["comparison"]["previous_window"]["audits_checked"] == 1
    assert payload["comparison"]["previous_window"]["failure_rate"] == 0.0
    assert payload["comparison"]["deltas"]["failure_rate"] == 1.0

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_prompt_quality_gate_snapshot_filters_by_tier() -> None:
    admin_user = models.User(
        email="admin-observability-quality-filter@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    db.add_all(
        [
            models.Audit(
                user_id=admin_user.id,
                url="https://fast-filter.example.com",
                geo_score=70,
                seo_score=71,
                aeo_score=72,
                full_report={
                    "debate": {
                        "requested_tier": "fast",
                        "pipeline_type": "fast_3step",
                        "quality_gate": {
                            "schema_version": "orchestra-v3-qg-1",
                            "requested_tier": "fast",
                            "pipeline_type": "fast_3step",
                            "passed": False,
                            "violations": [{"code": "generator_grounding_rate_low"}],
                        },
                    }
                },
            ),
            models.Audit(
                user_id=admin_user.id,
                url="https://smart-filter.example.com",
                geo_score=73,
                seo_score=74,
                aeo_score=75,
                full_report={
                    "debate": {
                        "requested_tier": "smart",
                        "pipeline_type": "smart_5step",
                        "quality_gate": {
                            "schema_version": "orchestra-v3-qg-1",
                            "requested_tier": "smart",
                            "pipeline_type": "smart_5step",
                            "passed": True,
                            "violations": [],
                        },
                    }
                },
            ),
        ]
    )
    db.commit()

    response = client.get("/api/v1/admin/observability/prompt-quality-gate?days=7&tier=smart")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audits_checked"] == 1
    assert payload["audits_failed"] == 0
    assert list(payload["tier_summary"].keys()) == ["smart"]

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_prompt_quality_calibration_snapshot_returns_report(
    monkeypatch,
) -> None:
    admin_user = models.User(
        email="admin-observability-calibration@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)
    captured_requested_tiers: list[str] = []

    monkeypatch.setattr(
        admin_observability.prompt_quality_calibration_service,
        "build_report",
        lambda **kwargs: (
            captured_requested_tiers.extend(kwargs.get("requested_tiers") or []),
            {
                "schema_version": "orchestra-v3-calibration-report-1",
                "summary": {
                    "audits_considered": 3,
                    "audits_with_quality_gate": 3,
                    "audits_failed": 1,
                    "failure_rate": 0.3333,
                    "audits_with_traces": 2,
                    "calibration_ready_audits": 2,
                    "calibration_ready_failures": 1,
                },
                "audits": [
                    {
                        "audit_id": 42,
                        "requested_tier": "deep_judgment",
                        "pipeline_type": "delta_flow",
                        "quality_gate_passed": False,
                        "trace_count": 8,
                        "calibration_ready": True,
                        "missing_artifacts": [],
                        "suggested_prompt_files": [
                            "backend/prompts/deep_judgment/global_magistrate.md"
                        ],
                        "violation_codes": ["magistrate_over_flagging"],
                    }
                ],
            },
        )[1],
    )

    response = client.get(
        "/api/v1/admin/observability/prompt-quality-calibration?days=7&limit=10&tier=deep_judgment"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["calibration_ready_failures"] == 1
    assert payload["audits"][0]["audit_id"] == 42
    assert payload["audits"][0]["suggested_prompt_files"][0].endswith("global_magistrate.md")
    assert captured_requested_tiers == ["deep_judgment"]

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_prompt_quality_calibration_snapshot_passes_explicit_audit_ids(
    monkeypatch,
) -> None:
    admin_user = models.User(
        email="admin-observability-calibration-audit-ids@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)
    captured_kwargs: dict[str, object] = {}

    def _capture_report(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "schema_version": "orchestra-v3-calibration-report-1",
            "summary": {
                "audits_considered": 2,
                "audits_with_quality_gate": 2,
                "audits_failed": 0,
                "failure_rate": 0.0,
                "audits_with_traces": 2,
                "calibration_ready_audits": 2,
                "calibration_ready_failures": 0,
            },
            "audits": [],
        }

    monkeypatch.setattr(
        admin_observability.prompt_quality_calibration_service,
        "build_report",
        _capture_report,
    )

    response = client.get(
        "/api/v1/admin/observability/prompt-quality-calibration?audit_id=101&audit_id=202"
    )

    assert response.status_code == 200
    assert captured_kwargs["audit_ids"] == [101, 202]
    assert captured_kwargs["days"] is None

    client.app.dependency_overrides.clear()
    db.close()


def test_admin_observability_dual_track_snapshot_reports_metrics(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-observability-metrics@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setattr(
        admin_observability,
        "_collect_dual_track_grounding_metrics",
        lambda: {
            "claims_observed": 8,
            "reason_codes_observed": 3,
            "fallbacks_observed": 1,
            "claim_dispositions": {
                "track_a": {"supported": 3},
                "track_b": {"blocked": 2, "rewrite_required": 3},
            },
            "reason_codes": {
                "track_b": {
                    "missing_citation": 1,
                    "unsupported_premise_ref": 2,
                }
            },
            "fallback_reasons": {"track_b_judge_unavailable": 1},
            "top_reason_codes": [
                {
                    "track": "track_b",
                    "reason_code": "unsupported_premise_ref",
                    "count": 2,
                }
            ],
        },
    )

    response = client.get("/api/v1/admin/observability/dual-track-grounding")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "canonical_deep_judgment"
    assert payload["effective_scope"] == "deep_judgment_only"
    assert payload["source"] == "canonical"
    assert payload["metrics"]["claims_observed"] == 8
    assert payload["metrics"]["reason_codes_observed"] == 3
    assert payload["metrics"]["fallbacks_observed"] == 1
    assert payload["metrics"]["claim_dispositions"]["track_b"]["rewrite_required"] == 3
    assert payload["metrics"]["reason_codes"]["track_b"]["unsupported_premise_ref"] == 2
    assert payload["metrics"]["fallback_reasons"]["track_b_judge_unavailable"] == 1
    assert payload["metrics"]["top_reason_codes"][0]["track"] == "track_b"

    client.app.dependency_overrides.clear()
    db.close()
