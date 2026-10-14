"""Tests for EPIC 11 / S11.1 quick-scan (flag-gated deterministic audit path).

These mirror the perform_audit smoke tests and assert that:
  * When ``QUICK_SCAN_ENABLED`` is True and the raw requested tier is
    "lite"/"quick", perform_audit returns the deterministic scores WITHOUT
    calling the LLM (``ai_client.generate_audit`` raises if invoked).
  * The quick-scan scores equal ``calculate_deterministic_scores`` evaluated
    with the exact same pre-scan inputs and findings=None (the pure
    deterministic base, no AI penalties).
  * No LLM / debate / findings keys leak into the quick-scan report.
  * When the flag is OFF (production default), "lite" still runs the full
    audit path and the LLM IS called.
"""

import pytest

import audit_runner
from audit_runner import perform_audit
from score_utils import calculate_deterministic_scores as real_calculate_deterministic_scores

from test_audit_smoke import (
    MockAIClient,
    MockNetworkAnalysisService,
    MockPerformanceService,
    MockScraperService,
)


class RaisingAIClient:
    """AI client whose generate_audit MUST NOT be called on the quick-scan path."""

    def __init__(self) -> None:
        self.generate_audit_called = False

    async def generate_audit(self, **kwargs):
        self.generate_audit_called = True
        raise AssertionError(
            "ai_client.generate_audit was called on the quick-scan path; "
            "the deterministic fast path must short-circuit before the LLM."
        )


class CallTrackingAIClient(MockAIClient):
    """Full-audit mock that records whether generate_audit was invoked."""

    def __init__(self) -> None:
        super().__init__()
        self.generate_audit_called = False

    async def generate_audit(self, **kwargs):
        self.generate_audit_called = True
        return await super().generate_audit(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_tier", ["lite", "quick"])
async def test_quick_scan_returns_deterministic_scores_without_llm(monkeypatch, raw_tier) -> None:
    # Patch the exact settings object audit_runner reads (robust against other
    # tests that reload/replace the core.config.settings singleton).
    monkeypatch.setattr(audit_runner.settings, "QUICK_SCAN_ENABLED", True)

    # Spy on calculate_deterministic_scores to capture the EXACT pre-scan inputs
    # perform_audit feeds it, while delegating to the real implementation.
    captured: dict = {}

    def _spy(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return real_calculate_deterministic_scores(**kwargs)

    monkeypatch.setattr(audit_runner, "calculate_deterministic_scores", _spy)

    ai_client = RaisingAIClient()

    report, score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="fast",
        requested_tier=raw_tier,
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=None,
    )

    # (a) The LLM must NOT have been called.
    assert ai_client.generate_audit_called is False

    # (b) Expected = pure deterministic base from the same pre-scan inputs.
    assert captured, "calculate_deterministic_scores was not invoked"
    assert captured["seo_findings"] is None
    assert captured["geo_findings"] is None
    assert captured["aeo_findings"] is None
    expected = real_calculate_deterministic_scores(**captured)

    # (c) Quick-scan scores EQUAL the deterministic computation.
    assert score_breakdown == {
        "seo": expected["seo_score"],
        "geo": expected["geo_score"],
        "aeo": expected["aeo_score"],
        "overall": expected["overall_score"],
    }
    assert report["scores"]["seo"] == expected["seo_score"]
    assert report["scores"]["geo"] == expected["geo_score"]
    assert report["scores"]["aeo"] == expected["aeo_score"]
    assert report["scores"]["overall"] == expected["overall_score"]

    # (d) No LLM / debate / findings keys leak into the quick-scan report.
    assert report["quick_scan"] is True
    assert report["metadata"]["quick_scan"] is True
    assert report["metadata"]["requested_tier"] == raw_tier
    assert report["metadata"]["score_source"] == "deterministic_quick_scan"
    for forbidden in ("debate", "hallucination", "analysis", "suggestions", "entities"):
        assert forbidden not in report, f"quick-scan report unexpectedly contains '{forbidden}'"


@pytest.mark.asyncio
async def test_quick_scan_disabled_runs_full_audit_path(monkeypatch) -> None:
    # Flag OFF (production default): "lite" must still run the FULL audit path,
    # i.e. the LLM IS called and the report is the full (non-quick-scan) shape.
    monkeypatch.setattr(audit_runner.settings, "QUICK_SCAN_ENABLED", False)

    ai_client = CallTrackingAIClient()

    report, _score_breakdown = await perform_audit(
        url="https://example.com",
        provider="mock-provider",
        tier="fast",
        requested_tier="lite",
        user_plan="business",
        scraper_service=MockScraperService(),
        performance_service=MockPerformanceService(),
        network_service=MockNetworkAnalysisService(),
        ai_client=ai_client,
        hallucination_service=None,
    )

    assert ai_client.generate_audit_called is True
    assert report.get("quick_scan") is not True
    # Full path produces the blended score source via the canonical adapter.
    assert report["metadata"].get("score_source") != "deterministic_quick_scan"
