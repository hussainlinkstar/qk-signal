"""SIGV2-1080: end-to-end render of the whole transactional email suite.

Every template is rendered against the shared realistic preview context in every
supported language. The suite asserts that nothing falls back to the error body,
that no placeholder survives into the output, that AIO and SEO are named the way
the product names them, and that no customer-facing email carries credit or
internal cost language.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.email_templates import (
    DEFAULT_PREVIEW_CONTEXT,
    RENDER_FAILURE_MARKER,
    TEMPLATE_DEFINITIONS,
    render_template,
)
from services.report_i18n_service import SUPPORTED_REPORT_LANGUAGES

# These two go to ADMIN_EMAILS, never to a customer, so they keep cost language.
INTERNAL_TEMPLATE_KEYS = frozenset({"admin_system_alert", "admin.model_lifecycle_alert"})

CUSTOMER_FACING_KEYS = tuple(
    key for key in TEMPLATE_DEFINITIONS if key not in INTERNAL_TEMPLATE_KEYS
)
ALL_KEYS = tuple(TEMPLATE_DEFINITIONS)

EMPTY_DETAIL_ROW = re.compile(r'detail-label">[^<]*</span>\s*</div>')
SCORE_LABEL = re.compile(r'class="score-label">([^<]*)<')
JINJA_LEFTOVER = re.compile(r"\{\{|\{%")


def _render(key: str, **overrides):
    return render_template(key, {**DEFAULT_PREVIEW_CONTEXT, **overrides})


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_template_renders_without_falling_back(key: str) -> None:
    rendered = _render(key)
    assert RENDER_FAILURE_MARKER not in rendered.html, key
    assert rendered.subject.strip(), key
    assert rendered.category == TEMPLATE_DEFINITIONS[key].category, key
    assert len(rendered.html) > 2000, key


@pytest.mark.parametrize("key", ALL_KEYS)
def test_no_placeholder_survives_into_the_output(key: str) -> None:
    rendered = _render(key)
    assert not JINJA_LEFTOVER.search(rendered.html), key
    assert not JINJA_LEFTOVER.search(rendered.subject), key
    assert not JINJA_LEFTOVER.search(rendered.text), key
    leftovers = EMPTY_DETAIL_ROW.findall(rendered.html)
    assert not leftovers, f"{key} rendered an empty detail row: {leftovers}"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_template_renders_in_every_supported_language(key: str) -> None:
    for language in SUPPORTED_REPORT_LANGUAGES:
        rendered = _render(key, lang=language)
        assert RENDER_FAILURE_MARKER not in rendered.html, (key, language)
        assert not JINJA_LEFTOVER.search(rendered.html), (key, language)


@pytest.mark.parametrize("key", CUSTOMER_FACING_KEYS)
def test_customer_facing_templates_never_mention_credits(key: str) -> None:
    rendered = _render(key)
    for surface, value in (
        ("subject", rendered.subject),
        ("html", rendered.html),
        ("text", rendered.text),
    ):
        assert "credit" not in value.lower(), f"{key} leaked credit language in {surface}"


@pytest.mark.parametrize("key", CUSTOMER_FACING_KEYS)
def test_customer_facing_templates_never_reference_a_credit_field(key: str) -> None:
    # A credit-denominated variable renders as a bare number, so the rendered
    # body cannot reveal the leak. The template source can.
    template_path = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / TEMPLATE_DEFINITIONS[key].html_template
    )
    source = template_path.read_text(encoding="utf-8").lower()
    assert "credit" not in source, f"{key} reads a credit-denominated field"


def test_internal_alerts_keep_their_credit_language() -> None:
    rendered = render_template(
        "admin_system_alert",
        {
            **DEFAULT_PREVIEW_CONTEXT,
            "rule_name": "negative_credit_balance",
            "metric_key": "user_credit_balance",
            "message": "User 17 internal credit balance is -4 (plan plan_standard).",
        },
    )
    assert "internal credit balance" in rendered.html.lower()
    assert rendered.category == "system_alert"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_no_email_attributes_our_score_to_google(key: str) -> None:
    rendered = _render(key)
    lowered = rendered.html.lower()
    assert "google score" not in lowered, key
    assert "ai visibility score" not in lowered, key
    assert "search visibility score" not in lowered, key


@pytest.mark.parametrize(
    "key",
    (
        "audit.completed",
        "audit.consensus_ready",
        "project.progress_report",
        "competitive.digest",
        "guest_audit.followup",
    ),
)
def test_score_cards_are_labelled_aio_score_and_seo_score(key: str) -> None:
    labels = [label.strip() for label in SCORE_LABEL.findall(_render(key).html)]
    assert labels == ["AIO score", "SEO score"], key


def test_score_card_labels_are_localized() -> None:
    expected = {
        "en": ["AIO score", "SEO score"],
        "fr": ["Score AIO", "Score SEO"],
        "de": ["AIO-Score", "SEO-Score"],
        "ar": ["درجة AIO", "درجة SEO"],
    }
    for language, labels in expected.items():
        rendered = _render("audit.completed", lang=language)
        assert [found.strip() for found in SCORE_LABEL.findall(rendered.html)] == labels, language


def test_alert_metric_rows_name_the_score() -> None:
    assert "Metric:</span> AIO score" in _render("alert.triggered", metric_name="aio_score").html
    assert "Metric:</span> SEO score" in _render("alert.triggered", metric_name="seo_score").html
    assert "Metric:</span> AIO score" in _render("alert.visibility_score_drop").html


@pytest.mark.parametrize("key", CUSTOMER_FACING_KEYS)
def test_allowances_are_denominated_in_scans(key: str) -> None:
    lowered = _render(key).html.lower()
    for forbidden in ("audits/mo", "audits / month", "audits/month", "audits per month"):
        assert forbidden not in lowered, f"{key} states an allowance in audits"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_no_em_dash_in_any_rendered_email(key: str) -> None:
    rendered = _render(key)
    for language in SUPPORTED_REPORT_LANGUAGES:
        localized = _render(key, lang=language)
        assert "\u2014" not in localized.html, (key, language)
    assert "\u2014" not in rendered.subject, key
    assert "\u2014" not in rendered.text, key
