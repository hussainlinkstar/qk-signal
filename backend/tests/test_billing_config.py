import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from billing.config import Plan, load_billing_config  # noqa: E402


def test_load_billing_config_handles_missing_trial_price_env_keys() -> None:
    config = load_billing_config(runtime_overrides={})

    assert config.price_id_for(Plan.AGENCY_TRIAL) == ""
    assert config.price_id_for_mode("test", Plan.AGENCY_TRIAL) == ""
    assert config.price_id_for_mode("live", Plan.AGENCY_TRIAL) == ""


@pytest.mark.parametrize(
    ("env_key", "env_value", "mode", "plan"),
    [
        ("STRIPE_PRICE_STANDARD_TEST", "price_test_plan_standard", "test", Plan.STANDARD),
        ("STRIPE_PRICE_SPECIALIST_TEST", "price_test_plan_specialist", "test", Plan.SPECIALIST),
        (
            "STRIPE_PRICE_EXECUTIVE_LIVE",
            "price_live_plan_executive",
            "live",
            Plan.EXECUTIVE,
        ),
    ],
)
def test_load_billing_config_prefers_canonical_plan_price_env_names(
    monkeypatch, env_key: str, env_value: str, mode: str, plan: Plan
) -> None:
    monkeypatch.setenv("STRIPE_MODE", mode)
    monkeypatch.setenv(env_key, env_value)

    config = load_billing_config(runtime_overrides={})

    assert config.price_id_for_mode(mode, plan) == env_value


def test_load_billing_config_ignores_removed_legacy_price_env_names(monkeypatch) -> None:
    # Legacy STARTER/PRO/ENTERPRISE fallback was removed; STARTER now maps to plan_starter only.
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_PRICE_STARTER_TEST", "price_test_starter")

    config = load_billing_config(runtime_overrides={})

    assert config.price_id_for_mode("test", Plan.STARTER) == "price_test_starter"
    assert config.price_id_for_mode("test", Plan.STANDARD) == ""
