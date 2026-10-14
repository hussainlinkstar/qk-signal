"""SIGV2-1047: Signal MVP branding and two-pillar (AIO + SEO) email alignment."""

import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.aio_view import derive_aio
from services import email_templates
from services.project_competitive_service import _rank_metrics


def _render(template_key: str, **overrides) -> str:
    if template_key == "guest_audit_followup":
        # Rendered directly by guest_audit_service, not via TEMPLATE_DEFINITIONS.
        context = {
            "brand_name": "Qiko Signal",
            "email_i18n": {},
            "support_address": "support@qiko.ai",
            "current_year": 2026,
            "subject": "Your AI audit report is waiting",
            "is_transactional": True,
        }
        context.update(overrides)
        return email_templates.env.get_template(f"{template_key}.html").render(**context)
    context = {
        "email": "qa@example.com",
        "target_url": "https://example.com",
        "report_url": "https://app.example.com/reports/1",
        "dashboard_url": "https://app.example.com/dashboard",
        "signup_url": "https://app.example.com/signup",
        "target_name": "example.com",
        "geo_score": 70,
        "seo_score": 60,
        "aeo_score": 80,
        "overall_score": 70,
        "current_scores": {"seo": 80, "geo": 75, "aeo": 85, "audit_count": 12},
        "delta": {"seo": "+5", "geo": "+3", "aeo": "+8"},
        "current_rank": {"aio": 1, "seo": 2, "geo": 1, "aeo": 1},
        "highlights": ["Benchmark refreshed."],
        "report_month_label": "March 2026",
    }
    context.update(overrides)
    return email_templates.render_template(template_key, context).html


class TestTwoPillarRendering:
    TEMPLATE_KEYS = (
        "audit.completed",
        "audit.consensus_ready",
        "project.progress_report",
        "competitive.digest",
        "guest_audit_followup",
    )

    def test_each_template_shows_only_aio_and_seo(self):
        for key in self.TEMPLATE_KEYS:
            overrides = {"aio_score": 70, "seo_score": 60} if key == "guest_audit_followup" else {}
            html = _render(key, **overrides)
            assert re.search(r'class="score-label">\s*AIO', html), key
            assert re.search(r'class="score-label">\s*SEO', html), key
            for forbidden_label in ("AI visibility", "Search visibility"):
                assert forbidden_label not in html, f"{key} leaked {forbidden_label}"
            for forbidden in ("GEO", "AEO", ">Geo<", ">Aeo<"):
                assert forbidden not in html, f"{key} leaked {forbidden}"

    def test_aio_matches_canonical_rollup(self):
        expected = derive_aio({"aeo_score": 91, "geo_score": 85})["aio_score"]
        assert expected == 88
        html = _render("audit.completed", aeo_score=91, geo_score=85)
        values = re.findall(r'class="score-value">(\d+|--)', html)
        assert str(expected) in values
        assert "91" not in values
        assert "85" not in values

    def test_single_component_fallback(self):
        html = _render("audit.completed", geo_score=70, aeo_score=None)
        values = re.findall(r'class="score-value">(\d+|--)', html)
        assert "70" in values

    def test_no_components_renders_dashes_never_zero(self):
        html = _render("audit.completed", geo_score=None, aeo_score=None)
        values = re.findall(r'class="score-value">(\d+|--)', html)
        assert "--" in values
        assert "0" not in values

    def test_progress_report_aio_delta_mean(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+5", "aeo": "+8", "geo": "+2"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines[0] == "Up 5 points since last month"

    def test_progress_report_aio_delta_single_component(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+5", "aeo": "+8"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines[0] == "Up 8 points since last month"

    def test_progress_report_aio_delta_missing(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+5"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["Up 5 points since last month"]


class TestScoreMovement:
    def test_progress_report_renders_movement_on_both_cards(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+5", "aeo": "+8", "geo": "+2"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == [
            "Up 5 points since last month",
            "Up 5 points since last month",
        ]

    def test_fractional_movement_rounds_half_up(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+5.4", "aeo": "+8", "geo": "+3"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["Up 6 points since last month", "Up 5 points since last month"]
        assert "5.5" not in html
        assert "5.4" not in html

    def test_singular_point_is_not_pluralised(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+1", "aeo": "+2", "geo": "0"},
        )
        assert "Up 1 point since last month" in html
        assert "Up 1 points" not in html

    def test_downward_and_flat_movement(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "0", "aeo": "-4", "geo": "-4"},
        )
        assert "Down 4 points since last month" in html
        assert "No change since last month" in html

    def test_sub_point_movement_rounds_to_flat(self):
        html = _render(
            "project.progress_report",
            delta={"seo": "+0.4", "aeo": "-0.4", "geo": "-0.4"},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["No change since last month", "No change since last month"]

    def test_missing_delta_omits_the_line(self):
        html = _render("project.progress_report", delta={"seo": "+5"})
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["Up 5 points since last month"]

    def test_digest_rank_movement(self):
        html = _render(
            "competitive.digest",
            current_rank={"aio": 1, "seo": 2},
            previous_rank={"aio": 3, "seo": 2},
        )
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["Up from #3", "No change"]

    def test_non_numeric_rank_renders_without_movement(self):
        html = _render(
            "competitive.digest",
            current_rank={"aio": "high", "seo": 2},
            previous_rank={"aio": 1, "seo": 2},
        )
        assert 'class="score-card aio"' in html
        lines = re.findall(r'class="score-desc">([^<]+)<', html)
        assert lines == ["No change"]

    def test_no_baseline_means_no_movement_line(self):
        html = _render("competitive.digest")
        assert 'class="score-desc"' not in html
        html = _render("audit.completed")
        assert 'class="score-desc"' not in html


class TestAlertMetricLabels:
    def test_internal_metric_keys_map_to_plain_labels(self):
        cases = {
            "geo_score": "AIO",
            "aeo_score": "AIO",
            "aio_score": "AIO",
            "ai_visibility_score": "AIO",
            "seo_score": "SEO",
        }
        for raw, expected in cases.items():
            html = _render("alert.triggered", metric_name=raw, message="drop detected")
            assert f"Metric:</span> {expected}" in html, raw
            for forbidden in ("GEO", "AEO", "Geo", "Aeo"):
                assert forbidden not in html, f"{raw} leaked {forbidden}"

    def test_unknown_metric_key_never_echoes(self):
        html = _render("alert.triggered", metric_name="internal_secret_key")
        assert "Metric:</span> Visibility score" in html
        assert "internal_secret_key" not in html


class TestRenderPurity:
    def test_render_template_does_not_mutate_context(self):
        context = {
            "email": "qa@example.com",
            "report_url": "https://app.example.com/reports/1",
            "report_month_label": "March 2026",
            "current_scores": {"seo": 80, "geo": 75, "aeo": 85, "audit_count": 12},
            "delta": {"seo": "+5", "geo": "+3", "aeo": "+8"},
        }
        snapshot = copy.deepcopy(context)
        email_templates.render_template("project.progress_report", context)
        assert context == snapshot


class TestMvpPalette:
    def test_tokens_present_old_palette_absent(self):
        html = _render("audit.completed")
        for token in ("#0C0F16", "#F6F7F9", "#9333EA"):
            assert token in html
        for legacy in ("#6366F1", "#E2E2E2", "#2B2B2D", "#6F6E6F", "#D4D4D8"):
            assert legacy not in html


class TestAccessibility:
    def test_light_mode_muted_text_uses_aa_compliant_grey(self):
        html = _render("audit.completed")
        assert "#5F6876" in html
        for selector in (".brand-sig", ".score-label", ".score-value small"):
            rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", html)
            assert rule, selector
            assert "#8A92A1" not in rule.group(1), selector

    def test_footer_links_are_underlined(self):
        html = _render("audit.completed")
        rule = re.search(r"\.footer-copy a\s*\{([^}]*)\}", html)
        assert rule
        assert "text-decoration: underline" in rule.group(1)

    def test_unsubscribe_link_label_and_guard(self):
        html = _render(
            "audit.completed",
            unsubscribe_token="tok123",
            is_transactional=False,
        )
        assert ">Unsubscribe</a>" in html
        transactional = _render(
            "audit.completed",
            unsubscribe_token="tok123",
            is_transactional=True,
        )
        assert ">Unsubscribe</a>" not in transactional
        no_token = _render("audit.completed", is_transactional=False)
        assert ">Unsubscribe</a>" not in no_token

    def test_company_address_is_escaped(self):
        html = _render(
            "audit.completed",
            company_legal_name="Acme SRL",
            company_address='<a href="https://evil.example">click</a>',
            is_transactional=False,
        )
        assert "&lt;a href=" in html
        assert '<a href="https://evil.example"' not in html

    def test_company_address_newline_still_joined(self):
        html = _render(
            "audit.completed",
            company_legal_name="Acme SRL",
            company_address="Line One\nLine Two",
            is_transactional=False,
        )
        assert "Line One, Line Two" in html


class TestBrandLockup:
    def test_default_lockup_renders_logo_and_signal_wordmark(self):
        html = _render("audit.completed")
        assert "/email/qiko-logo.png" in html
        assert ">Signal</span>" in html

    def test_custom_logo_suppresses_signal_wordmark(self):
        html = _render(
            "audit.completed",
            custom_logo_url="https://cdn.example.com/branding/acme-logo.png",
        )
        assert "acme-logo.png" in html
        assert ">Signal</span>" not in html
        assert "/email/qiko-logo.png" not in html


class TestAioRank:
    def test_aio_rank_uses_derived_score_not_component_or_averaged_ranks(self):
        # AIO ordering deliberately differs from both GEO and AEO ordering.
        project_scores = {"geo": 94, "seo": 90, "aeo": 90, "overall": 80}
        competitors = [
            {"geo": 95, "seo": 10, "aeo": 10, "overall": 40},  # AIO 53
            {"geo": 60, "seo": 10, "aeo": 95, "overall": 50},  # AIO 78
        ]
        # project AIO = mean(90, 94) = 92 -> rank 1; GEO rank 2; AEO rank 2.
        ranks = _rank_metrics(project_scores, competitors)
        assert ranks["aio"] == 1
        assert ranks["geo"] == 2
        assert ranks["aeo"] == 2
        # Ranking on a component or averaging component ranks would give 2.

    def test_aio_rank_none_when_project_has_no_components(self):
        project_scores = {"geo": None, "seo": 90, "aeo": None, "overall": None}
        competitors = [{"geo": 50, "seo": 10, "aeo": 50, "overall": 40}]
        ranks = _rank_metrics(project_scores, competitors)
        assert ranks["aio"] is None
        assert ranks["seo"] == 1
