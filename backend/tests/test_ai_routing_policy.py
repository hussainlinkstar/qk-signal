import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.ai_routing_policy import (
    normalize_audit_tier_class,
    provider_runtime_state_service,
    resolve_audit_route,
    resolve_competitor_discovery_route,
    resolve_content_brief_route,
    resolve_pre_scan_route,
    resolve_prompt_ai_route,
    resolve_site_classify_route,
    resolve_support_chat_route,
)
from services.ai_provider_runtime_service import ProviderRuntimeStatus


@pytest.fixture(autouse=True)
def _runtime_state_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda provider: ProviderRuntimeStatus(
            provider=provider,
            configured=True,
            available=True,
            state="healthy",
        ),
    )


def test_normalize_audit_tier_class_maps_legacy_aliases() -> None:
    assert normalize_audit_tier_class("standard") == "fast"
    assert normalize_audit_tier_class("smart") == "deep"
    assert normalize_audit_tier_class("deep") == "deep"
    assert normalize_audit_tier_class("deep_judgment") == "deep"
    assert normalize_audit_tier_class("lite") == "fast"


def test_resolve_audit_route_honors_selected_provider_and_model_list() -> None:
    # CUTOVER stage 1: reasoning routes unconditionally to Bedrock, so a user
    # provider/model selection is recorded but the resolved provider collapses
    # to bedrock (runtime fallback mode reflects the override could not be met).
    route = resolve_audit_route(
        tier="deep",
        provider="openai",
        selected_models=["openai", "anthropic"],
    )

    assert route.feature_key == "audit.main"
    assert route.requested_tier == "smart"
    assert route.tier_class == "deep"
    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"
    assert route.routing_mode == "user_selected_provider_runtime_fallback"
    assert route.preferred_provider == "bedrock"
    assert route.selected_models == ("openai", "anthropic")
    assert route.ignored_provider is None
    assert route.ignored_selected_models == ()


def test_resolve_audit_route_preserves_deep_judgment_contract() -> None:
    route = resolve_audit_route(tier="deep_judgment")

    assert route.requested_tier == "deep_judgment"
    assert route.tier_class == "deep"
    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"
    assert route.product_label == "High Confidence / Prescriptive Confidence mode"


def test_resolve_prompt_ai_route_uses_deep_class() -> None:
    route = resolve_prompt_ai_route()

    assert route.feature_key == "suggestions.prompt_ai"
    assert route.requested_tier == "smart"
    assert route.tier_class == "deep"
    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"


def test_resolve_content_brief_route_uses_deep_class() -> None:
    route = resolve_content_brief_route()

    assert route.feature_key == "content_brief.generate"
    assert route.tier_class == "deep"
    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"


def test_resolve_support_chat_route_uses_bedrock_lite() -> None:
    route = resolve_support_chat_route()

    assert route.feature_key == "support.thoth_chat"
    assert route.tier_class == "fast"
    assert route.provider == "bedrock"
    assert route.execution_tier == "lite"


def test_resolve_micro_task_routes_use_bedrock_fast() -> None:
    pre_scan_route = resolve_pre_scan_route()
    classify_route = resolve_site_classify_route()

    assert pre_scan_route.feature_key == "audit.pre_scan"
    assert pre_scan_route.provider == "bedrock"
    assert pre_scan_route.execution_tier == "fast"
    assert classify_route.feature_key == "site.classify"
    assert classify_route.provider == "bedrock"
    assert classify_route.execution_tier == "fast"


def test_resolve_audit_route_stays_bedrock_when_runtime_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With bedrock-only reasoning the audit route has a single bedrock
    # candidate; when bedrock is runtime-blocked there is no other provider to
    # fall back to, so the route stays on bedrock and records the block reason.
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda provider: ProviderRuntimeStatus(
            provider=provider,
            configured=True,
            available=False,
            state="quota_blocked",
            reason="provider_quota_exhausted",
            error_code="provider_quota_exhausted",
        ),
    )

    route = resolve_audit_route(tier="deep")

    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"
    assert route.preferred_provider == "bedrock"
    assert route.routing_mode == "server_policy"
    assert route.route_reason == "quota_blocked"


def test_resolve_prompt_ai_route_stays_bedrock_when_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda provider: ProviderRuntimeStatus(
            provider=provider,
            configured=True,
            available=False,
            state="temporarily_unavailable",
            reason="provider_unavailable",
            error_code="provider_unavailable",
        ),
    )

    route = resolve_prompt_ai_route()

    assert route.provider == "bedrock"
    assert route.execution_tier == "smart"
    assert route.routing_mode == "server_policy"
    assert route.preferred_provider == "bedrock"
    assert route.route_reason == "temporarily_unavailable"


def test_resolve_competitor_discovery_route_uses_bedrock_fast() -> None:
    route = resolve_competitor_discovery_route()

    assert route.feature_key == "competitors.discovery"
    assert route.tier_class == "fast"
    assert route.provider == "bedrock"
    assert route.execution_tier == "fast"
    assert route.routing_mode == "server_policy"
