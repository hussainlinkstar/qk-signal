import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import (
    PRIVATE_PLAN_IDS,
    UNPUBLISHED_CAPABILITY_KEYS,
    build_plan_feature_list,
    get_plan_monthly_price_usd,
)
from billing.router import list_plans
from services.public_plan_catalog import WITHHELD_PUBLIC_CAPABILITY_KEYS


class _FakeConfig:
    def price_id_for(self, plan, interval: str = "month") -> str:
        return f"price_{plan.value}"


class _PartialConfig:
    def price_id_for(self, plan, interval: str = "month") -> str:
        if plan.value == "plan_executive":
            return ""
        return f"price_{plan.value}"


def test_build_plan_feature_list_uses_canonical_entitlements() -> None:
    neural_features = build_plan_feature_list("plan_standard")
    pro_features = build_plan_feature_list("plan_specialist")
    elite_features = build_plan_feature_list("plan_executive")

    assert "200 audits/mo" in neural_features
    assert "Up to 1 site" in neural_features
    assert not any("credits" in feature for feature in neural_features)

    assert "800 audits/mo" in pro_features
    assert "Up to 10 sites" in pro_features
    assert not any("credits" in feature for feature in pro_features)

    # Executive states its scan allowance and then Jake's bespoke consultancy
    # copy (SIGV2-1211). "Unlimited sites" is no longer among its
    # highlights: the three derived lines that followed the allowance were
    # replaced wholesale, which is the point, because two of them
    # ("Multiple workspaces", "White-label delivery") were
    # read off capability keys the product now offers as custom build work.
    # The site allowance is still stated on the card's own metrics block and
    # in the comparison table, and still enforced.
    assert "2000 audits/mo" in elite_features
    assert "Agent deployment and hosting" in elite_features
    assert not any("white-label" in feature.lower() for feature in elite_features)
    assert not any("credits" in feature for feature in elite_features)


def test_get_plan_monthly_price_usd_uses_canonical_pricing_only() -> None:
    # The internal list price, which MRR and the Stripe catalogue read. The
    # customer-facing withholding of Executive's figure lives in
    # get_plan_catalog_entry, not here (SIGV2-1211).
    assert get_plan_monthly_price_usd("plan_standard") == 49
    assert get_plan_monthly_price_usd("plan_specialist") == 99
    assert get_plan_monthly_price_usd("plan_executive") == 999
    assert get_plan_monthly_price_usd("starter") == 0
    assert get_plan_monthly_price_usd("pro") == 0
    assert get_plan_monthly_price_usd("enterprise") == 0
    assert get_plan_monthly_price_usd("agency") == 0
    assert get_plan_monthly_price_usd("unknown") == 0


def test_list_plans_returns_plan_catalog_details(monkeypatch) -> None:
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            plan_type="plan_specialist",
            status="active",
            stripe_customer_id="cus_123",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)

    assert payload["current_plan"] == "plan_specialist"
    assert payload["status"] == "active"
    assert payload["portal_available"] is True

    plans_by_id = {plan["id"]: plan for plan in payload["plans"]}
    assert plans_by_id["plan_standard"]["features"][0] == "200 audits/mo"
    assert plans_by_id["plan_specialist"]["features"][0] == "800 audits/mo"
    assert plans_by_id["plan_executive"]["features"][0] == "2000 audits/mo"
    assert plans_by_id["plan_executive"]["capabilities"]["max_audits"] == 2000
    assert set(plans_by_id) == {
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    }
    assert "plan_agency_trial" not in plans_by_id
    assert not set(plans_by_id) & PRIVATE_PLAN_IDS


def test_list_plans_hides_private_capabilities_from_customer_surface(monkeypatch) -> None:
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    withdrawn = UNPUBLISHED_CAPABILITY_KEYS | WITHHELD_PUBLIC_CAPABILITY_KEYS

    for plan in payload["plans"]:
        assert isinstance(plan.get("capabilities"), dict)
        for key in plan["capabilities"]:
            assert key not in withdrawn, f"{plan['id']} exposes withdrawn capability {key}"


def test_list_plans_does_not_normalize_legacy_aliases_and_marks_portal_unavailable(
    monkeypatch,
) -> None:
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            plan_type="enterprise",
            status="active",
            stripe_customer_id="",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)

    assert payload["current_plan"] is None
    assert payload["portal_available"] is False


def test_list_plans_does_not_normalize_agency_alias_to_a_paid_plan(monkeypatch) -> None:
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            plan_type="agency",
            status="active",
            stripe_customer_id="cus_agency",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)

    assert payload["current_plan"] is None


def test_list_plans_exposes_checkout_availability_from_price_configuration(monkeypatch) -> None:
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _PartialConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    plans_by_id = {plan["id"]: plan for plan in payload["plans"]}

    assert plans_by_id["plan_standard"]["checkout_available"] is True
    assert plans_by_id["plan_specialist"]["checkout_available"] is True
    assert plans_by_id["plan_executive"]["checkout_available"] is False
    assert plans_by_id["plan_executive"]["price_id"] == ""
