"""Tests for AEX-38 Phase 2: In-App Plan Upgrade / Downgrade."""

import logging
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
from app.config.plans import diff_capabilities, get_plan_weight
from billing import Plan
from billing.config import BillingModeConfig
from middleware import maintenance as maintenance_module


# ---------------------------------------------------------------------------
# diff_capabilities tests
# ---------------------------------------------------------------------------


class TestDiffCapabilities:
    def test_upgrade_plan_standard_to_plan_specialist_gains_features(self):
        result = diff_capabilities("plan_standard", "plan_specialist")
        assert isinstance(result, dict)
        assert "gained" in result and "lost" in result
        gained_labels = result["gained"]
        assert len(gained_labels) > 0
        # Specialist unlocks competitor analysis, semantic gap, entity authority, etc.
        gained_lower = [g.lower() for g in gained_labels]
        assert any("entity" in g for g in gained_lower) or any(
            "competitor" in g for g in gained_lower
        )

    def test_downgrade_plan_specialist_to_plan_standard_loses_features(self):
        result = diff_capabilities("plan_specialist", "plan_standard")
        assert len(result["lost"]) > 0
        assert len(result["gained"]) == 0 or len(result["lost"]) > len(result["gained"])

    def test_same_plan_returns_empty_diff(self):
        result = diff_capabilities("plan_standard", "plan_standard")
        assert result == {"gained": [], "lost": []}

    def test_invalid_plan_returns_empty_diff(self):
        result = diff_capabilities("nonexistent", "plan_standard")
        assert result == {"gained": [], "lost": []}

    def test_upgrade_to_executive_gains_many(self):
        result = diff_capabilities("plan_standard", "plan_executive")
        assert len(result["gained"]) >= 5  # Many features gained

    def test_diff_is_symmetric(self):
        up = diff_capabilities("plan_standard", "plan_executive")
        down = diff_capabilities("plan_executive", "plan_standard")
        assert set(up["gained"]) == set(down["lost"])
        assert set(up["lost"]) == set(down["gained"])


# ---------------------------------------------------------------------------
# Helpers for router tests
# ---------------------------------------------------------------------------


def _mode_config(mode: str) -> BillingModeConfig:
    return BillingModeConfig(
        secret_key=f"{mode}-explicit-key",
        webhook_secret=f"{mode}-webhook-secret",
        price_ids={plan: f"price_{mode}_{plan.value}_month" for plan in Plan},
        annual_price_ids={plan: f"price_{mode}_{plan.value}_year" for plan in Plan},
        commitment_price_ids={},
        commitment_overage_price_id=None,
    )


class _FakeConfig:
    app_base_url = "http://localhost:3000"
    stripe_mode = "test"
    mode_configs = {
        "test": _mode_config("test"),
        "live": _mode_config("live"),
    }

    def __init__(self):
        self.price_lookups = []

    def price_id_for(self, plan, interval: str = "month") -> str:
        return self.price_id_for_mode(self.stripe_mode, plan, interval)

    def price_id_for_mode(self, mode, plan, interval: str = "month") -> str:
        self.price_lookups.append((mode, plan, interval))
        mode_config = self.mode_configs.get(mode)
        if mode_config is None or interval not in {"month", "year"}:
            return ""
        prices = mode_config.annual_price_ids if interval == "year" else mode_config.price_ids
        return prices.get(plan, "")


def _make_user(
    plan_type="plan_standard",
    status="active",
    stripe_sub_id="sub_123",
    stripe_cust_id="cus_123",
    billing_interval="month",
    **pending_state,
):
    subscription_fields = {
        "id": 17,
        "user_id": 1,
        "plan_type": plan_type,
        "status": status,
        "stripe_subscription_id": stripe_sub_id,
        "stripe_customer_id": stripe_cust_id,
        "stripe_mode": "test",
        "billing_interval": billing_interval,
        "current_period_end": None,
        "cancel_at_period_end": False,
        "stripe_schedule_id": None,
        "managed_plan_change_schedule_id": None,
        "pending_plan_type": None,
        "pending_billing_interval": None,
        "pending_change_effective_at": None,
        "plan_state_event_created_at": None,
    }
    subscription_fields.update(pending_state)
    sub = SimpleNamespace(**subscription_fields)
    return SimpleNamespace(id=1, subscription=sub)


def _stripe_subscription(
    *,
    price_id: str,
    interval: str,
    status: str = "active",
    current_period_start: int = 1747000000,
    current_period_end: int = 1750000000,
    quantity: int = 1,
    collection_method: str = "charge_automatically",
    metadata=None,
    schedule_id: str | None = None,
):
    return {
        "id": "sub_123",
        "customer": "cus_123",
        "status": status,
        "collection_method": collection_method,
        "items": {
            "data": [
                {
                    "id": "si_123",
                    "price": {
                        "id": price_id,
                        "recurring": {"interval": interval},
                    },
                    "quantity": quantity,
                }
            ]
        },
        "current_period_start": current_period_start,
        "current_period_end": current_period_end,
        "metadata": metadata or {},
        "schedule": schedule_id,
    }


def _downgrade_metadata(
    *,
    target_plan: str = "plan_standard",
    target_interval: str = "year",
    subscription_record_id: str = "17",
    previous_plan: str = "plan_specialist",
    previous_interval: str = "month",
) -> dict[str, str]:
    return {
        "user_id": "1",
        "plan": target_plan,
        "billing_interval": target_interval,
        "change_direction": "downgrade",
        "previous_plan": previous_plan,
        "previous_billing_interval": previous_interval,
        "qiko_schedule_kind": "plan_change",
        "qiko_subscription_record_id": subscription_record_id,
    }


def _owned_schedule(
    schedule_id: str = "sub_sched_downgrade",
    *,
    subscription_id: str = "sub_123",
    customer_id: str = "cus_123",
    status: str = "active",
    metadata=None,
):
    return {
        "id": schedule_id,
        "status": status,
        "subscription": subscription_id,
        "customer": customer_id,
        "metadata": (metadata if metadata is not None else _downgrade_metadata()),
    }


def _configured_schedule(
    schedule_id: str = "sub_sched_downgrade",
    *,
    current_price_id: str = "price_test_plan_specialist_month",
    current_interval: str = "month",
    target_price_id: str = "price_test_plan_standard_year",
    target_interval: str = "year",
    period_start: int = 1747000000,
    period_end: int = 1750000000,
    metadata=None,
):
    schedule_metadata = metadata or _downgrade_metadata(
        target_plan="plan_standard",
        target_interval=target_interval,
    )
    return {
        **_owned_schedule(schedule_id, metadata=schedule_metadata),
        "end_behavior": "release",
        "phases": [
            {
                "start_date": period_start,
                "end_date": period_end,
                "items": [
                    {
                        "price": {
                            "id": current_price_id,
                            "recurring": {"interval": current_interval},
                        },
                        "quantity": 1,
                    }
                ],
            },
            {
                "start_date": period_end,
                "items": [
                    {
                        "price": {
                            "id": target_price_id,
                            "recurring": {"interval": target_interval},
                        },
                        "quantity": 1,
                    }
                ],
                "metadata": schedule_metadata,
            },
        ],
    }


def _expected_schedule_phases(
    *,
    target_price_id: str = "price_test_plan_standard_year",
    target_interval: str = "year",
    period_start: int = 1747000000,
    period_end: int = 1750000000,
):
    return [
        {
            "start_date": period_start,
            "end_date": period_end,
            "items": [{"price": "price_test_plan_specialist_month", "quantity": 1}],
        },
        {
            "start_date": period_end,
            "items": [{"price": target_price_id, "quantity": 1}],
            "metadata": _downgrade_metadata(
                target_plan="plan_standard",
                target_interval=target_interval,
            ),
        },
    ]


def _expanded_active_phase(
    *,
    period_start: int = 1747000000,
    period_end: int = 1750000000,
    discount_field: str = "discounts",
):
    phase = {
        "start_date": period_start,
        "end_date": period_end,
        "items": [
            {
                "price": {
                    "id": "price_test_plan_specialist_month",
                    "object": "price",
                    "active": True,
                    "recurring": {"interval": "month"},
                },
                "plan": {
                    "id": "price_test_plan_specialist_month",
                    "object": "plan",
                    "recurring": {"interval": "month"},
                },
                "quantity": 3,
                "metadata": {
                    "item_scope": "workspace",
                    "source_item": "si_active_123",
                },
                "discounts": [],
            }
        ],
        "default_tax_rates": ["txr_active_vat", "txr_active_regional"],
        "automatic_tax": {"enabled": True},
        "billing_cycle_anchor": "phase_start",
        "currency": "usd",
        "description": "Preserve current customer contract",
        "proration_behavior": "create_prorations",
        "collection_method": "send_invoice",
        "invoice_settings": {
            "days_until_due": 14,
            "issuer": {"type": "self"},
        },
        "billing_thresholds": {
            "amount_gte": 25000,
            "reset_billing_cycle_anchor": False,
        },
        "transfer_data": {
            "destination": "acct_active_partner_123",
            "amount_percent": 12.5,
        },
        "application_fee_percent": 7.25,
        "default_payment_method": "pm_active_123",
        "metadata": {
            "active_contract": "preserve",
            "phase_owner": "customer",
        },
        "trial_end": period_end - 3600,
    }
    if discount_field == "coupon":
        phase["coupon"] = "coupon_active_loyalty_20"
        phase["discounts"] = []
    else:
        phase["coupon"] = None
        phase["discounts"] = [{"coupon": "coupon_active_loyalty_20"}]
    return phase


def _expanded_active_schedule(
    *,
    schedule_id: str = "sub_sched_downgrade",
    active_phase=None,
    metadata=None,
):
    return {
        **_owned_schedule(schedule_id, metadata=metadata),
        "object": "subscription_schedule",
        "end_behavior": "release",
        "phases": [deepcopy(active_phase or _expanded_active_phase())],
    }


def _expected_preserved_schedule_phases(active_phase):
    current_phase = deepcopy(active_phase)
    current_phase["items"][0]["price"] = active_phase["items"][0]["price"]["id"]
    current_phase["items"][0].pop("plan", None)
    if not current_phase["items"][0].get("discounts"):
        current_phase["items"][0].pop("discounts", None)
    if not current_phase.get("coupon"):
        current_phase.pop("coupon", None)
    if not current_phase.get("discounts"):
        current_phase.pop("discounts", None)
    return [
        current_phase,
        {
            "start_date": active_phase["end_date"],
            "items": [
                {
                    "price": "price_test_plan_standard_year",
                    "quantity": active_phase["items"][0]["quantity"],
                }
            ],
            "metadata": _downgrade_metadata(),
        },
    ]


def _expanded_preserved_schedule(
    *,
    schedule_id: str = "sub_sched_downgrade",
    active_phase=None,
):
    active_phase = deepcopy(active_phase or _expanded_active_phase())
    future_phase = {
        "start_date": active_phase["end_date"],
        "items": [
            {
                "price": {
                    "id": "price_test_plan_standard_year",
                    "object": "price",
                    "active": True,
                    "recurring": {"interval": "year"},
                },
                "quantity": active_phase["items"][0]["quantity"],
            }
        ],
        "metadata": _downgrade_metadata(),
    }
    return {
        **_owned_schedule(schedule_id),
        "object": "subscription_schedule",
        "end_behavior": "release",
        "metadata": _downgrade_metadata(),
        "phases": [active_phase, future_phase],
    }


def _active_schedule(
    schedule_id: str,
    subscription_id: str = "sub_123",
    customer_id: str = "cus_123",
    metadata=None,
):
    return {
        "id": schedule_id,
        "status": "active",
        "subscription": subscription_id,
        "customer": customer_id,
        "metadata": (metadata if metadata is not None else _downgrade_metadata()),
    }


def _released_schedule(
    schedule_id: str,
    subscription_id: str = "sub_123",
    customer_id: str = "cus_123",
    metadata=None,
):
    return {
        "id": schedule_id,
        "status": "released",
        "released_subscription": subscription_id,
        "customer": customer_id,
        "metadata": (metadata if metadata is not None else _downgrade_metadata()),
    }


def _pending_state(subscription):
    return (
        subscription.stripe_schedule_id,
        subscription.pending_plan_type,
        subscription.pending_billing_interval,
        subscription.pending_change_effective_at,
    )


def _non_pending_state(subscription):
    pending_fields = {
        "stripe_schedule_id",
        "pending_plan_type",
        "pending_billing_interval",
        "pending_change_effective_at",
    }
    return {key: value for key, value in vars(subscription).items() if key not in pending_fields}


def _patch_config(monkeypatch):
    config = _FakeConfig()
    monkeypatch.setattr("billing.router.get_billing_config", lambda _req, _db=None: config)
    return config


def _patch_portal_check(monkeypatch):
    monkeypatch.setattr("billing.router.require_not_portal_only", lambda *a, **kw: None)


def _patch_subscription_lock(monkeypatch, user):
    monkeypatch.setattr(
        "billing.router.lock_subscription_for_plan_change",
        lambda _db, _subscription_id: user.subscription,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Plan change request contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("request_name", ["UpgradePreviewRequest", "UpgradeRequest"])
def test_plan_change_requests_require_explicit_billing_interval(request_name):
    from billing import Plan
    from billing import router as billing_router

    request_type = getattr(billing_router, request_name)

    assert request_type.model_fields["billing_interval"].is_required()
    with pytest.raises(ValidationError):
        request_type(target_plan=Plan.SPECIALIST)

    assert (
        request_type(
            target_plan=Plan.SPECIALIST,
            billing_interval="month",
        ).billing_interval
        == "month"
    )
    assert (
        request_type(
            target_plan=Plan.SPECIALIST,
            billing_interval="year",
        ).billing_interval
        == "year"
    )
    with pytest.raises(ValidationError):
        request_type(target_plan=Plan.SPECIALIST, billing_interval="week")


# ---------------------------------------------------------------------------
# upgrade-preview endpoint
# ---------------------------------------------------------------------------


class TestUpgradePreview:
    @pytest.mark.parametrize(
        "current_plan",
        [Plan.AGENCY_TRIAL],
        ids=["private-agency-trial"],
    )
    def test_preview_from_non_self_service_current_plan_rejects_public_target_before_stripe(
        self,
        monkeypatch,
        current_plan,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type=current_plan.value, status="active")
        request = UpgradePreviewRequest(
            target_plan=Plan.STANDARD,
            billing_interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=None,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
        assert exc_info.value.detail["current_plan"] == current_plan.value
        assert exc_info.value.detail["current_status"] == "active"
        assert exc_info.value.detail["route"] == "/contact"
        assert mock_stripe.mock_calls == []

    def test_preview_allows_leaving_contact_cta_current_plan(self, monkeypatch):
        """SIGV2-1236: Executive is negotiated/contact-priced, not unpurchasable.

        A customer already on Executive must be able to reach a preview for
        moving to another plan; the self-service guard is only a *target*
        guard for a contact-CTA plan, never a current-plan trap.
        """
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_executive", billing_interval="month")
        req = UpgradePreviewRequest(target_plan=Plan.STANDARD, billing_interval="month")

        mock_sub = _stripe_subscription(
            price_id="price_test_plan_executive_month",
            interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = mock_sub
            mock_stripe.error = MagicMock()
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "downgrade"
        assert result["current_plan"]["id"] == "plan_executive"
        assert result["target_plan"]["id"] == "plan_standard"

    def test_preview_still_rejects_contact_cta_as_target(self, monkeypatch):
        """SIGV2-1236: a contact-CTA plan stays blocked as the *target*.

        Only leaving such a plan is allowed; selecting it still requires sales.
        """
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard", status="active")
        request = UpgradePreviewRequest(target_plan=Plan.EXECUTIVE, billing_interval="month")

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(http_request=None, request=request, user=user, db=None)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
        assert exc_info.value.detail["current_plan"] == "plan_standard"
        assert exc_info.value.detail["route"] == "/contact"
        assert mock_stripe.mock_calls == []

    def test_preview_upgrade_returns_direction_and_diff(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard")
        req = UpgradePreviewRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        # Mock Stripe calls
        mock_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )
        mock_invoice = MagicMock()
        mock_invoice.amount_due = 15000  # $150.00

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = mock_sub
            mock_stripe.Invoice.upcoming.return_value = mock_invoice
            mock_stripe.error = MagicMock()
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "upgrade"
        assert result["current_plan"]["id"] == "plan_standard"
        assert result["target_plan"]["id"] == "plan_specialist"
        assert result["immediate_charge"] is True
        assert result["proration_amount_usd"] == 150.0
        assert result["next_billing_date"] is not None
        assert "gained" in result["feature_diff"]
        assert len(result["feature_diff"]["gained"]) > 0
        assert "credit_adjustment" not in result

    def test_preview_same_tier_interval_change_is_immediate_and_prorated(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        config = _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        req = UpgradePreviewRequest(target_plan=Plan.STANDARD, billing_interval="year")
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )
        upcoming_invoice = SimpleNamespace(amount_due=9600)

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.Invoice.upcoming.return_value = upcoming_invoice
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "interval_change"
        assert result["immediate_charge"] is True
        assert result["current_billing_interval"] == "month"
        assert result["target_billing_interval"] == "year"
        assert result["proration_amount_usd"] == 96.0
        assert config.price_lookups == [
            ("test", Plan.STANDARD, "year"),
            ("test", Plan.STANDARD, "month"),
        ]
        upcoming_kwargs = mock_stripe.Invoice.upcoming.call_args.kwargs
        assert upcoming_kwargs["api_key"] == "test-explicit-key"
        assert upcoming_kwargs["subscription_items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_standard_year",
                "quantity": 1,
            }
        ]

    def test_preview_preserves_current_quantity_for_upcoming_invoice(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        request = UpgradePreviewRequest(
            target_plan=Plan.SPECIALIST,
            billing_interval="year",
        )
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
            quantity=3,
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.Invoice.upcoming.return_value = SimpleNamespace(amount_due=24000)
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=None,
            )

        assert result["direction"] == "upgrade"
        assert mock_stripe.Invoice.upcoming.call_args.kwargs["subscription_items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_specialist_year",
                "quantity": 3,
            }
        ]

    def test_preview_higher_tier_changed_interval_uses_exact_target_price(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        req = UpgradePreviewRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.Invoice.upcoming.return_value = SimpleNamespace(amount_due=24000)
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "upgrade"
        assert result["immediate_charge"] is True
        assert result["current_billing_interval"] == "month"
        assert result["target_billing_interval"] == "year"
        assert mock_stripe.Invoice.upcoming.call_args.kwargs["subscription_items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_specialist_year",
                "quantity": 1,
            }
        ]

    @pytest.mark.parametrize(
        "invalid_field",
        [
            "subscription_id",
            "customer_id",
            "status",
            "item_count",
            "current_price",
            "current_interval",
            "quantity",
            "collection_method",
        ],
    )
    def test_preview_rejects_invalid_current_subscription_without_misleading_proration(
        self,
        monkeypatch,
        invalid_field,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        request = UpgradePreviewRequest(
            target_plan=Plan.SPECIALIST,
            billing_interval="year",
        )
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )
        if invalid_field == "subscription_id":
            stripe_sub["id"] = "sub_foreign"
        elif invalid_field == "customer_id":
            stripe_sub["customer"] = "cus_foreign"
        elif invalid_field == "status":
            stripe_sub["status"] = "past_due"
        elif invalid_field == "item_count":
            stripe_sub["items"]["data"].append(deepcopy(stripe_sub["items"]["data"][0]))
        elif invalid_field == "current_price":
            stripe_sub["items"]["data"][0]["price"]["id"] = "price_test_plan_specialist_month"
        elif invalid_field == "current_interval":
            stripe_sub["items"]["data"][0]["price"]["recurring"]["interval"] = "year"
        elif invalid_field == "quantity":
            stripe_sub["items"]["data"][0]["quantity"] = 0
        else:
            stripe_sub["collection_method"] = "send_invoice"

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=None,
                )

        assert exc_info.value.status_code == 409
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail["code"] == "invalid_current_subscription"
        mock_stripe.Invoice.upcoming.assert_not_called()

    def test_preview_requires_stripe_subscription_id(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            stripe_sub_id=None,
        )

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(
                    http_request=None,
                    request=UpgradePreviewRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=None,
                )

        assert exc_info.value.status_code == 400
        mock_stripe.Subscription.retrieve.assert_not_called()
        mock_stripe.SubscriptionSchedule.retrieve.assert_not_called()
        mock_stripe.Invoice.upcoming.assert_not_called()

    @pytest.mark.parametrize(
        ("managed_schedule_id", "attached_schedule_id", "schedule"),
        [
            (
                "sub_sched_foreign_attached",
                "sub_sched_foreign_attached",
                _active_schedule("sub_sched_foreign_attached", metadata={}),
            ),
            (
                "sub_sched_locally_managed",
                "sub_sched_other_attached",
                _active_schedule("sub_sched_other_attached"),
            ),
            (
                None,
                "sub_sched_orphaned_qiko",
                _active_schedule("sub_sched_orphaned_qiko"),
            ),
        ],
        ids=["foreign", "local-stripe-mismatch", "orphaned-qiko"],
    )
    def test_preview_rejects_unreconciled_attached_schedule(
        self,
        monkeypatch,
        managed_schedule_id,
        attached_schedule_id,
        schedule,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=managed_schedule_id,
        )
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
            schedule_id=attached_schedule_id,
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.SubscriptionSchedule.retrieve.return_value = schedule
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(
                    http_request=None,
                    request=UpgradePreviewRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=None,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "invalid_current_subscription"
        mock_stripe.Invoice.upcoming.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()

    def test_preview_permits_exact_locally_managed_qiko_owned_attached_schedule(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        schedule_id = "sub_sched_locally_managed"
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=schedule_id,
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=schedule_id,
            )
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _active_schedule(
                schedule_id,
                metadata=_downgrade_metadata(
                    previous_plan="plan_standard",
                    previous_interval="month",
                ),
            )
            mock_stripe.Invoice.upcoming.return_value = SimpleNamespace(amount_due=24000)
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(
                http_request=None,
                request=UpgradePreviewRequest(
                    target_plan=Plan.SPECIALIST,
                    billing_interval="year",
                ),
                user=user,
                db=None,
            )

        assert result["direction"] == "upgrade"
        assert result["proration_amount_usd"] == 240.0
        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            schedule_id,
            api_key="test-explicit-key",
        )
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()

    @pytest.mark.parametrize(
        "recovery_path",
        [
            "natural_schedule_completion",
            "prior_execution_release_then_stripe_failure",
            "db_commit_failure_recovery",
        ],
    )
    def test_preview_permits_detached_subscription_after_exact_managed_schedule_released(
        self,
        monkeypatch,
        recovery_path,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        schedule_id = "sub_sched_locally_managed"
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=schedule_id,
        )
        original_state = deepcopy(vars(user.subscription))
        fake_db = MagicMock()
        events = []

        def retrieve_schedule(returned_schedule_id, **kwargs):
            assert returned_schedule_id == schedule_id
            assert kwargs == {"api_key": "test-explicit-key"}
            events.append("schedule_retrieve")
            return _released_schedule(
                schedule_id,
                metadata=_downgrade_metadata(
                    previous_plan="plan_standard",
                    previous_interval="month",
                ),
            )

        def upcoming_invoice(**_kwargs):
            assert events == ["schedule_retrieve"]
            events.append("invoice_upcoming")
            return SimpleNamespace(amount_due=24000)

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=None,
            )
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.Invoice.upcoming.side_effect = upcoming_invoice
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(
                http_request=None,
                request=UpgradePreviewRequest(
                    target_plan=Plan.SPECIALIST,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert result["direction"] == "upgrade", recovery_path
        assert result["proration_amount_usd"] == 240.0
        assert events == ["schedule_retrieve", "invoice_upcoming"]
        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            schedule_id,
            api_key="test-explicit-key",
        )
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()
        fake_db.rollback.assert_not_called()

    @pytest.mark.parametrize(
        "schedule",
        [
            _released_schedule(
                "sub_sched_locally_managed",
                metadata=_downgrade_metadata(subscription_record_id="999"),
            ),
            _released_schedule(
                "sub_sched_locally_managed",
                customer_id="cus_foreign",
            ),
            _released_schedule(
                "sub_sched_locally_managed",
                subscription_id="sub_foreign",
            ),
            _released_schedule("sub_sched_returned_other"),
            _active_schedule("sub_sched_locally_managed"),
        ],
        ids=[
            "foreign-owner",
            "wrong-customer",
            "wrong-released-subscription",
            "wrong-schedule-id",
            "still-active",
        ],
    )
    def test_preview_rejects_invalid_detached_managed_schedule_without_mutation(
        self,
        monkeypatch,
        schedule,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        schedule_id = "sub_sched_locally_managed"
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=schedule_id,
        )
        original_state = deepcopy(vars(user.subscription))
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=None,
            )
            mock_stripe.SubscriptionSchedule.retrieve.return_value = schedule
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(
                    http_request=None,
                    request=UpgradePreviewRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "invalid_current_subscription"
        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            schedule_id,
            api_key="test-explicit-key",
        )
        mock_stripe.Invoice.upcoming.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()
        fake_db.rollback.assert_not_called()

    def test_preview_downgrade_returns_correct_direction(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_specialist")
        req = UpgradePreviewRequest(target_plan=Plan.STANDARD, billing_interval="month")

        mock_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = mock_sub
            mock_stripe.error = MagicMock()
            mock_stripe.error.StripeError = Exception

            result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "downgrade"
        assert result["immediate_charge"] is False
        assert result["proration_amount_usd"] is None  # No proration for downgrade

    def test_preview_downgrade_normalizes_unsupported_stored_interval(self, monkeypatch, caplog):
        """A stored interval outside month/year must not block the plan change (SIGV2-1198)."""
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan

        config = _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_specialist", billing_interval="weekly")
        req = UpgradePreviewRequest(target_plan=Plan.STANDARD, billing_interval="month")

        mock_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = mock_sub
            mock_stripe.error = MagicMock()
            mock_stripe.error.StripeError = Exception

            with caplog.at_level(logging.WARNING, logger="billing.router"):
                result = preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert result["direction"] == "downgrade"
        assert result["current_billing_interval"] == "month"
        assert result["target_billing_interval"] == "month"
        assert ("test", Plan.SPECIALIST, "month") in config.price_lookups
        assert "billing_interval_normalized" in caplog.text

    def test_preview_same_plan_returns_400(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard")
        req = UpgradePreviewRequest(target_plan=Plan.STANDARD, billing_interval="month")

        with pytest.raises(HTTPException) as exc_info:
            preview_plan_change(http_request=None, request=req, user=user, db=None)
        assert exc_info.value.status_code == 400

    def test_preview_no_subscription_returns_400(self, monkeypatch):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = SimpleNamespace(id=1, subscription=None)
        req = UpgradePreviewRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        with pytest.raises(HTTPException) as exc_info:
            preview_plan_change(http_request=None, request=req, user=user, db=None)
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize(
        "failed_operation",
        ["subscription_retrieve", "upcoming_invoice"],
    )
    def test_preview_stripe_failure_returns_structured_502_without_partial_preview(
        self,
        monkeypatch,
        failed_operation,
    ):
        from billing.router import UpgradePreviewRequest, preview_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard")
        req = UpgradePreviewRequest(target_plan=Plan.SPECIALIST, billing_interval="month")
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.error.StripeError = Exception
            if failed_operation == "subscription_retrieve":
                mock_stripe.Subscription.retrieve.side_effect = Exception("Stripe down")
            else:
                mock_stripe.Subscription.retrieve.return_value = stripe_sub
                mock_stripe.Invoice.upcoming.side_effect = Exception("Invoice preview down")

            with pytest.raises(HTTPException) as exc_info:
                preview_plan_change(http_request=None, request=req, user=user, db=None)

        assert exc_info.value.status_code == 502
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail["code"] == "proration_preview_failed"
        assert isinstance(exc_info.value.detail["message"], str)
        assert exc_info.value.detail["message"]
        if failed_operation == "subscription_retrieve":
            mock_stripe.Invoice.upcoming.assert_not_called()
        else:
            mock_stripe.Invoice.upcoming.assert_called_once()


# ---------------------------------------------------------------------------
# execute plan change endpoint
# ---------------------------------------------------------------------------


class TestExecutePlanChange:
    @pytest.mark.parametrize(
        "current_plan",
        [Plan.AGENCY_TRIAL],
        ids=["private-agency-trial"],
    )
    def test_execute_from_non_self_service_current_plan_rejects_public_target_before_lock_or_stripe(
        self,
        monkeypatch,
        current_plan,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type=current_plan.value, status="active")
        fake_db = MagicMock()
        lock_mock = MagicMock(return_value=user.subscription)
        monkeypatch.setattr(
            "billing.router.lock_subscription_for_plan_change",
            lock_mock,
            raising=False,
        )

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="month",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
        assert exc_info.value.detail["current_plan"] == current_plan.value
        assert exc_info.value.detail["current_status"] == "active"
        assert exc_info.value.detail["route"] == "/contact"
        lock_mock.assert_not_called()
        assert mock_stripe.mock_calls == []
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        "locked_current_plan",
        [Plan.AGENCY_TRIAL],
        ids=["private-agency-trial"],
    )
    def test_execute_rechecks_non_self_service_current_plan_after_row_lock_before_stripe(
        self,
        monkeypatch,
        locked_current_plan,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", status="active")
        locked_subscription = _make_user(
            plan_type=locked_current_plan.value,
            status="active",
        ).subscription
        fake_db = MagicMock()
        lock_mock = MagicMock(return_value=locked_subscription)
        monkeypatch.setattr(
            "billing.router.lock_subscription_for_plan_change",
            lock_mock,
            raising=False,
        )

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="month",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
        assert exc_info.value.detail["current_plan"] == locked_current_plan.value
        assert exc_info.value.detail["current_status"] == "active"
        assert exc_info.value.detail["route"] == "/contact"
        lock_mock.assert_called_once_with(fake_db, user.subscription.id)
        assert mock_stripe.mock_calls == []
        fake_db.commit.assert_not_called()

    def test_execute_allows_leaving_contact_cta_current_plan(self, monkeypatch):
        """SIGV2-1236: a customer on Executive can reach an executed plan
        change away from it; the guard only blocks Executive as a target.
        """
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        config = _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_executive",
            billing_interval="month",
        )
        lock = MagicMock(return_value=user.subscription)
        monkeypatch.setattr(
            "billing.router.lock_subscription_for_plan_change",
            lock,
            raising=False,
        )
        request = UpgradeRequest(target_plan=Plan.STANDARD, billing_interval="year")
        fake_db = MagicMock()
        period_start = 1747000000
        period_end = 1750000000
        active_phase = _expanded_active_phase(
            period_start=period_start,
            period_end=period_end,
        )
        active_phase["items"][0]["price"]["id"] = "price_test_plan_executive_month"
        active_phase["items"][0]["plan"]["id"] = "price_test_plan_executive_month"
        active_phase["items"][0]["quantity"] = 1
        change_metadata = _downgrade_metadata(
            target_plan="plan_standard",
            target_interval="year",
            previous_plan="plan_executive",
            previous_interval="month",
        )
        modified_schedule = _expanded_preserved_schedule(active_phase=active_phase)
        modified_schedule["metadata"] = change_metadata
        modified_schedule["phases"][1]["metadata"] = change_metadata

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_executive_month",
                interval="month",
                current_period_start=period_start,
                current_period_end=period_end,
            )
            mock_stripe.SubscriptionSchedule.create.return_value = {
                "id": "sub_sched_downgrade",
            }
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _expanded_active_schedule(
                active_phase=active_phase,
                metadata={},
            )
            mock_stripe.SubscriptionSchedule.modify.return_value = modified_schedule
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        lock.assert_called_once_with(fake_db, 17)
        assert ("test", Plan.EXECUTIVE, "month") in config.price_lookups
        assert result["direction"] == "downgrade"
        assert result["previous_plan"] == "plan_executive"
        assert result["new_plan"] == "plan_standard"
        assert result["immediate"] is False

    def test_execute_still_rejects_contact_cta_as_target(self, monkeypatch):
        """SIGV2-1236: selecting a contact-CTA plan as the target still 409s."""
        from billing.router import UpgradeRequest, execute_plan_change
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", status="active")
        fake_db = MagicMock()
        lock_mock = MagicMock(return_value=user.subscription)
        monkeypatch.setattr(
            "billing.router.lock_subscription_for_plan_change",
            lock_mock,
            raising=False,
        )

        with patch("billing.router.stripe") as mock_stripe:
            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.EXECUTIVE,
                        billing_interval="month",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
        assert exc_info.value.detail["current_plan"] == "plan_standard"
        assert exc_info.value.detail["route"] == "/contact"
        lock_mock.assert_not_called()
        assert mock_stripe.mock_calls == []
        fake_db.commit.assert_not_called()

    def test_upgrade_calls_stripe_with_always_invoice(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard")
        _patch_subscription_lock(monkeypatch, user)
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        mock_sub = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
        )
        updated_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
            current_period_end=1752000000,
            metadata={
                "user_id": "1",
                "plan": "plan_specialist",
                "billing_interval": "month",
                "change_direction": "upgrade",
                "previous_plan": "plan_standard",
                "previous_billing_interval": "month",
            },
        )

        fake_db = MagicMock()
        operation_at = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)
        fence_seen_at_commit = []
        fake_db.commit.side_effect = lambda: fence_seen_at_commit.append(
            user.subscription.plan_state_event_created_at
        )

        with (
            patch("billing.router.datetime") as mock_datetime,
            patch("billing.router.stripe") as mock_stripe,
        ):
            mock_datetime.now.return_value = operation_at
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            mock_stripe.Subscription.retrieve.return_value = mock_sub
            mock_stripe.Subscription.modify.return_value = updated_sub
            mock_stripe.error = MagicMock()
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(http_request=None, request=req, user=user, db=fake_db)

        assert result["direction"] == "upgrade"
        assert result["previous_plan"] == "plan_standard"
        assert result["new_plan"] == "plan_specialist"
        assert result["immediate"] is True

        # Verify Stripe invoices immediately and rejects unpaid transitions atomically.
        call_kwargs = mock_stripe.Subscription.modify.call_args
        assert call_kwargs[1]["proration_behavior"] == "always_invoice"
        assert call_kwargs[1]["payment_behavior"] == "error_if_incomplete"
        assert user.subscription.plan_state_event_created_at is operation_at
        assert user.subscription.plan_state_event_created_at.tzinfo is not None
        assert user.subscription.plan_state_event_created_at.utcoffset() is not None
        assert fence_seen_at_commit == [operation_at]
        fake_db.commit.assert_called_once_with()

    def test_immediate_change_preserves_and_validates_current_quantity(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        request = UpgradeRequest(
            target_plan=Plan.SPECIALIST,
            billing_interval="year",
        )
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                quantity=3,
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                quantity=3,
                metadata=target_metadata,
            )
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        assert result["immediate"] is True
        assert mock_stripe.Subscription.modify.call_args.kwargs["items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_specialist_year",
                "quantity": 3,
            }
        ]
        assert user.subscription.plan_type == "plan_specialist"
        assert user.subscription.billing_interval == "year"
        fake_db.commit.assert_called_once_with()

    def test_immediate_change_rejects_returned_quantity_mismatch_without_local_publication(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_state = deepcopy(vars(user.subscription))
        request = UpgradeRequest(
            target_plan=Plan.SPECIALIST,
            billing_interval="year",
        )
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                quantity=3,
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                quantity=2,
                metadata={
                    "user_id": "1",
                    "plan": "plan_specialist",
                    "billing_interval": "year",
                    "change_direction": "upgrade",
                    "previous_plan": "plan_standard",
                    "previous_billing_interval": "month",
                },
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        assert mock_stripe.Subscription.modify.call_args.kwargs["items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_specialist_year",
                "quantity": 3,
            }
        ]
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()

    def test_immediate_change_rejects_unsupported_current_collection_method_before_modify(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_state = deepcopy(vars(user.subscription))
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                collection_method="send_invoice",
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.Subscription.modify.assert_not_called()
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        ("returned_status", "returned_collection_method"),
        [
            ("past_due", "charge_automatically"),
            ("incomplete", "charge_automatically"),
            ("active", "send_invoice"),
        ],
        ids=["card_decline", "requires_action", "unsupported_collection_method"],
    )
    def test_immediate_change_rejects_unpayable_or_unsupported_returned_state_without_local_publication(
        self,
        monkeypatch,
        returned_status,
        returned_collection_method,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_state = deepcopy(vars(user.subscription))
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                status=returned_status,
                collection_method=returned_collection_method,
                metadata=target_metadata,
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        assert mock_stripe.Subscription.modify.call_args.kwargs["payment_behavior"] == (
            "error_if_incomplete"
        )
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        ("managed_schedule_id", "attached_schedule_id", "attached_schedule"),
        [
            (
                "sub_sched_foreign_attached",
                "sub_sched_foreign_attached",
                _active_schedule("sub_sched_foreign_attached", metadata={}),
            ),
            (
                "sub_sched_locally_managed",
                "sub_sched_other_attached",
                _active_schedule("sub_sched_other_attached"),
            ),
            (
                None,
                "sub_sched_orphaned_qiko",
                _active_schedule("sub_sched_orphaned_qiko"),
            ),
        ],
        ids=["foreign", "local-stripe-mismatch", "orphaned-qiko"],
    )
    def test_immediate_change_rejects_unreconciled_attached_schedule_before_modify(
        self,
        monkeypatch,
        managed_schedule_id,
        attached_schedule_id,
        attached_schedule,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=managed_schedule_id,
        )
        _patch_subscription_lock(monkeypatch, user)
        original_state = deepcopy(vars(user.subscription))
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        fake_db = MagicMock()

        def retrieve_schedule(schedule_id, **_kwargs):
            if schedule_id == attached_schedule_id:
                return attached_schedule
            return _active_schedule(schedule_id)

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=attached_schedule_id,
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                metadata=target_metadata,
            )
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.SubscriptionSchedule.release.side_effect = (
                lambda schedule_id, **_kwargs: _released_schedule(schedule_id)
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.Subscription.modify.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()

    def test_immediate_change_releases_exact_managed_schedule_then_refreshes_detached_subscription(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        schedule_id = "sub_sched_locally_managed"
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id=schedule_id,
        )
        _patch_subscription_lock(monkeypatch, user)
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        events = []
        fake_db = MagicMock()

        def retrieve_schedule(*_args, **_kwargs):
            events.append("schedule_retrieve")
            return _active_schedule(
                schedule_id,
                metadata=_downgrade_metadata(
                    previous_plan="plan_standard",
                    previous_interval="month",
                ),
            )

        def release_schedule(*_args, **_kwargs):
            events.append("schedule_release")
            return _released_schedule(
                schedule_id,
                metadata=_downgrade_metadata(
                    previous_plan="plan_standard",
                    previous_interval="month",
                ),
            )

        def retrieve_subscription(*_args, **_kwargs):
            if not events:
                events.append("subscription_retrieve_attached")
                return _stripe_subscription(
                    price_id="price_test_plan_standard_month",
                    interval="month",
                    schedule_id=schedule_id,
                )
            assert events == [
                "subscription_retrieve_attached",
                "schedule_retrieve",
                "schedule_release",
            ]
            events.append("subscription_refresh_detached")
            return _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=None,
            )

        def modify_subscription(*_args, **_kwargs):
            events.append("subscription_modify")
            return _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                metadata=target_metadata,
                schedule_id=None,
            )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.SubscriptionSchedule.release.side_effect = release_schedule
            mock_stripe.Subscription.retrieve.side_effect = retrieve_subscription
            mock_stripe.Subscription.modify.side_effect = modify_subscription
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.SPECIALIST,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert result["immediate"] is True
        assert events == [
            "subscription_retrieve_attached",
            "schedule_retrieve",
            "schedule_release",
            "subscription_refresh_detached",
            "subscription_modify",
        ]
        mock_stripe.SubscriptionSchedule.release.assert_called_once_with(
            schedule_id,
            api_key="test-explicit-key",
            idempotency_key=f"plan-change-schedule-release:{schedule_id}",
        )
        assert mock_stripe.Subscription.retrieve.call_count == 2
        assert all(
            call.args == ("sub_123",) and call.kwargs == {"api_key": "test-explicit-key"}
            for call in mock_stripe.Subscription.retrieve.call_args_list
        )
        assert user.subscription.managed_plan_change_schedule_id is None
        fake_db.commit.assert_called_once_with()

    def test_immediate_change_rejects_post_modify_response_with_attached_schedule(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_state = deepcopy(vars(user.subscription))
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=None,
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_year",
                interval="year",
                metadata={
                    "user_id": "1",
                    "plan": "plan_specialist",
                    "billing_interval": "year",
                    "change_direction": "upgrade",
                    "previous_plan": "plan_standard",
                    "previous_billing_interval": "month",
                },
                schedule_id="sub_sched_reattached_after_modify",
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.Subscription.modify.assert_called_once()
        assert vars(user.subscription) == original_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        ("target_plan", "direction"),
        [
            (Plan.STANDARD, "interval_change"),
            (Plan.SPECIALIST, "upgrade"),
        ],
    )
    def test_immediate_change_with_complete_pending_schedule_returns_structured_conflict_before_stripe_mutation(
        self,
        monkeypatch,
        target_plan,
        direction,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        pending_effective_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            stripe_schedule_id="sub_sched_pending",
            pending_plan_type="plan_starter",
            pending_billing_interval="year",
            pending_change_effective_at=pending_effective_at,
        )
        _patch_subscription_lock(monkeypatch, user)
        original_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            _pending_state(user.subscription),
        )
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=target_plan,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail["code"] == "pending_plan_change_conflict"
        assert exc_info.value.detail["requested_change_kind"] == direction
        assert exc_info.value.detail["pending_plan_change"] == {
            "schedule_id": "sub_sched_pending",
            "target_plan": "plan_starter",
            "target_billing_interval": "year",
            "effective_at": pending_effective_at.isoformat(),
        }
        mock_stripe.SubscriptionSchedule.retrieve.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            _pending_state(user.subscription),
        ) == original_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        ("current_interval", "target_interval"),
        [("month", "year"), ("year", "month")],
    )
    def test_same_tier_interval_change_uses_exact_price_and_updates_state_atomically(
        self,
        monkeypatch,
        current_interval,
        target_interval,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval=current_interval,
        )
        _patch_subscription_lock(monkeypatch, user)
        req = UpgradeRequest(
            target_plan=Plan.STANDARD,
            billing_interval=target_interval,
        )
        current_price_id = f"price_test_plan_standard_{current_interval}"
        target_price_id = f"price_test_plan_standard_{target_interval}"
        retrieved_sub = _stripe_subscription(
            price_id=current_price_id,
            interval=current_interval,
        )
        updated_sub = _stripe_subscription(
            price_id=target_price_id,
            interval=target_interval,
            current_period_end=1760000000,
            metadata={
                "user_id": "1",
                "plan": "plan_standard",
                "billing_interval": target_interval,
                "change_direction": "interval_change",
                "previous_plan": "plan_standard",
                "previous_billing_interval": current_interval,
            },
        )
        fake_db = MagicMock()
        operation_at = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)

        with (
            patch("billing.router.datetime") as mock_datetime,
            patch("billing.router.stripe") as mock_stripe,
        ):
            mock_datetime.now.return_value = operation_at
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            mock_stripe.Subscription.retrieve.return_value = retrieved_sub
            mock_stripe.Subscription.modify.return_value = updated_sub
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=req,
                user=user,
                db=fake_db,
            )

        assert result["direction"] == "interval_change"
        assert result["immediate"] is True
        modify_kwargs = mock_stripe.Subscription.modify.call_args.kwargs
        assert modify_kwargs["api_key"] == "test-explicit-key"
        assert modify_kwargs["items"] == [{"id": "si_123", "price": target_price_id, "quantity": 1}]
        assert modify_kwargs["proration_behavior"] == "always_invoice"
        assert modify_kwargs["metadata"]["billing_interval"] == target_interval
        assert modify_kwargs["metadata"]["previous_billing_interval"] == current_interval
        assert modify_kwargs["metadata"]["change_direction"] == "interval_change"
        assert user.subscription.plan_type == "plan_standard"
        assert user.subscription.billing_interval == target_interval
        assert user.subscription.plan_state_event_created_at is operation_at
        assert user.subscription.plan_state_event_created_at.tzinfo is not None
        assert user.subscription.plan_state_event_created_at.utcoffset() is not None
        assert _pending_state(user.subscription) == (None, None, None, None)
        fake_db.commit.assert_called_once_with()

    def test_higher_tier_changed_interval_is_immediate_and_uses_exact_price(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_standard", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        updated_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_year",
            interval="year",
            current_period_end=1760000000,
            metadata={
                "user_id": "1",
                "plan": "plan_specialist",
                "billing_interval": "year",
                "change_direction": "upgrade",
                "previous_plan": "plan_standard",
                "previous_billing_interval": "month",
            },
        )
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.Subscription.modify.return_value = updated_sub
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=req,
                user=user,
                db=fake_db,
            )

        assert result["direction"] == "upgrade"
        assert result["immediate"] is True
        modify_kwargs = mock_stripe.Subscription.modify.call_args.kwargs
        assert modify_kwargs["items"] == [
            {
                "id": "si_123",
                "price": "price_test_plan_specialist_year",
                "quantity": 1,
            }
        ]
        assert modify_kwargs["proration_behavior"] == "always_invoice"
        assert modify_kwargs["metadata"]["billing_interval"] == "year"
        assert modify_kwargs["metadata"]["previous_billing_interval"] == "month"
        assert user.subscription.plan_type == "plan_specialist"
        assert user.subscription.billing_interval == "year"

    def test_pending_schedule_conflict_precedes_even_a_configured_release_failure(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        pending_effective_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            stripe_schedule_id="sub_sched_release_failure",
            pending_plan_type="plan_specialist",
            pending_billing_interval="year",
            pending_change_effective_at=pending_effective_at,
        )
        _patch_subscription_lock(monkeypatch, user)
        pending_state = _pending_state(user.subscription)
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = AssertionError(
                "pending conflict must precede schedule retrieval"
            )
            mock_stripe.SubscriptionSchedule.release.side_effect = Exception(
                "schedule release failed"
            )
            mock_stripe.Subscription.modify.side_effect = AssertionError(
                "pending conflict must precede subscription modification"
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "pending_plan_change_conflict"
        mock_stripe.SubscriptionSchedule.retrieve.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert _pending_state(user.subscription) == pending_state
        fake_db.commit.assert_not_called()

    def test_immediate_change_recovers_after_commit_failure_without_repeating_stripe(
        self, monkeypatch
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
        )
        _patch_subscription_lock(monkeypatch, user)
        request = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        target_stripe_state = _stripe_subscription(
            price_id="price_test_plan_specialist_year",
            interval="year",
            current_period_end=1760000000,
            metadata=target_metadata,
        )
        fake_db = MagicMock()
        commit_count = 0

        def commit():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 1:
                user.subscription.plan_type = "plan_standard"
                user.subscription.billing_interval = "month"
                user.subscription.status = "active"
                user.subscription.plan_state_event_created_at = None
                raise RuntimeError("database commit failed")

        fake_db.commit.side_effect = commit

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.side_effect = [
                _stripe_subscription(
                    price_id="price_test_plan_standard_month",
                    interval="month",
                ),
                target_stripe_state,
            ]
            mock_stripe.Subscription.modify.return_value = target_stripe_state
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as first_error:
                execute_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=fake_db,
                )
            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        assert first_error.value.status_code == 502
        assert result["direction"] == "upgrade"
        assert result["immediate"] is True
        mock_stripe.SubscriptionSchedule.retrieve.assert_not_called()
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        assert mock_stripe.Subscription.modify.call_count == 1
        assert user.subscription.plan_type == "plan_specialist"
        assert user.subscription.billing_interval == "year"
        assert _pending_state(user.subscription) == (None, None, None, None)
        assert commit_count == 2

    def test_immediate_change_rejects_managed_schedule_with_wrong_qiko_owner(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id="sub_sched_managed_foreign",
        )
        _patch_subscription_lock(monkeypatch, user)
        fake_db = MagicMock()
        events: list[str] = []

        def retrieve_subscription(*_args, **_kwargs):
            events.append("subscription_retrieve")
            return _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id="sub_sched_managed_foreign",
            )

        def retrieve_schedule(*_args, **_kwargs):
            assert events == ["subscription_retrieve"]
            events.append("schedule_ownership_rejected")
            return _active_schedule(
                "sub_sched_managed_foreign",
                metadata=_downgrade_metadata(
                    subscription_record_id="999",
                    previous_plan="plan_specialist",
                ),
            )

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.side_effect = retrieve_subscription
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.SPECIALIST,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code in {409, 502}
        assert events == ["subscription_retrieve", "schedule_ownership_rejected"]
        mock_stripe.Subscription.retrieve.assert_called_once_with(
            "sub_123",
            api_key="test-explicit-key",
        )
        mock_stripe.SubscriptionSchedule.release.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert user.subscription.managed_plan_change_schedule_id == ("sub_sched_managed_foreign")
        assert _pending_state(user.subscription) == (None, None, None, None)
        fake_db.commit.assert_not_called()

    def test_immediate_retry_reconciles_released_managed_schedule_without_pending_claim(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id="sub_sched_managed",
        )
        _patch_subscription_lock(monkeypatch, user)
        request = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        target_metadata = {
            "user_id": "1",
            "plan": "plan_specialist",
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": "plan_standard",
            "previous_billing_interval": "month",
        }
        attached_subscription = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
            schedule_id="sub_sched_managed",
        )
        detached_subscription = _stripe_subscription(
            price_id="price_test_plan_standard_month",
            interval="month",
            schedule_id=None,
        )
        updated_subscription = _stripe_subscription(
            price_id="price_test_plan_specialist_year",
            interval="year",
            metadata=target_metadata,
        )
        fake_db = MagicMock()
        modify_attempts = 0

        def modify_subscription(*args, **kwargs):
            nonlocal modify_attempts
            modify_attempts += 1
            assert user.subscription.managed_plan_change_schedule_id is None
            assert _pending_state(user.subscription) == (None, None, None, None)
            if modify_attempts == 1:
                raise Exception("subscription update failed after schedule release")
            return updated_subscription

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = [
                _active_schedule("sub_sched_managed"),
                _released_schedule("sub_sched_managed"),
            ]
            mock_stripe.SubscriptionSchedule.release.return_value = _released_schedule(
                "sub_sched_managed"
            )
            mock_stripe.Subscription.retrieve.side_effect = [
                attached_subscription,
                detached_subscription,
                detached_subscription,
            ]
            mock_stripe.Subscription.modify.side_effect = modify_subscription
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as first_error:
                execute_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=fake_db,
                )
            assert user.subscription.managed_plan_change_schedule_id == ("sub_sched_managed")
            assert _pending_state(user.subscription) == (None, None, None, None)

            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        assert first_error.value.status_code == 502
        assert mock_stripe.Subscription.retrieve.call_count == 3
        assert all(
            call.args == ("sub_123",) and call.kwargs == {"api_key": "test-explicit-key"}
            for call in mock_stripe.Subscription.retrieve.call_args_list
        )
        assert mock_stripe.SubscriptionSchedule.retrieve.call_count == 2
        assert all(
            call.args == ("sub_sched_managed",)
            and call.kwargs
            == {
                "api_key": "test-explicit-key",
            }
            for call in mock_stripe.SubscriptionSchedule.retrieve.call_args_list
        )
        mock_stripe.SubscriptionSchedule.release.assert_called_once_with(
            "sub_sched_managed",
            api_key="test-explicit-key",
            idempotency_key="plan-change-schedule-release:sub_sched_managed",
        )
        assert user.subscription.managed_plan_change_schedule_id is None
        assert _pending_state(user.subscription) == (None, None, None, None)
        assert result["immediate"] is True

    def test_immediate_change_captures_final_fence_after_release_and_validated_modify_before_commit(
        self,
        monkeypatch,
    ):
        from billing import Plan
        from billing import router as billing_router
        from billing.router import UpgradeRequest, execute_plan_change

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
            managed_plan_change_schedule_id="sub_sched_fence_order",
        )
        _patch_subscription_lock(monkeypatch, user)
        request_started_at = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)
        release_event_created_at = request_started_at.replace(microsecond=500_000)
        final_fence_at = datetime(2026, 7, 28, 15, 30, 1, tzinfo=timezone.utc)
        events: list[str] = []
        now_values = iter([request_started_at, final_fence_at])
        real_validate = billing_router.validate_immediate_plan_change
        updated_subscription = _stripe_subscription(
            price_id="price_test_plan_specialist_year",
            interval="year",
            current_period_end=1760000000,
            metadata={
                "user_id": "1",
                "plan": "plan_specialist",
                "billing_interval": "year",
                "change_direction": "upgrade",
                "previous_plan": "plan_standard",
                "previous_billing_interval": "month",
            },
        )
        fake_db = MagicMock()

        def now(_timezone):
            value = next(now_values)
            events.append("request_start" if value == request_started_at else "final_fence")
            return value

        def retrieve_subscription(*_args, **_kwargs):
            if "release" not in events:
                events.append("subscription_retrieve_attached")
                return _stripe_subscription(
                    price_id="price_test_plan_standard_month",
                    interval="month",
                    schedule_id="sub_sched_fence_order",
                )
            events.append("subscription_refresh_detached")
            return _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
                schedule_id=None,
            )

        def retrieve_schedule(*_args, **_kwargs):
            events.append("schedule_retrieve")
            return _active_schedule("sub_sched_fence_order")

        def release_schedule(*_args, **_kwargs):
            events.append("release")
            return _released_schedule("sub_sched_fence_order")

        def modify_subscription(*_args, **_kwargs):
            events.append("modify")
            return updated_subscription

        def validate_modified_subscription(*args, **kwargs):
            events.append("validate")
            return real_validate(*args, **kwargs)

        def commit():
            events.append("commit")
            assert user.subscription.plan_state_event_created_at == final_fence_at

        fake_db.commit.side_effect = commit
        monkeypatch.setattr(
            billing_router,
            "validate_immediate_plan_change",
            validate_modified_subscription,
        )

        with (
            patch("billing.router.datetime") as mock_datetime,
            patch("billing.router.stripe") as mock_stripe,
        ):
            mock_datetime.now.side_effect = now
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.SubscriptionSchedule.release.side_effect = release_schedule
            mock_stripe.Subscription.retrieve.side_effect = retrieve_subscription
            mock_stripe.Subscription.modify.side_effect = modify_subscription
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.SPECIALIST,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert result["immediate"] is True
        assert events == [
            "request_start",
            "subscription_retrieve_attached",
            "schedule_retrieve",
            "release",
            "subscription_refresh_detached",
            "modify",
            "validate",
            "final_fence",
            "commit",
        ]
        assert user.subscription.plan_state_event_created_at == final_fence_at
        assert user.subscription.plan_state_event_created_at > release_event_created_at
        assert user.subscription.managed_plan_change_schedule_id is None
        assert _pending_state(user.subscription) == (None, None, None, None)

    def test_invalid_immediate_stripe_response_preserves_active_state(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
        )
        _patch_subscription_lock(monkeypatch, user)
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        pending_state = _pending_state(user.subscription)
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.Subscription.modify.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                metadata={
                    "user_id": "1",
                    "plan": "plan_specialist",
                    "billing_interval": "month",
                    "change_direction": "upgrade",
                    "previous_plan": "plan_standard",
                    "previous_billing_interval": "month",
                },
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=req,
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == active_state
        assert _pending_state(user.subscription) == pending_state
        fake_db.commit.assert_not_called()

    def test_downgrade_releases_managed_schedule_before_creating_new_pending_schedule(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_specialist",
            billing_interval="month",
            managed_plan_change_schedule_id="sub_sched_managed_old",
        )
        _patch_subscription_lock(monkeypatch, user)
        active_phase = _expanded_active_phase()
        active_phase["items"][0]["quantity"] = 1
        events: list[str] = []
        fake_db = MagicMock()

        def retrieve_subscription(*args, **kwargs):
            events.append("subscription_retrieve")
            assert user.subscription.managed_plan_change_schedule_id is None
            return _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
            )

        def create_schedule(*args, **kwargs):
            events.append("create")
            assert user.subscription.managed_plan_change_schedule_id is None
            return {"id": "sub_sched_new_pending"}

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = [
                _active_schedule("sub_sched_managed_old"),
                _expanded_active_schedule(
                    schedule_id="sub_sched_new_pending",
                    active_phase=active_phase,
                    metadata={},
                ),
            ]
            mock_stripe.SubscriptionSchedule.release.side_effect = lambda *a, **kw: (
                events.append("release") or _released_schedule("sub_sched_managed_old")
            )
            mock_stripe.Subscription.retrieve.side_effect = retrieve_subscription
            mock_stripe.SubscriptionSchedule.create.side_effect = create_schedule
            mock_stripe.SubscriptionSchedule.modify.return_value = _expanded_preserved_schedule(
                schedule_id="sub_sched_new_pending",
                active_phase=active_phase,
            )
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.STANDARD,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert events == ["release", "subscription_retrieve", "create"]
        assert user.subscription.managed_plan_change_schedule_id is None
        assert _pending_state(user.subscription) == (
            "sub_sched_new_pending",
            "plan_standard",
            "year",
            datetime.fromtimestamp(active_phase["end_date"], tz=timezone.utc),
        )
        assert result["immediate"] is False

    def test_downgrade_creates_validated_schedule_and_only_publishes_pending_state(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        config = _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_specialist",
            billing_interval="month",
        )
        original_active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        original_pending_state = _pending_state(user.subscription)
        lock = MagicMock(return_value=user.subscription)
        monkeypatch.setattr(
            "billing.router.lock_subscription_for_plan_change",
            lock,
            raising=False,
        )
        request = UpgradeRequest(target_plan=Plan.STANDARD, billing_interval="year")
        fake_db = MagicMock()
        period_start = 1747000000
        period_end = 1750000000
        active_phase = _expanded_active_phase(
            period_start=period_start,
            period_end=period_end,
        )
        active_phase["items"][0]["quantity"] = 1
        stripe_events = []

        def create_schedule(*args, **kwargs):
            stripe_events.append(("create", args, kwargs))
            assert _pending_state(user.subscription) == original_pending_state
            assert (
                user.subscription.plan_type,
                user.subscription.billing_interval,
                user.subscription.status,
            ) == original_active_state
            fake_db.commit.assert_not_called()
            return {"id": "sub_sched_downgrade"}

        def retrieve_schedule(*args, **kwargs):
            stripe_events.append(("retrieve", args, kwargs))
            assert [event[0] for event in stripe_events] == ["create", "retrieve"]
            return _expanded_active_schedule(
                active_phase=active_phase,
                metadata={},
            )

        def modify_schedule(*args, **kwargs):
            stripe_events.append(("modify", args, kwargs))
            assert [event[0] for event in stripe_events] == [
                "create",
                "retrieve",
                "modify",
            ]
            assert _pending_state(user.subscription) == original_pending_state
            assert (
                user.subscription.plan_type,
                user.subscription.billing_interval,
                user.subscription.status,
            ) == original_active_state
            fake_db.commit.assert_not_called()
            return _expanded_preserved_schedule(active_phase=active_phase)

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                current_period_start=period_start,
                current_period_end=period_end,
            )
            mock_stripe.SubscriptionSchedule.create.side_effect = create_schedule
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.SubscriptionSchedule.modify.side_effect = modify_schedule
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        lock.assert_called_once_with(fake_db, 17)
        mock_stripe.Subscription.retrieve.assert_called_once_with(
            "sub_123",
            api_key="test-explicit-key",
        )
        mock_stripe.Subscription.modify.assert_not_called()
        assert mock_stripe.SubscriptionSchedule.create.call_args.args == ()
        create_kwargs = mock_stripe.SubscriptionSchedule.create.call_args.kwargs
        assert set(create_kwargs) == {
            "from_subscription",
            "api_key",
            "idempotency_key",
        }
        assert create_kwargs["from_subscription"] == "sub_123"
        assert create_kwargs["api_key"] == "test-explicit-key"
        assert create_kwargs["idempotency_key"]
        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            "sub_sched_downgrade",
            api_key="test-explicit-key",
            expand=["phases.items.price"],
        )
        modify_args = mock_stripe.SubscriptionSchedule.modify.call_args.args
        modify_kwargs = mock_stripe.SubscriptionSchedule.modify.call_args.kwargs
        assert modify_args == ("sub_sched_downgrade",)
        assert modify_kwargs["api_key"] == "test-explicit-key"
        assert modify_kwargs["phases"] == _expected_preserved_schedule_phases(active_phase)
        assert modify_kwargs["end_behavior"] == "release"
        assert modify_kwargs["proration_behavior"] == "none"
        assert modify_kwargs["expand"] == ["phases.items.price"]
        assert modify_kwargs["metadata"] == _downgrade_metadata()
        assert modify_kwargs["idempotency_key"]
        assert create_kwargs["idempotency_key"] != modify_kwargs["idempotency_key"]
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == original_active_state
        assert _pending_state(user.subscription) == (
            "sub_sched_downgrade",
            "plan_standard",
            "year",
            datetime.fromtimestamp(period_end, tz=timezone.utc),
        )
        fake_db.commit.assert_called_once_with()
        assert ("test", Plan.SPECIALIST, "month") in config.price_lookups
        assert ("test", Plan.STANDARD, "year") in config.price_lookups
        assert result["direction"] == "downgrade"
        assert result["previous_plan"] == "plan_specialist"
        assert result["new_plan"] == "plan_standard"
        assert result["current_billing_interval"] == "month"
        assert result["target_billing_interval"] == "year"
        assert result["immediate"] is False
        assert (
            result["effective_date"]
            == datetime.fromtimestamp(
                period_end,
                tz=timezone.utc,
            ).isoformat()
        )

    def test_scheduled_downgrade_captures_final_fence_after_validated_schedule_before_commit(
        self,
        monkeypatch,
    ):
        from billing import Plan
        from billing import router as billing_router
        from billing.router import UpgradeRequest, execute_plan_change

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        active_phase = _expanded_active_phase()
        active_phase["items"][0]["quantity"] = 1
        final_fence_at = datetime(2026, 7, 28, 15, 30, 1, tzinfo=timezone.utc)
        expected_pending_state = (
            "sub_sched_downgrade",
            "plan_standard",
            "year",
            datetime.fromtimestamp(active_phase["end_date"], tz=timezone.utc),
        )
        events: list[str] = []
        real_validate = billing_router.validate_configured_downgrade_schedule
        fake_db = MagicMock()

        def retrieve_subscription(*_args, **_kwargs):
            events.append("subscription_retrieve")
            return _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                current_period_start=active_phase["start_date"],
                current_period_end=active_phase["end_date"],
            )

        def create_schedule(*_args, **_kwargs):
            events.append("schedule_create")
            return {"id": "sub_sched_downgrade"}

        def retrieve_schedule(*_args, **_kwargs):
            events.append("schedule_retrieve")
            return _expanded_active_schedule(active_phase=active_phase, metadata={})

        def modify_schedule(*_args, **_kwargs):
            events.append("schedule_modify")
            return _expanded_preserved_schedule(active_phase=active_phase)

        def validate_schedule(*args, **kwargs):
            result = real_validate(*args, **kwargs)
            events.append("schedule_validated")
            assert user.subscription.plan_state_event_created_at is None
            return result

        def now(_timezone):
            assert events[-1] == "schedule_validated"
            assert _pending_state(user.subscription) == expected_pending_state
            events.append("final_fence")
            return final_fence_at

        def commit():
            events.append("commit")
            assert events[-2:] == ["final_fence", "commit"]
            assert user.subscription.plan_state_event_created_at == final_fence_at
            assert _pending_state(user.subscription) == expected_pending_state

        fake_db.commit.side_effect = commit
        monkeypatch.setattr(
            billing_router,
            "validate_configured_downgrade_schedule",
            validate_schedule,
        )

        with (
            patch("billing.router.datetime") as mock_datetime,
            patch("billing.router.stripe") as mock_stripe,
        ):
            mock_datetime.now.side_effect = now
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            mock_stripe.Subscription.retrieve.side_effect = retrieve_subscription
            mock_stripe.SubscriptionSchedule.create.side_effect = create_schedule
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = retrieve_schedule
            mock_stripe.SubscriptionSchedule.modify.side_effect = modify_schedule
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.STANDARD,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert result["immediate"] is False
        assert events == [
            "subscription_retrieve",
            "schedule_create",
            "schedule_retrieve",
            "schedule_modify",
            "schedule_validated",
            "final_fence",
            "commit",
        ]
        assert user.subscription.plan_state_event_created_at == final_fence_at
        assert user.subscription.plan_state_event_created_at.tzinfo is not None
        assert user.subscription.plan_state_event_created_at.utcoffset() is not None
        fake_db.commit.assert_called_once_with()

    @pytest.mark.parametrize("discount_field", ["coupon", "discounts"])
    def test_downgrade_retrieves_expanded_active_phase_after_minimal_create(
        self,
        monkeypatch,
        discount_field,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        active_phase = _expanded_active_phase(discount_field=discount_field)
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
            current_period_start=active_phase["start_date"],
            current_period_end=active_phase["end_date"],
        )
        stripe_sub["items"]["data"][0]["quantity"] = active_phase["items"][0]["quantity"]
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.SubscriptionSchedule.create.return_value = {"id": "sub_sched_downgrade"}
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _expanded_active_schedule(
                active_phase=active_phase, metadata={}
            )
            mock_stripe.SubscriptionSchedule.modify.return_value = _expanded_preserved_schedule(
                active_phase=active_phase
            )
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.STANDARD,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        assert mock_stripe.SubscriptionSchedule.create.call_args.args == ()
        create_kwargs = mock_stripe.SubscriptionSchedule.create.call_args.kwargs
        assert set(create_kwargs) == {
            "from_subscription",
            "api_key",
            "idempotency_key",
        }
        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            "sub_sched_downgrade",
            api_key="test-explicit-key",
            expand=["phases.items.price"],
        )
        modify_kwargs = mock_stripe.SubscriptionSchedule.modify.call_args.kwargs
        assert modify_kwargs["expand"] == ["phases.items.price"]
        assert modify_kwargs["proration_behavior"] == "none"
        assert modify_kwargs["phases"] == _expected_preserved_schedule_phases(active_phase)
        assert modify_kwargs["phases"][1] == {
            "start_date": active_phase["end_date"],
            "items": [
                {
                    "price": "price_test_plan_standard_year",
                    "quantity": 3,
                }
            ],
            "metadata": _downgrade_metadata(),
        }
        assert result["immediate"] is False
        fake_db.commit.assert_called_once_with()

    def test_locally_recorded_qiko_schedule_reuse_requests_expanded_phase_prices(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        active_phase = _expanded_active_phase()
        user = _make_user(
            plan_type="plan_specialist",
            billing_interval="month",
            stripe_schedule_id="sub_sched_expanded_existing",
            pending_plan_type="plan_standard",
            pending_billing_interval="year",
            pending_change_effective_at=datetime.fromtimestamp(
                active_phase["end_date"], tz=timezone.utc
            ),
        )
        _patch_subscription_lock(monkeypatch, user)
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
            current_period_start=active_phase["start_date"],
            current_period_end=active_phase["end_date"],
            schedule_id="sub_sched_expanded_existing",
        )
        stripe_sub["items"]["data"][0]["quantity"] = active_phase["items"][0]["quantity"]
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _expanded_active_schedule(
                schedule_id="sub_sched_expanded_existing",
                active_phase=active_phase,
            )
            mock_stripe.SubscriptionSchedule.modify.return_value = _expanded_preserved_schedule(
                schedule_id="sub_sched_expanded_existing",
                active_phase=active_phase,
            )
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.STANDARD,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            "sub_sched_expanded_existing",
            api_key="test-explicit-key",
            expand=["phases.items.price"],
        )
        assert mock_stripe.SubscriptionSchedule.modify.call_args.kwargs["expand"] == [
            "phases.items.price"
        ]
        mock_stripe.SubscriptionSchedule.create.assert_not_called()
        assert result["immediate"] is False

    @pytest.mark.parametrize(
        "schedule_metadata",
        [
            _downgrade_metadata(subscription_record_id="999"),
            _downgrade_metadata(
                target_plan="plan_starter",
                target_interval="month",
            ),
        ],
        ids=["wrong_local_owner", "unrelated_target"],
    )
    def test_downgrade_rejects_untrusted_attached_schedule_before_modify(
        self,
        monkeypatch,
        schedule_metadata,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        active_phase = _expanded_active_phase()
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
            current_period_start=active_phase["start_date"],
            current_period_end=active_phase["end_date"],
            schedule_id="sub_sched_untrusted_attached",
        )
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _expanded_active_schedule(
                schedule_id="sub_sched_untrusted_attached",
                active_phase=active_phase,
                metadata=schedule_metadata,
            )
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code in {409, 502}
        mock_stripe.SubscriptionSchedule.create.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert _pending_state(user.subscription) == (None, None, None, None)
        fake_db.commit.assert_not_called()

    def test_unmarked_attached_schedule_is_rejected_when_exact_create_replay_returns_other_id(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        active_phase = _expanded_active_phase()
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                schedule_id="sub_sched_unmarked_attached",
            )
            mock_stripe.SubscriptionSchedule.retrieve.return_value = _expanded_active_schedule(
                schedule_id="sub_sched_unmarked_attached",
                active_phase=active_phase,
                metadata={},
            )
            mock_stripe.SubscriptionSchedule.create.return_value = {
                "id": "sub_sched_unrelated_replay"
            }
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code in {409, 502}
        assert mock_stripe.SubscriptionSchedule.create.call_args.args == ()
        create_kwargs = mock_stripe.SubscriptionSchedule.create.call_args.kwargs
        assert set(create_kwargs) == {
            "from_subscription",
            "api_key",
            "idempotency_key",
        }
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        assert _pending_state(user.subscription) == (None, None, None, None)
        fake_db.commit.assert_not_called()

    def test_downgrade_replaces_future_phase_on_existing_owned_active_schedule(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        old_effective_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        user = _make_user(
            plan_type="plan_specialist",
            billing_interval="month",
            stripe_schedule_id="sub_sched_existing",
            pending_plan_type="plan_starter",
            pending_billing_interval="month",
            pending_change_effective_at=old_effective_at,
        )
        _patch_subscription_lock(monkeypatch, user)
        original_active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        period_start = 1747000000
        period_end = 1750000000
        old_metadata = _downgrade_metadata(
            target_plan="plan_starter",
            target_interval="month",
        )
        existing_schedule = _configured_schedule(
            "sub_sched_existing",
            target_price_id="price_test_plan_starter_month",
            target_interval="month",
            period_start=period_start,
            period_end=period_end,
            metadata=old_metadata,
        )
        replacement_schedule = _configured_schedule(
            "sub_sched_existing",
            period_start=period_start,
            period_end=period_end,
        )
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                current_period_start=period_start,
                current_period_end=period_end,
                schedule_id="sub_sched_existing",
            )
            mock_stripe.SubscriptionSchedule.retrieve.return_value = existing_schedule
            mock_stripe.SubscriptionSchedule.modify.return_value = replacement_schedule
            mock_stripe.error.StripeError = Exception

            result = execute_plan_change(
                http_request=None,
                request=UpgradeRequest(
                    target_plan=Plan.STANDARD,
                    billing_interval="year",
                ),
                user=user,
                db=fake_db,
            )

        mock_stripe.SubscriptionSchedule.retrieve.assert_called_once_with(
            "sub_sched_existing",
            api_key="test-explicit-key",
            expand=["phases.items.price"],
        )
        mock_stripe.SubscriptionSchedule.create.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        modify_kwargs = mock_stripe.SubscriptionSchedule.modify.call_args.kwargs
        assert modify_kwargs["phases"] == _expected_schedule_phases(
            period_start=period_start,
            period_end=period_end,
        )
        assert modify_kwargs["metadata"] == _downgrade_metadata()
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == original_active_state
        assert _pending_state(user.subscription) == (
            "sub_sched_existing",
            "plan_standard",
            "year",
            datetime.fromtimestamp(period_end, tz=timezone.utc),
        )
        fake_db.commit.assert_called_once_with()
        assert result["immediate"] is False

    @pytest.mark.parametrize(
        "invalid_field",
        [
            "subscription_id",
            "customer_id",
            "status",
            "item_count",
            "item_id",
            "current_price",
            "current_interval",
            "current_period_start",
            "current_period_end",
            "reversed_period",
        ],
    )
    def test_downgrade_rejects_invalid_current_subscription_before_schedule_or_mutation(
        self,
        monkeypatch,
        invalid_field,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        original_pending_state = _pending_state(user.subscription)
        stripe_sub = _stripe_subscription(
            price_id="price_test_plan_specialist_month",
            interval="month",
        )
        if invalid_field == "subscription_id":
            stripe_sub["id"] = "sub_foreign"
        elif invalid_field == "customer_id":
            stripe_sub["customer"] = "cus_foreign"
        elif invalid_field == "status":
            stripe_sub["status"] = "past_due"
        elif invalid_field == "item_count":
            stripe_sub["items"]["data"] = []
        elif invalid_field == "item_id":
            stripe_sub["items"]["data"][0]["id"] = ""
        elif invalid_field == "current_price":
            stripe_sub["items"]["data"][0]["price"]["id"] = "price_test_plan_standard_month"
        elif invalid_field == "current_interval":
            stripe_sub["items"]["data"][0]["price"]["recurring"]["interval"] = "year"
        elif invalid_field == "current_period_start":
            stripe_sub["current_period_start"] = None
        elif invalid_field == "current_period_end":
            stripe_sub["current_period_end"] = None
        else:
            stripe_sub["current_period_start"] = stripe_sub["current_period_end"]
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = stripe_sub
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.Subscription.modify.assert_not_called()
        mock_stripe.SubscriptionSchedule.retrieve.assert_not_called()
        mock_stripe.SubscriptionSchedule.create.assert_not_called()
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == original_active_state
        assert _pending_state(user.subscription) == original_pending_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        ("foreign_field", "foreign_value"),
        [
            ("id", "sub_sched_foreign"),
            ("customer", "cus_foreign"),
            ("subscription", "sub_foreign"),
            ("status", "released"),
            ("marker_kind", "unrelated"),
            ("marker_owner", "999"),
        ],
    )
    def test_downgrade_rejects_unowned_retrieved_schedule_before_modify_or_local_mutation(
        self,
        monkeypatch,
        foreign_field,
        foreign_value,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        original_pending_state = _pending_state(user.subscription)
        created_schedule = _owned_schedule()
        if foreign_field == "marker_kind":
            created_schedule["metadata"]["qiko_schedule_kind"] = foreign_value
        elif foreign_field == "marker_owner":
            created_schedule["metadata"]["qiko_subscription_record_id"] = foreign_value
        else:
            created_schedule[foreign_field] = foreign_value
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
            )
            mock_stripe.SubscriptionSchedule.create.return_value = {"id": "sub_sched_downgrade"}
            mock_stripe.SubscriptionSchedule.retrieve.return_value = created_schedule
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.SubscriptionSchedule.modify.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == original_active_state
        assert _pending_state(user.subscription) == original_pending_state
        fake_db.commit.assert_not_called()

    @pytest.mark.parametrize(
        "malformation",
        [
            "schedule_id",
            "customer_id",
            "subscription_id",
            "status",
            "end_behavior",
            "phase_count",
            "current_start",
            "current_end",
            "current_price",
            "current_interval",
            "current_quantity",
            "future_start",
            "future_price",
            "future_interval",
            "future_quantity",
            "schedule_metadata",
            "future_metadata",
        ],
    )
    def test_downgrade_validates_complete_modified_schedule_before_local_mutation(
        self,
        monkeypatch,
        malformation,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        original_active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        original_pending_state = _pending_state(user.subscription)
        schedule = _configured_schedule()
        created_schedule = _expanded_active_schedule(active_phase=deepcopy(schedule["phases"][0]))
        if malformation == "schedule_id":
            schedule["id"] = "sub_sched_other"
        elif malformation == "customer_id":
            schedule["customer"] = "cus_other"
        elif malformation == "subscription_id":
            schedule["subscription"] = "sub_other"
        elif malformation == "status":
            schedule["status"] = "canceled"
        elif malformation == "end_behavior":
            schedule["end_behavior"] = "cancel"
        elif malformation == "phase_count":
            schedule["phases"] = schedule["phases"][:1]
        elif malformation == "current_start":
            schedule["phases"][0]["start_date"] += 1
        elif malformation == "current_end":
            schedule["phases"][0]["end_date"] += 1
        elif malformation == "current_price":
            schedule["phases"][0]["items"][0]["price"]["id"] = "price_other"
        elif malformation == "current_interval":
            schedule["phases"][0]["items"][0]["price"]["recurring"]["interval"] = "year"
        elif malformation == "current_quantity":
            schedule["phases"][0]["items"][0]["quantity"] = 2
        elif malformation == "future_start":
            schedule["phases"][1]["start_date"] += 1
        elif malformation == "future_price":
            schedule["phases"][1]["items"][0]["price"]["id"] = "price_other"
        elif malformation == "future_interval":
            schedule["phases"][1]["items"][0]["price"]["recurring"]["interval"] = "month"
        elif malformation == "future_quantity":
            schedule["phases"][1]["items"][0]["quantity"] = 2
        elif malformation == "schedule_metadata":
            schedule["metadata"] = {**schedule["metadata"], "plan": "plan_starter"}
        else:
            schedule["phases"][1]["metadata"] = {
                **schedule["phases"][1]["metadata"],
                "billing_interval": "month",
            }
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
            )
            mock_stripe.SubscriptionSchedule.create.return_value = {"id": "sub_sched_downgrade"}
            mock_stripe.SubscriptionSchedule.retrieve.return_value = created_schedule
            mock_stripe.SubscriptionSchedule.modify.return_value = schedule
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(
                    http_request=None,
                    request=UpgradeRequest(
                        target_plan=Plan.STANDARD,
                        billing_interval="year",
                    ),
                    user=user,
                    db=fake_db,
                )

        assert exc_info.value.status_code == 502
        mock_stripe.Subscription.modify.assert_not_called()
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == original_active_state
        assert _pending_state(user.subscription) == original_pending_state
        fake_db.commit.assert_not_called()

    def test_downgrade_retry_replays_exact_create_and_modify_operation_keys(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(plan_type="plan_specialist", billing_interval="month")
        _patch_subscription_lock(monkeypatch, user)
        request = UpgradeRequest(target_plan=Plan.STANDARD, billing_interval="year")
        period_end = 1750000000
        active_phase = _expanded_active_phase(period_end=period_end)
        active_phase["items"][0]["quantity"] = 1
        unmarked_schedule = _expanded_active_schedule(
            active_phase=active_phase,
            metadata={},
        )
        configured_schedule = _expanded_preserved_schedule(active_phase=active_phase)
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.Subscription.retrieve.side_effect = [
                _stripe_subscription(
                    price_id="price_test_plan_specialist_month",
                    interval="month",
                ),
                _stripe_subscription(
                    price_id="price_test_plan_specialist_month",
                    interval="month",
                    schedule_id="sub_sched_downgrade",
                ),
            ]
            mock_stripe.SubscriptionSchedule.create.side_effect = [
                {"id": "sub_sched_downgrade"},
                {"id": "sub_sched_downgrade"},
            ]
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = [
                unmarked_schedule,
                unmarked_schedule,
            ]
            mock_stripe.SubscriptionSchedule.modify.side_effect = [
                Exception("modify response lost after Stripe applied it"),
                configured_schedule,
            ]
            mock_stripe.error.StripeError = Exception

            with pytest.raises(HTTPException) as first_error:
                execute_plan_change(
                    http_request=None,
                    request=request,
                    user=user,
                    db=fake_db,
                )
            result = execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        assert first_error.value.status_code == 502
        create_calls = mock_stripe.SubscriptionSchedule.create.call_args_list
        assert len(create_calls) == 2
        assert all(
            call.args == ()
            and set(call.kwargs) == {"from_subscription", "api_key", "idempotency_key"}
            for call in create_calls
        )
        assert (
            create_calls[0].kwargs["idempotency_key"] == create_calls[1].kwargs["idempotency_key"]
        )
        modify_calls = mock_stripe.SubscriptionSchedule.modify.call_args_list
        assert len(modify_calls) == 2
        assert (
            modify_calls[0].kwargs["idempotency_key"] == modify_calls[1].kwargs["idempotency_key"]
        )
        retrieve_calls = mock_stripe.SubscriptionSchedule.retrieve.call_args_list
        assert len(retrieve_calls) == 2
        assert all(
            call.args == ("sub_sched_downgrade",)
            and call.kwargs
            == {
                "api_key": "test-explicit-key",
                "expand": ["phases.items.price"],
            }
            for call in retrieve_calls
        )
        mock_stripe.Subscription.modify.assert_not_called()
        assert _pending_state(user.subscription) == (
            "sub_sched_downgrade",
            "plan_standard",
            "year",
            datetime.fromtimestamp(period_end, tz=timezone.utc),
        )
        assert user.subscription.plan_type == "plan_specialist"
        assert user.subscription.billing_interval == "month"
        fake_db.commit.assert_called_once_with()
        assert result["immediate"] is False

    def test_replacement_operation_key_is_deterministic_and_includes_previous_target_and_boundary(
        self,
        monkeypatch,
    ):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        effective_at = datetime.fromtimestamp(1750000000, tz=timezone.utc)
        user = _make_user(
            plan_type="plan_specialist",
            billing_interval="month",
            stripe_schedule_id="sub_sched_replacement",
            pending_plan_type="plan_starter",
            pending_billing_interval="month",
            pending_change_effective_at=effective_at,
        )
        _patch_subscription_lock(monkeypatch, user)
        request = UpgradeRequest(target_plan=Plan.STANDARD, billing_interval="year")
        fake_db = MagicMock()

        def set_previous_pending(
            interval: str,
            *,
            pending_effective_at: datetime = effective_at,
        ) -> None:
            user.subscription.stripe_schedule_id = "sub_sched_replacement"
            user.subscription.pending_plan_type = "plan_starter"
            user.subscription.pending_billing_interval = interval
            user.subscription.pending_change_effective_at = pending_effective_at

        old_month = _configured_schedule(
            "sub_sched_replacement",
            target_price_id="price_test_plan_starter_month",
            target_interval="month",
            metadata=_downgrade_metadata(
                target_plan="plan_starter",
                target_interval="month",
            ),
        )
        old_year = _configured_schedule(
            "sub_sched_replacement",
            target_price_id="price_test_plan_starter_year",
            target_interval="year",
            metadata=_downgrade_metadata(
                target_plan="plan_starter",
                target_interval="year",
            ),
        )
        later_period_end = 1751000000
        later_effective_at = datetime.fromtimestamp(
            later_period_end,
            tz=timezone.utc,
        )
        old_year_later_boundary = _configured_schedule(
            "sub_sched_replacement",
            target_price_id="price_test_plan_starter_year",
            target_interval="year",
            period_end=later_period_end,
            metadata=_downgrade_metadata(
                target_plan="plan_starter",
                target_interval="year",
            ),
        )

        with patch("billing.router.stripe") as mock_stripe:
            current_subscription = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                schedule_id="sub_sched_replacement",
            )
            later_subscription = _stripe_subscription(
                price_id="price_test_plan_specialist_month",
                interval="month",
                current_period_end=later_period_end,
                schedule_id="sub_sched_replacement",
            )
            mock_stripe.Subscription.retrieve.side_effect = [
                current_subscription,
                current_subscription,
                current_subscription,
                later_subscription,
            ]
            mock_stripe.SubscriptionSchedule.retrieve.side_effect = [
                old_month,
                old_year,
                old_year,
                old_year_later_boundary,
            ]
            mock_stripe.SubscriptionSchedule.modify.side_effect = [
                _configured_schedule("sub_sched_replacement"),
                _configured_schedule("sub_sched_replacement"),
                _configured_schedule("sub_sched_replacement"),
                _configured_schedule(
                    "sub_sched_replacement",
                    period_end=later_period_end,
                ),
            ]
            mock_stripe.error.StripeError = Exception

            execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )
            set_previous_pending("year")
            execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )
            set_previous_pending("year")
            execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )
            set_previous_pending(
                "year",
                pending_effective_at=later_effective_at,
            )
            execute_plan_change(
                http_request=None,
                request=request,
                user=user,
                db=fake_db,
            )

        modify_keys = [
            call.kwargs["idempotency_key"]
            for call in mock_stripe.SubscriptionSchedule.modify.call_args_list
        ]
        assert len(modify_keys) == 4
        assert modify_keys[0] != modify_keys[1]
        assert modify_keys[1] == modify_keys[2]
        assert modify_keys[2] != modify_keys[3]
        mock_stripe.SubscriptionSchedule.create.assert_not_called()
        mock_stripe.Subscription.modify.assert_not_called()
        assert fake_db.commit.call_count == 4

    def test_execute_same_plan_returns_400(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_specialist")
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        with pytest.raises(HTTPException) as exc_info:
            execute_plan_change(http_request=None, request=req, user=user, db=None)
        assert exc_info.value.status_code == 400

    def test_execute_no_stripe_sub_returns_400(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard", stripe_sub_id=None)
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        with pytest.raises(HTTPException) as exc_info:
            execute_plan_change(http_request=None, request=req, user=user, db=None)
        assert exc_info.value.status_code == 400

    def test_stripe_failure_preserves_active_plan_change_state(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)
        user = _make_user(
            plan_type="plan_standard",
            billing_interval="month",
        )
        _patch_subscription_lock(monkeypatch, user)
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="year")
        active_state = (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        )
        pending_state = _pending_state(user.subscription)
        fake_db = MagicMock()

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.error.StripeError = Exception
            mock_stripe.Subscription.retrieve.return_value = _stripe_subscription(
                price_id="price_test_plan_standard_month",
                interval="month",
            )
            mock_stripe.Subscription.modify.side_effect = Exception("Stripe error")

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(http_request=None, request=req, user=user, db=fake_db)

        assert exc_info.value.status_code == 502
        assert (
            user.subscription.plan_type,
            user.subscription.billing_interval,
            user.subscription.status,
        ) == active_state
        assert _pending_state(user.subscription) == pending_state
        fake_db.commit.assert_not_called()

    def test_execute_stripe_failure_returns_502(self, monkeypatch):
        from billing.router import UpgradeRequest, execute_plan_change
        from billing import Plan
        from fastapi import HTTPException

        _patch_config(monkeypatch)
        _patch_portal_check(monkeypatch)

        user = _make_user(plan_type="plan_standard")
        req = UpgradeRequest(target_plan=Plan.SPECIALIST, billing_interval="month")

        with patch("billing.router.stripe") as mock_stripe:
            mock_stripe.error.StripeError = Exception
            mock_stripe.Subscription.retrieve.return_value = {"items": {"data": [{"id": "si_123"}]}}
            mock_stripe.Subscription.modify.side_effect = Exception("Stripe error")

            with pytest.raises(HTTPException) as exc_info:
                execute_plan_change(http_request=None, request=req, user=user, db=None)
            assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Plan weight ordering sanity
# ---------------------------------------------------------------------------


class TestPlanWeightOrdering:
    def test_upgrade_direction_detection(self):
        assert get_plan_weight("plan_specialist") > get_plan_weight("plan_standard")
        assert get_plan_weight("plan_executive") > get_plan_weight("plan_specialist")

    def test_downgrade_direction_detection(self):
        assert get_plan_weight("plan_standard") < get_plan_weight("plan_specialist")


# ---------------------------------------------------------------------------
# Request-validation error shape on the plan-change routes (SIGV2-1172)
# ---------------------------------------------------------------------------

UPGRADE_PREVIEW_URL = "/api/v1/billing/upgrade-preview"
CHECKOUT_SESSION_URL = "/api/v1/billing/checkout-session"


@pytest.fixture
def plan_change_http_ctx(monkeypatch):
    """TestClient over the real app so FastAPI request validation runs, with
    auth/db/middleware neutralised; the tests only ever reach the validation
    handler, never the endpoint body."""

    async def noop_tenant_resolver(request, call_next):
        return await call_next(request)

    def override_get_db():
        yield None

    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = lambda: _make_user()

    client = TestClient(main.app)
    yield client

    main.app.dependency_overrides.clear()


class TestPlanChangeValidationErrors:
    def test_invalid_billing_interval_returns_named_code(self, plan_change_http_ctx):
        resp = plan_change_http_ctx.post(
            UPGRADE_PREVIEW_URL,
            json={"target_plan": "plan_specialist", "billing_interval": "quarterly"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "INVALID_BILLING_INTERVAL"
        assert detail["message"]

    def test_invalid_target_plan_returns_named_code(self, plan_change_http_ctx):
        resp = plan_change_http_ctx.post(
            UPGRADE_PREVIEW_URL,
            json={"target_plan": "plan_made_up", "billing_interval": "month"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "INVALID_TARGET_PLAN"
        assert detail["message"]

    def test_missing_fields_returns_generic_code(self, plan_change_http_ctx):
        resp = plan_change_http_ctx.post(UPGRADE_PREVIEW_URL, json={})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "INVALID_PLAN_CHANGE_REQUEST"
        assert detail["message"]

    def test_upgrade_route_shares_the_shape(self, plan_change_http_ctx):
        resp = plan_change_http_ctx.post(
            "/api/v1/billing/upgrade",
            json={"target_plan": "plan_specialist", "billing_interval": "weekly"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "INVALID_BILLING_INTERVAL"

    def test_unrelated_route_keeps_default_list_detail(self, plan_change_http_ctx):
        resp = plan_change_http_ctx.post(CHECKOUT_SESSION_URL, json={})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert detail and detail[0]["loc"] == ["body", "plan"]
