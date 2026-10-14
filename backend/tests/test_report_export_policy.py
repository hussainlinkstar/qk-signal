"""SIGV2-1019: report export authorization beyond the enqueue gate.

Covers the shared export policy, manifest resolution parity, the worker-side
entitlement re-check and the withheld-sections projection.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from job_models import PDFJobPayload
from services.pdf_reports.assembler import resolve_effective_export_manifest
from services.report_export_policy import (
    first_unmet_report_export_requirement,
    resolve_report_export_requirements,
)


def _user_on_plan(plan_type: str | None) -> SimpleNamespace:
    subscription = SimpleNamespace(status="active", plan_type=plan_type) if plan_type else None
    return SimpleNamespace(subscription=subscription, trial_plan=None)


# ---------------------------------------------------------------------------
# resolve_report_export_requirements: manifest -> ordered requirements
# ---------------------------------------------------------------------------

_STANDARD_MANIFEST = {
    "report_kind": "standard",
    "branding_mode": "platform",
    "render_report_type": "standard",
}
_BATTLE_MANIFEST = {
    "report_kind": "competitors",
    "branding_mode": "platform",
    "render_report_type": "battle",
}
_COMPETITOR_KIND_MANIFEST = {
    "report_kind": "competitors",
    "branding_mode": "platform",
    "render_report_type": "standard",
}
_WHITE_LABEL_MANIFEST = {
    "report_kind": "executive",
    "branding_mode": "white_label",
    "render_report_type": "whitelabel",
}
_BRANDED_MANIFEST = {
    "report_kind": "executive",
    "branding_mode": "platform",
    "render_report_type": "branded",
}
_BRANDED_COMPETITOR_MANIFEST = {
    "report_kind": "competitors",
    "branding_mode": "platform",
    "render_report_type": "branded",
}
_EMPTY_MANIFEST: dict = {}


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        (_STANDARD_MANIFEST, ("has_pdf_audit_reports",)),
        (_EMPTY_MANIFEST, ("has_pdf_audit_reports",)),
        (_BATTLE_MANIFEST, ("has_competitor_analysis",)),
        (_COMPETITOR_KIND_MANIFEST, ("has_competitor_analysis",)),
        (_WHITE_LABEL_MANIFEST, ("pdf_white_label",)),
        (_BRANDED_MANIFEST, ("has_advanced_reporting",)),
        (
            _BRANDED_COMPETITOR_MANIFEST,
            ("has_competitor_analysis", "has_advanced_reporting"),
        ),
    ],
)
def test_resolve_report_export_requirements_order_and_keys(manifest, expected):
    requirements = resolve_report_export_requirements(manifest)
    assert tuple(req.feature_key for req in requirements) == expected


def test_resolve_report_export_requirements_detail_strings_unchanged():
    details = {
        req.feature_key: req.detail
        for manifest in (
            _STANDARD_MANIFEST,
            _BATTLE_MANIFEST,
            _WHITE_LABEL_MANIFEST,
            _BRANDED_MANIFEST,
        )
        for req in resolve_report_export_requirements(manifest)
    }
    assert details == {
        "has_pdf_audit_reports": "PDF audit reports are not available on your current plan.",
        "has_competitor_analysis": (
            "Battle PDF reports are available on plans with competitor analysis."
        ),
        "pdf_white_label": (
            "White-label PDF reports are available on plans with PDF white-label access."
        ),
        "has_advanced_reporting": (
            "Branded PDF reports are available on plans with advanced reporting."
        ),
    }


@pytest.mark.parametrize(
    ("manifest", "plan", "expected_feature"),
    [
        (_STANDARD_MANIFEST, "plan_starter", None),
        (_BATTLE_MANIFEST, "plan_starter", "has_competitor_analysis"),
        (_BATTLE_MANIFEST, "plan_standard", "has_competitor_analysis"),
        (_BATTLE_MANIFEST, "plan_specialist", None),
        (_BATTLE_MANIFEST, "plan_executive", None),
        (_COMPETITOR_KIND_MANIFEST, "plan_starter", "has_competitor_analysis"),
        (_WHITE_LABEL_MANIFEST, "plan_specialist", "pdf_white_label"),
        (_BRANDED_MANIFEST, "plan_standard", "has_advanced_reporting"),
        (_BRANDED_MANIFEST, "plan_specialist", None),
        (_BRANDED_COMPETITOR_MANIFEST, "plan_standard", "has_competitor_analysis"),
        (_STANDARD_MANIFEST, None, None),  # starter still gets base PDF reports
    ],
)
def test_first_unmet_report_export_requirement_per_plan(manifest, plan, expected_feature):
    unmet = first_unmet_report_export_requirement(_user_on_plan(plan), manifest)
    assert (unmet.feature_key if unmet else None) == expected_feature


def test_http_adapter_denial_surface_is_unchanged():
    """_require_report_export_access still raises HTTP 402 with identical detail."""
    from fastapi import HTTPException

    from routers.api_router import _require_report_export_access

    for manifest, plan, expected_detail in (
        (
            _BATTLE_MANIFEST,
            "plan_starter",
            "Battle PDF reports are available on plans with competitor analysis.",
        ),
        (
            _WHITE_LABEL_MANIFEST,
            "plan_specialist",
            "White-label PDF reports are available on plans with PDF white-label access.",
        ),
        (
            _BRANDED_MANIFEST,
            "plan_standard",
            "Branded PDF reports are available on plans with advanced reporting.",
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _require_report_export_access(_user_on_plan(plan), export_manifest=manifest)
        assert exc_info.value.status_code == 402
        assert exc_info.value.detail == expected_detail

    # Allowed combinations do not raise.
    _require_report_export_access(_user_on_plan("plan_starter"), export_manifest=_STANDARD_MANIFEST)
    _require_report_export_access(
        _user_on_plan("plan_specialist"), export_manifest=_BATTLE_MANIFEST
    )


# ---------------------------------------------------------------------------
# resolve_effective_export_manifest: one manifest for policy and renderer
# ---------------------------------------------------------------------------


def test_effective_manifest_prefers_stored_manifest():
    stored = dict(_BATTLE_MANIFEST)
    resolved = resolve_effective_export_manifest(
        export_manifest=stored,
        options={"report_kind": "standard"},
        template_type="Executive",
        branding_config=None,
    )
    assert resolved["report_kind"] == "competitors"
    assert resolved["render_report_type"] == "battle"


def test_effective_manifest_empty_stored_manifest_derives_comparative_battle():
    """The earlier hole: a falsy stored manifest plus Comparative must not bypass."""
    resolved = resolve_effective_export_manifest(
        export_manifest={},
        options={},
        template_type="Comparative",
        branding_config=None,
    )
    assert resolved["render_report_type"] == "battle"
    assert resolved["report_kind"] == "competitors"
    unmet = first_unmet_report_export_requirement(_user_on_plan("plan_starter"), resolved)
    assert unmet is not None
    assert unmet.feature_key == "has_competitor_analysis"


def test_render_report_pdf_uses_same_resolved_manifest():
    """The stored manifest wins over diverging job options inside the renderer."""
    from services.pdf_reports import report_suite_service

    audit = SimpleNamespace(
        id=1,
        url="https://example.com",
        geo_score=70,
        user=None,
        project=None,
        site_id=None,
        project_id=None,
        full_report={},
    )
    audit.audit_type = None
    resolved = resolve_effective_export_manifest(
        export_manifest=dict(_STANDARD_MANIFEST),
        options={"report_kind": "competitors"},
        template_type="Executive",
        branding_config=None,
    )
    assert resolved["report_kind"] == "standard"

    with (
        patch.object(
            report_suite_service, "render_white_label_pdf", return_value=b"%PDF"
        ) as mock_white_label,
        patch.object(
            report_suite_service, "render_battle_report_pdf", return_value=b"%PDF"
        ) as mock_battle,
        patch.object(report_suite_service, "_prepare_primary_payload", return_value={}),
    ):
        report_suite_service.render_report_pdf(
            db=MagicMock(),
            selected_audits=[audit],
            template_type="Executive",
            options={"report_kind": "competitors"},
            export_manifest=resolved,
        )
        mock_white_label.assert_called_once()
        mock_battle.assert_not_called()


# ---------------------------------------------------------------------------
# pdf_worker: render-time entitlement re-check
# ---------------------------------------------------------------------------


@pytest.fixture()
def worker_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = testing_session_local()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_worker_user(db, plan_type):
    user = models.User(
        email=f"{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _make_worker_job(db, user, export_manifest=None):
    job = models.ComplexReportJob(
        id="job-under-test",
        user_id=user.id,
        status="queued",
        export_manifest=export_manifest,
    )
    db.add(job)
    db.commit()
    return job


def _battle_job_payload(job_id="job-under-test", user_id=1, export_manifest=None):
    return PDFJobPayload(
        job_id=job_id,
        user_id=user_id,
        template_type="Comparative",
        audit_ids=[1],
        options={},
        branding_config={},
        export_manifest=export_manifest,
    )


@pytest.mark.asyncio
async def test_worker_denies_battle_report_after_downgrade(worker_db):
    """Headline repro: enqueued on specialist, downgraded to starter, no PDF."""
    user = _make_worker_user(worker_db, "plan_specialist")
    job = _make_worker_job(
        worker_db,
        user,
        export_manifest={
            "report_kind": "competitors",
            "branding_mode": "platform",
            "render_report_type": "battle",
        },
    )
    # Downgrade after enqueue.
    user.subscription.plan_type = "plan_starter"
    worker_db.commit()

    payload = _battle_job_payload(
        user_id=user.id,
        export_manifest=job.export_manifest,
    )

    with (
        patch("pdf_worker.SessionLocal", return_value=worker_db),
        patch("pdf_worker.render_report_pdf") as mock_render,
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), AsyncMock())

    job = (
        worker_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "job-under-test")
        .one()
    )
    assert job.status == "failed"
    assert job.error == "Battle PDF reports are available on plans with competitor analysis."
    assert job.completed_at is not None
    mock_render.assert_not_called()


@pytest.mark.asyncio
async def test_worker_denies_empty_manifest_comparative_battle(worker_db):
    """Empty stored manifest + Comparative template must not slip through."""
    user = _make_worker_user(worker_db, "plan_starter")
    job = _make_worker_job(worker_db, user, export_manifest=None)

    payload = _battle_job_payload(user_id=user.id, export_manifest=None)

    with (
        patch("pdf_worker.SessionLocal", return_value=worker_db),
        patch("pdf_worker.render_report_pdf") as mock_render,
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), AsyncMock())

    job = (
        worker_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "job-under-test")
        .one()
    )
    assert job.status == "failed"
    assert "competitor analysis" in job.error
    mock_render.assert_not_called()


@pytest.mark.asyncio
async def test_worker_denial_does_not_requeue(worker_db):
    """Authorization failure is permanent: no retry push to the queue."""
    user = _make_worker_user(worker_db, "plan_starter")
    _make_worker_job(worker_db, user, export_manifest=dict(_BATTLE_MANIFEST))
    mock_redis = AsyncMock()

    payload = _battle_job_payload(user_id=user.id, export_manifest=dict(_BATTLE_MANIFEST))

    with (
        patch("pdf_worker.SessionLocal", return_value=worker_db),
        patch("pdf_worker.render_report_pdf"),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), mock_redis)

    mock_redis.lpush.assert_not_called()


@pytest.mark.asyncio
async def test_worker_renders_when_entitlement_still_valid(worker_db):
    user = _make_worker_user(worker_db, "plan_specialist")
    job = _make_worker_job(worker_db, user, export_manifest=dict(_STANDARD_MANIFEST))
    audit = models.Audit(
        user_id=user.id,
        url="https://example.com",
        geo_score=70,
        full_report={"metadata": {}, "scores": {"overall": 70}},
    )
    worker_db.add(audit)
    worker_db.commit()
    worker_db.refresh(audit)

    payload = PDFJobPayload(
        job_id=job.id,
        user_id=user.id,
        template_type="Executive",
        audit_ids=[audit.id],
        options={},
        branding_config={},
        export_manifest=dict(_STANDARD_MANIFEST),
    )
    captured = {}

    def _capture_render(**kwargs):
        captured["manifest"] = kwargs["export_manifest"]
        return b"%PDF-fake"

    mock_gcs = MagicMock()
    mock_gcs.upload_file.return_value = "local://reports/x.pdf"

    with (
        patch("pdf_worker.SessionLocal", return_value=worker_db),
        patch("pdf_worker.render_report_pdf", side_effect=_capture_render),
        patch("pdf_worker.get_storage_service", return_value=mock_gcs),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), AsyncMock())

    job = (
        worker_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "job-under-test")
        .one()
    )
    assert job.status == "succeeded"
    # The renderer received the manifest the worker resolved, not a re-derived one.
    assert captured["manifest"] == dict(_STANDARD_MANIFEST)


# ---------------------------------------------------------------------------
# Withheld sections projection (AC3)
# ---------------------------------------------------------------------------


def test_withheld_sections_projection_exposes_only_public_fields():
    from services.pdf_reports.assembler import build_report_context

    payload = {
        "target": {"type": "website", "name": "example.com", "url": "https://example.com"},
        "site": {"url": "https://example.com", "language": "en"},
        "scores": {"seo": 70, "geo": 60, "aeo": 65, "overall": 65},
        "metadata": {
            "plan": "plan_starter",
            "locked_sections": {
                "competitors": {
                    "is_locked": True,
                    "capability_key": "has_competitor_analysis",
                    "required_plan": "plan_specialist",
                    "required_plan_label": "Specialist",
                    "detail": "Competitor benchmarks and discovered rivals are locked on the current plan.",
                    "lock_origin": "read",
                },
                "entities": {
                    "is_locked": True,
                    "capability_key": "has_entity_enhancement",
                    "required_plan": "plan_specialist",
                    "detail": "Entity extraction and semantic node mapping are locked on the current plan.",
                    "lock_origin": "read",
                },
                "unlocked_section": {"is_locked": False, "capability_key": "x"},
            },
        },
    }

    context = build_report_context(payload, "standard")
    withheld = context["withheld_sections"]

    assert [item["section"] for item in withheld] == ["competitors", "entities"]
    competitors = withheld[0]
    assert competitors["withheld"] is True
    assert "locked on the current plan" in competitors["detail"]
    assert competitors["required_plan_label"] == "Specialist"
    # Forbidden fields must not be projected at all.
    for item in withheld:
        assert set(item.keys()) <= {
            "section",
            "section_label",
            "withheld",
            "detail",
            "required_plan_label",
            "upgrade_hint",
        }
        serialized = str(item)
        assert "capability_key" not in serialized
        assert "has_competitor_analysis" not in serialized
        assert "has_entity_enhancement" not in serialized
        assert "plan_specialist" not in serialized
        assert "lock_origin" not in serialized


def test_plan_standard_still_receives_advisor_rollup():
    """Invariant pin: advisor attach is deliberately NOT gated.

    attach_advisor_view reads the already-sanitized payload and makes no LLM
    call; _lock_advanced_reporting leaves `advisor` alone. Gating it would
    strip "what to fix, in order" from paying plan_standard customers
    (has_advanced_reporting is False on plan_starter AND plan_standard).
    """
    from app.services.advisor_view import attach_advisor_view
    from services.audit_feature_gating_service import sanitize_audit_payload_for_plan

    report = {
        "metadata": {"plan": "plan_standard"},
        "recommendations": {
            "items": [
                {
                    "action": "Add FAQPage schema to the pricing page",
                    "estimated_effort": "low",
                    "expected_score_impact": {"aeo": 15},
                    "grounded_by_findings": ["aeo.no_faq_schema"],
                    "derived_from": ["analysis.answerability"],
                }
            ]
        },
    }

    sanitized = sanitize_audit_payload_for_plan(report, "plan_standard", lock_origin="read")
    result = attach_advisor_view(sanitized)

    advisor = result["metadata"]["advisor"]
    assert advisor["actions"], "plan_standard must still receive the advisor roll-up"
    assert advisor["actions"][0]["action"] == "Add FAQPage schema to the pricing page"


def test_complex_report_pdf_raw_payload_branch_has_no_production_caller():
    """Invariant pin: _build_complex_report_pdf(db=None) is latent only.

    The db=None branch renders from a raw payload without the plan
    sanitization path; wiring it up to a real caller must be loud. Assert the
    latent signature stays optional and that no production call site omits
    the db argument.
    """
    import inspect

    import routers.api_router as api_router

    source = inspect.getsource(api_router)
    signature = inspect.signature(api_router._build_complex_report_pdf)
    assert signature.parameters["db"].default is None, (
        "db must stay an optional latent parameter; making it required changes "
        "this invariant and this test should be revisited"
    )

    call_lines = [
        line.strip()
        for line in source.splitlines()
        if "_build_complex_report_pdf(" in line and "def _build_complex_report_pdf" not in line
    ]
    # There are currently no production call sites. If one is added, it must
    # pass an explicit db (the sanitized path); the db=None raw-payload branch
    # has no sanitization and must not be reachable.
    for call in call_lines:
        assert "db=" in call, f"raw-payload report path wired to a caller: {call}"


def test_entity_analysis_survives_sanitization_on_unentitled_plan():
    """Invariant pin: metadata.entity_analysis is NOT gated content.

    _lock_entities withholds payload["entities"], the gated deliverable.
    The metadata keys feed two non-gated consumers: the `brand` search-type
    heuristic prefers metadata.entity_analysis.brand_trust_score
    (services/query_taxonomy.py:253, :281) on every plan, and the PDF
    entity_strength column (_entity_strength_score, assembler.py:743) only
    renders on competitors reports, which require has_competitor_analysis,
    a feature no plan holds without has_entity_enhancement. Clearing this
    key would silently downgrade the `brand` score to the scores.geo
    fallback for plan_starter and the paying plan_standard tier.
    """
    from services.audit_feature_gating_service import sanitize_audit_payload_for_plan

    payload = {
        "entities": [{"name": "Acme Corp", "type": "Organization"}],
        "metadata": {"entity_analysis": {"brand_trust_score": 41, "entity_clarity_score": 58}},
    }

    sanitized = sanitize_audit_payload_for_plan(payload, "plan_starter", lock_origin="read")

    assert sanitized["entities"] == []
    assert sanitized["metadata"]["entity_analysis"] == {
        "brand_trust_score": 41,
        "entity_clarity_score": 58,
    }
