"""The billing currency contract (SIGV2-1133).

Qiko Signal bills in exactly one currency. Before this suite existed the code
stated two: ``app/config/plans.py`` stored the plan price under
``monthly_price_usd`` while its own capability description called it "Monthly
plan price in EUR", and the commitment activation email printed a euro sign in
front of an amount that Stripe charges in USD.

The currency is established from the Stripe configuration, which is the only
authority that matters, because that is what the customer's card is charged in:

* ``stripe_catalog_service._create_price`` is the only place this application
  creates a Stripe price, and it sends ``BILLING_CURRENCY``.
* ``_price_shape_matches_definition`` refuses to reuse a price in any other
  currency, so a stray foreign-currency price is replaced rather than adopted.
* ``credit_commitment_service`` rejects a checkout session or a renewal invoice
  whose currency is not ``BILLING_CURRENCY``.
* ``credit_top_up_orders`` carries a CHECK constraint pinning ``'usd'``.

These tests pin that single answer to every surface that renders it, so a
future reader cannot reintroduce the contradiction by trusting a stale comment.
No test here performs a live Stripe call: the Stripe client is faked.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import CAPABILITY_DESCRIPTIONS
from billing import BILLING_CURRENCY, BILLING_CURRENCY_DISPLAY
from services import credit_commitment_service, email_templates, stripe_catalog_service
from tests.test_stripe_catalog_service import _install_fake_stripe


BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Every currency sign except the one we bill in. If one of these appears on a
# customer-facing price surface, that surface contradicts the stored amount.
FOREIGN_CURRENCY_SIGNS = ("\u20ac", "\u00a3", "\u00a5", "\u20b9", "\u20bd")


def test_billing_currency_is_usd_and_is_not_environment_dependent() -> None:
    """One currency, declared once, not resolved per environment.

    A per-environment currency would mean the same ``_usd`` field meant
    different money in test and live, which is the second way the old field
    name could have been wrong. It is a module constant, so it cannot drift.
    """
    assert BILLING_CURRENCY == "usd"
    assert BILLING_CURRENCY_DISPLAY == "USD"
    assert BILLING_CURRENCY == BILLING_CURRENCY_DISPLAY.lower()

    from core.config import settings

    # No setting may introduce a second opinion about the billing currency.
    currency_settings = [
        name for name in dir(settings) if "CURRENCY" in name.upper() and not name.startswith("_")
    ]
    assert currency_settings == []


def test_every_catalog_definition_expects_the_billing_currency() -> None:
    definitions = stripe_catalog_service._catalog_definitions("all")
    assert definitions, "catalog definitions must not be empty"
    for definition in definitions:
        expected = stripe_catalog_service._build_expected_shape(definition)
        assert (
            expected["currency"] == BILLING_CURRENCY
        ), f"{definition.kind}:{definition.key} expects {expected['currency']!r}"


def test_catalog_sync_creates_every_price_in_the_billing_currency(monkeypatch) -> None:
    """The charged currency: what we actually send to Stripe on price creation."""
    state = _install_fake_stripe(monkeypatch)

    stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_currency_contract",
        mode="test",
        scope="all",
        dry_run=False,
    )

    created = state["calls"]["price_create"]
    assert created, "expected the sync to create prices"
    for call in created:
        assert call["currency"] == BILLING_CURRENCY


def test_a_price_in_another_currency_is_never_reused() -> None:
    definition = stripe_catalog_service._catalog_definitions("plans")[0]
    foreign_price = {
        "active": True,
        "currency": "eur",
        "unit_amount": definition.unit_amount,
        "recurring": dict(definition.recurring),
        "billing_scheme": definition.billing_scheme or "per_unit",
    }

    assert not stripe_catalog_service._price_shape_matches_definition(foreign_price, definition)

    native_price = {**foreign_price, "currency": BILLING_CURRENCY}
    assert stripe_catalog_service._price_shape_matches_definition(native_price, definition)


def test_plan_price_capability_description_states_the_billing_currency() -> None:
    """The description must agree with the field name and with Stripe.

    This is the exact contradiction SIGV2-1133 was raised for: the key said
    usd, the description said EUR, and Stripe charged usd.
    """
    description = CAPABILITY_DESCRIPTIONS["monthly_price_usd"]
    assert BILLING_CURRENCY_DISPLAY in description
    assert "EUR" not in description.upper()


def test_commitment_activation_email_states_the_billing_currency() -> None:
    rendered = email_templates.render_template(
        "commitment.activated",
        {
            "email": "finance@example.com",
            "user_name": "Acme Lab",
            "tier": "growth",
            "monthly_fee_usd": "180.00",
            "monthly_fee_currency": BILLING_CURRENCY_DISPLAY,
            "cycle_end": "2026-04-01T00:00:00+00:00",
        },
    )

    assert f"180.00 {BILLING_CURRENCY_DISPLAY}" in rendered.html
    for sign in FOREIGN_CURRENCY_SIGNS:
        assert sign not in rendered.html


def test_commitment_activation_email_defaults_to_the_billing_currency() -> None:
    """A sender that omits the currency still cannot produce a bare amount."""
    rendered = email_templates.render_template(
        "commitment.activated",
        {
            "email": "finance@example.com",
            "user_name": "Acme Lab",
            "tier": "growth",
            "monthly_fee_usd": "180.00",
            "cycle_end": "2026-04-01T00:00:00+00:00",
        },
    )

    assert f"180.00 {BILLING_CURRENCY_DISPLAY}" in rendered.html


def test_no_email_template_hardcodes_a_foreign_currency_sign() -> None:
    offenders: list[str] = []
    for template in sorted((BACKEND_ROOT / "templates").glob("*.html")):
        body = template.read_text(encoding="utf-8")
        if any(sign in body for sign in FOREIGN_CURRENCY_SIGNS):
            offenders.append(template.name)

    assert offenders == [], f"templates hardcode a non-{BILLING_CURRENCY_DISPLAY} sign: {offenders}"


def test_billing_sources_make_no_eur_claim_about_a_usd_field() -> None:
    """Guard against reintroducing a stale "stores EUR" comment."""
    watched = (
        BACKEND_ROOT / "app" / "config" / "plans.py",
        BACKEND_ROOT / "services" / "credit_commitment_service.py",
        BACKEND_ROOT / "services" / "stripe_catalog_service.py",
        BACKEND_ROOT / "services" / "public_plan_catalog.py",
        BACKEND_ROOT / "billing_webhook_worker.py",
    )
    offenders: list[str] = []
    for source in watched:
        for lineno, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            if "EUR" in line.upper() and "_usd" in line:
                offenders.append(f"{source.name}:{lineno}")
            elif any(sign in line for sign in FOREIGN_CURRENCY_SIGNS):
                offenders.append(f"{source.name}:{lineno}")

    assert offenders == [], f"billing source claims a foreign currency: {offenders}"


def test_commitment_tier_fees_are_charged_in_the_billing_currency(monkeypatch) -> None:
    """The tier fee stored as monthly_fee_usd is what Stripe charges, in USD."""
    state = _install_fake_stripe(monkeypatch)

    stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_currency_contract",
        mode="test",
        scope="commitments",
        dry_run=False,
    )

    fees_in_minor_units = {
        int(definition.monthly_fee_usd * 100)
        for definition in credit_commitment_service.COMMITMENT_TIER_DEFINITIONS.values()
    }
    created_fixed_amounts = {
        call["unit_amount"]
        for call in state["calls"]["price_create"]
        if call["recurring"]["usage_type"] == "licensed"
    }

    assert created_fixed_amounts == fees_in_minor_units
    for call in state["calls"]["price_create"]:
        assert call["currency"] == BILLING_CURRENCY


def _eligible_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        subscription=SimpleNamespace(
            status="active",
            plan_type="plan_specialist",
            stripe_customer_id="cus_currency_contract",
        ),
    )


def test_commitment_checkout_in_another_currency_is_rejected() -> None:
    """A foreign-currency checkout is refused, not silently recorded as USD."""
    user = _eligible_user()
    session = {
        "object": "checkout.session",
        "mode": "subscription",
        "status": "complete",
        "payment_status": "paid",
        "currency": "eur",
    }

    with pytest.raises(ValueError) as excinfo:
        credit_commitment_service.validate_commitment_checkout_fulfillment(
            session=session,
            subscription_payload={},
            stripe_mode="test",
            config=SimpleNamespace(mode_configs={}),
            user=user,
            local_subscription=user.subscription,
        )

    assert str(excinfo.value) == "invalid_checkout_currency"


def test_commitment_checkout_in_the_billing_currency_passes_the_currency_gate() -> None:
    """The same session in the billing currency gets past the currency check."""
    user = _eligible_user()
    session = {
        "object": "checkout.session",
        "mode": "subscription",
        "status": "complete",
        "payment_status": "paid",
        "currency": BILLING_CURRENCY,
    }

    with pytest.raises(ValueError) as excinfo:
        credit_commitment_service.validate_commitment_checkout_fulfillment(
            session=session,
            subscription_payload={},
            stripe_mode="test",
            config=SimpleNamespace(mode_configs={}),
            user=user,
            local_subscription=user.subscription,
        )

    assert str(excinfo.value) != "invalid_checkout_currency"


def test_commitment_renewal_in_another_currency_is_rejected() -> None:
    commitment = SimpleNamespace(
        stripe_mode="test",
        stripe_subscription_id="sub_currency_contract",
        tier="growth",
        pending_tier=None,
        pending_change_effective_at=None,
    )
    local_subscription = SimpleNamespace(stripe_customer_id="cus_currency_contract")
    invoice = {
        "status": "paid",
        "paid": True,
        "billing_reason": "subscription_cycle",
        "customer": "cus_currency_contract",
        "subscription": "sub_currency_contract",
        "currency": "eur",
    }

    with pytest.raises(ValueError) as excinfo:
        credit_commitment_service.validate_commitment_renewal_invoice(
            invoice=invoice,
            stripe_mode="test",
            config=SimpleNamespace(mode_configs={}),
            commitment=commitment,
            local_subscription=local_subscription,
        )

    assert str(excinfo.value) == "invalid_renewal_currency"
