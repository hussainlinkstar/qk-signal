import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import services.pdf_report_renderer as pdf_report_renderer
from services.pdf_reports.assembler import _publicize_aio_terms, build_report_context
from services.pdf_reports.logo_constants import QIKO_MARK_DATA_URI
from services.pdf_reports.assets import resolve_asset_data_uri
from services.pdf_reports.charts import build_score_radar_svg
from services.pdf_reports.renderer import render_pdf_from_template
from services.pdf_report_renderer import (
    BrandingConfig,
    render_battle_report_pdf,
    render_white_label_pdf,
)


class DummyCSS:
    def __init__(self, string: str, base_url: str | None = None):
        self.string = string
        self.base_url = base_url


class DummyHTML:
    def __init__(self, string: str, base_url: str | None = None):
        self.string = string
        self.base_url = base_url

    def write_pdf(self, stylesheets=None):
        _ = stylesheets
        return (
            b"%PDF-1.7\n"
            b"1 0 obj<</CreationDate (D:20260519101010Z) /ModDate (D:20260519101010Z)>>endobj\n"
            b"trailer<</ID [<abcdefabcdefabcdefabcdefabcdefab> <12345123451234512345123451234512>]>>\n"
            b"%%EOF"
        )


def _sample_audit_payload() -> dict:
    return {
        "target": {
            "type": "website",
            "name": "example.com",
            "url": "https://example.com",
            "metadata": {},
        },
        "site": {
            "url": "https://example.com",
            "market": "us",
            "language": "en",
        },
        "geo": {
            "content_citability": 72,
            "source_authority": 69,
            "entity_clarity": 81,
        },
        "aeo": {
            "llm_schema_readiness": 77,
            "semantic_entity_density": 68,
            "information_gain": 73,
            "snippet_formatting": 61,
            "schema_health": {
                "score": 79,
                "detected_schema_types": ["FAQPage", "Organization"],
                "missing_high_impact_types": ["HowTo"],
            },
        },
        "entities": ["ExampleCo", "Generative Search", "Answer Engine"],
        "suggestions": [
            {
                "priority": 1,
                "title": "Add FAQ schema",
                "summary": "Publish FAQPage JSON-LD on the highest-intent pages.",
                "action": "Publish FAQPage JSON-LD",
                "category": "Technical",
                "owner": "engineering",
                "estimated_effort": "medium",
                "cross_score_leverage": ["aeo", "geo"],
                "expected_score_impact": {"aeo": 12, "geo": 6},
            },
            {
                "priority": 2,
                "title": "Strengthen entity coverage",
                "summary": "Expand brand and service entity coverage across answer pages.",
                "action": "Expand entity-rich copy",
                "category": "Content",
                "owner": "content",
                "estimated_effort": "medium",
                "cross_score_leverage": ["seo", "aeo"],
            },
            {
                "priority": 3,
                "title": "Improve answer formatting",
                "summary": "Add tighter summary blocks for extraction-oriented sections.",
                "action": "Add tighter summary blocks",
                "category": "Content",
                "owner": "content",
                "estimated_effort": "low",
                "cross_score_leverage": ["aeo"],
            },
        ],
        "raw_ai_scores": {"seo": 91, "geo": 88, "aeo": 90},
        "scores": {
            "seo": 74,
            "geo": 71,
            "aeo": 76,
            "overall": 74,
            "seo_breakdown": {
                "score": 74,
                "components": {},
                "penalties": [{"reason": "Missing canonical URL", "impact": -10}],
                "bonuses": [],
            },
            "geo_breakdown": {
                "score": 71,
                "components": {},
                "penalties": [{"reason": "Weak local schema coverage", "impact": -14}],
                "bonuses": [],
            },
            "aeo_breakdown": {
                "score": 76,
                "components": {},
                "penalties": [{"reason": "Low snippet formatting", "impact": -8}],
                "bonuses": [],
            },
        },
        "metadata": {
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "plan": "plan_specialist",
            "version": "2.0",
            "audit_target_type": "website",
            "target_name": "example.com",
            "target_url": "https://example.com",
            "target_metadata": {},
            "service_status": {},
            "service_errors": {},
            "competitor_summary": {
                "benchmark": {
                    "columns": [
                        {"key": "rank", "label": "Rank", "type": "number"},
                        {"key": "name", "label": "Brand", "type": "text"},
                        {"key": "geo_visibility", "label": "GEO Visibility", "type": "number"},
                        {"key": "aeo_score", "label": "AEO Score", "type": "number"},
                        {"key": "entity_strength", "label": "Entity Strength", "type": "number"},
                        {"key": "overall_score", "label": "Overall Score", "type": "number"},
                    ],
                    "rows": [
                        {
                            "rank": 1,
                            "name": "Leader Corp",
                            "is_target": False,
                            "geo_visibility": 79,
                            "aeo_score": 78,
                            "entity_strength": 75,
                            "overall_score": 77.33,
                            "deltas_vs_target": {
                                "geo_visibility": 8,
                                "aeo_score": 2,
                                "entity_strength": 4,
                            },
                        },
                        {
                            "rank": 2,
                            "name": "example.com",
                            "is_target": True,
                            "geo_visibility": 71,
                            "aeo_score": 76,
                            "entity_strength": 71,
                            "overall_score": 72.67,
                            "deltas_vs_target": {
                                "geo_visibility": 0,
                                "aeo_score": 0,
                                "entity_strength": 0,
                            },
                        },
                    ],
                }
            },
            "scores_available": True,
            "audit_outcome": "completed",
            "intent": "informational",
            "query_type": "informational",
            "ai_generation": {"provider": "google", "token_usage": 1234},
            "neural_executive_summary": "The target is credible, but AI citation readiness is constrained by schema and local signal gaps.",
            "strategic_intelligence_grid": [
                {
                    "agent_correlation": "Google SGE and chat models are over-weighting competitor schema breadth.",
                    "neural_logic": "Entity framing is present but not reinforced consistently across answer blocks.",
                    "architect_fix": "Create schema-complete answer hubs tied to target entities.",
                    "discovery": "Competitors with stronger FAQ clustering are outranking the target in generative answers.",
                    "priority_weight": "High",
                }
            ],
            "market_dominance_blueprint": "Close the schema gap first, then expand entity-rich answer surfaces to reverse the visibility deficit.",
        },
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": True,
            "grounding_profile": "dual_track_v1",
            "summary": {
                "total_claims": 6,
                "track_a_total": 4,
                "track_a_supported": 3,
                "track_a_flagged": 1,
                "track_a_omitted": 0,
                "track_b_total": 2,
                "track_b_supported": 1,
                "track_b_flagged": 1,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [
                {"track": "track_a", "category": "missing_evidence", "count": 1},
                {"track": "track_b", "category": "generic_recommendation", "count": 1},
            ],
            "degraded": True,
            "degraded_reason": "track_b_judge_unavailable",
        },
        "deltas_vs_target": {
            "geo_visibility": 8,
            "aeo_score": 2,
            "entity_strength": 4,
        },
    }


def _build_branding_config(**overrides) -> BrandingConfig:
    payload = {
        "title": "Agency Report",
        "primary_color": "#FF4D2D",
        "generated_date": "2026-01-10",
        "company_name": "Acme Agency",
    }
    payload.update(overrides)
    return BrandingConfig(**payload)


def test_build_score_radar_svg_contains_svg_and_labels():
    svg = build_score_radar_svg(
        metrics={"GEO": 78, "SEO": 82, "AEO": 69, "Performance": 74},
        primary_color="#112233",
        secondary_color="#445566",
    )

    assert svg.startswith("<svg")
    assert "GEO" in svg
    assert "Performance" in svg
    assert "#112233" in svg


def test_render_white_label_pdf_uses_white_label_template(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_render_pdf_from_template(
        *, template_name: str, context: dict, deterministic: bool = False
    ):
        captured["template_name"] = template_name
        captured["context"] = context
        captured["deterministic"] = deterministic
        return b"%PDF-fake"

    monkeypatch.setattr(
        pdf_report_renderer, "render_pdf_from_template", _fake_render_pdf_from_template
    )

    pdf_bytes = render_white_label_pdf(
        audit_id=123,
        audit_url="https://example.com",
        geo_score=87.3,
        highlights=["Improved structured data", "Better trust signals"],
        full_report=_sample_audit_payload(),
        branding=_build_branding_config(is_white_label=True, report_type="whitelabel"),
        include_competitor_analysis=True,
        selected_sections=["overview", "geo", "seo", "aeo", "ai"],
    )

    assert pdf_bytes == b"%PDF-fake"
    assert captured["template_name"] == "white_label.html"
    context = captured["context"]
    assert context["report_type"] == "whitelabel"
    assert context["export_manifest"]["branding_mode"] == "white_label"
    assert context["export_manifest"]["hide_credit_cost"] is True
    assert context["target"]["name"] == "example.com"
    assert context["report_kind"] == "executive"
    assert context["context_page"]["title"] == "Diagnostic Blueprint"
    assert context["sections"]["executive_dashboard"]["cards"]
    assert context["integrity_page"]["certificate_items"]
    assert context["branding"]["show_platform_branding"] is False
    assert context["branding"]["vendor_name"] == ""
    assert "raw_ai_scores" not in json.dumps(context)
    assert "ai_generation" not in json.dumps(context)


def test_render_battle_report_pdf_builds_benchmark_context(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_render_pdf_from_template(
        *, template_name: str, context: dict, deterministic: bool = False
    ):
        captured["template_name"] = template_name
        captured["context"] = context
        captured["deterministic"] = deterministic
        return b"%PDF-fake"

    monkeypatch.setattr(
        pdf_report_renderer, "render_pdf_from_template", _fake_render_pdf_from_template
    )

    left_report = _sample_audit_payload()
    right_report = _sample_audit_payload()
    right_report["target"] = {
        "type": "website",
        "name": "competitor.com",
        "url": "https://competitor.com",
        "metadata": {},
    }
    right_report["scores"]["geo"] = 77
    right_report["scores"]["aeo"] = 72
    right_report["scores"]["overall"] = 75

    pdf_bytes = render_battle_report_pdf(
        left_title="example.com",
        right_title="competitor.com",
        left_report=left_report,
        right_report=right_report,
        branding=_build_branding_config(title="Battle Report", company_name=None),
        selected_sections=["overview", "geo"],
    )

    assert pdf_bytes == b"%PDF-fake"
    assert captured["template_name"] == "battle.html"
    context = captured["context"]
    assert context["report_type"] == "battle"
    assert context["sections"]["trust_banner"]["items"]
    assert context["context_page"]["title"] == "Competitive Context"
    assert context["sections"]["battlefield_leaderboard"]["rows"]
    assert context["sections"]["delta_analysis"]["items"]
    assert context["sections"]["competitive_position"]["headline"]


def test_render_white_label_pdf_marks_cjk_context(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_render_pdf_from_template(
        *, template_name: str, context: dict, deterministic: bool = False
    ):
        captured["context"] = context
        return b"%PDF-fake"

    monkeypatch.setattr(
        pdf_report_renderer, "render_pdf_from_template", _fake_render_pdf_from_template
    )

    render_white_label_pdf(
        audit_id=321,
        audit_url="https://example.jp",
        geo_score=81.2,
        highlights=["FAQ coverage improved"],
        full_report=_sample_audit_payload(),
        branding=_build_branding_config(language="ja", report_type="standard"),
        include_competitor_analysis=False,
    )

    assert captured["context"]["is_cjk"] is True
    assert captured["context"]["branding"]["language"] == "ja"


def test_render_white_label_pdf_seeds_target_from_audit_record(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_render_pdf_from_template(
        *, template_name: str, context: dict, deterministic: bool = False
    ):
        captured["context"] = context
        return b"%PDF-fake"

    monkeypatch.setattr(
        pdf_report_renderer, "render_pdf_from_template", _fake_render_pdf_from_template
    )

    audit_record = SimpleNamespace(
        target_url=None,
        url="https://example.com",
        target_name="Acme Brand",
        target_metadata={"industry": "B2B SaaS"},
        created_at=datetime(2026, 2, 3, tzinfo=timezone.utc),
        audit_target_type=SimpleNamespace(value="brand"),
        project=SimpleNamespace(language="en"),
    )

    render_white_label_pdf(
        audit_id=456,
        audit_url="https://example.com",
        geo_score=84.0,
        highlights=["Entity profile improved"],
        full_report={"analysis": {"summary": "Structured metadata is maturing."}},
        branding=_build_branding_config(report_type="standard"),
        include_competitor_analysis=False,
        audit_record=audit_record,
    )

    context = captured["context"]
    assert context["target"]["name"] == "Acme Brand"
    assert context["target"]["type"] == "brand"
    assert context["report_type"] == "standard"


def test_build_report_context_strips_whitelabel_platform_branding():
    context = build_report_context(
        _sample_audit_payload(),
        "whitelabel",
        agency_branding_data={
            "agency_name": "Client Agency",
            "primary_color": "#112233",
            "generated_date": "2026-01-01",
        },
    )

    assert context["branding"]["show_platform_branding"] is False
    assert context["branding"]["vendor_name"] == ""
    assert "ThothGraph" not in json.dumps(context)


@pytest.mark.parametrize("report_type", ["whitelabel", "branded"])
def test_agency_covers_never_render_the_platform_lockup(monkeypatch, report_type):
    # The "Qiko mark + Signal word" lockup is platform branding. Agency and
    # white-label covers must render the agency's own logo or name only.
    captured: dict[str, str] = {}

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (DummyCSS, CapturingHTML),
    )
    context = build_report_context(
        _sample_audit_payload(),
        report_type,
        agency_branding_data={
            "agency_name": "Client Agency",
            "generated_date": "2026-01-01",
        },
    )

    render_pdf_from_template(template_name="white_label.html", context=context)

    cover = captured["html"].split("</section>", 1)[0]
    assert "cover-brand-word" not in cover
    assert QIKO_MARK_DATA_URI not in cover
    assert "Client Agency" in cover


def test_build_report_context_exposes_trust_banner_and_structured_roadmap():
    context = build_report_context(
        _sample_audit_payload(),
        "branded",
        agency_branding_data={
            "agency_name": "Client Agency",
            "primary_color": "#112233",
            "generated_date": "2026-01-01",
        },
    )

    assert context["report_kind"] == "executive"
    assert context["context_page"]["title"] == "Diagnostic Blueprint"
    assert context["integrity_page"]["certificate_items"]
    assert context["integrity_page"]["blocked_buckets"]
    assert context["integrity_page"]["review_notes"]
    action_item = context["sections"]["top_action_items"]["items"][0]
    assert action_item["owner"] == "Engineering"
    assert action_item["effort"] == "Medium"
    # AEO and GEO are internal AIO components; MVP kinds expose them as AIO.
    assert action_item["affected_scores"] == ["AIO"]
    # SIGV2-1211: no action item carries a predicted point gain. The old
    # "Expected impact: AIO +6 pts" string was built here and read by no
    # template, while all four action sections state that no predicted gain is
    # attached, so the helper is gone rather than wired up.
    assert "impact_summary" not in action_item


def test_build_report_context_humanizes_vision_only_overreach_bucket() -> None:
    payload = _sample_audit_payload()
    payload["integrity_certificate"]["blocked_claim_buckets"] = [
        {"track": "track_b", "category": "vision_only_overreach", "count": 2}
    ]

    context = build_report_context(
        payload,
        "branded",
        agency_branding_data={
            "agency_name": "Client Agency",
            "primary_color": "#112233",
            "generated_date": "2026-01-01",
        },
    )

    assert context["integrity_page"]["blocked_buckets"] == [
        {
            "track_label": "Track B",
            "category_label": "Vision Only Overreach",
            "count": 2,
        }
    ]


def test_build_report_context_exposes_standard_score_diagnostics():
    context = build_report_context(
        _sample_audit_payload(),
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
    )

    assert context["sections"]["trust_banner"]["items"]
    # The AEO and GEO panels merge into a single AIO panel for the MVP kinds.
    assert [panel["label"] for panel in context["sections"]["why_this_score"]["items"]] == [
        "SEO",
        "AIO",
    ]


def test_build_report_context_uses_the_approved_mark_everywhere():
    context = build_report_context(
        _sample_audit_payload(),
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
    )

    branding = context["branding"]
    assert branding["logo_data_uri"] == branding["header_logo_data_uri"]
    assert branding["header_logo_data_uri"].startswith("data:image/")
    assert branding["cover_logo_data_uri"].startswith("data:image/")
    # SIGV2-1275: header and cover both carry the bare approved Qiko mark.
    # The cover sets "Signal" in Satoshi beside it; the reportlab header
    # cannot (Satoshi is .woff2 only), so it shows the mark alone.
    assert branding["cover_logo_data_uri"] == QIKO_MARK_DATA_URI
    assert branding["header_logo_data_uri"] == QIKO_MARK_DATA_URI


def test_embedded_qiko_mark_matches_approved_brand_asset():
    # The cover mark must equal the approved frontend asset
    # (frontend/public/qiko-logo.png), pixel-identical to the mark inside
    # SignalBrandLockup, even when the frontend directory is absent from the
    # PDF worker image.
    prefix = "data:image/png;base64,"
    assert QIKO_MARK_DATA_URI.startswith(prefix)
    embedded = base64.b64decode(QIKO_MARK_DATA_URI[len(prefix) :])
    assert hashlib.sha256(embedded).hexdigest() == (
        "413bd8e0b3bec40fef931a05697db3b0126c0f556711b4282e935bd4fe987782"
    )


@pytest.mark.parametrize("report_kind", ["standard", "aio", "seo", "executive"])
def test_four_report_kinds_use_the_persisted_aio_and_seo_cover_scores(report_kind):
    payload = _sample_audit_payload()
    payload["metadata"]["aio"] = {
        "aio_score": 68,
        "scope": "The audited website",
        "summary": "AI answers cite some audited pages.",
    }
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={"report_kind": report_kind, "branding_mode": "platform"},
    )

    assert context["report_kind"] == report_kind
    assert context["scores"]["aio"] == 68
    assert context["scores"]["seo"] == 74
    assert [(card["label"], card["display_value"]) for card in context["scores"]["cards"]] == [
        ("AI visibility", "68"),
        ("Search visibility", "74"),
    ]
    if report_kind == "executive":
        assert [card["label"] for card in context["sections"]["executive_dashboard"]["cards"]] == [
            "AI visibility",
            "Search visibility",
        ]
    if report_kind == "aio":
        assert context["sections"]["aio_result"]["title"] == "AIO Score"
    if report_kind == "seo":
        assert context["sections"]["seo_overview"]["title"] == "SEO Score"


@pytest.mark.parametrize("report_kind", ["standard", "aio", "seo", "executive"])
def test_missing_aio_score_is_unavailable_not_inferred_from_geo_or_aeo(report_kind):
    context = build_report_context(
        _sample_audit_payload(),
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={"report_kind": report_kind, "branding_mode": "platform"},
    )

    assert context["scores"]["aio"] is None
    aio_card = next(card for card in context["scores"]["cards"] if card["label"] == "AI visibility")
    assert aio_card["display_value"] == "-"
    if report_kind == "executive":
        assert context["sections"]["executive_dashboard"]["cards"][0]["display_value"] == "-"


@pytest.mark.parametrize("report_kind", ["standard", "aio", "seo", "executive"])
def test_four_report_covers_render_aio_and_seo_score_titles(monkeypatch, report_kind):
    captured: dict[str, str] = {}

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (DummyCSS, CapturingHTML),
    )
    payload = _sample_audit_payload()
    payload["metadata"]["aio"] = {"aio_score": 68}
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={"report_kind": report_kind, "branding_mode": "platform"},
    )

    render_pdf_from_template(template_name="white_label.html", context=context)

    cover = captured["html"].split("</section>", 1)[0]
    expected_title = {
        "standard": "Visibility Report",
        "aio": "AIO Report",
        "seo": "SEO Report",
        "executive": "Executive Summary",
    }[report_kind]
    assert "cover-brand-text" not in cover
    # Approved cover lockup: the bare Qiko mark with "Signal" set in type.
    assert '<span class="cover-brand-word">Signal</span>' in cover
    assert f'<div class="cover-kicker">{expected_title}</div>' in cover
    assert '<div class="cover-card-label">AI visibility</div>' in cover
    assert '<div class="cover-card-label">Search visibility</div>' in cover
    if report_kind == "executive":
        score_section = captured["html"].split('<div class="pillar-score-grid">', 1)[1]
        score_section = score_section.split("</section>", 1)[0]
        assert re.findall(r'<div class="metric-label">([^<]+)</div>', score_section) == [
            "AI visibility",
            "Search visibility",
        ]


@pytest.mark.parametrize(
    ("report_kind", "expected_order"),
    [
        (
            "standard",
            [
                "what this report measures",
                "contents",
                "where you stand",
                "actions",
                "questions",
                "trust",
                "engines",
                "seo factors",
                "traffic",
                "evidence",
            ],
        ),
        (
            "aio",
            [
                "what this report measures",
                "contents",
                "where you stand",
                "actions",
                "questions",
                "trust",
                "engines",
                "evidence",
            ],
        ),
        (
            "seo",
            [
                "what this report measures",
                "contents",
                "where you stand",
                "actions",
                "seo factors",
                "traffic",
                "evidence",
            ],
        ),
        ("executive", ["what this report measures", "where you stand", "actions", "evidence"]),
    ],
)
def test_four_report_bodies_follow_the_mvp_heading_hierarchy(
    monkeypatch, report_kind, expected_order
):
    captured: dict[str, str] = {}

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (DummyCSS, CapturingHTML),
    )
    payload = _sample_audit_payload()
    payload["metadata"]["aio"] = {"aio_score": 23}
    payload["scores"]["seo"] = 41
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={"report_kind": report_kind, "branding_mode": "platform"},
    )

    render_pdf_from_template(template_name="white_label.html", context=context)

    html = captured["html"]
    headings = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip().lower()
        for text in re.findall(
            r'<h[12] class="(?:cover-title|section-title)">(.*?)</h[12]>', html, re.DOTALL
        )
    ]
    next_heading = 0
    for expected in expected_order:
        next_heading = next(
            index + 1 for index in range(next_heading, len(headings)) if expected in headings[index]
        )

    if report_kind == "executive":
        assert 'class="report-section toc-page"' not in html
    else:
        assert 'class="report-section toc-page"' in html

    # The two headline score cards are labelled with the approved customer-
    # facing names; AIO/SEO stay as pillar names in prose only.
    score_card_labels = re.findall(
        r'<div class="(?:metric-label|cover-card-label)">([^<]+)</div>', html
    )
    assert "AI visibility" in score_card_labels
    assert "Search visibility" in score_card_labels

    # AEO and GEO are internal components of AIO and must never appear as
    # standalone tokens in the customer-facing text of the four MVP kinds.
    visible_text = re.sub(r"<style.*?</style>", " ", html, flags=re.DOTALL)
    visible_text = re.sub(r"<[^>]+>", " ", visible_text)
    assert not re.search(r"\b(?:AEO|GEO)\b", visible_text)

    cover = html.split("</section>", 1)[0]
    assert re.findall(r'<div class="cover-card-value">([^<]+)<small>/100</small></div>', cover) == [
        "23",
        "41",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GEO and AEO", "AIO"),
        ("GEO, AEO and SEO", "AIO and SEO"),
        ("broader GEO and AEO gains.", "broader AIO gains."),
        ("GEO, AEO, SEO", "AIO, SEO"),
        ("AEO & GEO", "AIO"),
        ("SEO and GEO", "SEO and AIO"),
        ("no tokens here", "no tokens here"),
    ],
)
def test_publicize_aio_terms_collapses_repeated_aio_runs(raw, expected):
    assert _publicize_aio_terms(raw) == expected


def test_build_report_context_routes_executive_report_kind_to_blueprint_sections():
    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "executive_blueprint": {
            "target_name": "ExampleCo",
            "target_url": "https://example.com",
            "target_type": "website",
            "project_name": "Example Project",
            "icp_roles": ["CMO", "SEO Lead"],
            "usp": "Audit-backed visibility growth",
            "active_sources": [
                {"label": "Google Search Console", "mode": "Live Connection"},
            ],
            "supporting_references": [
                {"label": "Entity", "value": "ExampleCo"},
            ],
            "source_warnings": ["Ground-truth evidence is partially degraded."],
        }
    }

    context = build_report_context(
        payload,
        "branded",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "executive",
            "branding_mode": "platform",
            "hide_credit_cost": True,
            "template_type": "Executive",
        },
    )

    assert context["report_kind"] == "executive"
    assert context["context_page"]["title"] == "Diagnostic Blueprint"
    assert "executive_dashboard" in context["sections"]
    assert "why_this_score" not in context["sections"]
    assert context["integrity_page"]["title"] == "Integrity & Confidence Certificate"


def test_build_report_context_routes_project_report_kind_to_project_sections():
    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "project_report": {
            "audit_count": 3,
            "coverage_start": "2026-01-01T00:00:00Z",
            "coverage_end": "2026-03-01T00:00:00Z",
            "delta": {"seo": 6, "geo": 5, "aeo": 4, "overall": 5},
            "trend_points": [
                {"date": "2026-01-01T00:00:00Z", "overall": 68, "seo": 69, "geo": 66, "aeo": 69},
                {"date": "2026-03-01T00:00:00Z", "overall": 73, "seo": 75, "geo": 71, "aeo": 73},
            ],
            "task_status_summary": {"todo": 1, "in_progress": 1, "done": 2, "validated": 1},
            "task_movement": {
                "new": 2,
                "resolved": 1,
                "validated": 1,
                "new_titles": ["Refresh FAQ schema"],
                "resolved_titles": ["Fix duplicate canonicals"],
            },
            "validated_impact": [{"title": "Validated schema fix"}],
            "remaining_issues": ["Expand citations", "Tighten answer formatting"],
        }
    }

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "project",
            "branding_mode": "platform",
            "hide_credit_cost": True,
            "template_type": "Executive",
        },
    )

    assert context["report_kind"] == "project"
    assert context["context_page"]["title"] == "Project Context"
    assert "project_score_delta" in context["sections"]
    assert context["sections"]["task_movement"]["items"][0]["value"] == "2"
    assert "why_this_score" not in context["sections"]


def test_build_report_context_routes_financial_report_kind_to_ledger_sections():
    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "financial_report": {
            "redacted": False,
            "budget_status": "healthy",
            "current_period": {
                "start": "2026-03-01T00:00:00Z",
                "end": "2026-03-31T00:00:00Z",
                "consumed_credits": 21,
                "remaining_credits": 79,
            },
            "recent_periods": [
                {"period_start": "2026-02-01T00:00:00Z", "consumed_credits": 18},
            ],
            "ledger_rows": [
                {
                    "date": "2026-03-02T00:00:00Z",
                    "target": "example.com",
                    "credits_consumed": 7,
                    "estimated_credits": 9,
                    "audit_type": "audit",
                    "status": "completed",
                }
            ],
            "total_consumed_credits": 7,
            "run_count": 1,
        }
    }

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "financial",
            "branding_mode": "platform",
            "hide_credit_cost": False,
            "template_type": "Executive",
        },
    )

    assert context["report_kind"] == "financial"
    assert context["context_page"]["title"] == "Financial Context"
    assert "financial_summary" in context["sections"]
    assert context["sections"]["ledger_rows"]["items"][0]["credits_consumed"] == 7
    assert context["integrity_page"]["financial_disclosure"]["enabled"] is True


def test_build_report_context_strips_credit_cost_fields_when_hide_credit_cost_enabled():
    payload = _sample_audit_payload()
    payload["metadata"] = {
        **payload.get("metadata", {}),
        "estimated_credit_cost": 5,
        "consumed_credit_cost": 4,
        "remaining_credits": 91,
        "report_suite": {
            "financial_report": {
                "redacted": True,
                "redaction_reason": "Credit cost disclosure was withheld for client presentation.",
                "budget_status": "healthy",
                "period_count": 2,
            }
        },
    }

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "financial",
            "branding_mode": "platform",
            "hide_credit_cost": True,
            "template_type": "Executive",
        },
    )

    serialized = json.dumps(context)
    assert "estimated_credit_cost" not in serialized
    assert "consumed_credit_cost" not in serialized
    assert "remaining_credits" not in serialized
    assert context["export_manifest"]["hide_credit_cost"] is True
    assert context["sections"]["redaction_notice"]["title"] == "Credit cost disclosure withheld"


def test_build_report_context_exposes_competitor_trend_timeline_for_battle_exports():
    payload = _sample_audit_payload()
    payload["metadata"]["competitor_summary"]["trend_timeline"] = {
        "enabled": True,
        "project_label": "example.com",
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-03-01T00:00:00Z",
        "audit_count": 4,
        "competitors": [
            {
                "name": "Leader Corp",
                "project_points": [
                    {
                        "date": "2026-01-01T00:00:00Z",
                        "overall": 68,
                        "seo": 70,
                        "geo": 66,
                        "aeo": 68,
                    },
                    {
                        "date": "2026-03-01T00:00:00Z",
                        "overall": 74,
                        "seo": 74,
                        "geo": 71,
                        "aeo": 76,
                    },
                ],
                "competitor_points": [
                    {
                        "date": "2026-01-01T00:00:00Z",
                        "overall": 75,
                        "seo": 75,
                        "geo": 76,
                        "aeo": 74,
                    },
                    {
                        "date": "2026-03-01T00:00:00Z",
                        "overall": 77,
                        "seo": 76,
                        "geo": 79,
                        "aeo": 78,
                    },
                ],
                "project_latest": {"overall": 74},
                "competitor_latest": {"overall": 77},
                "project_delta_overall": 6,
                "competitor_delta_overall": 2,
            }
        ],
    }

    context = build_report_context(
        payload,
        "battle",
        agency_branding_data={"generated_date": "2026-03-01"},
        export_manifest={
            "report_kind": "competitors",
            "branding_mode": "platform",
            "competitor_mode": "trend",
            "render_report_type": "battle",
            "hide_credit_cost": True,
        },
    )

    trend_section = context["sections"]["competitive_trend_timeline"]
    assert context["context_page"]["title"] == "Competitive Context"
    assert trend_section["enabled"] is True
    assert trend_section["coverage_start"] == "January 01, 2026"
    assert trend_section["competitors"][0]["name"] == "Leader Corp"
    assert trend_section["competitors"][0]["project_latest_overall"] == "74"
    assert "why_this_score" not in context["sections"]


def test_resolve_asset_data_uri_rejects_unsafe_remote_url():
    assert resolve_asset_data_uri("http://localhost/logo.png") is None
    assert resolve_asset_data_uri("https://127.0.0.1/logo.png") is None


def test_render_pdf_from_template_normalizes_pdf_bytes_when_deterministic(monkeypatch):
    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint", lambda: (DummyCSS, DummyHTML)
    )

    context = build_report_context(
        _sample_audit_payload(),
        "standard",
        agency_branding_data={
            "agency_name": "Acme",
            "primary_color": "#112233",
            "secondary_color": "#334455",
            "generated_date": "2026-01-01",
        },
    )
    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
        deterministic=True,
    )

    assert pdf.startswith(b"%PDF")
    assert b"D:20260519101010Z" not in pdf
    assert b"D:20240101000000Z" in pdf
    assert b"abcdef" not in pdf


def test_render_pdf_from_template_falls_back_when_shared_pages_are_missing(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        def __init__(self, string: str, base_url: str | None = None):
            captured["css"] = string
            super().__init__(string, base_url)

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    context = build_report_context(
        _sample_audit_payload(),
        "whitelabel",
        agency_branding_data={
            "agency_name": "Acme",
            "primary_color": "#112233",
            "secondary_color": "#334455",
            "generated_date": "2026-01-01",
        },
    )
    context.pop("context_page", None)
    context.pop("integrity_page", None)

    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    # The MVP context page renders its approved static copy even when no
    # persisted context page was supplied.
    assert "What this report measures" in captured["html"]
    # Autoescaping is on (SIGV2-1224), so the ampersand reaches the source
    # as `&amp;`. The heading the reader sees is unchanged, which is what
    # this assertion is about, so it is made against the decoded text.
    assert "Integrity & Confidence Certificate" in unescape(captured["html"])
    assert (
        "Grounding and review metadata were not available for this export context."
        in captured["html"]
    )


def test_render_pdf_from_template_avoids_missing_report_css_and_known_weasyprint_warnings(
    monkeypatch,
):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        def __init__(self, string: str, base_url: str | None = None):
            captured["css"] = string
            super().__init__(string, base_url)

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    context = build_report_context(
        _sample_audit_payload(),
        "branded",
        agency_branding_data={
            "agency_name": "Acme",
            "primary_color": "#112233",
            "secondary_color": "#334455",
            "generated_date": "2026-01-01",
        },
    )
    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    assert 'href="report.css"' not in captured["html"]
    # Decoded for the same reason as above: the escaped ampersand is a
    # source-level detail, the displayed heading is unchanged.
    assert "Integrity & Confidence Certificate" in unescape(captured["html"])
    assert "Blocked Claim Buckets" in captured["html"]
    assert "Track B Judge Unavailable" in captured["html"]
    stylesheet = str(captured["css"])
    assert "font-weight: 750" not in stylesheet
    for declaration in (
        "flex: 1 1 calc(33.333% - 4mm)",
        "box-shadow",
        "fill: none",
        "stroke-width: 12",
        "stroke-linecap: round",
        "inset: 0",
    ):
        assert declaration not in stylesheet


def test_render_pdf_from_template_renders_executive_context_lists(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        pass

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "executive_blueprint": {
            "target_name": "ExampleCo",
            "target_url": "https://example.com",
            "target_type": "website",
            "project_name": "Example Project",
            "icp_roles": ["CMO", "SEO Lead"],
            "usp": "Audit-backed visibility growth",
            "active_sources": [
                {"label": "Google Search Console", "mode": "Live Connection"},
            ],
            "supporting_references": [
                {"label": "Entity", "value": "ExampleCo"},
            ],
        }
    }
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "executive",
            "branding_mode": "platform",
            "hide_credit_cost": True,
            "template_type": "Executive",
        },
    )

    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    assert "Connected sources" in captured["html"]
    assert "Google Search Console (Live Connection)" in captured["html"]
    assert "CMO" in captured["html"]


def test_render_pdf_from_template_uses_compact_standard_layout_and_logo_variants(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        def __init__(self, string: str, base_url: str | None = None):
            captured["css"] = string
            super().__init__(string, base_url)

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    context = build_report_context(
        _sample_audit_payload(),
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
    )

    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    assert "report-kind-standard" in captured["html"]
    # The header logo is drawn by the reportlab chrome overlay, not the HTML;
    # the cover embeds the bare Qiko mark next to the typeset "Signal" word.
    assert context["branding"]["cover_logo_data_uri"] in captured["html"]
    assert '<span class="cover-brand-word">Signal</span>' in captured["html"]
    stylesheet = str(captured["css"])
    # The four MVP kinds give each named section its own page, except the
    # section immediately after the cover, which follows it on the same sheet.
    for kind in ("standard", "aio", "seo", "executive"):
        assert f"body.report-kind-{kind} .report-section" in stylesheet
        assert f"body.report-kind-{kind} .report-cover + .report-section" in stylesheet
    section_rule = re.search(
        r"body\.report-kind-standard \.report-section,\s*"
        r"body\.report-kind-aio \.report-section,\s*"
        r"body\.report-kind-seo \.report-section,\s*"
        r"body\.report-kind-executive \.report-section\s*\{([^}]+)\}",
        stylesheet,
    )
    assert section_rule is not None
    assert "break-before: page;" in section_rule.group(1)
    assert "page-break-before: always;" in section_rule.group(1)
    assert "break-before: auto;" in stylesheet
    assert "page-break-before: auto;" in stylesheet
    assert ".metric-card.four-up," in stylesheet


def test_render_pdf_from_template_renders_project_summary_cards_inline(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        pass

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "project_report": {
            "audit_count": 3,
            "coverage_start": "2026-01-01T00:00:00Z",
            "coverage_end": "2026-03-01T00:00:00Z",
            "delta": {"seo": 6, "geo": 5, "aeo": 4, "overall": 5},
            "trend_points": [
                {"date": "2026-01-01T00:00:00Z", "overall": 68, "seo": 69, "geo": 66, "aeo": 69},
                {"date": "2026-03-01T00:00:00Z", "overall": 73, "seo": 75, "geo": 71, "aeo": 73},
            ],
            "task_status_summary": {"todo": 1, "in_progress": 1, "done": 2, "validated": 1},
            "task_movement": {
                "new": 2,
                "resolved": 1,
                "validated": 1,
                "new_titles": ["Refresh FAQ schema"],
                "resolved_titles": ["Fix duplicate canonicals"],
            },
            "validated_impact": [{"title": "Validated schema fix"}],
            "remaining_issues": ["Expand citations", "Tighten answer formatting"],
        }
    }
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "project",
            "branding_mode": "platform",
            "hide_credit_cost": True,
            "template_type": "Executive",
        },
    )

    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    assert "Project Score Delta" in captured["html"]
    assert "Action status" in captured["html"]
    assert 'class="metric-card four-up' in captured["html"]


def test_render_pdf_from_template_renders_financial_disclosure_items(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingCSS(DummyCSS):
        pass

    class CapturingHTML(DummyHTML):
        def __init__(self, string: str, base_url: str | None = None):
            captured["html"] = string
            super().__init__(string, base_url)

        def write_pdf(self, stylesheets=None):
            captured["stylesheets"] = stylesheets
            return b"%PDF-fake"

    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint",
        lambda: (CapturingCSS, CapturingHTML),
    )

    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "financial_report": {
            "redacted": False,
            "budget_status": "healthy",
            "current_period": {
                "start": "2026-03-01T00:00:00Z",
                "end": "2026-03-31T00:00:00Z",
                "consumed_credits": 21,
                "remaining_credits": 79,
            },
            "ledger_rows": [],
            "total_consumed_credits": 7,
            "run_count": 1,
        }
    }
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01"},
        export_manifest={
            "report_kind": "financial",
            "branding_mode": "platform",
            "hide_credit_cost": False,
            "template_type": "Executive",
        },
    )

    pdf = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
    )

    assert pdf == b"%PDF-fake"
    assert "Financial Disclosure" in captured["html"]
    assert "Total consumed" in captured["html"]
    assert "7 credits" in captured["html"]
    assert 'class="metric-card four-up' in captured["html"]
    assert 'class="panel-card four-up' in captured["html"]


def test_render_pdf_from_template_renders_battle_report(monkeypatch):
    monkeypatch.setattr(
        "services.pdf_reports.renderer._load_weasyprint", lambda: (DummyCSS, DummyHTML)
    )

    context = build_report_context(
        _sample_audit_payload(),
        "battle",
        agency_branding_data={
            "primary_color": "#112233",
            "secondary_color": "#334455",
            "generated_date": "2026-01-01",
        },
    )
    pdf = render_pdf_from_template(
        template_name="battle.html",
        context=context,
    )

    assert pdf.startswith(b"%PDF")


def test_render_pdf_from_template_raises_when_weasyprint_unavailable(monkeypatch):
    monkeypatch.setattr("services.pdf_reports.renderer._load_weasyprint", lambda: (None, None))

    try:
        render_pdf_from_template(template_name="white_label.html", context={})
    except RuntimeError as exc:
        assert "WeasyPrint" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when WeasyPrint is unavailable")
