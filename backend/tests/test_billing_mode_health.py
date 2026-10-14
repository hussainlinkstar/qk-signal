"""SIGV2-1270: a wrong billing mode must be visible on the health surface.

Production once resolved STRIPE_MODE=test while .env said live, because the
SSM overlay is authoritative. Checkout worked, nothing was captured, and the
health endpoint reported Operational. These tests pin the effective-mode
reporting through billing.config.load_billing_config - the same path
checkout uses - and the production-environment Degraded verdict.

Resolution-only: nothing here may construct a Stripe client.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))


import system_checks


def _billing_env(monkeypatch, *, environment: str, stripe_mode: str) -> None:
    monkeypatch.setattr(system_checks.settings, "ENVIRONMENT", environment)
    monkeypatch.setenv("STRIPE_MODE", stripe_mode)
    monkeypatch.setattr(system_checks.settings, "STRIPE_SECRET_KEY_TEST", "sk_test_x")
    monkeypatch.setattr(system_checks.settings, "STRIPE_SECRET_KEY_LIVE", "sk_live_x")


def test_test_mode_in_production_is_degraded(monkeypatch):
    _billing_env(monkeypatch, environment="production", stripe_mode="test")
    status, details = system_checks._stripe_billing_status(None)
    assert status == "Degraded"
    assert "test" in details
    assert "production" in details
    assert "no payment will be captured" in details


def test_live_mode_in_production_is_operational(monkeypatch):
    _billing_env(monkeypatch, environment="production", stripe_mode="live")
    status, details = system_checks._stripe_billing_status(None)
    assert status == "Operational"
    assert "live" in details


def test_test_mode_in_development_is_operational(monkeypatch):
    """Preprod/local legitimately run Stripe test mode; no crying wolf."""
    _billing_env(monkeypatch, environment="development", stripe_mode="test")
    status, details = system_checks._stripe_billing_status(None)
    assert status == "Operational"
    assert "test" in details


def test_details_always_name_the_effective_mode(monkeypatch):
    for env, mode in (("production", "test"), ("production", "live"), ("development", "test")):
        _billing_env(monkeypatch, environment=env, stripe_mode=mode)
        _, details = system_checks._stripe_billing_status(None)
        assert f"mode: {mode}" in details, details


def test_no_stripe_client_is_constructed(monkeypatch):
    """Resolution-only: if this check ever starts constructing a Stripe
    client the health endpoint would open a billing API connection."""
    import stripe

    def _boom(*_args, **_kwargs):
        raise AssertionError("Stripe client constructed during a health check")

    monkeypatch.setattr(stripe, "StripeClient", _boom, raising=False)
    _billing_env(monkeypatch, environment="production", stripe_mode="test")
    status, _ = system_checks._stripe_billing_status(None)
    assert status == "Degraded"


def test_missing_key_reports_not_configured_with_mode(monkeypatch):
    _billing_env(monkeypatch, environment="development", stripe_mode="live")
    monkeypatch.setattr(system_checks.settings, "STRIPE_SECRET_KEY_LIVE", "")
    status, details = system_checks._stripe_billing_status(None)
    assert status == "Not Configured"
    assert "live" in details
