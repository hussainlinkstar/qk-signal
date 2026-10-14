"""Tests for services.model_lifecycle_monitor_service."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from services.model_lifecycle_monitor_service import (
    MONITOR_SOURCES,
    _active_bedrock_models,
    _bedrock_family_token,
    _build_alerts_from_diff,
    _classify_severity,
    _extract_model_references,
    _hash_content,
    _is_our_model,
    _strip_html,
    _MODEL_PATTERNS,
    run_model_lifecycle_check,
)


# ── _strip_html ─────────────────────────────────────────────────────


class TestStripHtml:
    def test_strip_html_basic(self) -> None:
        raw = (
            "<html><head><script>var x=1;</script>"
            "<style>body{color:red}</style></head>"
            "<body><p>Hello &amp; World</p></body></html>"
        )
        result = _strip_html(raw)
        # Scripts and styles removed
        assert "var x=1" not in result
        assert "color:red" not in result
        # Tags removed
        assert "<p>" not in result
        assert "<html>" not in result
        # Entity decoded
        assert "Hello & World" in result

    def test_strip_html_empty(self) -> None:
        assert _strip_html("") == ""


# ── _hash_content ───────────────────────────────────────────────────


class TestHashContent:
    def test_hash_content_deterministic(self) -> None:
        text = "some page content"
        h1 = _hash_content(text)
        h2 = _hash_content(text)
        assert h1 == h2
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert h1 == expected

        # Different input → different hash
        assert _hash_content("different") != h1


# ── _extract_model_references ───────────────────────────────────────


class TestExtractModelReferences:
    def test_extract_model_references_openai(self) -> None:
        text = "The model gpt-5.4-nano has been deprecated as of 2025-06-01."
        refs = _extract_model_references(text, "openai")
        assert len(refs) >= 1
        entry = refs[0]
        assert entry["model"] == "gpt-5.4-nano"
        # Post-Bedrock cutover we don't run GPT, so it is not "ours".
        assert entry["is_ours"] is False
        assert "deprecated" in entry.get("lifecycle_keywords", [])

    def test_extract_model_references_google(self) -> None:
        text = "We are releasing gemini-2.5-flash as a stable model."
        refs = _extract_model_references(text, "google")
        names = [r["model"] for r in refs]
        assert "gemini-2.5-flash" in names
        flash_entry = next(r for r in refs if r["model"] == "gemini-2.5-flash")
        # Gemini is not run via Bedrock → not ours.
        assert flash_entry["is_ours"] is False
        assert "stable" in flash_entry.get("lifecycle_keywords", [])

    def test_extract_model_references_anthropic(self) -> None:
        # claude-sonnet-4-5 is extracted by the Anthropic pattern, but is no
        # longer configured as our active Bedrock smart model.
        text = "claude-sonnet-4-5 is now available in preview."
        refs = _extract_model_references(text, "anthropic")
        names = [r["model"] for r in refs]
        assert "claude-sonnet-4-5" in names
        entry = next(r for r in refs if r["model"] == "claude-sonnet-4-5")
        assert entry["is_ours"] is False

    def test_extract_model_references_unknown_model(self) -> None:
        text = "gpt-99-turbo is a hypothetical model nobody uses."
        refs = _extract_model_references(text, "openai")
        names = [r["model"] for r in refs]
        assert "gpt-99-turbo" in names
        entry = next(r for r in refs if r["model"] == "gpt-99-turbo")
        assert entry["is_ours"] is False

    def test_non_our_model_appeared_has_empty_affected_models(self) -> None:
        # A non-ours model appearing must NOT populate affected_models, so the
        # email gate (which requires affected_models) stays silent for it.
        curr = [{"model": "gpt-5.4-nano", "is_ours": False, "lifecycle_keywords": ["deprecated"]}]
        alerts = _build_alerts_from_diff("openai", "http://x", "deprecations", None, curr)
        assert len(alerts) == 1
        assert alerts[0]["affected_models"] == []

    def test_our_model_appeared_populates_affected_models(self) -> None:
        curr = [{"model": "nova-pro", "is_ours": True, "lifecycle_keywords": ["deprecated"]}]
        alerts = _build_alerts_from_diff("openai", "http://x", "deprecations", None, curr)
        assert alerts[0]["affected_models"] == ["nova-pro"]
        assert alerts[0]["severity"] == "critical"

    def test_extract_model_references_no_provider_pattern(self) -> None:
        text = "gpt-5.4-nano and gemini-2.5-flash are listed."
        refs = _extract_model_references(text, "unknown")
        assert refs == []

    def test_extract_model_references_dedup(self) -> None:
        text = "gpt-5.4-nano is great. We love gpt-5.4-nano. " "Did I mention gpt-5.4-nano?"
        refs = _extract_model_references(text, "openai")
        model_names = [r["model"] for r in refs]
        assert model_names.count("gpt-5.4-nano") == 1


class TestBedrockAnchoring:
    def test_bedrock_family_token(self) -> None:
        assert (
            _bedrock_family_token("eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
            == "claude-sonnet-4-5"
        )
        assert _bedrock_family_token("eu.amazon.nova-lite-v1:0") == "nova-lite"

    def test_active_bedrock_models_includes_configured(self) -> None:
        active = _active_bedrock_models()
        assert "nova-pro" in active
        assert any(fam.startswith("nova") for fam in active)

    def test_is_our_model(self) -> None:
        active = {"nova-pro", "nova-lite"}
        assert _is_our_model("nova-pro", active) is True
        assert _is_our_model("gpt-5.4-nano", active) is False


# ── _classify_severity ──────────────────────────────────────────────


class TestClassifySeverity:
    def test_classify_severity_critical(self) -> None:
        result = _classify_severity(
            alert_type="lifecycle_change",
            affected_our_models=["gpt-5.4-nano"],
            lifecycle_keywords=["deprecated"],
        )
        assert result == "critical"

    def test_classify_severity_warning_our_models(self) -> None:
        result = _classify_severity(
            alert_type="model_appeared",
            affected_our_models=["gpt-5.4-nano"],
            lifecycle_keywords=["preview"],
        )
        assert result == "warning"

    def test_classify_severity_info_page_changed(self) -> None:
        result = _classify_severity(
            alert_type="page_changed",
            affected_our_models=[],
            lifecycle_keywords=[],
        )
        assert result == "info"

    def test_classify_severity_warning_default(self) -> None:
        result = _classify_severity(
            alert_type="model_appeared",
            affected_our_models=[],
            lifecycle_keywords=[],
        )
        assert result == "warning"


# ── _build_alerts_from_diff ─────────────────────────────────────────


class TestBuildAlertsFromDiff:
    def test_build_alerts_new_model_appeared(self) -> None:
        prev: list[dict] = []
        curr = [{"model": "gpt-5.4-nano", "is_ours": True, "lifecycle_keywords": ["deprecated"]}]
        alerts = _build_alerts_from_diff(
            "openai", "https://example.com", "deprecations", prev, curr
        )
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "model_appeared"
        assert "gpt-5.4-nano" in alert["affected_models"]
        assert alert["severity"] == "critical"  # our model + deprecated
        assert "THIS MODEL IS USED IN OUR APPLICATION" in alert["description"]

    def test_build_alerts_lifecycle_change(self) -> None:
        prev = [{"model": "gpt-5.4-nano", "is_ours": True, "lifecycle_keywords": ["preview"]}]
        curr = [
            {
                "model": "gpt-5.4-nano",
                "is_ours": True,
                "lifecycle_keywords": ["preview", "deprecated"],
            }
        ]
        alerts = _build_alerts_from_diff(
            "openai", "https://example.com", "deprecations", prev, curr
        )
        lifecycle_alerts = [a for a in alerts if a["alert_type"] == "lifecycle_change"]
        assert len(lifecycle_alerts) == 1
        alert = lifecycle_alerts[0]
        assert alert["severity"] == "critical"  # our model + deprecated keyword
        assert "deprecated" in alert["details"]["new_keywords"]

    def test_build_alerts_model_removed(self) -> None:
        prev = [{"model": "gpt-5.4-nano", "is_ours": True}]
        curr: list[dict] = []
        alerts = _build_alerts_from_diff(
            "openai", "https://example.com", "deprecations", prev, curr
        )
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "model_removed"
        assert "gpt-5.4-nano" in alert["affected_models"]
        assert alert["severity"] == "warning"  # our model removed

    def test_build_alerts_no_changes(self) -> None:
        models_list = [{"model": "gpt-5.4-nano", "is_ours": True, "lifecycle_keywords": ["stable"]}]
        alerts = _build_alerts_from_diff(
            "openai", "https://example.com", "deprecations", models_list, models_list
        )
        assert alerts == []


# ── run_model_lifecycle_check ───────────────────────────────────────


def _mock_db_session(prev_snapshot=None):
    """Build a MagicMock(spec=Session) with query chain returning *prev_snapshot*."""
    db = MagicMock(spec=Session)
    query_chain = MagicMock()
    db.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.first.return_value = prev_snapshot
    return db


_SAMPLE_HTML = "<html><body><p>gpt-5.4-nano deprecated 2025-06-01</p></body></html>"
_SAMPLE_PLAIN = _strip_html(_SAMPLE_HTML)
_SAMPLE_HASH = _hash_content(_SAMPLE_PLAIN)


class TestRunModelLifecycleCheck:
    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [{"provider": "openai", "url": "https://example.com/dep", "page_type": "deprecations"}],
    )
    def test_run_lifecycle_check_first_run(self, mock_fetch, mock_email_cls) -> None:
        """First run — no previous snapshot. Should create snapshot + alerts."""
        mock_fetch.return_value = _SAMPLE_HTML
        mock_email_cls.return_value = MagicMock()

        db = _mock_db_session(prev_snapshot=None)

        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["sources_failed"] == 0
        assert summary["pages_changed"] == 1
        assert summary["alerts_created"] >= 1
        # Snapshot and alert(s) should be added to the session
        assert db.add.call_count >= 2  # at least 1 snapshot + 1 alert

    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [{"provider": "openai", "url": "https://example.com/dep", "page_type": "deprecations"}],
    )
    def test_run_lifecycle_check_no_change(self, mock_fetch, mock_email_cls) -> None:
        """Content unchanged — no new alerts or snapshots."""
        mock_fetch.return_value = _SAMPLE_HTML
        mock_email_cls.return_value = MagicMock()

        prev = MagicMock()
        prev.content_hash = _SAMPLE_HASH
        prev.extracted_models = []
        db = _mock_db_session(prev_snapshot=prev)

        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["pages_changed"] == 0
        assert summary["alerts_created"] == 0

    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [{"provider": "openai", "url": "https://example.com/dep", "page_type": "deprecations"}],
    )
    def test_run_lifecycle_check_page_changed(self, mock_fetch, mock_email_cls) -> None:
        """Page changed compared to previous snapshot — should detect change."""
        mock_fetch.return_value = _SAMPLE_HTML
        mock_email_cls.return_value = MagicMock()

        prev = MagicMock()
        prev.content_hash = "old_hash_that_does_not_match"
        prev.extracted_models = []
        db = _mock_db_session(prev_snapshot=prev)

        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["pages_changed"] == 1
        # Should create alerts (model_appeared for gpt-5.4-nano + possibly page_changed)
        assert summary["alerts_created"] >= 1

    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [{"provider": "openai", "url": "https://example.com/dep", "page_type": "deprecations"}],
    )
    def test_run_lifecycle_check_fetch_failure(self, mock_fetch, mock_email_cls) -> None:
        """Fetch returns None — should increment sources_failed."""
        mock_fetch.return_value = None
        mock_email_cls.return_value = MagicMock()

        db = _mock_db_session(prev_snapshot=None)

        summary = run_model_lifecycle_check(db)

        assert summary["sources_failed"] == 1
        assert summary["sources_checked"] == 0
        assert summary["alerts_created"] == 0


# ── Expanded provider coverage (AEX-32) ────────────────────────────


class TestMonitorSourcesCoverage:
    def test_monitor_sources_has_14_entries(self) -> None:
        """7 providers × 2 page types = 14 entries."""
        assert len(MONITOR_SOURCES) == 14

    def test_all_providers_have_deprecation_and_pricing(self) -> None:
        providers = {"openai", "google", "anthropic", "perplexity", "bing", "xai", "deepseek"}
        for provider in providers:
            types = {s["page_type"] for s in MONITOR_SOURCES if s["provider"] == provider}
            assert types == {"deprecations", "pricing"}, f"{provider} missing page types: {types}"

    def test_perplexity_urls(self) -> None:
        pplx_sources = [s for s in MONITOR_SOURCES if s["provider"] == "perplexity"]
        urls = {s["url"] for s in pplx_sources}
        assert "https://docs.perplexity.ai/changelog" in urls
        assert "https://docs.perplexity.ai/guides/pricing" in urls

    def test_bing_urls(self) -> None:
        bing_sources = [s for s in MONITOR_SOURCES if s["provider"] == "bing"]
        urls = {s["url"] for s in bing_sources}
        assert any("model-retirements" in u for u in urls)
        assert any("pricing" in u for u in urls)

    def test_xai_urls(self) -> None:
        xai_sources = [s for s in MONITOR_SOURCES if s["provider"] == "xai"]
        assert len(xai_sources) == 2

    def test_deepseek_urls(self) -> None:
        ds_sources = [s for s in MONITOR_SOURCES if s["provider"] == "deepseek"]
        assert len(ds_sources) == 2
        urls = {s["url"] for s in ds_sources}
        assert any("pricing" in u for u in urls)


class TestModelPatternsExpanded:
    def test_perplexity_sonar_pattern(self) -> None:
        text = "sonar-medium-online is now deprecated. Use sonar-pro instead."
        refs = _extract_model_references(text, "perplexity")
        names = {r["model"] for r in refs}
        assert "sonar-medium-online" in names
        assert "sonar-pro" in names

    def test_perplexity_sonar_bare(self) -> None:
        text = "The default model is sonar for online queries."
        refs = _extract_model_references(text, "perplexity")
        names = {r["model"] for r in refs}
        assert "sonar" in names

    def test_perplexity_sonar_reasoning(self) -> None:
        text = "sonar-reasoning-pro delivers enhanced accuracy."
        refs = _extract_model_references(text, "perplexity")
        names = {r["model"] for r in refs}
        assert "sonar-reasoning-pro" in names

    def test_bing_uses_gpt_pattern(self) -> None:
        text = "Azure OpenAI gpt-4o-mini will be retired on 2025-07-01."
        refs = _extract_model_references(text, "bing")
        names = {r["model"] for r in refs}
        assert "gpt-4o-mini" in names

    def test_xai_grok_pattern(self) -> None:
        text = "grok-3-mini is now available for all tiers."
        refs = _extract_model_references(text, "xai")
        names = {r["model"] for r in refs}
        assert "grok-3-mini" in names
        entry = next(r for r in refs if r["model"] == "grok-3-mini")
        # We don't run grok via Bedrock → not ours.
        assert entry["is_ours"] is False

    def test_xai_grok_full_model(self) -> None:
        text = "grok-3 has been updated with improved reasoning."
        refs = _extract_model_references(text, "xai")
        names = {r["model"] for r in refs}
        assert "grok-3" in names

    def test_deepseek_chat_pattern(self) -> None:
        text = "deepseek-chat v2 is now the default model."
        refs = _extract_model_references(text, "deepseek")
        names = {r["model"] for r in refs}
        assert "deepseek-chat" in names
        entry = next(r for r in refs if r["model"] == "deepseek-chat")
        # We run deepseek-v3.2 on Bedrock, not deepseek-chat → not ours.
        assert entry["is_ours"] is False

    def test_deepseek_reasoner_pattern(self) -> None:
        text = "deepseek-reasoner is entering beta phase."
        refs = _extract_model_references(text, "deepseek")
        names = {r["model"] for r in refs}
        assert "deepseek-reasoner" in names
        entry = next(r for r in refs if r["model"] == "deepseek-reasoner")
        assert entry["is_ours"] is False
        assert "beta" in entry.get("lifecycle_keywords", [])

    def test_all_providers_have_patterns(self) -> None:
        """Every provider in MONITOR_SOURCES should have a model pattern."""
        providers_in_sources = {s["provider"] for s in MONITOR_SOURCES}
        for provider in providers_in_sources:
            assert provider in _MODEL_PATTERNS, f"No pattern for provider: {provider}"


class TestPerplexityAlertGeneration:
    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [
            {
                "provider": "perplexity",
                "url": "https://docs.perplexity.ai/changelog",
                "page_type": "deprecations",
            }
        ],
    )
    def test_perplexity_deprecation_alert(self, mock_fetch, mock_email_cls) -> None:
        html_content = "<html><body><p>sonar-medium-online is deprecated as of 2025-08-01. Use sonar-pro.</p></body></html>"
        mock_fetch.return_value = html_content
        mock_email_cls.return_value = MagicMock()

        db = _mock_db_session(prev_snapshot=None)
        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["pages_changed"] == 1
        assert summary["alerts_created"] >= 1


class TestXaiAlertGeneration:
    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [{"provider": "xai", "url": "https://docs.x.ai/changelog", "page_type": "deprecations"}],
    )
    def test_xai_grok_alert(self, mock_fetch, mock_email_cls) -> None:
        html_content = (
            "<html><body><p>grok-3-mini is now stable and generally available.</p></body></html>"
        )
        mock_fetch.return_value = html_content
        mock_email_cls.return_value = MagicMock()

        db = _mock_db_session(prev_snapshot=None)
        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["pages_changed"] == 1
        assert summary["alerts_created"] >= 1


class TestDeepSeekAlertGeneration:
    @patch("services.model_lifecycle_monitor_service.EmailService")
    @patch("services.model_lifecycle_monitor_service._fetch_page")
    @patch(
        "services.model_lifecycle_monitor_service.MONITOR_SOURCES",
        [
            {
                "provider": "deepseek",
                "url": "https://api-docs.deepseek.com/news",
                "page_type": "deprecations",
            }
        ],
    )
    def test_deepseek_deprecation_alert(self, mock_fetch, mock_email_cls) -> None:
        html_content = "<html><body><p>deepseek-chat v1 is sunset as of March 2025. deepseek-reasoner is now available.</p></body></html>"
        mock_fetch.return_value = html_content
        mock_email_cls.return_value = MagicMock()

        db = _mock_db_session(prev_snapshot=None)
        summary = run_model_lifecycle_check(db)

        assert summary["sources_checked"] == 1
        assert summary["pages_changed"] == 1
        assert summary["alerts_created"] >= 1
