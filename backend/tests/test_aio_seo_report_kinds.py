"""SIGV2-1018: aio and seo report kinds on the PDF pipeline.

Covers kind acceptance end to end (normalization, manifest, request
validation, worker payload), the per-kind section matrix, filename acronyms,
the unchanged base-entitlement policy surface, and the no-LLM-cost pin for
the new kinds.
"""

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from job_models import PDFJobPayload
from services.pdf_reports.assembler import (
    build_report_context,
    normalize_report_kind,
    resolve_export_manifest,
    resolve_report_kind,
)
from services.pdf_reports.filenames import resolve_pdf_export_filename
from services.pdf_reports.report_suite_service import should_generate_ai_summary
from services.report_export_policy import (
    first_unmet_report_export_requirement,
    resolve_report_export_requirements,
)
from tests.test_pdf_report_renderer import _sample_audit_payload


def _user_on_plan(plan_type: str | None) -> SimpleNamespace:
    subscription = SimpleNamespace(status="active", plan_type=plan_type) if plan_type else None
    return SimpleNamespace(subscription=subscription, trial_plan=None)


def _aio_audit_payload() -> dict:
    payload = _sample_audit_payload()
    payload["metadata"]["aio"] = {
        "aio_score": 74,
        "components": {"aeo": 76, "geo": 71},
        "summary": "AI optimization roll-up summary.",
        "scope": "website_and_brand",
    }
    return payload


# ---------------------------------------------------------------------------
# Kind acceptance: normalization, aliases, manifest
# ---------------------------------------------------------------------------


def test_normalize_report_kind_accepts_aio_and_seo() -> None:
    assert normalize_report_kind("aio") == "aio"
    assert normalize_report_kind("seo") == "seo"
    assert normalize_report_kind("AIO") == "aio"


def test_normalize_report_kind_still_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        normalize_report_kind("aiox")
    with pytest.raises(ValueError):
        normalize_report_kind("technical")


def test_resolve_report_kind_returns_explicit_new_kinds() -> None:
    assert resolve_report_kind(explicit_report_kind="aio") == "aio"
    assert resolve_report_kind(explicit_report_kind="seo") == "seo"


def test_resolve_report_kind_fallbacks_never_produce_new_kinds() -> None:
    """No existing input may accidentally resolve to aio/seo (AC1)."""
    for kwargs in (
        {"explicit_report_type": "standard"},
        {"explicit_report_type": "battle"},
        {"explicit_report_type": "branded"},
        {"explicit_report_type": "whitelabel"},
        {"template_type": "Comparative"},
        {"template_type": "Executive"},
        {"template_type": "Standard"},
        {},
    ):
        resolved = resolve_report_kind(**kwargs)
        assert resolved in {"standard", "executive", "competitors"}


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_resolve_export_manifest_round_trips_new_kinds(kind: str) -> None:
    manifest = resolve_export_manifest(
        explicit_report_kind=kind,
        explicit_branding_mode="platform",
        template_type="Standard",
        hide_credit_cost=True,
    )
    assert manifest["report_kind"] == kind


def test_pdf_job_payload_round_trips_new_kind_manifest() -> None:
    payload = PDFJobPayload(
        job_id="job-aio",
        user_id=1,
        template_type="Standard",
        audit_ids=[1],
        options={},
        branding_config={},
        export_manifest={"report_kind": "aio", "branding_mode": "platform"},
    )
    parsed = type(payload)(**payload.to_dict())
    assert parsed.export_manifest["report_kind"] == "aio"


# ---------------------------------------------------------------------------
# Request-level whitelist: 422 for unknown kinds, never coerced (AC1)
# ---------------------------------------------------------------------------


def test_complex_report_options_accepts_new_kinds() -> None:
    from routers.api_router import ComplexReportOptions

    assert ComplexReportOptions(report_kind="aio").report_kind == "aio"
    assert ComplexReportOptions(report_kind="seo").report_kind == "seo"


def test_request_models_reject_unknown_kind() -> None:
    from routers.api_router import ComplexReportOptions, WhiteLabelReportRequest

    with pytest.raises(ValidationError):
        ComplexReportOptions(report_kind="aiox")
    with pytest.raises(ValidationError):
        WhiteLabelReportRequest(audit_id=1, report_kind="aiox")


# ---------------------------------------------------------------------------
# Section matrix (AC2): aio leads with metadata.aio, seo leads with SEO
# ---------------------------------------------------------------------------


def test_aio_sections_lead_with_canonical_aio() -> None:
    context = build_report_context(
        _aio_audit_payload(),
        "standard",
        export_manifest={"report_kind": "aio", "branding_mode": "platform"},
    )
    assert context["report_kind"] == "aio"
    sections = context["sections"]
    assert "aio_result" in sections
    assert sections["aio_result"]["value"] == 74
    assert sections["aio_result"]["scope"] == "website_and_brand"
    component_labels = {card["label"] for card in sections["aio_result"]["components"]}
    # AEO and GEO are internal AIO components and surface as AIO labels.
    assert component_labels == {"AIO"}


def test_aio_sections_explain_aio_only() -> None:
    context = build_report_context(
        _aio_audit_payload(),
        "standard",
        export_manifest={"report_kind": "aio", "branding_mode": "platform"},
    )
    sections = context["sections"]
    # The GEO and AEO panels merge into a single AIO panel; SEO stays out.
    panel_labels = {panel["label"] for panel in sections["why_this_score"]["items"]}
    assert "SEO" not in panel_labels
    assert panel_labels == {"AIO"}
    breakdown_domains = {group["domain"] for group in sections["score_breakdown"]["items"]}
    assert "SEO" not in breakdown_domains
    blocker_categories = {item["category"] for item in sections["critical_blockers"]["items"]}
    assert "SEO" not in blocker_categories


def test_seo_sections_lead_with_canonical_seo() -> None:
    context = build_report_context(
        _aio_audit_payload(),
        "standard",
        export_manifest={"report_kind": "seo", "branding_mode": "platform"},
    )
    assert context["report_kind"] == "seo"
    sections = context["sections"]
    assert "seo_overview" in sections
    assert sections["seo_overview"]["score"]["value"] == context["scores"]["seo"]


def test_seo_sections_explain_seo_only() -> None:
    context = build_report_context(
        _aio_audit_payload(),
        "standard",
        export_manifest={"report_kind": "seo", "branding_mode": "platform"},
    )
    sections = context["sections"]
    assert "aio_result" not in sections
    assert "geo_metrics" not in sections
    assert "aeo_readiness_dashboard" not in sections
    panel_labels = {panel["label"] for panel in sections["why_this_score"]["items"]}
    assert panel_labels == {"SEO"}
    breakdown_domains = {group["domain"] for group in sections["score_breakdown"]["items"]}
    assert breakdown_domains == {"SEO"}
    focus_labels = {group["label"] for group in sections["seo_focus"]["groups"]}
    assert focus_labels == {"Technical", "On-Page", "Performance"}


def test_aio_and_seo_have_own_toc_specs() -> None:
    """A missing spec must not silently degrade to the standard TOC (AC1)."""
    for kind, forbidden, required in (
        ("aio", "Executive Dashboard", "AI Optimization"),
        ("seo", "Executive Dashboard", "SEO Score"),
    ):
        context = build_report_context(
            _aio_audit_payload(),
            "standard",
            export_manifest={"report_kind": kind, "branding_mode": "platform"},
        )
        labels = [entry["label"] for entry in context["toc_entries"]]
        assert labels, f"{kind} produced no TOC entries"
        assert forbidden not in labels
        assert any(required in label for label in labels)


def test_sparse_payload_still_builds_both_kinds() -> None:
    sparse = {
        "target": {"type": "website", "name": "example.com", "url": "https://example.com"},
        "scores": {"seo": 40, "overall": 40},
        "metadata": {},
    }
    for kind in ("aio", "seo"):
        context = build_report_context(
            sparse,
            "standard",
            export_manifest={"report_kind": kind, "branding_mode": "platform"},
        )
        assert context["report_kind"] == kind
        assert isinstance(context["sections"], dict)


# ---------------------------------------------------------------------------
# No LLM cost for the new kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_no_ai_summary_for_new_kinds(kind: str) -> None:
    assert should_generate_ai_summary(kind) is False


# ---------------------------------------------------------------------------
# Policy: base has_pdf_audit_reports only, every plan (AC5)
# ---------------------------------------------------------------------------


_ALL_PLANS = [
    "plan_starter",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
    "plan_agency_trial",
    None,
]


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_new_kinds_require_only_base_pdf_feature(kind: str) -> None:
    manifest = {
        "report_kind": kind,
        "branding_mode": "platform",
        "render_report_type": "standard",
    }
    requirements = resolve_report_export_requirements(manifest)
    assert tuple(req.feature_key for req in requirements) == ("has_pdf_audit_reports",)


@pytest.mark.parametrize("kind", ["aio", "seo"])
@pytest.mark.parametrize("plan", _ALL_PLANS)
def test_new_kinds_allowed_on_every_plan(kind: str, plan: str | None) -> None:
    manifest = {
        "report_kind": kind,
        "branding_mode": "platform",
        "render_report_type": "standard",
    }
    assert first_unmet_report_export_requirement(_user_on_plan(plan), manifest) is None


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_new_kind_worker_recheck_still_applies(kind: str) -> None:
    """The worker entitlement re-check covers the new kinds."""
    manifest = {
        "report_kind": kind,
        "branding_mode": "platform",
        "render_report_type": "standard",
    }
    with patch("services.report_export_policy._plan_validator.has_feature", return_value=False):
        unmet = first_unmet_report_export_requirement(_user_on_plan("plan_specialist"), manifest)
    assert unmet is not None
    assert unmet.feature_key == "has_pdf_audit_reports"


# ---------------------------------------------------------------------------
# Filenames: acronym rendering
# ---------------------------------------------------------------------------


def test_aio_filename_uses_acronym() -> None:
    filename = resolve_pdf_export_filename(
        project_name="Acme",
        audit_type="DEEP",
        report_type="Standard",
        report_kind="aio",
    )
    assert "_AIO_" in filename


def test_seo_filename_uses_acronym() -> None:
    filename = resolve_pdf_export_filename(
        project_name="Acme",
        audit_type="DEEP",
        report_type="Standard",
        report_kind="seo",
    )
    assert "_SEO_" in filename


# ---------------------------------------------------------------------------
# Redaction: withheld sections and credit suppression on the new kinds (AC5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_withheld_sections_render_on_new_kinds(kind: str) -> None:
    payload = _aio_audit_payload()
    payload["metadata"]["locked_sections"] = {
        "competitors": {
            "is_locked": True,
            "detail": "Competitor analysis requires a higher plan.",
            "required_plan_label": "Specialist",
            "capability_key": "has_competitor_analysis",
            "required_plan": "plan_specialist",
            "lock_origin": "read",
        }
    }
    context = build_report_context(
        payload,
        "standard",
        export_manifest={"report_kind": kind, "branding_mode": "platform"},
    )
    withheld = context["withheld_sections"]
    assert len(withheld) == 1
    assert withheld[0]["section"] == "competitors"
    assert withheld[0]["withheld"] is True
    assert withheld[0]["required_plan_label"] == "Specialist"
    for forbidden_key in ("capability_key", "required_plan", "lock_origin"):
        assert forbidden_key not in withheld[0]


@pytest.mark.parametrize("kind", ["aio", "seo"])
def test_credit_details_stay_suppressed_on_new_kinds(kind: str) -> None:
    context = build_report_context(
        _aio_audit_payload(),
        "standard",
        export_manifest={
            "report_kind": kind,
            "branding_mode": "platform",
            "hide_credit_cost": False,
        },
    )
    integrity_items = _flatten_text(context["integrity_page"])
    assert "credit" not in integrity_items.lower()


def _flatten_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(v) for v in value)
    return ""


# ---------------------------------------------------------------------------
# Worker re-check integration for a new kind
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


@pytest.mark.asyncio
async def test_worker_recheck_covers_aio_kind(worker_db):
    """A denied base entitlement fails an aio job permanently, no PDF."""
    user = models.User(
        email="aio@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    worker_db.add(user)
    worker_db.flush()
    worker_db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type="plan_specialist",
            status="active",
        )
    )
    worker_db.commit()
    job = models.ComplexReportJob(
        id="job-aio",
        user_id=user.id,
        status="queued",
        export_manifest={
            "report_kind": "aio",
            "branding_mode": "platform",
            "render_report_type": "standard",
        },
    )
    worker_db.add(job)
    worker_db.commit()

    payload = PDFJobPayload(
        job_id=job.id,
        user_id=user.id,
        template_type="Standard",
        audit_ids=[1],
        options={},
        branding_config={},
        export_manifest=job.export_manifest,
    )
    with (
        patch("pdf_worker.SessionLocal", return_value=worker_db),
        patch("pdf_worker.render_report_pdf") as mock_render,
        patch("services.report_export_policy._plan_validator.has_feature", return_value=False),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), AsyncMock())

    job = (
        worker_db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "job-aio")
        .one()
    )
    assert job.status == "failed"
    assert job.error == "PDF audit reports are not available on your current plan."
    mock_render.assert_not_called()


# ---------------------------------------------------------------------------
# Real WeasyPrint renders: AIO and SEO end to end with text extraction
# ---------------------------------------------------------------------------


def _real_render_skip_reason() -> str | None:
    try:
        from weasyprint import HTML
    except Exception as exc:
        return f"WeasyPrint is not importable ({type(exc).__name__}: {exc})"
    try:
        HTML(string="<p>probe</p>").write_pdf()
    except Exception as exc:
        return f"WeasyPrint cannot render ({type(exc).__name__}: {exc})"
    return None


_RENDER_SKIP = _real_render_skip_reason()
rendermark = pytest.mark.skipif(_RENDER_SKIP is not None, reason=_RENDER_SKIP or "")


def _render_kind(payload: dict, kind: str) -> str:
    from pypdf import PdfReader

    from services.pdf_reports.renderer import render_pdf_from_template

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01T00:00:00Z"},
        export_manifest={"report_kind": kind, "branding_mode": "platform"},
    )
    pdf_bytes = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
        deterministic=True,
    )
    assert pdf_bytes.startswith(b"%PDF-1.")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)


@rendermark
def test_aio_pdf_renders_aio_first_not_seo_lead() -> None:
    text = _render_kind(_aio_audit_payload(), "aio")
    # The cover kicker and score card use the operator's "AIO" naming.
    assert "AIO REPORT" in text
    assert "AIO" in text
    assert "74" in text
    # SEO must not lead the AIO report.
    assert "SEO REPORT" not in text
    assert "Technical, On-Page & Performance" not in text


@rendermark
def test_seo_pdf_renders_seo_first_not_aio_lead() -> None:
    text = _render_kind(_aio_audit_payload(), "seo")
    # The cover kicker and score card use the operator's "SEO" naming.
    assert "SEO REPORT" in text
    assert "SEO" in text
    assert "74" in text
    # The AIO roll-up card is not part of the SEO report.
    assert "AIO REPORT" not in text
    assert "AI Optimization score" not in text
    # The SEO factors section renders real group content out of seo_focus.groups.
    assert "Technical" in text
    assert "Security Accessibility" in text


@rendermark
def test_sparse_aio_pdf_renders_without_crashing() -> None:
    sparse = {
        "target": {"type": "website", "name": "example.com", "url": "https://example.com"},
        "scores": {"seo": 4.0, "overall": 4.0},
        "metadata": {"plan": "plan_specialist"},
    }
    text = _render_kind(sparse, "aio")
    assert "AIO" in text


@rendermark
def test_gated_seo_pdf_renders_withheld_placeholder() -> None:
    payload = _aio_audit_payload()
    payload["metadata"]["locked_sections"] = {
        "competitors": {
            "is_locked": True,
            "detail": "Competitor analysis requires a higher plan.",
            "required_plan_label": "Specialist",
            "capability_key": "has_competitor_analysis",
            "required_plan": "plan_specialist",
            "lock_origin": "read",
        }
    }
    text = _render_kind(payload, "seo")
    assert "Sections not included in this report" in text
    assert "Competitors" in text
    for forbidden in ("has_competitor_analysis", "plan_specialist", "lock_origin"):
        assert forbidden not in text
