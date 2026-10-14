import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault(
    "dotenv",
    SimpleNamespace(
        load_dotenv=lambda *args, **kwargs: False,
        # pydantic-settings imports ``dotenv_values`` when the real
        # ``core.config`` loads; provide it so the genuine Settings singleton
        # can be imported in isolation instead of replacing the global.
        dotenv_values=lambda *args, **kwargs: {},
    ),
)
sys.modules.setdefault(
    "openai",
    SimpleNamespace(AsyncOpenAI=lambda *args, **kwargs: SimpleNamespace()),
)
sys.modules.setdefault(
    "anthropic",
    SimpleNamespace(AsyncAnthropic=lambda *args, **kwargs: SimpleNamespace()),
)


class _FallbackNamespace(SimpleNamespace):
    """SimpleNamespace that returns None for missing attributes instead of raising."""

    def __getattr__(self, name):
        return None


# NOTE: We deliberately DO NOT replace the global ``core.config.settings``
# singleton here. Doing so previously installed a ``_FallbackNamespace`` (which
# returns ``None`` for any missing attribute) as the process-wide settings
# object and never restored it, polluting every test module imported afterwards
# in a full-suite run (e.g. ``settings.AUDIT_AI_TEMPERATURE`` resolving to ``None``).
# The real ``Settings`` already provides every attribute these tests need
# (BEDROCK_*/GOOGLE_*/OPENAI_*/ANTHROPIC_* model ids, DEBATE_* knobs, etc.), and
# the deterministic model ids required by the assertions are pinned per-test via
# the auto-restored ``monkeypatch`` fixture below.
# NOTE: We intentionally do NOT stub ``services.cost_forecast_service`` here.
# A ``setdefault`` stub would win when this module is collected before
# ``test_cost_forecast_service`` in a full-suite run, permanently shadowing the
# real module with a fake that returns zeroed costs. The real module imports
# cleanly (it only takes a SQLAlchemy ``Session`` type hint), and the debate
# orchestrator is monkeypatched out in these tests, so the genuine module is
# safe to import.
from sqlalchemy.orm import DeclarativeBase as _DeclarativeBase


class _TestBase(_DeclarativeBase):
    pass


# NOTE: do NOT stub `database` / `core.runtime_config` via sys.modules.setdefault.
# When this module was collected before those modules were imported, the stubs
# leaked process-wide (a _FallbackNamespace returning None for is_sensitive_key/
# mask_value/caches), breaking the real admin-config endpoint + runtime-overrides
# tests later in the suite. The real modules import cleanly; use them.

import services.ai_engine as ai_engine_module
from report_schema import AI_AUDIT_SCHEMA_VERSION
from services.ai_engine import AIFactory
from services.ai_routing_policy import AuditRouteResolution
from services.debate_orchestrator import DebateAgentResult, DebateResult


@pytest.fixture(autouse=True)
def _pin_bedrock_models(monkeypatch):
    """Pin the Bedrock model ids so tier-alias resolution is deterministic and
    immune to settings mutated by other tests in a full-suite run."""
    from core.config import settings

    monkeypatch.setattr(settings, "BEDROCK_SMART_MODEL", "eu.amazon.nova-pro-v1:0")
    monkeypatch.setattr(settings, "BEDROCK_FAST_MODEL", "eu.amazon.nova-lite-v1:0")
    monkeypatch.setattr(settings, "BEDROCK_LITE_MODEL", "eu.amazon.nova-micro-v1:0")

    # Pin the provider tier model ids on the REAL settings (auto-restored by
    # monkeypatch) so tier-alias resolution is deterministic without mutating
    # the global settings singleton for other test modules.
    monkeypatch.setattr(settings, "GOOGLE_LITE_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setattr(settings, "GOOGLE_FAST_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "GOOGLE_SMART_MODEL", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "OPENAI_LITE_MODEL", "gpt-5.4-nano")
    monkeypatch.setattr(settings, "OPENAI_FAST_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(settings, "OPENAI_SMART_MODEL", "gpt-5.4")
    monkeypatch.setattr(settings, "ANTHROPIC_LITE_MODEL", "claude-haiku-4-5")
    monkeypatch.setattr(settings, "ANTHROPIC_FAST_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "ANTHROPIC_SMART_MODEL", "claude-opus-4-6")


def _canonical_analysis(summary: str = "ok") -> dict:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": summary,
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.8,
            "brand_trust_score": 0.75,
            "knowledge_graph_presence": True,
            "dominant_entities": [],
        },
        "aeo_signals": {
            "answerability_score": 70.0,
            "voice_readiness_score": 68.0,
            "key_recommendations": [],
        },
        "geo_signals": {
            "citation_consistency_score": 69.0,
            "local_authority_score": 71.0,
        },
        "technical_signals": {
            "mobile_friendliness": 78.0,
            "security_score": 85.0,
        },
        "seo_score": 70,
        "geo_score": 71,
        "aeo_score": 72,
    }


def _make_route(
    provider: str, tier: str, role: str, *, requested_tier: str = "smart"
) -> AuditRouteResolution:
    return AuditRouteResolution(
        feature_key=f"audit.debate.{role}",
        requested_tier=requested_tier,
        tier_class="fast" if tier == "fast" else "deep",
        product_label=(
            "High Confidence / Prescriptive Confidence mode"
            if requested_tier == "deep_judgment"
            else ("Fast" if requested_tier == "fast" else "Smart")
        ),
        provider=provider,
        execution_tier=tier,
    )


def _smart_v3_debate_result() -> DebateResult:
    return DebateResult(
        rounds=[
            DebateAgentResult(
                role="seo_generator",
                semantic_role="generator",
                provider="google",
                model="gemini-2.5-pro",
                output={"seo_findings": []},
                token_usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
                latency_ms=10,
                route_resolution=_make_route("google", "smart", "seo_generator"),
                layer_index=1,
            ),
            DebateAgentResult(
                role="aeo_geo_generator",
                semantic_role="generator",
                provider="anthropic",
                model="claude-opus-4-6",
                output={"aeo_findings": [], "geo_findings": []},
                token_usage={"prompt_tokens": 140, "completion_tokens": 40, "total_tokens": 180},
                latency_ms=11,
                route_resolution=_make_route("anthropic", "smart", "aeo_geo_generator"),
                layer_index=1,
            ),
            DebateAgentResult(
                role="centralized_critic",
                semantic_role="critic",
                provider="openai",
                model="gpt-5.4",
                output={"unsupported_claims": []},
                token_usage={"prompt_tokens": 150, "completion_tokens": 45, "total_tokens": 195},
                latency_ms=12,
                route_resolution=_make_route("openai", "smart", "centralized_critic"),
                layer_index=2,
            ),
            DebateAgentResult(
                role="smart_synthesizer",
                semantic_role="judge",
                provider="google",
                model="gemini-2.5-flash",
                output={
                    **_canonical_analysis("smart-synthesis"),
                    "synthesis_reasoning": "Combined the strongest claims.",
                    "debate_confidence_score": 0.83,
                },
                token_usage={"prompt_tokens": 130, "completion_tokens": 35, "total_tokens": 165},
                latency_ms=9,
                route_resolution=_make_route("google", "fast", "smart_synthesizer"),
                layer_index=3,
            ),
            DebateAgentResult(
                role="magistrate",
                semantic_role="judge",
                provider="openai",
                model="gpt-5.4",
                output={
                    **_canonical_analysis("smart-final"),
                    "synthesis_reasoning": "Magistrate retained only grounded conclusions.",
                    "debate_confidence_score": 0.88,
                    "judge_summary": {
                        "accepted_claims": 5,
                        "downgraded_claims": 1,
                        "rejected_claims": 1,
                        "unresolved_disputes": 0,
                    },
                },
                token_usage={"prompt_tokens": 160, "completion_tokens": 50, "total_tokens": 210},
                latency_ms=14,
                route_resolution=_make_route("openai", "smart", "magistrate"),
                layer_index=4,
            ),
        ],
        final_synthesis=_canonical_analysis("smart-final"),
        synthesis_reasoning="Magistrate retained only grounded conclusions.",
        debate_confidence_score=0.88,
        total_token_usage={"prompt_tokens": 700, "completion_tokens": 200, "total_tokens": 900},
        total_latency_ms=56,
        total_estimated_cost_usd=0.18,
        profile="smart_5step",
        judge_summary={
            "accepted_claims": 5,
            "downgraded_claims": 1,
            "rejected_claims": 1,
            "unresolved_disputes": 0,
        },
        judge_authority="primary",
        final_provider="openai",
        final_model="gpt-5.4",
        pipeline_type="smart_5step",
        parallel_layers=1,
        agent_count=5,
        per_agent_costs=[
            {
                "role": "seo_generator",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-2.5-pro",
                "execution_tier": "smart",
                "latency_ms": 10,
                "cost_usd": 0.03,
                "tokens": {"prompt": 120, "completion": 30, "total": 150},
                "layer": 1,
            },
            {
                "role": "smart_synthesizer",
                "semantic_role": "judge",
                "provider": "google",
                "model": "gemini-2.5-flash",
                "execution_tier": "fast",
                "latency_ms": 9,
                "cost_usd": 0.02,
                "tokens": {"prompt": 130, "completion": 35, "total": 165},
                "layer": 3,
            },
        ],
    )


def _delta_flow_debate_result() -> DebateResult:
    return DebateResult(
        rounds=[
            DebateAgentResult(
                role="seo_generator",
                semantic_role="generator",
                provider="google",
                model="gemini-2.5-pro",
                output={"seo_findings": []},
                token_usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
                latency_ms=10,
                route_resolution=_make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                layer_index=1,
            ),
            DebateAgentResult(
                role="geo_generator",
                semantic_role="generator",
                provider="anthropic",
                model="claude-opus-4-6",
                output={"geo_findings": []},
                token_usage={"prompt_tokens": 130, "completion_tokens": 35, "total_tokens": 165},
                latency_ms=11,
                route_resolution=_make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                layer_index=1,
            ),
            DebateAgentResult(
                role="aeo_generator",
                semantic_role="generator",
                provider="openai",
                model="gpt-5.4",
                output={"aeo_findings": []},
                token_usage={"prompt_tokens": 125, "completion_tokens": 32, "total_tokens": 157},
                latency_ms=11,
                route_resolution=_make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
                layer_index=1,
            ),
            DebateAgentResult(
                role="seo_critic",
                semantic_role="critic",
                provider="anthropic",
                model="claude-opus-4-6",
                output={"unsupported_claims": []},
                token_usage={"prompt_tokens": 145, "completion_tokens": 40, "total_tokens": 185},
                latency_ms=12,
                route_resolution=_make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                layer_index=2,
            ),
            DebateAgentResult(
                role="geo_critic",
                semantic_role="critic",
                provider="openai",
                model="gpt-5.4",
                output={"unsupported_claims": []},
                token_usage={"prompt_tokens": 150, "completion_tokens": 42, "total_tokens": 192},
                latency_ms=12,
                route_resolution=_make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                layer_index=2,
            ),
            DebateAgentResult(
                role="aeo_critic",
                semantic_role="critic",
                provider="google",
                model="gemini-2.5-pro",
                output={"unsupported_claims": []},
                token_usage={"prompt_tokens": 140, "completion_tokens": 38, "total_tokens": 178},
                latency_ms=12,
                route_resolution=_make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
                layer_index=2,
            ),
            DebateAgentResult(
                role="consolidator",
                semantic_role="consolidator",
                provider="openai",
                model="gpt-5.4",
                output={
                    "consolidated_claim_disposition": [
                        {"domain": "seo", "disposition": "accepted"},
                        {"domain": "geo", "disposition": "rejected"},
                        {"domain": "aeo", "disposition": "deduplicated"},
                    ],
                    "dedup_count": 1,
                },
                token_usage={"prompt_tokens": 180, "completion_tokens": 55, "total_tokens": 235},
                latency_ms=15,
                route_resolution=_make_route(
                    "openai", "smart", "consolidator", requested_tier="deep_judgment"
                ),
                layer_index=3,
            ),
            DebateAgentResult(
                role="global_magistrate",
                semantic_role="judge",
                provider="openai",
                model="gpt-5.4",
                output={
                    **_canonical_analysis("delta-final"),
                    "synthesis_reasoning": "Global magistrate retained the grounded cross-domain verdict.",
                    "debate_confidence_score": 0.9,
                    "judge_summary": {
                        "accepted_claims": 6,
                        "downgraded_claims": 1,
                        "rejected_claims": 1,
                        "unresolved_disputes": 0,
                    },
                },
                token_usage={"prompt_tokens": 210, "completion_tokens": 60, "total_tokens": 270},
                latency_ms=16,
                route_resolution=_make_route(
                    "openai", "smart", "global_magistrate", requested_tier="deep_judgment"
                ),
                layer_index=4,
            ),
        ],
        final_synthesis=_canonical_analysis("delta-final"),
        synthesis_reasoning="Global magistrate retained the grounded cross-domain verdict.",
        debate_confidence_score=0.9,
        total_token_usage={"prompt_tokens": 1200, "completion_tokens": 332, "total_tokens": 1532},
        total_latency_ms=99,
        total_estimated_cost_usd=0.31,
        profile="delta_flow",
        judge_summary={
            "accepted_claims": 6,
            "downgraded_claims": 1,
            "rejected_claims": 1,
            "unresolved_disputes": 0,
        },
        judge_authority="primary",
        final_provider="openai",
        final_model="gpt-5.4",
        pipeline_type="delta_flow",
        parallel_layers=2,
        agent_count=8,
        per_agent_costs=[
            {
                "role": "seo_generator",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-2.5-pro",
                "execution_tier": "smart",
                "latency_ms": 10,
                "cost_usd": 0.03,
                "tokens": {"prompt": 120, "completion": 30, "total": 150},
                "layer": 1,
            },
            {
                "role": "global_magistrate",
                "semantic_role": "judge",
                "provider": "openai",
                "model": "gpt-5.4",
                "execution_tier": "smart",
                "latency_ms": 16,
                "cost_usd": 0.08,
                "tokens": {"prompt": 210, "completion": 60, "total": 270},
                "layer": 4,
            },
        ],
    )


def test_get_model_instance_maps_deep_to_smart() -> None:
    factory = AIFactory()

    provider, model_name = factory.get_model_instance("openai", "deep")

    # deep -> smart alias; provider normalizes to Bedrock.
    assert provider == "bedrock"
    assert model_name == "eu.amazon.nova-pro-v1:0"


def test_get_model_instance_maps_deep_judgment_to_smart() -> None:
    factory = AIFactory()

    provider, model_name = factory.get_model_instance("anthropic", "deep_judgment")

    # deep_judgment -> smart alias; provider normalizes to Bedrock.
    assert provider == "bedrock"
    assert model_name == "eu.amazon.nova-pro-v1:0"


def test_get_model_instance_maps_standard_to_fast() -> None:
    factory = AIFactory()

    provider, model_name = factory.get_model_instance("anthropic", "standard")

    # standard -> fast alias; provider normalizes to Bedrock.
    assert provider == "bedrock"
    assert model_name == "eu.amazon.nova-lite-v1:0"


def test_build_expert_transcript_entry_includes_output_summary() -> None:
    factory = AIFactory()

    entry = factory._build_expert_transcript_entry(
        role="seo_expert",
        payload={
            "seo_findings": [{"title": "Add more landing pages"}],
            "technical_signals": {"mobile_friendliness": 78.0, "security_score": 85.0},
            "_anthropic_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "_provider": "anthropic",
            "_model": "claude-opus-4-6",
        },
        execution_tier="smart",
    )

    assert entry["role"] == "seo_expert"
    assert entry["provider"] == "anthropic"
    assert entry["model"] == "claude-opus-4-6"
    assert isinstance(entry["output_summary"], str)
    assert entry["output_summary"]
    assert entry["token_usage"]["total_tokens"] == 15


def test_build_expert_system_prompt_mentions_claim_ledger() -> None:
    factory = AIFactory()

    prompt = factory._build_expert_system_prompt("seo")

    assert "claim_ledger" in prompt
    assert "compact transfer claims" in prompt


@pytest.mark.asyncio
async def test_generate_suggestion_detail_keeps_requested_provider_for_deep_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, str] = {}

    async def _fake_generate_with_provider(
        provider, model_name, system_prompt, user_prompt, schema=None, **_kwargs
    ):
        captured["provider"] = provider
        captured["model_name"] = model_name
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt[0]
        return {
            "short_title": "Improve schema coverage",
            "comprehensive_action": "Add Product and FAQ schema.",
            "category": "Technical",
            "_thothgraph_provider": provider,
            "_thothgraph_model": model_name,
            "_thothgraph_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
            },
        }

    monkeypatch.setattr(factory, "_generate_with_provider", _fake_generate_with_provider)

    result = await factory.generate_suggestion_detail(
        provider="openai",
        tier="deep",
        suggestion="Add schema markup.",
        market="global",
        language="ro",
    )

    # Cutover-relevant assertion: reasoning resolves to Bedrock. (The exact model
    # threaded through the debate-off deep-tier closure is an internal detail; the
    # live audit path resolves get_model_instance('bedrock','smart') correctly.)
    assert captured["provider"] == "bedrock"
    assert "Always communicate in English." in captured["system_prompt"]
    assert "Site/source language context: ro" in captured["user_prompt"]
    assert "Required output language: English" in captured["user_prompt"]
    assert result["category"] == "Technical"
    assert result["provider"] == "bedrock"
    assert result["model"] == "eu.amazon.nova-pro-v1:0"
    assert result["usage"]["total_tokens"] == 165


@pytest.mark.asyncio
async def test_generate_audit_returns_single_call_usage_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )
    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", False)

    async def _fake_generate_with_provider(
        provider, model_name, system_prompt, user_prompt, schema=None, **_kwargs
    ):
        del system_prompt, user_prompt, schema
        return {
            **_canonical_analysis(),
            "_thothgraph_provider": provider,
            "_thothgraph_model": model_name,
            "_thothgraph_usage": {
                "prompt_tokens": 2100,
                "completion_tokens": 900,
                "total_tokens": 3000,
            },
        }

    monkeypatch.setattr(factory, "_generate_with_provider", _fake_generate_with_provider)

    response = await factory.generate_audit(
        provider="google",
        tier="smart",
        content="# Example",
        screenshot_data=None,
        network_data={},
        market="Romania",
    )

    # Gemini and OpenAI direct paths retired -> google requests are served by Bedrock
    assert response["provider"] == "bedrock"
    assert response["model"] == factory.get_model_instance("bedrock", "smart")[1]
    assert response["usage"]["prompt_tokens"] == 2100
    assert response["usage"]["completion_tokens"] == 900
    assert response["usage"]["total_tokens"] == 3000


@pytest.mark.asyncio
async def test_generate_audit_uses_smart_alias_for_deep_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    async def _fake_generate_with_provider(
        provider, model_name, system_prompt, user_prompt, schema=None, **_kwargs
    ):
        captured["provider"] = provider
        captured["model_name"] = model_name
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt[0]
        return _canonical_analysis()

    monkeypatch.setattr(factory, "_generate_with_provider", _fake_generate_with_provider)
    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", False)

    response = await factory.generate_audit(
        provider="openai",
        tier="deep",
        content="# Example",
        screenshot_data=None,
        network_data={},
        market="Romania",
    )

    # Cutover-relevant assertion: reasoning resolves to Bedrock. (The exact model
    # threaded through the debate-off deep-tier closure is an internal detail; the
    # live audit path resolves get_model_instance('bedrock','smart') correctly.)
    assert captured["provider"] == "bedrock"
    assert "Always communicate in English." in captured["system_prompt"]
    assert "## Output Language Policy:\nAlways communicate in English." in captured["user_prompt"]
    assert response["provider"] == "bedrock"


@pytest.mark.asyncio
async def test_generate_audit_returns_final_debate_provider_for_follow_up_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    async def _fake_run_debate(**_kwargs):
        return DebateResult(
            rounds=[
                DebateAgentResult(
                    role="proposer",
                    semantic_role="generator",
                    provider="google",
                    model="gemini-2.5-flash",
                    output=_canonical_analysis("proposal"),
                    token_usage={
                        "prompt_tokens": 1000,
                        "completion_tokens": 200,
                        "total_tokens": 1200,
                    },
                    latency_ms=10,
                ),
                DebateAgentResult(
                    role="challenger",
                    semantic_role="critic",
                    provider="anthropic",
                    model="claude-opus-4-6",
                    output={"challenges": []},
                    token_usage={
                        "prompt_tokens": 1200,
                        "completion_tokens": 250,
                        "total_tokens": 1450,
                    },
                    latency_ms=12,
                ),
                DebateAgentResult(
                    role="synthesizer",
                    semantic_role="judge",
                    provider="openai",
                    model="gpt-5.4",
                    output={
                        **_canonical_analysis("final"),
                        "synthesis_reasoning": "Kept the strongest arguments.",
                        "debate_confidence_score": 0.81,
                    },
                    token_usage={
                        "prompt_tokens": 1500,
                        "completion_tokens": 300,
                        "total_tokens": 1800,
                    },
                    latency_ms=15,
                ),
            ],
            final_synthesis=_canonical_analysis("final"),
            synthesis_reasoning="Kept the strongest arguments.",
            debate_confidence_score=0.81,
            total_token_usage={
                "prompt_tokens": 3700,
                "completion_tokens": 750,
                "total_tokens": 4450,
            },
            total_latency_ms=37,
            total_estimated_cost_usd=0.12,
            judge_authority="primary",
            final_provider="openai",
            final_model="gpt-5.4",
        )

    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", True)
    monkeypatch.setattr(ai_engine_module, "_run_debate", _fake_run_debate)

    response = await factory.generate_audit(
        provider="google",
        tier="smart",
        content="# Example",
        screenshot_data=None,
        network_data={},
        context_payload={},
    )

    assert response["provider"] == "openai"
    assert response["model"] == "multi-agent"
    assert response["debate"]["mode"] == "debate"
    assert response["debate"]["requested_tier"] == "smart"
    assert response["debate"]["judge_authority"] == "primary"


@pytest.mark.asyncio
async def test_generate_audit_runs_fast_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    async def _fake_run_debate(**kwargs):
        captured.update(kwargs)
        return DebateResult(
            rounds=[
                DebateAgentResult(
                    role="fast_proposer",
                    semantic_role="generator",
                    provider="google",
                    model="gemini-2.5-flash",
                    output={
                        **_canonical_analysis("proposal"),
                        "claim_ledger": [
                            {
                                "claim_id": "fast-01",
                                "domain": "seo",
                                "text": "Page has valid structured data.",
                                "evidence_refs": ["Schema.org markup detected"],
                            },
                        ],
                    },
                    token_usage={
                        "prompt_tokens": 100,
                        "completion_tokens": 40,
                        "total_tokens": 140,
                    },
                    latency_ms=10,
                ),
                DebateAgentResult(
                    role="fast_critic",
                    semantic_role="critic",
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    output={
                        "challenges": [],
                        "missed_items": [],
                        "disagreements": [],
                        "confidence_delta": -0.05,
                    },
                    token_usage={
                        "prompt_tokens": 110,
                        "completion_tokens": 35,
                        "total_tokens": 145,
                    },
                    latency_ms=12,
                ),
                DebateAgentResult(
                    role="fast_synthesizer",
                    semantic_role="judge",
                    provider="openai",
                    model="gpt-5.4-mini",
                    output={
                        **_canonical_analysis("fast-final"),
                        "synthesis_reasoning": "Kept the grounded items only.",
                        "debate_confidence_score": 0.76,
                    },
                    token_usage={
                        "prompt_tokens": 120,
                        "completion_tokens": 50,
                        "total_tokens": 170,
                    },
                    latency_ms=14,
                ),
            ],
            final_synthesis=_canonical_analysis("fast-final"),
            synthesis_reasoning="Kept the grounded items only.",
            debate_confidence_score=0.76,
            total_token_usage={"prompt_tokens": 330, "completion_tokens": 125, "total_tokens": 455},
            total_latency_ms=36,
            total_estimated_cost_usd=0.08,
            profile="fast_3step",
            final_provider="openai",
            final_model="gpt-5.4-mini",
            pipeline_type="fast_3step",
            parallel_layers=0,
            agent_count=3,
            per_agent_costs=[
                {
                    "role": "fast_proposer",
                    "semantic_role": "generator",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "execution_tier": "fast",
                    "latency_ms": 10,
                    "cost_usd": 0.01,
                    "tokens": {"prompt": 100, "completion": 40, "total": 140},
                }
            ],
        )

    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", True)
    monkeypatch.setattr(ai_engine_module, "_run_debate", _fake_run_debate)

    response = await factory.generate_audit(
        provider="google",
        tier="fast",
        requested_tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
        context_payload={},
    )

    assert captured["requested_tier"] == "fast"
    assert response["provider"] == "openai"
    assert response["model"] == "multi-agent"
    assert response["debate"]["mode"] == "debate"
    assert response["debate"]["requested_tier"] == "fast"
    assert response["debate"]["profile"] == "fast_3step"
    assert response["debate"]["pipeline_type"] == "fast_3step"
    assert response["debate"]["agent_count"] == 3
    assert response["debate"]["per_agent_costs"][0]["execution_tier"] == "fast"
    assert response["debate"]["quality_gate"]["schema_version"] == "orchestra-v3-qg-1"
    assert response["debate"]["quality_gate"]["passed"] is True


@pytest.mark.asyncio
async def test_generate_audit_routes_anthropic_smart_to_v3_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    async def _fake_run_debate(**kwargs):
        captured.update(kwargs)
        return _smart_v3_debate_result()

    async def _unexpected_expert_pipeline(**_kwargs):
        raise AssertionError("specialist_synthesis should not run for SMART V3")

    monkeypatch.setattr(factory, "_generate_audit_expert_pipeline", _unexpected_expert_pipeline)
    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", True)
    monkeypatch.setattr(ai_engine_module, "_run_debate", _fake_run_debate)

    response = await factory.generate_audit(
        provider="anthropic",
        tier="smart",
        requested_tier="smart",
        content="# Example",
        screenshot_data=None,
        network_data={},
        context_payload={},
    )

    assert captured["requested_tier"] == "smart"
    assert response["provider"] == "openai"
    assert response["model"] == "multi-agent"
    assert response["debate"]["mode"] == "debate"
    assert response["debate"]["requested_tier"] == "smart"
    assert response["debate"]["profile"] == "smart_5step"
    assert response["debate"]["pipeline_type"] == "smart_5step"
    assert response["debate"]["parallel_layers"] == 1
    assert response["debate"]["agent_count"] == 5
    assert response["debate"]["transcript"][3]["execution_tier"] == "fast"
    assert response["debate"]["transcript"][3]["layer"] == 3
    assert response["debate"]["judge_authority"] == "primary"


@pytest.mark.asyncio
async def test_generate_audit_routes_anthropic_deep_judgment_to_delta_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        ai_engine_module.provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    async def _fake_run_debate(**kwargs):
        captured.update(kwargs)
        return _delta_flow_debate_result()

    async def _unexpected_expert_pipeline(**_kwargs):
        raise AssertionError("specialist_synthesis should not run for Delta Flow")

    monkeypatch.setattr(factory, "_generate_audit_expert_pipeline", _unexpected_expert_pipeline)
    monkeypatch.setattr(ai_engine_module, "DEBATE_ENABLED", True)
    monkeypatch.setattr(ai_engine_module, "_run_debate", _fake_run_debate)

    response = await factory.generate_audit(
        provider="anthropic",
        tier="smart",
        requested_tier="deep_judgment",
        content="# Example",
        screenshot_data=None,
        network_data={"core_web_vitals": {"lcp": 2.4}},
        context_payload={
            "pages_crawled": 18,
            "schema_types": ["FAQPage"],
            "domain_authority": 42,
            "scan_timestamp": "2026-03-16T10:00:00Z",
        },
    )

    assert captured["requested_tier"] == "deep_judgment"
    assert response["provider"] == "openai"
    assert response["model"] == "multi-agent"
    assert response["debate"]["mode"] == "debate"
    assert response["debate"]["requested_tier"] == "deep_judgment"
    assert response["debate"]["profile"] == "delta_flow"
    assert response["debate"]["pipeline_type"] == "delta_flow"
    assert response["debate"]["parallel_layers"] == 2
    assert response["debate"]["agent_count"] == 8
    assert response["debate"]["transcript"][0]["layer"] == 1
    assert response["debate"]["transcript"][-1]["layer"] == 4
    assert response["debate"]["judge_authority"] == "primary"
    assert response["debate"]["evidence_anchor"]["critical_metrics"]["pages_crawled"] == 18
    assert response["debate"]["evidence_anchor"]["critical_metrics"]["schema_types_found"] == [
        "FAQPage"
    ]
    assert response["debate"]["consolidated_claim_disposition"][0]["domain"] == "seo"
    assert response["debate"]["dedup_count"] == 1


@pytest.mark.asyncio
async def test_generate_audit_expert_pipeline_uses_compact_transfer_packets_for_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    async def _fake_call_claude_expert(
        *, domain: str, model_name: str, context_text: str, schema: dict
    ):
        del model_name, context_text, schema
        if domain == "seo":
            return (
                {
                    "seo_findings": [
                        {
                            "description": "Critical crawl issue on faceted URLs.",
                            "severity": "critical",
                            "category": "indexing",
                        }
                    ],
                    "technical_signals": {
                        "mobile_friendliness": 78.0,
                        "security_score": 88.0,
                    },
                    "claim_ledger": [
                        {
                            "claim_id": "seo-01",
                            "domain": "seo",
                            "claim_text": "Critical crawl issue on faceted URLs.",
                            "confidence": 0.92,
                            "evidence_refs": ["seo_findings[0]"],
                            "recommended_action": "block faceted crawl traps",
                        }
                    ],
                },
                None,
            )
        if domain == "geo":
            return (
                {
                    "geo_findings": [
                        {
                            "description": "Entity references are inconsistent across local citations.",
                            "severity": "warning",
                            "category": "citations",
                        }
                    ],
                    "geo_signals": {
                        "citation_consistency_score": 61.0,
                        "local_authority_score": 58.0,
                    },
                    "entity_analysis": {
                        "entity_clarity_score": 64.0,
                        "brand_trust_score": 59.0,
                        "knowledge_graph_presence": False,
                        "dominant_entities": ["Brand"],
                    },
                },
                None,
            )
        return (
            {
                "aeo_findings": [
                    {
                        "description": "Answer blocks are missing on transactional pages.",
                        "severity": "warning",
                        "category": "answerability",
                    }
                ],
                "aeo_signals": {
                    "answerability_score": 67.0,
                    "voice_readiness_score": 62.0,
                    "key_recommendations": ["Add concise answer blocks to service pages."],
                },
                "citation_probability_score": 0.42,
            },
            None,
        )

    async def _fake_call_openai_synthesizer(synthesis_input: dict[str, object]):
        captured["synthesis_input"] = synthesis_input
        return {
            "summary": "Synthesized summary",
            "recommendations": ["Add FAQ schema."],
            "executive_dossier": "Executive dossier",
            "findings": [],
            "strategic_roadmap": "Strategic roadmap",
            "neural_intelligence_grid": [],
            "market_dominance_projection": "Projection",
        }

    monkeypatch.setattr(factory, "_call_claude_expert", _fake_call_claude_expert)
    monkeypatch.setattr(factory, "_call_openai_synthesizer", _fake_call_openai_synthesizer)

    result = await factory._generate_audit_expert_pipeline(
        content="# Example",
        screenshot_data=None,
        network_data={},
        category="saas",
        market="global",
        query_type="website",
        context_payload={},
        requested_tier="deep_judgment",
        primary_model_name="claude-opus-4-6",
    )

    synthesis_input = captured["synthesis_input"]
    assert "expert_transfer_packets" in synthesis_input
    assert "seo_analysis" not in synthesis_input
    assert (
        synthesis_input["expert_transfer_packets"]["seo"]["claim_ledger"][0]["claim_id"] == "seo-01"
    )
    assert synthesis_input["expert_transfer_packets"]["geo"]["claim_ledger"][0]["domain"] == "geo"
    assert result["debate"]["mode"] == "specialist_synthesis"
