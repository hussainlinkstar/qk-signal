from __future__ import annotations

from dataclasses import dataclass

from services.ai_provider_runtime_service import provider_runtime_state_service


VALID_AUDIT_PRODUCT_TIERS: frozenset[str] = frozenset({"fast", "smart", "deep_judgment"})

_AUDIT_PRODUCT_TIER_ALIASES: dict[str, str] = {
    "fast": "fast",
    "standard": "fast",
    "lite": "fast",
    "deep": "smart",
    "smart": "smart",
    "deep_judgment": "deep_judgment",
}
_AUDIT_PRODUCT_TIER_TO_CLASS: dict[str, str] = {
    "fast": "fast",
    "smart": "deep",
    "deep_judgment": "deep",
}
# Legacy map kept for backwards-compatible report metadata; new code
# should use ``core.tier_labels.get_tier_display()`` instead.
_AUDIT_PRODUCT_TIER_LABELS: dict[str, str] = {
    "fast": "Fast",
    "smart": "Smart",
    "deep_judgment": "High Confidence / Prescriptive Confidence mode",
}
# "bedrock" is included so it survives provider validation/filters: CUTOVER
# stage 1 collapses every reasoning route to the bedrock provider unconditionally.
_AUDIT_PROVIDER_KEYS: frozenset[str] = frozenset(
    {"google", "openai", "anthropic", "xai", "deepseek", "bedrock"}
)

_PRE_SCAN_ROUTE: tuple[str, str] = ("google", "fast")
_SITE_CLASSIFY_ROUTE: tuple[str, str] = ("google", "fast")

_AUDIT_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "fast": (
        ("google", "fast"),
        ("anthropic", "fast"),
        ("openai", "fast"),
        ("xai", "fast"),
        ("deepseek", "fast"),
    ),
    "smart": (
        ("google", "smart"),
        ("anthropic", "smart"),
        ("openai", "smart"),
        ("xai", "smart"),
        ("deepseek", "smart"),
    ),
    "deep_judgment": (("anthropic", "smart"), ("openai", "smart"), ("google", "smart")),
}
_PROMPT_AI_ROUTE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("openai", "smart"),
    ("google", "smart"),
    ("anthropic", "smart"),
)
_CONTENT_BRIEF_ROUTE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("openai", "smart"),
    ("google", "smart"),
    ("anthropic", "smart"),
)
_SUPPORT_CHAT_ROUTE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("openai", "lite"),
    ("google", "fast"),
)
_COMPETITOR_DISCOVERY_ROUTE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("google", "fast"),
    ("openai", "fast"),
)

_DEBATE_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "proposer": (("google", "fast"), ("anthropic", "fast"), ("openai", "fast")),
    "challenger": (("anthropic", "smart"), ("google", "smart"), ("openai", "smart")),
    "synthesizer": (("google", "smart"), ("anthropic", "smart"), ("openai", "smart")),
}
_HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "generator": (("anthropic", "fast"), ("openai", "fast"), ("google", "fast")),
    "critic": (("anthropic", "smart"), ("openai", "smart"), ("google", "smart")),
    "judge": (("openai", "smart"), ("anthropic", "smart"), ("google", "smart")),
}
_FAST_V3_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "fast_proposer": (("google", "fast"), ("anthropic", "fast"), ("openai", "fast")),
    "fast_critic": (("anthropic", "fast"), ("google", "fast"), ("openai", "fast")),
    "fast_synthesizer": (("google", "fast"), ("openai", "fast"), ("anthropic", "fast")),
}
_SMART_V3_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "seo_generator": (("google", "smart"), ("anthropic", "smart"), ("openai", "smart")),
    "aeo_geo_generator": (("anthropic", "smart"), ("google", "smart"), ("openai", "smart")),
    "centralized_critic": (("anthropic", "smart"), ("openai", "smart"), ("google", "smart")),
    # Deliberately the fast tier, and not an oversight despite being the only
    # fast row in a smart table. This role assembles a compact packet *for
    # the magistrate* (see ``_build_smart_synthesizer_prompt``): the
    # generators and the critic produce the judgement on the smart tier, and
    # the magistrate below rules on it on the smart tier. Packing their
    # output into a transfer packet is not where judgement happens, so it
    # does not buy the smart model. ``test_v3_smart_synthesizer_prefers_fast_candidates``
    # pins this.
    "smart_synthesizer": (("google", "fast"), ("openai", "fast"), ("anthropic", "fast")),
    "magistrate": (("openai", "smart"), ("anthropic", "smart"), ("google", "smart")),
}
_DELTA_TEAM_ROUTE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "seo_generator": (("google", "smart"), ("anthropic", "smart"), ("openai", "smart")),
    "geo_generator": (("google", "smart"), ("anthropic", "smart"), ("openai", "smart")),
    "aeo_generator": (("anthropic", "smart"), ("google", "smart"), ("openai", "smart")),
    "seo_critic": (("anthropic", "smart"), ("openai", "smart"), ("google", "smart")),
    "geo_critic": (("openai", "smart"), ("anthropic", "smart"), ("google", "smart")),
    "aeo_critic": (("google", "smart"), ("anthropic", "smart"), ("openai", "smart")),
    "consolidator": (("openai", "smart"), ("google", "smart"), ("anthropic", "smart")),
    "global_magistrate": (("openai", "smart"), ("anthropic", "smart"), ("google", "smart")),
}
_V3_DEBATE_ROUTE_CANDIDATES_BY_TIER: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "fast": _FAST_V3_ROUTE_CANDIDATES,
    "smart": _SMART_V3_ROUTE_CANDIDATES,
    "deep_judgment": _DELTA_TEAM_ROUTE_CANDIDATES,
}
_V3_DEBATE_ROLES: frozenset[str] = frozenset(
    {
        *tuple(_FAST_V3_ROUTE_CANDIDATES.keys()),
        *tuple(_SMART_V3_ROUTE_CANDIDATES.keys()),
        *tuple(_DELTA_TEAM_ROUTE_CANDIDATES.keys()),
    }
)
_DEBATE_ROLE_ALIASES: dict[str, str] = {
    "proposer": "generator",
    "challenger": "critic",
    "synthesizer": "judge",
    "generator": "generator",
    "critic": "critic",
    "judge": "judge",
}
_DEBATE_COMPATIBILITY_ROLES: dict[str, str] = {
    "generator": "proposer",
    "critic": "challenger",
    "judge": "synthesizer",
}


_BEDROCK_PROVIDER: str = "bedrock"


def _bedrock_only_reasoning() -> bool:
    """Whether every reasoning/debate route should collapse to Bedrock.

    CUTOVER stage 1: Bedrock is now the unconditional reasoning provider, so
    this always returns ``True`` regardless of any flag. The
    ``settings.BEDROCK_ONLY_REASONING`` field is retained but no longer
    consulted here; routing is collapsed to Bedrock for every accessor.
    """
    return True


def _bedrock_candidates(
    candidates: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Collapse a role's candidate list to a single Bedrock candidate.

    Preserves the execution tier of the FIRST existing candidate, so smart
    roles map to ``(("bedrock", "smart"),)`` and fast roles to
    ``(("bedrock", "fast"),)``. Deterministic; never mutates the input.
    """
    if not candidates:
        return candidates
    tier = candidates[0][1]
    return ((_BEDROCK_PROVIDER, tier),)


def _bedrock_route(route: tuple[str, str]) -> tuple[str, str]:
    """Rewrite a single hardcoded ``(provider, tier)`` route to Bedrock."""
    return (_BEDROCK_PROVIDER, route[1])


def _bedrock_candidates_by_role(
    candidates_by_role: dict[str, tuple[tuple[str, str], ...]],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Rewrite every role's candidates to Bedrock-only (on the fly)."""
    return {role: _bedrock_candidates(cands) for role, cands in candidates_by_role.items()}


def _route_candidates(
    candidates: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Return Bedrock-only candidates when the flag is on, else the default."""
    if _bedrock_only_reasoning():
        return _bedrock_candidates(candidates)
    return candidates


@dataclass(frozen=True)
class AuditRouteResolution:
    feature_key: str
    requested_tier: str
    tier_class: str
    product_label: str
    provider: str
    execution_tier: str
    routing_mode: str = "server_policy"
    preferred_provider: str | None = None
    route_reason: str | None = None
    selected_models: tuple[str, ...] = ()
    ignored_provider: str | None = None
    ignored_selected_models: tuple[str, ...] = ()


def is_valid_audit_tier(tier: str | None) -> bool:
    cleaned = str(tier or "").strip().lower()
    return cleaned in _AUDIT_PRODUCT_TIER_ALIASES


def normalize_audit_tier(tier: str | None) -> str:
    cleaned = str(tier or "").strip().lower()
    if not cleaned:
        return "fast"
    return _AUDIT_PRODUCT_TIER_ALIASES.get(cleaned, "fast")


def get_audit_tier_label(tier: str | None) -> str:
    normalized = normalize_audit_tier(tier)
    return _AUDIT_PRODUCT_TIER_LABELS.get(normalized, _AUDIT_PRODUCT_TIER_LABELS["fast"])


def normalize_audit_tier_class(tier: str | None) -> str:
    return _AUDIT_PRODUCT_TIER_TO_CLASS.get(normalize_audit_tier(tier), "fast")


def _normalize_provider_key(provider: str | None) -> str | None:
    cleaned = str(provider or "").strip().lower()
    if not cleaned:
        return None
    return cleaned if cleaned in _AUDIT_PROVIDER_KEYS else None


def _normalize_selected_provider_keys(
    selected_models: list[str] | tuple[str, ...] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized: list[str] = []
    ignored: list[str] = []
    seen: set[str] = set()
    for model in selected_models or []:
        cleaned = str(model).strip().lower()
        if not cleaned:
            continue
        if cleaned not in _AUDIT_PROVIDER_KEYS:
            ignored.append(cleaned)
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return tuple(normalized), tuple(ignored)


def _prioritize_provider(
    candidates: tuple[tuple[str, str], ...],
    *,
    preferred_provider: str | None,
) -> tuple[tuple[str, str], ...]:
    if preferred_provider is None:
        return candidates
    preferred = tuple(candidate for candidate in candidates if candidate[0] == preferred_provider)
    if not preferred:
        return candidates
    return preferred + tuple(
        candidate for candidate in candidates if candidate[0] != preferred_provider
    )


def _deprioritize_providers(
    candidates: tuple[tuple[str, str], ...],
    *,
    deprioritized_providers: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    providers = {provider for provider in (deprioritized_providers or set()) if provider}
    if not providers:
        return candidates
    preferred = tuple(candidate for candidate in candidates if candidate[0] not in providers)
    fallback = tuple(candidate for candidate in candidates if candidate[0] in providers)
    return preferred + fallback if preferred else candidates


def _select_runtime_candidate(
    *,
    candidates: tuple[tuple[str, str], ...],
) -> tuple[str, str, str, str | None, str | None]:
    preferred_provider, preferred_execution_tier = candidates[0]
    preferred_status = provider_runtime_state_service.get_status(preferred_provider)

    for provider, execution_tier in candidates:
        status = provider_runtime_state_service.get_status(provider)
        if status.configured and status.available:
            routing_mode = (
                "server_policy"
                if provider == preferred_provider
                else "server_policy_runtime_fallback"
            )
            route_reason = None
            if provider != preferred_provider:
                route_reason = (
                    preferred_status.state
                    if not preferred_status.available
                    else "preferred_provider_unavailable"
                )
            return provider, execution_tier, routing_mode, preferred_provider, route_reason

    route_reason = (
        preferred_status.state
        if not preferred_status.available
        else "no_runtime_healthy_candidates"
    )
    return (
        preferred_provider,
        preferred_execution_tier,
        "server_policy",
        preferred_provider,
        route_reason,
    )


def _resolve_v3_debate_candidates(
    *,
    role: str,
    requested_tier: str,
) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    candidates_by_role = _V3_DEBATE_ROUTE_CANDIDATES_BY_TIER.get(requested_tier, {})
    candidates = candidates_by_role.get(role)
    if candidates is None:
        return None
    return role, candidates


def _resolve_legacy_debate_candidates(
    *,
    role: str,
    requested_tier: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    semantic_role = _DEBATE_ROLE_ALIASES.get(role)
    if semantic_role is None:
        raise ValueError(f"Unknown debate role: {role!r}")

    compatibility_role = _DEBATE_COMPATIBILITY_ROLES[semantic_role]
    feature_role = compatibility_role
    candidates = _DEBATE_ROUTE_CANDIDATES.get(compatibility_role)
    if requested_tier == "deep_judgment":
        feature_role = semantic_role
        candidates = _HIGH_CONFIDENCE_DEBATE_ROUTE_CANDIDATES.get(semantic_role)
    if candidates is None:
        raise ValueError(f"Unknown debate role: {role!r}")
    return feature_role, candidates


def _resolve_debate_candidates(
    *,
    role: str,
    requested_tier: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    v3_resolution = _resolve_v3_debate_candidates(role=role, requested_tier=requested_tier)
    if v3_resolution is not None:
        feature_role, candidates = v3_resolution
    else:
        feature_role, candidates = _resolve_legacy_debate_candidates(
            role=role, requested_tier=requested_tier
        )
    if _bedrock_only_reasoning():
        candidates = _bedrock_candidates(candidates)
    return feature_role, candidates


def _build_debate_route_resolution(
    *,
    feature_role: str,
    candidates: tuple[tuple[str, str], ...],
    requested_tier: str,
) -> AuditRouteResolution:
    provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(candidates=candidates)
    )
    tier_class = "fast" if execution_tier == "fast" else "deep"
    return AuditRouteResolution(
        feature_key=f"audit.debate.{feature_role}",
        requested_tier=requested_tier,
        tier_class=tier_class,
        product_label=get_audit_tier_label(requested_tier),
        provider=provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
    )


def _enforce_provider_diversity(
    roles_in_layer: list[str],
    candidates: dict[str, tuple[tuple[str, str], ...]],
    *,
    exclude_providers: set[str] | None = None,
    preferred_provider: str | None = None,
) -> dict[str, tuple[str, str]]:
    used_providers: set[str] = {provider for provider in (exclude_providers or set()) if provider}
    assignments: dict[str, tuple[str, str]] = {}

    for role in roles_in_layer:
        role_candidates = candidates.get(role)
        if not role_candidates:
            continue
        # Honour the user's preferred provider before diversity deprioritisation
        reordered_candidates = _prioritize_provider(
            role_candidates,
            preferred_provider=preferred_provider,
        )
        prioritized_candidates = _deprioritize_providers(
            reordered_candidates,
            deprioritized_providers=used_providers,
        )
        provider, execution_tier, _routing_mode, _preferred_provider, _route_reason = (
            _select_runtime_candidate(candidates=prioritized_candidates)
        )
        assignments[role] = (provider, execution_tier)
        used_providers.add(provider)

    return assignments


def resolve_audit_route(
    *,
    tier: str | None,
    provider: str | None = None,
    selected_models: list[str] | tuple[str, ...] | None = None,
) -> AuditRouteResolution:
    requested_tier = normalize_audit_tier(tier)
    tier_class = normalize_audit_tier_class(requested_tier)
    raw_provider = str(provider or "").strip().lower() or None
    normalized_provider = _normalize_provider_key(provider)
    normalized_selected_models, ignored_selected_models = _normalize_selected_provider_keys(
        selected_models
    )
    preferred_provider = normalized_provider or (
        normalized_selected_models[0] if normalized_selected_models else None
    )
    candidates = _prioritize_provider(
        _route_candidates(_AUDIT_ROUTE_CANDIDATES[requested_tier]),
        preferred_provider=preferred_provider,
    )
    routed_provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(candidates=candidates)
    )
    if normalized_provider is not None:
        routing_mode = (
            "user_selected_provider"
            if routed_provider == normalized_provider
            else "user_selected_provider_runtime_fallback"
        )
    elif normalized_selected_models:
        routing_mode = (
            "user_selected_models"
            if routed_provider == normalized_selected_models[0]
            else "user_selected_models_runtime_fallback"
        )
    return AuditRouteResolution(
        feature_key="audit.main",
        requested_tier=requested_tier,
        tier_class=tier_class,
        product_label=get_audit_tier_label(requested_tier),
        provider=routed_provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
        selected_models=normalized_selected_models,
        ignored_provider=(
            raw_provider if raw_provider is not None and normalized_provider is None else None
        ),
        ignored_selected_models=ignored_selected_models,
    )


def resolve_prompt_ai_route() -> AuditRouteResolution:
    provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(candidates=_route_candidates(_PROMPT_AI_ROUTE_CANDIDATES))
    )
    return AuditRouteResolution(
        feature_key="suggestions.prompt_ai",
        requested_tier="smart",
        tier_class="deep",
        product_label=get_audit_tier_label("smart"),
        provider=provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
    )


def resolve_content_brief_route() -> AuditRouteResolution:
    provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(candidates=_route_candidates(_CONTENT_BRIEF_ROUTE_CANDIDATES))
    )
    return AuditRouteResolution(
        feature_key="content_brief.generate",
        requested_tier="smart",
        tier_class="deep",
        product_label=get_audit_tier_label("smart"),
        provider=provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
    )


def resolve_support_chat_route() -> AuditRouteResolution:
    provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(candidates=_route_candidates(_SUPPORT_CHAT_ROUTE_CANDIDATES))
    )
    return AuditRouteResolution(
        feature_key="support.thoth_chat",
        requested_tier="fast",
        tier_class="fast",
        product_label=get_audit_tier_label("fast"),
        provider=provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
    )


def resolve_pre_scan_route() -> AuditRouteResolution:
    provider, execution_tier = (
        _bedrock_route(_PRE_SCAN_ROUTE) if _bedrock_only_reasoning() else _PRE_SCAN_ROUTE
    )
    return AuditRouteResolution(
        feature_key="audit.pre_scan",
        requested_tier="fast",
        tier_class="fast",
        product_label=get_audit_tier_label("fast"),
        provider=provider,
        execution_tier=execution_tier,
    )


def resolve_site_classify_route() -> AuditRouteResolution:
    provider, execution_tier = (
        _bedrock_route(_SITE_CLASSIFY_ROUTE) if _bedrock_only_reasoning() else _SITE_CLASSIFY_ROUTE
    )
    return AuditRouteResolution(
        feature_key="site.classify",
        requested_tier="fast",
        tier_class="fast",
        product_label=get_audit_tier_label("fast"),
        provider=provider,
        execution_tier=execution_tier,
    )


def resolve_competitor_discovery_route() -> AuditRouteResolution:
    provider, execution_tier, routing_mode, preferred_provider, route_reason = (
        _select_runtime_candidate(
            candidates=_route_candidates(_COMPETITOR_DISCOVERY_ROUTE_CANDIDATES)
        )
    )
    return AuditRouteResolution(
        feature_key="competitors.discovery",
        requested_tier="fast",
        tier_class="fast",
        product_label=get_audit_tier_label("fast"),
        provider=provider,
        execution_tier=execution_tier,
        routing_mode=routing_mode,
        preferred_provider=preferred_provider,
        route_reason=route_reason,
    )


def resolve_debate_route(
    role: str,
    *,
    requested_tier: str = "smart",
    exclude_provider: str | None = None,
    preferred_provider: str | None = None,
) -> AuditRouteResolution:
    normalized_role = str(role or "").strip().lower()
    normalized_requested_tier = normalize_audit_tier(requested_tier)
    feature_role, candidates = _resolve_debate_candidates(
        role=normalized_role,
        requested_tier=normalized_requested_tier,
    )
    # Honour user's preferred provider, then deprioritise excluded providers
    reordered_candidates = _prioritize_provider(
        candidates,
        preferred_provider=preferred_provider,
    )
    reordered_candidates = _deprioritize_providers(
        reordered_candidates,
        deprioritized_providers={exclude_provider} if exclude_provider else None,
    )
    return _build_debate_route_resolution(
        feature_role=feature_role,
        candidates=reordered_candidates,
        requested_tier=normalized_requested_tier,
    )


def resolve_debate_routes_for_layer(
    roles: list[str],
    *,
    requested_tier: str = "smart",
    exclude_providers: set[str] | None = None,
    preferred_provider: str | None = None,
) -> dict[str, AuditRouteResolution]:
    normalized_requested_tier = normalize_audit_tier(requested_tier)
    normalized_roles = [
        str(role or "").strip().lower() for role in roles if str(role or "").strip()
    ]
    if not normalized_roles:
        return {}

    candidates_by_role = _V3_DEBATE_ROUTE_CANDIDATES_BY_TIER.get(normalized_requested_tier, {})
    if _bedrock_only_reasoning():
        candidates_by_role = _bedrock_candidates_by_role(candidates_by_role)
    v3_roles = [role for role in normalized_roles if role in candidates_by_role]
    assignments = _enforce_provider_diversity(
        v3_roles,
        candidates_by_role,
        exclude_providers=exclude_providers,
        preferred_provider=preferred_provider,
    )

    resolutions: dict[str, AuditRouteResolution] = {}
    for role in normalized_roles:
        if role in assignments:
            feature_role, role_candidates = _resolve_debate_candidates(
                role=role,
                requested_tier=normalized_requested_tier,
            )
            assigned_provider, assigned_tier = assignments[role]
            assigned_candidate = (assigned_provider, assigned_tier)
            reordered_candidates = (assigned_candidate,) + tuple(
                candidate for candidate in role_candidates if candidate != assigned_candidate
            )
            resolutions[role] = _build_debate_route_resolution(
                feature_role=feature_role,
                candidates=reordered_candidates,
                requested_tier=normalized_requested_tier,
            )
            continue

        resolutions[role] = resolve_debate_route(
            role,
            requested_tier=normalized_requested_tier,
            exclude_provider=None,
            preferred_provider=preferred_provider,
        )

    return resolutions
