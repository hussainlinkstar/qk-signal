"""EPIC 12 / S12.1 — Bedrock-only reasoning routing (CUTOVER stage 1).

Bedrock is now the UNCONDITIONAL reasoning provider: every reasoning/debate/team
route collapses to the ``bedrock`` provider regardless of any flag. The
``settings.BEDROCK_ONLY_REASONING`` field is retained but no longer consulted by
the routing policy, so toggling it has no effect on routing.

No live AWS calls: this only exercises the pure routing-policy resolution layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings  # noqa: E402
from services import ai_routing_policy  # noqa: E402


# Representative role sets per V3 debate tier (audit + debate/team accessors).
_LEGACY_DEBATE_ROLES = ("proposer", "challenger", "synthesizer")
_DEEP_JUDGMENT_DEBATE_ROLES = ("generator", "critic", "judge")
_LAYER_ROLES_BY_TIER = {
    "fast": ["fast_proposer", "fast_critic", "fast_synthesizer"],
    "smart": [
        "seo_generator",
        "aeo_geo_generator",
        "centralized_critic",
        "smart_synthesizer",
        "magistrate",
    ],
    "deep_judgment": [
        "seo_generator",
        "geo_generator",
        "aeo_generator",
        "seo_critic",
        "geo_critic",
        "aeo_critic",
        "consolidator",
        "global_magistrate",
    ],
}


@pytest.fixture(autouse=True)
def _restore_flag(monkeypatch):
    # Ensure each test starts from a known default and never leaks state.
    monkeypatch.setattr(settings, "BEDROCK_ONLY_REASONING", False, raising=False)
    yield


# --------------------------------------------------------------------------- #
# Flag has no effect: routing is unconditionally bedrock even with flag OFF.
# --------------------------------------------------------------------------- #
def test_flag_off_audit_route_is_still_bedrock(monkeypatch):
    monkeypatch.setattr(settings, "BEDROCK_ONLY_REASONING", False, raising=False)
    resolution = ai_routing_policy.resolve_audit_route(tier="smart")
    assert resolution.provider == "bedrock"


def test_flag_off_debate_route_is_still_bedrock(monkeypatch):
    monkeypatch.setattr(settings, "BEDROCK_ONLY_REASONING", False, raising=False)
    resolution = ai_routing_policy.resolve_debate_route("challenger", requested_tier="smart")
    assert resolution.provider == "bedrock"


def test_flag_off_debate_layer_is_still_bedrock(monkeypatch):
    monkeypatch.setattr(settings, "BEDROCK_ONLY_REASONING", False, raising=False)
    resolutions = ai_routing_policy.resolve_debate_routes_for_layer(
        _LAYER_ROLES_BY_TIER["smart"], requested_tier="smart"
    )
    assert resolutions  # non-empty
    for resolution in resolutions.values():
        assert resolution.provider == "bedrock"


# --------------------------------------------------------------------------- #
# Unconditional: every reasoning/debate/team route resolves to bedrock
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tier", ["fast", "smart", "deep_judgment"])
def test_audit_route_is_bedrock(tier):
    resolution = ai_routing_policy.resolve_audit_route(tier=tier)
    assert resolution.provider == "bedrock"


@pytest.mark.parametrize(
    "role, tier",
    [
        *((role, "fast") for role in _LEGACY_DEBATE_ROLES),
        *((role, "smart") for role in _LEGACY_DEBATE_ROLES),
        *((role, "deep_judgment") for role in _DEEP_JUDGMENT_DEBATE_ROLES),
    ],
)
def test_debate_route_is_bedrock(role, tier):
    resolution = ai_routing_policy.resolve_debate_route(role, requested_tier=tier)
    assert resolution.provider == "bedrock"


@pytest.mark.parametrize("tier", ["fast", "smart", "deep_judgment"])
def test_debate_layer_is_bedrock(tier):
    resolutions = ai_routing_policy.resolve_debate_routes_for_layer(
        _LAYER_ROLES_BY_TIER[tier], requested_tier=tier
    )
    assert resolutions
    for resolution in resolutions.values():
        assert resolution.provider == "bedrock"


def test_auxiliary_reasoning_routes_are_bedrock():
    accessors = (
        ai_routing_policy.resolve_prompt_ai_route,
        ai_routing_policy.resolve_content_brief_route,
        ai_routing_policy.resolve_support_chat_route,
        ai_routing_policy.resolve_competitor_discovery_route,
        ai_routing_policy.resolve_pre_scan_route,
        ai_routing_policy.resolve_site_classify_route,
    )
    for accessor in accessors:
        assert accessor().provider == "bedrock", accessor.__name__


def test_preserves_execution_tier():
    # smart audit -> bedrock smart; fast pre-scan -> bedrock fast
    assert ai_routing_policy.resolve_audit_route(tier="smart").execution_tier == "smart"
    assert ai_routing_policy.resolve_pre_scan_route().execution_tier == "fast"
