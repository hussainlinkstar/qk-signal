from __future__ import annotations


from core.model_resolution import (
    MODEL_ENV_DEFAULTS,
    MODEL_ENV_VAR_MAP,
    resolve_model_name,
)
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

import models
from core.pricing_matrix import get_token_pricing_for_model
from services.ai_routing_policy import (
    normalize_audit_tier,
    resolve_audit_route,
    resolve_debate_route,
)
from services.pricing_policy_service import calculate_credits_from_real_cost, get_pricing_policy

DATAFORSEO_COST_PER_SERP_QUERY_USD = Decimal("0.003")
DATAFORSEO_COST_PER_PAA_QUERY_USD = Decimal("0.002")

_SERP_ITEM_TEXT_KEYS = (
    "title",
    "description",
    "snippet",
    "text",
    "answer",
    "headline",
)
_CONTENT_TEXT_KEYS = (
    "content",
    "markdown",
    "body_excerpt",
    "text",
    "title",
    "meta_description",
    "description",
    "summary",
)
# Canonical model maps live in core.model_resolution (single source of truth).
_MODEL_ENV_DEFAULTS = MODEL_ENV_DEFAULTS
_MODEL_ENV_VAR_MAP = MODEL_ENV_VAR_MAP
_ROLE_OUTPUT_TOKENS = {
    "proposer": 4_000,
    "challenger": 6_000,
    "synthesizer": 6_000,
}
_HIGH_CONFIDENCE_FORECAST_ROLES: tuple[tuple[str, str], ...] = (
    ("generator", "proposer"),
    ("critic", "challenger"),
    ("judge", "synthesizer"),
)
_STANDARD_DEBATE_FORECAST_ROLES: tuple[tuple[str, str], ...] = (
    ("proposer", "proposer"),
    ("challenger", "challenger"),
    ("synthesizer", "synthesizer"),
)


@dataclass(frozen=True)
class SerpComplexitySignal:
    keyword_count: int
    total_organic_results: int
    featured_snippet_present: bool
    paa_question_count: int
    knowledge_panel_present: bool
    local_pack_present: bool
    avg_serp_item_content_length: int
    ai_overview_present: bool
    serp_density_score: float


@dataclass(frozen=True)
class ContentComplexitySignal:
    page_text_chars: int
    entity_count: int
    has_structured_data: bool
    link_count: int
    image_count: int
    proposer_input_tokens: int
    challenger_input_tokens: int
    synthesizer_input_tokens: int
    estimated_prompt_tokens: int
    estimated_output_tokens: int
    content_density_score: float


@dataclass(frozen=True)
class CostForecast:
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    pricing_currency: str
    estimated_llm_cost_usd: Decimal
    estimated_serp_cost_usd: Decimal
    estimated_infra_cost_usd: Decimal
    estimated_total_cogs_usd: Decimal
    estimated_credits: int
    confidence: float
    breakdown: dict[str, Any]


@dataclass(frozen=True)
class ActualAuditCostBreakdown:
    provider: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    pricing_currency: str
    token_cost_usd: Decimal
    infra_cost_usd: Decimal
    orchestration_cost_usd: Decimal
    retry_risk_usd: Decimal
    total_cogs_usd: Decimal
    usage_mode: str
    step_count: int
    breakdown: dict[str, Any]

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _to_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            try:
                return Decimal(cleaned)
            except Exception:
                return Decimal("0")
    return Decimal("0")


def _money(value: Decimal | float | int | str | None) -> Decimal:
    return _to_decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    payload = usage if isinstance(usage, dict) else {}
    prompt_tokens = _safe_int(
        payload.get("prompt_tokens")
        or payload.get("input_tokens")
        or payload.get("prompt_token_count")
    )
    completion_tokens = _safe_int(
        payload.get("completion_tokens")
        or payload.get("output_tokens")
        or payload.get("candidates_token_count")
    )
    total_tokens = _safe_int(payload.get("total_tokens") or (prompt_tokens + completion_tokens))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _resolve_model_name(provider: str | None, execution_tier: str | None) -> str:
    return resolve_model_name(provider, execution_tier)


def _estimate_usage_cost_usd(
    model_name: str | None, prompt_tokens: int, completion_tokens: int
) -> Decimal:
    pricing = get_token_pricing_for_model(model_name)
    input_rate = _to_decimal(pricing.get("input"))
    output_rate = _to_decimal(pricing.get("output"))
    input_cost = (Decimal(max(0, int(prompt_tokens))) / Decimal("1000000")) * input_rate
    output_cost = (Decimal(max(0, int(completion_tokens))) / Decimal("1000000")) * output_rate
    return _money(input_cost + output_cost)


def _collect_text(value: Any, *, depth: int = 0) -> list[str]:
    if value is None or depth > 3:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        collected: list[str] = []
        for item in value[:20]:
            collected.extend(_collect_text(item, depth=depth + 1))
        return collected
    if isinstance(value, dict):
        collected: list[str] = []
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in _CONTENT_TEXT_KEYS or depth < 1:
                collected.extend(_collect_text(item, depth=depth + 1))
        return collected
    return []


def _extract_serp_items(entry: Any) -> list[dict[str, Any]]:
    if not isinstance(entry, dict):
        return []
    for key in ("items", "results", "serp_items"):
        value = entry.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def analyze_serp_complexity(
    dataforseo_results: list[dict[str, Any]] | None,
) -> SerpComplexitySignal:
    results = dataforseo_results if isinstance(dataforseo_results, list) else []
    keyword_count = len(results)
    total_organic_results = 0
    featured_snippet_present = False
    paa_question_count = 0
    knowledge_panel_present = False
    local_pack_present = False
    ai_overview_present = False
    content_lengths: list[int] = []

    for result in results:
        items = _extract_serp_items(result)
        if not items:
            organic_results = result.get("organic_results")
            if isinstance(organic_results, list):
                total_organic_results += len(organic_results)
                items = [item for item in organic_results if isinstance(item, dict)]

        for item in items:
            item_type = str(item.get("type") or item.get("item_type") or "").strip().lower()
            if "organic" in item_type or not item_type:
                total_organic_results += 1
            if "featured" in item_type and "snippet" in item_type:
                featured_snippet_present = True
            if (
                item_type in {"people_also_ask", "paa", "related_question"}
                or "people_also_ask" in item_type
            ):
                paa_question_count += 1
            if "knowledge" in item_type and "panel" in item_type:
                knowledge_panel_present = True
            if "local" in item_type and "pack" in item_type:
                local_pack_present = True
            if (
                "ai_overview" in item_type
                or "ai_answer" in item_type
                or "google_ai_overview" in item_type
            ):
                ai_overview_present = True
            item_text = " ".join(
                str(item.get(key) or "").strip()
                for key in _SERP_ITEM_TEXT_KEYS
                if str(item.get(key) or "").strip()
            )
            if item_text:
                content_lengths.append(len(item_text))

        if result.get("featured_snippet_present") is True:
            featured_snippet_present = True
        if result.get("knowledge_panel_present") is True:
            knowledge_panel_present = True
        if result.get("local_pack_present") is True:
            local_pack_present = True
        if result.get("ai_overview_present") is True or result.get("ai_overview_detected") is True:
            ai_overview_present = True
        paa_question_count += _safe_int(result.get("paa_question_count"))

    avg_content_length = int(sum(content_lengths) / len(content_lengths)) if content_lengths else 0
    density = 0.2
    density += min(0.3, paa_question_count * 0.1)
    density += 0.15 if featured_snippet_present else 0.0
    density += 0.10 if knowledge_panel_present else 0.0
    density += 0.05 if local_pack_present else 0.0
    density += 0.10 if ai_overview_present else 0.0
    density += min(0.20, max(0, avg_content_length - 500) * 0.001)

    return SerpComplexitySignal(
        keyword_count=max(0, keyword_count),
        total_organic_results=max(0, total_organic_results),
        featured_snippet_present=featured_snippet_present,
        paa_question_count=max(0, paa_question_count),
        knowledge_panel_present=knowledge_panel_present,
        local_pack_present=local_pack_present,
        avg_serp_item_content_length=max(0, avg_content_length),
        ai_overview_present=ai_overview_present,
        serp_density_score=round(_clamp(density, 0.0, 1.0), 4),
    )


def analyze_content_complexity(
    audit_data: dict[str, Any] | None,
    entities_count: int = 0,
) -> ContentComplexitySignal:
    payload = audit_data if isinstance(audit_data, dict) else {}
    text_fragments = _collect_text(payload)
    page_text = "\n".join(fragment for fragment in text_fragments if fragment)
    page_text_chars = len(page_text)
    entity_count = max(0, int(entities_count or 0))
    html_content = str(payload.get("html") or payload.get("content") or "")
    link_count = html_content.lower().count("<a ")
    image_count = html_content.lower().count("<img ")

    has_structured_data = False
    schema_payload = (
        payload.get("schema") or payload.get("structured_data") or payload.get("schema_structure")
    )
    if isinstance(schema_payload, (dict, list)) and bool(schema_payload):
        has_structured_data = True
    elif "@type" in html_content or "application/ld+json" in html_content:
        has_structured_data = True

    base_content_tokens = min(page_text_chars // 4, 15_000)
    prompt_overhead_tokens = (
        900
        + min(entity_count, 12) * 110
        + min(link_count, 80) * 6
        + min(image_count, 30) * 14
        + (400 if has_structured_data else 0)
    )

    proposer_input_tokens = min(15_000, base_content_tokens) + prompt_overhead_tokens
    challenger_input_tokens = (
        min(10_000, base_content_tokens) + int(prompt_overhead_tokens * 0.55) + 4_000
    )
    synthesizer_input_tokens = (
        min(8_000, base_content_tokens) + int(prompt_overhead_tokens * 0.35) + 10_000
    )
    estimated_prompt_tokens = (
        proposer_input_tokens + challenger_input_tokens + synthesizer_input_tokens
    )
    estimated_output_tokens = sum(_ROLE_OUTPUT_TOKENS.values())

    density = 0.15
    density += min(0.45, page_text_chars / 60_000)
    density += min(0.15, entity_count * 0.025)
    density += min(0.10, link_count / 250)
    density += min(0.08, image_count / 120)
    density += 0.07 if has_structured_data else 0.0

    return ContentComplexitySignal(
        page_text_chars=max(0, page_text_chars),
        entity_count=entity_count,
        has_structured_data=has_structured_data,
        link_count=max(0, link_count),
        image_count=max(0, image_count),
        proposer_input_tokens=max(0, proposer_input_tokens),
        challenger_input_tokens=max(0, challenger_input_tokens),
        synthesizer_input_tokens=max(0, synthesizer_input_tokens),
        estimated_prompt_tokens=max(0, estimated_prompt_tokens),
        estimated_output_tokens=estimated_output_tokens,
        content_density_score=round(_clamp(density, 0.0, 1.0), 4),
    )


def build_audit_forecast_input(
    *,
    target_url: str | None = None,
    target_name: str | None = None,
    target_metadata: dict[str, Any] | None = None,
    category: str | None = None,
    market: str | None = None,
    language: str | None = None,
    audit_data: dict[str, Any] | None = None,
    entities: list[str] | None = None,
) -> dict[str, Any]:
    payload = dict(audit_data or {})
    if target_url:
        payload.setdefault("target_url", target_url)
        payload.setdefault("url", target_url)
    if target_name:
        payload.setdefault("target_name", target_name)
    if isinstance(target_metadata, dict) and target_metadata:
        payload.setdefault("target_metadata", dict(target_metadata))
    if category:
        payload.setdefault("category", category)
    if market:
        payload.setdefault("market", market)
    if language:
        payload.setdefault("language", language)
    if entities:
        payload.setdefault(
            "entities_detected", [entity for entity in entities if str(entity).strip()]
        )
    return payload


def get_calibration_factor(
    db: Session | None,
    *,
    feature_key: str,
    tier_class: str,
    requested_tier: str | None = None,
    lookback_days: int = 30,
) -> tuple[Decimal, int]:
    if db is None:
        return Decimal("1.0"), 0

    window_start = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days or 30)))
    rows = (
        db.query(models.AIEconomicsLedgerEntry)
        .filter(
            models.AIEconomicsLedgerEntry.feature_key
            == str(feature_key or "audit.main").strip().lower(),
            models.AIEconomicsLedgerEntry.tier_class == str(tier_class or "fast").strip().lower(),
            models.AIEconomicsLedgerEntry.created_at >= window_start,
        )
        .order_by(models.AIEconomicsLedgerEntry.created_at.desc())
        .limit(200)
        .all()
    )

    requested_tier_filter = normalize_audit_tier(requested_tier) if requested_tier else None
    estimated_values: list[Decimal] = []
    actual_values: list[Decimal] = []
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        if requested_tier_filter == "deep_judgment":
            payload_requested_tier = (
                normalize_audit_tier(payload.get("requested_tier"))
                if isinstance(payload.get("requested_tier"), str)
                else None
            )
            payload_profile = str(payload.get("debate_profile") or "").strip().lower()
            if payload_requested_tier != "deep_judgment" and payload_profile != "high_confidence":
                continue
        estimated = _to_decimal(
            payload.get("estimated_total_cogs_usd") or payload.get("estimated_cost_usd")
        )
        actual = _to_decimal(payload.get("actual_total_cogs_usd") or row.real_cost_usd)
        if estimated > 0 and actual > 0:
            estimated_values.append(estimated)
            actual_values.append(actual)

    sample_size = len(estimated_values)
    if sample_size == 0:
        return Decimal("1.0"), 0

    avg_estimated = sum(estimated_values) / Decimal(sample_size)
    avg_actual = sum(actual_values) / Decimal(sample_size)
    if avg_estimated <= 0:
        return Decimal("1.0"), sample_size

    factor = avg_actual / avg_estimated
    clamped = min(Decimal("1.5"), max(Decimal("0.8"), factor))
    return _money(clamped), sample_size


def _estimate_serp_prompt_tokens(signal: SerpComplexitySignal) -> int:
    if signal.keyword_count <= 0:
        return 0
    base = signal.keyword_count * 240
    base += min(signal.total_organic_results, 10) * 55
    base += signal.paa_question_count * 120
    base += int(signal.avg_serp_item_content_length / 5)
    if signal.featured_snippet_present:
        base += 300
    if signal.knowledge_panel_present:
        base += 220
    if signal.local_pack_present:
        base += 140
    return max(0, base)


def _estimate_serp_cost(signal: SerpComplexitySignal) -> Decimal:
    if signal.keyword_count <= 0:
        return Decimal("0")
    serp_cost = DATAFORSEO_COST_PER_SERP_QUERY_USD * Decimal(signal.keyword_count)
    if signal.paa_question_count > 0:
        serp_cost += DATAFORSEO_COST_PER_PAA_QUERY_USD * Decimal(signal.keyword_count)
    return _money(serp_cost)


def _normalized_selected_models(
    selected_models: list[str] | tuple[str, ...] | None,
) -> list[str]:
    return [str(model).strip().lower() for model in (selected_models or []) if str(model).strip()]


def _resolve_forecast_requested_tier(*, tier_class: str, requested_tier: str | None) -> str:
    if isinstance(requested_tier, str) and requested_tier.strip():
        return normalize_audit_tier(requested_tier)
    return normalize_audit_tier(tier_class)


def _resolve_forecast_debate_profile(requested_tier: str, *, is_consensus: bool) -> str | None:
    if is_consensus:
        return None
    normalized_requested_tier = normalize_audit_tier(requested_tier)
    if normalized_requested_tier == "deep_judgment":
        return "high_confidence"
    if normalized_requested_tier == "smart":
        return "standard"
    return None


def _resolve_forecast_roles(requested_tier: str) -> tuple[tuple[str, str], ...]:
    if normalize_audit_tier(requested_tier) == "deep_judgment":
        return _HIGH_CONFIDENCE_FORECAST_ROLES
    return _STANDARD_DEBATE_FORECAST_ROLES


def forecast_audit_cost(
    *,
    audit_data: dict[str, Any] | None,
    dataforseo_results: list[dict[str, Any]] | None,
    tier_class: str,
    requested_tier: str | None = None,
    policy_version: str | None,
    feature_key: str = "audit.main",
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
    provider: str | None = None,
    selected_models: list[str] | tuple[str, ...] | None = None,
    db: Session | None = None,
) -> CostForecast:
    normalized_tier_class = str(tier_class or "fast").strip().lower() or "fast"
    resolved_requested_tier = _resolve_forecast_requested_tier(
        tier_class=normalized_tier_class,
        requested_tier=requested_tier,
    )
    normalized_models = _normalized_selected_models(selected_models)
    route = resolve_audit_route(
        tier=resolved_requested_tier,
        provider=provider,
        selected_models=normalized_models or None,
    )
    routed_selected_models = list(route.selected_models)
    content_signal = analyze_content_complexity(audit_data, entities_count=entities_count)
    serp_signal = analyze_serp_complexity(dataforseo_results)
    serp_prompt_tokens = _estimate_serp_prompt_tokens(serp_signal)

    step_breakdown: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_llm_cost_usd = Decimal("0")

    if len(routed_selected_models) >= 2:
        if route.tier_class == "deep":
            per_model_input_tokens = content_signal.estimated_prompt_tokens + serp_prompt_tokens
            per_model_output_tokens = content_signal.estimated_output_tokens
        else:
            base_input_tokens = min(12_000, max(1_200, content_signal.page_text_chars // 4 + 950))
            if category:
                base_input_tokens += 180
            if market:
                base_input_tokens += 160
            base_input_tokens += min(entities_count, 12) * 100
            per_model_input_tokens = base_input_tokens + serp_prompt_tokens
            per_model_output_tokens = 3_200

        for provider_name in routed_selected_models:
            model_name = _resolve_model_name(provider_name, route.execution_tier)
            step_cost_usd = _estimate_usage_cost_usd(
                model_name,
                per_model_input_tokens,
                per_model_output_tokens,
            )
            step_cost_usd = step_cost_usd
            total_input_tokens += per_model_input_tokens
            total_output_tokens += per_model_output_tokens
            total_llm_cost_usd += step_cost_usd
            step_breakdown.append(
                {
                    "role": f"model:{provider_name}",
                    "provider": provider_name,
                    "tier": route.execution_tier,
                    "model": model_name,
                    "input_tokens": per_model_input_tokens,
                    "output_tokens": per_model_output_tokens,
                    "estimated_cost_usd": float(_money(step_cost_usd)),
                }
            )

        synthesis_input_tokens = min(
            16_000,
            2_400 + (len(routed_selected_models) * 2_800) + (content_signal.page_text_chars // 10),
        ) + int(serp_prompt_tokens * 0.25)
        synthesis_output_tokens = 3_200
        synthesis_model = _resolve_model_name("google", "fast")
        synthesis_cost_usd = _estimate_usage_cost_usd(
            synthesis_model,
            synthesis_input_tokens,
            synthesis_output_tokens,
        )
        synthesis_cost_usd = synthesis_cost_usd
        total_input_tokens += synthesis_input_tokens
        total_output_tokens += synthesis_output_tokens
        total_llm_cost_usd += synthesis_cost_usd
        step_breakdown.append(
            {
                "role": "consensus_synthesis",
                "provider": "google",
                "tier": "fast",
                "model": synthesis_model,
                "input_tokens": synthesis_input_tokens,
                "output_tokens": synthesis_output_tokens,
                "estimated_cost_usd": float(_money(synthesis_cost_usd)),
            }
        )
    elif route.tier_class == "deep":
        step_inputs = {
            "proposer": content_signal.proposer_input_tokens + int(serp_prompt_tokens * 0.45),
            "challenger": content_signal.challenger_input_tokens + int(serp_prompt_tokens * 0.35),
            "synthesizer": content_signal.synthesizer_input_tokens + int(serp_prompt_tokens * 0.20),
        }
        exclude_provider: str | None = None
        for forecast_role, compatibility_role in _resolve_forecast_roles(route.requested_tier):
            debate_route = resolve_debate_route(
                forecast_role,
                requested_tier=route.requested_tier,
                exclude_provider=exclude_provider,
            )
            model_name = _resolve_model_name(debate_route.provider, debate_route.execution_tier)
            output_tokens = _ROLE_OUTPUT_TOKENS[compatibility_role]
            input_tokens = max(0, step_inputs[compatibility_role])
            step_cost_usd = _estimate_usage_cost_usd(model_name, input_tokens, output_tokens)
            step_cost_usd = step_cost_usd
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            total_llm_cost_usd += step_cost_usd
            step_breakdown.append(
                {
                    "role": forecast_role,
                    "semantic_role": (
                        forecast_role
                        if route.requested_tier == "deep_judgment"
                        else {
                            "proposer": "generator",
                            "challenger": "critic",
                            "synthesizer": "judge",
                        }.get(forecast_role, forecast_role)
                    ),
                    "compatibility_role": compatibility_role,
                    "provider": debate_route.provider,
                    "tier": debate_route.execution_tier,
                    "execution_tier": debate_route.execution_tier,
                    "model": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "routing_mode": debate_route.routing_mode,
                    "route_reason": debate_route.route_reason,
                    "requested_tier": debate_route.requested_tier,
                    "estimated_cost_usd": float(_money(step_cost_usd)),
                }
            )
            exclude_provider = debate_route.provider
    else:
        model_name = _resolve_model_name(route.provider, route.execution_tier)
        base_input_tokens = min(12_000, max(1_200, content_signal.page_text_chars // 4 + 950))
        if category:
            base_input_tokens += 180
        if market:
            base_input_tokens += 160
        base_input_tokens += min(entities_count, 12) * 100
        input_tokens = base_input_tokens + serp_prompt_tokens
        output_tokens = 3_200
        step_cost_usd = _estimate_usage_cost_usd(model_name, input_tokens, output_tokens)
        step_cost_usd = step_cost_usd
        total_input_tokens = input_tokens
        total_output_tokens = output_tokens
        total_llm_cost_usd = step_cost_usd
        step_breakdown.append(
            {
                "role": "audit",
                "provider": route.provider,
                "tier": route.execution_tier,
                "model": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": float(_money(step_cost_usd)),
            }
        )

    policy = get_pricing_policy(policy_version)
    orchestration_hops = max(1, len(step_breakdown))
    raw_infra = (
        policy.resolve_infra_alloc(feature_key)
        if (total_input_tokens + total_output_tokens) > 0
        else Decimal("0")
    )
    raw_infra += (
        policy.resolve_orchestration_cost(feature_key) * Decimal(orchestration_hops)
        if (total_input_tokens + total_output_tokens) > 0
        else Decimal("0")
    )
    raw_serp_cost = _estimate_serp_cost(serp_signal)
    total_llm_cost_usd = total_llm_cost_usd
    raw_total_cogs = _money(total_llm_cost_usd + raw_serp_cost + raw_infra)

    calibration_factor, calibration_sample_size = get_calibration_factor(
        db,
        feature_key=feature_key,
        tier_class=route.tier_class,
        requested_tier=route.requested_tier,
    )
    calibrated_total = _money(raw_total_cogs * calibration_factor)
    estimated_credits, _ = calculate_credits_from_real_cost(
        real_cost_usd=calibrated_total,
        policy_version=policy.version,
        feature_key=feature_key,
        tier_class=route.tier_class,
        billable=True,
    )

    confidence = 0.45
    if content_signal.page_text_chars > 0:
        confidence += 0.20
    if serp_signal.keyword_count > 0:
        confidence += 0.15
    if calibration_sample_size >= 5:
        confidence += min(0.15, calibration_sample_size / 100)
    if content_signal.page_text_chars == 0 and serp_signal.keyword_count == 0:
        confidence -= 0.15
    confidence = round(_clamp(confidence, 0.2, 0.95), 4)

    debate_profile = _resolve_forecast_debate_profile(
        route.requested_tier,
        is_consensus=len(route.selected_models) >= 2,
    )
    breakdown = {
        "requested_tier": route.requested_tier,
        "mode_label": route.product_label,
        "resolved_provider": route.provider,
        "resolved_execution_tier": route.execution_tier,
        "tier_class": route.tier_class,
        "forecast_mode": "multi_model_consensus" if len(route.selected_models) >= 2 else "standard",
        "debate_profile": debate_profile,
        "calibration_scope": "requested_tier"
        if route.requested_tier == "deep_judgment"
        else "tier_class",
        "selected_models": list(route.selected_models),
        "content_density_score": content_signal.content_density_score,
        "serp_density_score": serp_signal.serp_density_score,
        "content_signal": {
            "page_text_chars": content_signal.page_text_chars,
            "entity_count": content_signal.entity_count,
            "has_structured_data": content_signal.has_structured_data,
            "link_count": content_signal.link_count,
            "image_count": content_signal.image_count,
        },
        "serp_signal": asdict(serp_signal),
        "steps": step_breakdown,
        "pricing_currency": "USD",
        "raw_total_llm_cost_usd": float(_money(total_llm_cost_usd)),
        "raw_total_cogs_usd": float(raw_total_cogs),
        "calibration_factor": float(calibration_factor),
        "calibration_sample_size": calibration_sample_size,
        "orchestration_hops": orchestration_hops,
        "estimated_serp_prompt_tokens": serp_prompt_tokens,
    }
    return CostForecast(
        estimated_input_tokens=max(0, total_input_tokens),
        estimated_output_tokens=max(0, total_output_tokens),
        estimated_total_tokens=max(0, total_input_tokens + total_output_tokens),
        pricing_currency="USD",
        estimated_llm_cost_usd=_money(total_llm_cost_usd),
        estimated_serp_cost_usd=_money(raw_serp_cost),
        estimated_infra_cost_usd=_money(raw_infra),
        estimated_total_cogs_usd=calibrated_total,
        estimated_credits=max(1, int(estimated_credits or 1)),
        confidence=confidence,
        breakdown=breakdown,
    )


def serialize_cost_forecast(forecast: CostForecast) -> dict[str, Any]:
    return {
        "estimated_input_tokens": forecast.estimated_input_tokens,
        "estimated_output_tokens": forecast.estimated_output_tokens,
        "estimated_total_tokens": forecast.estimated_total_tokens,
        "pricing_currency": forecast.pricing_currency,
        "estimated_llm_cost_usd": float(forecast.estimated_llm_cost_usd),
        "estimated_serp_cost_usd": float(forecast.estimated_serp_cost_usd),
        "estimated_infra_cost_usd": float(forecast.estimated_infra_cost_usd),
        "estimated_total_cogs_usd": float(forecast.estimated_total_cogs_usd),
        "estimated_credits": forecast.estimated_credits,
        "confidence": forecast.confidence,
        "breakdown": dict(forecast.breakdown),
    }


def calculate_actual_audit_cost(
    *,
    report: dict[str, Any] | None,
    policy_version: str | None,
    feature_key: str = "audit.main",
) -> ActualAuditCostBreakdown:
    payload = report if isinstance(report, dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    ai_generation = (
        metadata.get("ai_generation") if isinstance(metadata.get("ai_generation"), dict) else {}
    )
    if not ai_generation and isinstance(payload.get("ai_generation"), dict):
        ai_generation = payload.get("ai_generation")

    transcript = (
        ai_generation.get("transcript") if isinstance(ai_generation.get("transcript"), list) else []
    )
    post_processing_transcript = (
        ai_generation.get("post_processing_transcript")
        if isinstance(ai_generation.get("post_processing_transcript"), list)
        else []
    )
    usage_mode = str(ai_generation.get("mode") or "unknown").strip().lower() or "unknown"
    provider = str(ai_generation.get("provider") or "").strip() or None
    model = str(ai_generation.get("model") or "").strip() or None
    requested_tier_value = (
        metadata.get("requested_tier")
        if metadata.get("requested_tier")
        else payload.get("requested_tier")
    )
    requested_tier = (
        normalize_audit_tier(requested_tier_value)
        if isinstance(requested_tier_value, str) and requested_tier_value
        else None
    )
    debate_profile = str(ai_generation.get("profile") or "").strip().lower() or None

    input_tokens = 0
    output_tokens = 0
    token_cost_usd = Decimal("0")
    steps: list[dict[str, Any]] = []

    def _append_transcript_steps(
        source_transcript: list[dict[str, Any]],
        *,
        pipeline_stage: str,
    ) -> None:
        nonlocal input_tokens, output_tokens, token_cost_usd
        for step in source_transcript:
            if not isinstance(step, dict):
                continue
            step_usage = _normalize_usage(
                step.get("token_usage") if isinstance(step.get("token_usage"), dict) else {}
            )
            if step_usage["total_tokens"] <= 0:
                continue
            step_provider = str(step.get("provider") or "").strip().lower() or None
            step_execution_tier = (
                str(step.get("execution_tier") or step.get("tier") or "").strip().lower() or None
            )
            step_model = str(step.get("model") or "").strip() or _resolve_model_name(
                step_provider,
                step_execution_tier,
            )
            step_cost_usd = _estimate_usage_cost_usd(
                step_model,
                step_usage["prompt_tokens"],
                step_usage["completion_tokens"],
            )
            step_cost_usd = step_cost_usd
            input_tokens += step_usage["prompt_tokens"]
            output_tokens += step_usage["completion_tokens"]
            token_cost_usd += step_cost_usd
            steps.append(
                {
                    "pipeline_stage": pipeline_stage,
                    "operation": str(step.get("operation") or "").strip() or None,
                    "role": str(step.get("role") or "").strip() or "unknown",
                    "semantic_role": str(step.get("semantic_role") or "").strip() or None,
                    "provider": step_provider,
                    "model": step_model,
                    "execution_tier": step_execution_tier,
                    "input_tokens": step_usage["prompt_tokens"],
                    "output_tokens": step_usage["completion_tokens"],
                    "actual_cost_usd": float(_money(step_cost_usd)),
                }
            )

    if transcript:
        if usage_mode == "unknown":
            usage_mode = "debate"
        provider = provider or "multi-provider"
        model = model or "multi-agent"
        _append_transcript_steps(transcript, pipeline_stage="generation")
    else:
        usage = _normalize_usage(
            ai_generation.get("usage") if isinstance(ai_generation.get("usage"), dict) else {}
        )
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]
        token_cost_usd = _estimate_usage_cost_usd(model, input_tokens, output_tokens)
        token_cost_usd = token_cost_usd
        if usage["total_tokens"] > 0:
            steps.append(
                {
                    "pipeline_stage": "generation",
                    "operation": None,
                    "role": "audit",
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "actual_cost_usd": float(_money(token_cost_usd)),
                }
            )
            if usage_mode == "unknown":
                usage_mode = "single"

    _append_transcript_steps(post_processing_transcript, pipeline_stage="post_processing")

    total_tokens = input_tokens + output_tokens
    policy = get_pricing_policy(policy_version)
    token_cost_usd = token_cost_usd
    infra_cost = policy.resolve_infra_alloc(feature_key) if total_tokens > 0 else Decimal("0")
    orchestration_cost = (
        policy.resolve_orchestration_cost(feature_key) * Decimal(max(1, len(steps)))
        if total_tokens > 0
        else Decimal("0")
    )
    retry_risk = Decimal("0")
    total_cogs = _money(token_cost_usd + infra_cost + orchestration_cost + retry_risk)

    return ActualAuditCostBreakdown(
        provider=provider,
        model=model,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
        pricing_currency="USD",
        token_cost_usd=_money(token_cost_usd),
        infra_cost_usd=_money(infra_cost),
        orchestration_cost_usd=_money(orchestration_cost),
        retry_risk_usd=_money(retry_risk),
        total_cogs_usd=total_cogs,
        usage_mode=usage_mode,
        step_count=len(steps),
        breakdown={
            "steps": steps,
            "ai_generation": dict(ai_generation),
            "requested_tier": requested_tier,
            "debate_profile": debate_profile,
            "pricing_currency": "USD",
        },
    )
