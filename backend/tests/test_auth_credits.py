import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from auth import credits


def _make_user(*, credits_value: int, subscription_status: str | None):
    subscription = None
    if subscription_status is not None:
        subscription = SimpleNamespace(status=subscription_status)
    return SimpleNamespace(credits=credits_value, subscription=subscription)


def test_calculate_audit_credit_cost_applies_provider_tier_and_inputs():
    baseline = credits.calculate_audit_credit_cost(provider="google", tier="fast")
    weighted = credits.calculate_audit_credit_cost(
        provider="openai",
        tier="smart",
        entities_count=4,
        category="Local SEO",
        market="ro",
    )

    assert baseline == 2
    assert weighted > baseline


def test_calculate_audit_credit_cost_maps_deep_to_smart():
    deep_cost = credits.calculate_audit_credit_cost(provider="openai", tier="deep")
    smart_cost = credits.calculate_audit_credit_cost(provider="openai", tier="smart")

    assert deep_cost == smart_cost


def test_calculate_audit_credit_cost_supports_deep_judgment_contract():
    deep_judgment_cost = credits.calculate_audit_credit_cost(
        provider="openai",
        tier="deep_judgment",
    )
    smart_cost = credits.calculate_audit_credit_cost(provider="openai", tier="smart")

    assert deep_judgment_cost == smart_cost


def test_calculate_audit_credit_cost_maps_standard_to_fast():
    standard_cost = credits.calculate_audit_credit_cost(provider="google", tier="standard")
    fast_cost = credits.calculate_audit_credit_cost(provider="google", tier="fast")

    assert standard_cost == fast_cost


def test_tier_requires_quota_uses_env_and_normalizes_case(monkeypatch):
    monkeypatch.setenv("AUDIT_QUOTA_TIERS", "pro, ENTERPRISE, Starter ")

    assert credits.tier_requires_quota("PRO") is True
    assert credits.tier_requires_quota("enterprise") is True
    assert credits.tier_requires_quota("sTaRtEr") is True
    assert credits.tier_requires_quota("plan_starter") is False


def test_should_decrement_credits_always_returns_true(monkeypatch):
    monkeypatch.setenv("AUDIT_QUOTA_TIERS", "pro,ENTERPRISE")

    active_user = _make_user(credits_value=99, subscription_status="active")
    inactive_user = _make_user(credits_value=99, subscription_status="canceled")

    assert credits.should_decrement_credits(active_user, "FREE") is True
    assert credits.should_decrement_credits(active_user, "PrO") is True
    assert credits.should_decrement_credits(inactive_user, "FREE") is True
    assert credits.should_decrement_credits(inactive_user, "EnTeRpRiSe") is True


def test_prompt_recommendation_credit_cost_is_fixed_and_positive():
    assert credits.PROMPT_RECOMMENDATION_CREDIT_COST == 3
