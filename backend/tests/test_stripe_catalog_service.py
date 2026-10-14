import sys
from pathlib import Path

import stripe

sys.path.append(str(Path(__file__).resolve().parents[1]))

from billing.config import ANNUAL_DISCOUNT_PCT
from services import stripe_catalog_service


def _install_fake_stripe(
    monkeypatch,
    *,
    products: list[dict[str, object]] | None = None,
    prices: list[dict[str, object]] | None = None,
    missing_price_ids: set[str] | None = None,
):
    state = {
        "products": {str(item["id"]): dict(item) for item in (products or [])},
        "prices": {str(item["id"]): dict(item) for item in (prices or [])},
        "calls": {
            "product_create": [],
            "price_create": [],
            "price_retrieve": [],
        },
    }
    missing_ids = set(missing_price_ids or set())

    def product_list(**_kwargs):
        return {"data": list(state["products"].values())}

    def product_create(**kwargs):
        product_id = f"prod_auto_{len(state['products']) + 1}"
        product = {
            "id": product_id,
            "name": kwargs["name"],
            "metadata": dict(kwargs["metadata"]),
            "active": True,
        }
        state["products"][product_id] = product
        state["calls"]["product_create"].append(kwargs)
        return product

    def price_list(*, product, **_kwargs):
        return {
            "data": [
                dict(item)
                for item in state["prices"].values()
                if item.get("product") == product and item.get("active", True)
            ]
        }

    def price_create(**kwargs):
        price_id = f"price_auto_{len(state['prices']) + 1}"
        price = {
            "id": price_id,
            "product": kwargs["product"],
            "currency": kwargs["currency"],
            "unit_amount": kwargs["unit_amount"],
            "recurring": dict(kwargs["recurring"]),
            "billing_scheme": kwargs.get("billing_scheme", "per_unit"),
            "metadata": dict(kwargs.get("metadata", {})),
            "active": True,
        }
        state["prices"][price_id] = price
        state["calls"]["price_create"].append(kwargs)
        return price

    def price_retrieve(price_id, **kwargs):
        state["calls"]["price_retrieve"].append({"price_id": price_id, **kwargs})
        if price_id in missing_ids or price_id not in state["prices"]:
            error = stripe.error.InvalidRequestError("No such price", param="price")
            error.code = "resource_missing"
            raise error

        price = dict(state["prices"][price_id])
        if "product" in kwargs.get("expand", []):
            price["product"] = dict(state["products"][str(price["product"])])
        return price

    monkeypatch.setattr(stripe_catalog_service.stripe.Product, "list", product_list)
    monkeypatch.setattr(stripe_catalog_service.stripe.Product, "create", product_create)
    monkeypatch.setattr(stripe_catalog_service.stripe.Price, "list", price_list)
    monkeypatch.setattr(stripe_catalog_service.stripe.Price, "create", price_create)
    monkeypatch.setattr(stripe_catalog_service.stripe.Price, "retrieve", price_retrieve)
    return state


def _managed_price_id(definition) -> str:
    if definition.kind == "plan_annual":
        return f"price_{definition.key}_annual"
    return f"price_{definition.key}"


def _build_managed_plan_catalog_state():
    products: list[dict[str, object]] = []
    prices: list[dict[str, object]] = []
    for definition in stripe_catalog_service._catalog_definitions("plans"):
        product_id = f"prod_{definition.key}"
        # Monthly and annual share one managed product per plan, as in Stripe.
        if not any(product["id"] == product_id for product in products):
            products.append(
                {
                    "id": product_id,
                    "name": definition.product_name,
                    "metadata": dict(definition.product_metadata),
                    "active": True,
                }
            )
        prices.append(
            {
                "id": _managed_price_id(definition),
                "product": product_id,
                "currency": "usd",
                "unit_amount": definition.unit_amount,
                "recurring": dict(definition.recurring),
                "billing_scheme": definition.billing_scheme or "per_unit",
                "active": True,
            }
        )
    return products, prices


def _expected_annual_unit_amount(plan: str) -> int:
    monthly_price_usd = stripe_catalog_service.get_plan_monthly_price_usd(plan)
    return monthly_price_usd * 12 * (100 - ANNUAL_DISCOUNT_PCT)


def test_plan_sync_creates_missing_products_and_prices(monkeypatch) -> None:
    state = _install_fake_stripe(monkeypatch)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="plans",
    )

    assert set(result.plan_price_ids) == {
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    }
    assert len(state["calls"]["product_create"]) == 4
    # Four monthly prices plus one annual price for each of the three paid plans.
    assert len(state["calls"]["price_create"]) == 7
    assert {item["name"] for item in state["calls"]["product_create"]} == {
        "Qiko Signal - Starter",
        "Qiko Signal - Standard",
        "Qiko Signal - Specialist",
        "Qiko Signal - Executive",
    }
    starter_price = state["prices"][result.plan_price_ids["plan_starter"]]
    assert starter_price["unit_amount"] == int(
        stripe_catalog_service.get_plan_monthly_price_usd("plan_starter") * 100
    )
    assert all(item.action == "created" for item in result.items)


def test_plan_sync_reuses_existing_managed_products_and_prices(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    state = _install_fake_stripe(monkeypatch, products=products, prices=prices)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="plans",
    )

    assert set(result.plan_price_ids) == {
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    }
    assert len(state["calls"]["product_create"]) == 0
    assert len(state["calls"]["price_create"]) == 0
    assert all(item.action == "reused" for item in result.items)


def test_commitment_sync_creates_fixed_and_shared_overage_prices(monkeypatch) -> None:
    state = _install_fake_stripe(monkeypatch)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="live",
        scope="commitments",
    )

    assert len(result.commitment_price_ids) == 3
    assert result.commitment_overage_price_id is not None
    assert len(state["calls"]["product_create"]) == 4
    assert len(state["calls"]["price_create"]) == 4


def test_dry_run_performs_no_stripe_writes(monkeypatch) -> None:
    state = _install_fake_stripe(monkeypatch)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="all",
        dry_run=True,
    )

    assert len(state["calls"]["product_create"]) == 0
    assert len(state["calls"]["price_create"]) == 0
    assert not result.plan_price_ids
    assert not result.commitment_price_ids
    assert result.commitment_overage_price_id is None
    assert all(item.action == "warning" for item in result.items)


def test_validate_catalog_returns_valid_for_matching_price_ids(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    _install_fake_stripe(monkeypatch, products=products, prices=prices)

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_starter": "price_plan_starter",
            "plan_agency_trial": "price_plan_agency_trial",
            "plan_standard": "price_plan_standard",
            "plan_specialist": "price_plan_specialist",
            "plan_executive": "price_plan_executive",
        },
        configured_annual_plan_price_ids={
            "plan_standard": "price_plan_standard_annual",
            "plan_specialist": "price_plan_specialist_annual",
            "plan_executive": "price_plan_executive_annual",
        },
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    assert {(item.kind, item.key) for item in results} == {
        ("plan", "plan_starter"),
        ("plan", "plan_standard"),
        ("plan", "plan_specialist"),
        ("plan", "plan_executive"),
        ("plan_annual", "plan_standard"),
        ("plan_annual", "plan_specialist"),
        ("plan_annual", "plan_executive"),
    }
    assert all(item.status == "valid" for item in results)


def test_validate_catalog_returns_missing_for_unknown_price_ids(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    _install_fake_stripe(
        monkeypatch,
        products=products,
        prices=prices,
        missing_price_ids={"price_missing"},
    )

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_standard": "price_missing",
        },
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    statuses = {(item.kind, item.key): item.status for item in results}
    assert statuses[("plan", "plan_standard")] == "missing"
    assert statuses[("plan", "plan_specialist")] == "unconfigured"


def test_validate_catalog_returns_mismatch_for_wrong_price_shape(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    standard_price = next(p for p in prices if p["id"] == "price_plan_standard")
    standard_price["unit_amount"] = 12345
    _install_fake_stripe(monkeypatch, products=products, prices=prices)

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_standard": "price_plan_standard",
        },
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    statuses = {(item.kind, item.key): item.status for item in results}
    assert statuses[("plan", "plan_standard")] == "mismatch"


def test_plan_sync_creates_annual_prices_for_plans_that_offer_them(monkeypatch) -> None:
    state = _install_fake_stripe(monkeypatch)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="plans",
    )

    assert set(result.annual_plan_price_ids) == {
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    }
    standard_annual = state["prices"][result.annual_plan_price_ids["plan_standard"]]
    assert standard_annual["unit_amount"] == _expected_annual_unit_amount("plan_standard")
    assert standard_annual["unit_amount"] == 47040
    assert standard_annual["recurring"]["interval"] == "year"
    specialist_annual = state["prices"][result.annual_plan_price_ids["plan_specialist"]]
    assert specialist_annual["unit_amount"] == 95040
    annual_items = [item for item in result.items if item.kind == "plan_annual"]
    assert {item.key for item in annual_items} == {
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    }
    assert all(item.action == "created" for item in annual_items)


def test_plan_sync_adds_no_annual_price_for_a_free_plan(monkeypatch) -> None:
    _install_fake_stripe(monkeypatch)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="plans",
    )

    assert "plan_starter" not in result.annual_plan_price_ids
    assert not any(
        item.kind == "plan_annual" and item.key == "plan_starter" for item in result.items
    )


def test_plan_sync_repositions_a_wrong_annual_price(monkeypatch) -> None:
    """A deliberately wrong annual price must be corrected, not left alone."""
    products, prices = _build_managed_plan_catalog_state()
    wrong_annual = next(price for price in prices if price["id"] == "price_plan_standard_annual")
    wrong_annual["unit_amount"] = 95040
    state = _install_fake_stripe(monkeypatch, products=products, prices=prices)

    result = stripe_catalog_service.sync_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        scope="plans",
    )

    created_annual = [
        call for call in state["calls"]["price_create"] if call["recurring"]["interval"] == "year"
    ]
    assert len(created_annual) == 1
    assert created_annual[0]["unit_amount"] == _expected_annual_unit_amount("plan_standard")
    corrected_price_id = result.annual_plan_price_ids["plan_standard"]
    assert corrected_price_id != "price_plan_standard_annual"
    assert state["prices"][corrected_price_id]["unit_amount"] == 47040
    assert any("plan_annual:plan_standard" in warning for warning in result.warnings)
    # The monthly price sits on the same product and is still correct.
    assert result.plan_price_ids["plan_standard"] == "price_plan_standard"
    assert not any("plan:plan_standard" in warning for warning in result.warnings)


def test_validate_catalog_flags_a_missing_annual_price(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    _install_fake_stripe(monkeypatch, products=products, prices=prices)

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_standard": "price_plan_standard",
        },
        configured_annual_plan_price_ids={},
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    statuses = {(item.kind, item.key): item.status for item in results}
    assert statuses[("plan", "plan_standard")] == "valid"
    assert statuses[("plan_annual", "plan_standard")] == "unconfigured"
    assert not all(item.status == "valid" for item in results)


def test_validate_catalog_flags_a_mismatched_annual_price(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    drifted_annual = next(price for price in prices if price["id"] == "price_plan_standard_annual")
    drifted_annual["unit_amount"] = 95040
    _install_fake_stripe(monkeypatch, products=products, prices=prices)

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_standard": "price_plan_standard",
        },
        configured_annual_plan_price_ids={
            "plan_standard": "price_plan_standard_annual",
        },
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    statuses = {(item.kind, item.key): item.status for item in results}
    assert statuses[("plan", "plan_standard")] == "valid"
    assert statuses[("plan_annual", "plan_standard")] == "mismatch"
    mismatch = next(
        item for item in results if (item.kind, item.key) == ("plan_annual", "plan_standard")
    )
    assert mismatch.expected["unit_amount"] == _expected_annual_unit_amount("plan_standard")
    assert mismatch.actual["unit_amount"] == 95040


def test_validate_catalog_reports_annual_valid_when_it_matches(monkeypatch) -> None:
    products, prices = _build_managed_plan_catalog_state()
    _install_fake_stripe(monkeypatch, products=products, prices=prices)

    results = stripe_catalog_service.validate_catalog(
        stripe_secret_key="sk_test_catalog",
        mode="test",
        configured_plan_price_ids={
            "plan_standard": "price_plan_standard",
        },
        configured_annual_plan_price_ids={
            "plan_standard": "price_plan_standard_annual",
        },
        configured_commitment_price_ids={},
        configured_commitment_overage_price_id=None,
        scope="plans",
    )

    statuses = {(item.kind, item.key): item.status for item in results}
    assert statuses[("plan_annual", "plan_standard")] == "valid"
