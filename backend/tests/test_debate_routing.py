"""Integration tests for debate routing resolution.

CUTOVER stage 1: reasoning routes unconditionally to the ``bedrock`` provider.
Every role collapses to a single ``(bedrock, <tier>)`` candidate, so the
provider-diversity / preferred-provider / exclude-provider knobs no longer
change the resolved provider (it is always ``bedrock``). The per-role execution
tier is still preserved, and that is what these tests now assert.
"""

from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.ai_routing_policy import (
    _DELTA_TEAM_ROUTE_CANDIDATES,
    _DEBATE_ROUTE_CANDIDATES,
    _FAST_V3_ROUTE_CANDIDATES,
    _HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES,
    _SMART_V3_ROUTE_CANDIDATES,
    resolve_debate_route,
    resolve_debate_routes_for_layer,
)


def _mock_status(configured=True, available=True, state="ok"):
    status = MagicMock()
    status.configured = configured
    status.available = available
    status.state = state
    return status


def _all_healthy(provider):
    del provider
    return _mock_status(configured=True, available=True)


def _only_google_healthy(provider):
    if provider == "google":
        return _mock_status(configured=True, available=True)
    return _mock_status(configured=True, available=False, state="circuit_open")


class TestDebateRouteResolution:
    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_proposer_resolves_fast_tier(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("proposer")
        assert route.feature_key == "audit.debate.proposer"
        assert route.requested_tier == "smart"
        assert route.tier_class == "fast"
        assert route.execution_tier == "fast"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_challenger_resolves_smart_tier(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("challenger")
        assert route.feature_key == "audit.debate.challenger"
        assert route.requested_tier == "smart"
        assert route.tier_class == "deep"
        assert route.execution_tier == "smart"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_deep_judgment_alias_routes_to_generator_profile(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("proposer", requested_tier="deep_judgment")
        assert route.feature_key == "audit.debate.generator"
        assert route.requested_tier == "deep_judgment"
        assert route.provider == "bedrock"
        assert route.execution_tier == "fast"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_judge_alias_resolves_for_high_confidence(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("judge", requested_tier="deep_judgment")
        assert route.feature_key == "audit.debate.judge"
        assert route.provider == "bedrock"
        assert route.execution_tier == "smart"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_v3_fast_role_resolves_from_fast_candidates(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("fast_proposer", requested_tier="fast")
        assert route.feature_key == "audit.debate.fast_proposer"
        assert route.requested_tier == "fast"
        assert route.provider == "bedrock"
        assert route.execution_tier == "fast"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_v3_smart_role_resolves_from_smart_candidates(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("seo_generator", requested_tier="smart")
        assert route.feature_key == "audit.debate.seo_generator"
        assert route.requested_tier == "smart"
        assert route.provider == "bedrock"
        assert route.execution_tier == "smart"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_v3_delta_role_resolves_from_delta_candidates(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("consolidator", requested_tier="deep_judgment")
        assert route.feature_key == "audit.debate.consolidator"
        assert route.requested_tier == "deep_judgment"
        assert route.provider == "bedrock"
        assert route.execution_tier == "smart"

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="Unknown debate role"):
            resolve_debate_route("arbiter")


class TestProviderDiversity:
    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_exclude_provider_has_no_effect_under_bedrock_only(self, mock_runtime):
        # The single bedrock candidate cannot be excluded away, so both the
        # default and exclude-anthropic resolutions stay on bedrock.
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)

        route_default = resolve_debate_route("challenger", requested_tier="deep_judgment")
        assert route_default.provider == "bedrock"

        route_diverse = resolve_debate_route(
            "challenger",
            requested_tier="deep_judgment",
            exclude_provider="anthropic",
        )
        assert route_diverse.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_exclude_nonexistent_provider_no_effect(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route("proposer", exclude_provider="nonexistent")
        assert route.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_layer_resolution_collapses_v3_parallel_roles_to_bedrock(self, mock_runtime):
        # With bedrock-only routing the parallel roles no longer diversify
        # across providers; every role resolves to the single bedrock provider.
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)

        routes = resolve_debate_routes_for_layer(
            ["seo_generator", "geo_generator", "aeo_generator"],
            requested_tier="deep_judgment",
        )

        assert set(routes.keys()) == {"seo_generator", "geo_generator", "aeo_generator"}
        providers = {route.provider for route in routes.values()}
        assert providers == {"bedrock"}

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_layer_resolution_stays_bedrock_with_excluded_providers(self, mock_runtime):
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)

        routes = resolve_debate_routes_for_layer(
            ["seo_generator", "aeo_geo_generator"],
            requested_tier="smart",
            exclude_providers={"google"},
        )

        assert routes["seo_generator"].provider == "bedrock"
        assert routes["aeo_geo_generator"].provider == "bedrock"


class TestDebateRouteFallback:
    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_stays_bedrock_when_other_providers_down(self, mock_runtime):
        # Bedrock itself is healthy; the health of legacy providers is
        # irrelevant because the route only has a bedrock candidate.
        def selective_status(provider):
            if provider == "anthropic":
                return _mock_status(configured=True, available=False, state="circuit_open")
            return _mock_status(configured=True, available=True)

        mock_runtime.get_status = MagicMock(side_effect=selective_status)
        route = resolve_debate_route("challenger", requested_tier="deep_judgment")
        assert route.provider == "bedrock"
        assert route.routing_mode == "server_policy"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_stays_bedrock_even_when_bedrock_unhealthy(self, mock_runtime):
        # Only google healthy => bedrock is unavailable, but with no alternate
        # candidate the route still resolves to bedrock (and records no switch).
        mock_runtime.get_status = MagicMock(side_effect=_only_google_healthy)
        route = resolve_debate_route("judge", requested_tier="deep_judgment")
        assert route.provider == "bedrock"


class TestRouteCandidatesConfig:
    def test_standard_roles_have_candidates(self):
        for role in ("proposer", "challenger", "synthesizer"):
            assert role in _DEBATE_ROUTE_CANDIDATES
            assert len(_DEBATE_ROUTE_CANDIDATES[role]) >= 2

    def test_high_confidence_roles_have_candidates(self):
        for role in ("generator", "critic", "judge"):
            assert role in _HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES
            assert len(_HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES[role]) >= 2

    def test_v3_fast_roles_have_candidates(self):
        for role in ("fast_proposer", "fast_critic", "fast_synthesizer"):
            assert role in _FAST_V3_ROUTE_CANDIDATES
            assert len(_FAST_V3_ROUTE_CANDIDATES[role]) >= 2

    def test_v3_smart_roles_have_candidates(self):
        for role in (
            "seo_generator",
            "aeo_geo_generator",
            "centralized_critic",
            "smart_synthesizer",
            "magistrate",
        ):
            assert role in _SMART_V3_ROUTE_CANDIDATES
            assert len(_SMART_V3_ROUTE_CANDIDATES[role]) >= 2

    def test_v3_delta_roles_have_candidates(self):
        for role in (
            "seo_generator",
            "geo_generator",
            "aeo_generator",
            "seo_critic",
            "geo_critic",
            "aeo_critic",
            "consolidator",
            "global_magistrate",
        ):
            assert role in _DELTA_TEAM_ROUTE_CANDIDATES
            assert len(_DELTA_TEAM_ROUTE_CANDIDATES[role]) >= 2

    def test_standard_proposer_uses_fast_candidates(self):
        for _, tier in _DEBATE_ROUTE_CANDIDATES["proposer"]:
            assert tier == "fast"

    def test_high_confidence_critic_uses_smart_candidates(self):
        for _, tier in _HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES["critic"]:
            assert tier == "smart"

    def test_high_confidence_judge_prefers_smart_candidates(self):
        for _, tier in _HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES["judge"]:
            assert tier == "smart"

    def test_v3_smart_synthesizer_prefers_fast_candidates(self):
        for _, tier in _SMART_V3_ROUTE_CANDIDATES["smart_synthesizer"]:
            assert tier == "fast"


class TestPreferredProvider:
    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_preferred_provider_has_no_effect_under_bedrock_only(self, mock_runtime):
        """Under bedrock-only routing the preferred_provider knob is inert."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route_default = resolve_debate_route("challenger", requested_tier="deep_judgment")
        assert route_default.provider == "bedrock"

        route_pref = resolve_debate_route(
            "challenger",
            requested_tier="deep_judgment",
            preferred_provider="openai",
        )
        assert route_pref.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_preferred_provider_nonexistent_no_effect(self, mock_runtime):
        """A preferred_provider value that matches no candidate is ignored."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route(
            "proposer",
            preferred_provider="nonexistent",
        )
        assert route.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_preferred_provider_combined_with_exclude(self, mock_runtime):
        """Preferred/exclude knobs are both inert: the route stays on bedrock."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route = resolve_debate_route(
            "challenger",
            requested_tier="deep_judgment",
            preferred_provider="anthropic",
            exclude_provider="anthropic",
        )
        assert route.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_preferred_provider_for_v3_smart_role(self, mock_runtime):
        """V3 smart roles also collapse to bedrock regardless of preference."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        route_default = resolve_debate_route("seo_generator", requested_tier="smart")
        assert route_default.provider == "bedrock"

        route_pref = resolve_debate_route(
            "seo_generator",
            requested_tier="smart",
            preferred_provider="anthropic",
        )
        assert route_pref.provider == "bedrock"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_preferred_provider_when_preferred_is_down(self, mock_runtime):
        """Even if a legacy preferred provider is down, the route stays bedrock."""

        def selective_status(provider):
            if provider == "openai":
                return _mock_status(configured=True, available=False, state="circuit_open")
            return _mock_status(configured=True, available=True)

        mock_runtime.get_status = MagicMock(side_effect=selective_status)
        route = resolve_debate_route(
            "challenger",
            requested_tier="deep_judgment",
            preferred_provider="openai",
        )
        assert route.provider == "bedrock"
        assert route.routing_mode == "server_policy"

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_layer_preferred_provider_collapses_to_bedrock(self, mock_runtime):
        """In layer resolution every role collapses to bedrock; no diversity."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        routes = resolve_debate_routes_for_layer(
            ["seo_generator", "geo_generator", "aeo_generator"],
            requested_tier="deep_judgment",
            preferred_provider="anthropic",
        )
        providers = {r.provider for r in routes.values()}
        assert providers == {"bedrock"}

    @patch("services.ai_routing_policy.provider_runtime_state_service")
    def test_layer_preferred_provider_with_exclude_stays_bedrock(self, mock_runtime):
        """exclude_providers cannot move the route off the single bedrock candidate."""
        mock_runtime.get_status = MagicMock(side_effect=_all_healthy)
        routes = resolve_debate_routes_for_layer(
            ["seo_generator", "aeo_geo_generator"],
            requested_tier="smart",
            preferred_provider="google",
            exclude_providers={"google"},
        )
        for role, route in routes.items():
            assert (
                route.provider == "bedrock"
            ), f"Role '{role}' should resolve to bedrock under bedrock-only routing"
