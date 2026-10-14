from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping

import stripe

from app.config.plans import PUBLIC_PLAN_TYPES, get_plan_catalog_entry, get_plan_monthly_price_usd
from billing import BILLING_CURRENCY, CommitmentTier, Plan
from billing.config import ANNUAL_DISCOUNT_PCT
from services.credit_commitment_service import COMMITMENT_TIER_DEFINITIONS


APP_TAG = "thothgraph"
MANAGED_TAG = "auto"

CatalogScope = Literal["plans", "commitments", "all"]
CatalogItemKind = Literal["plan", "plan_annual", "commitment_fixed", "commitment_overage"]
CatalogAction = Literal["reused", "created", "warning", "error"]
ValidationStatus = Literal["valid", "unconfigured", "missing", "mismatch"]


@dataclass(frozen=True)
class StripeCatalogItemResult:
    kind: CatalogItemKind
    key: str
    product_id: str | None
    price_id: str | None
    action: CatalogAction
    message: str | None = None


@dataclass(frozen=True)
class StripeCatalogSyncResult:
    mode: Literal["test", "live"]
    dry_run: bool
    items: list[StripeCatalogItemResult] = field(default_factory=list)
    plan_price_ids: dict[str, str] = field(default_factory=dict)
    annual_plan_price_ids: dict[str, str] = field(default_factory=dict)
    commitment_price_ids: dict[str, str] = field(default_factory=dict)
    commitment_overage_price_id: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StripeCatalogValidationResult:
    kind: CatalogItemKind
    key: str
    configured_price_id: str | None
    status: ValidationStatus
    message: str | None = None
    expected: dict[str, object] = field(default_factory=dict)
    actual: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _CatalogDefinition:
    kind: CatalogItemKind
    key: str
    product_name: str
    product_metadata: dict[str, str]
    unit_amount: int
    recurring: dict[str, str]
    billing_scheme: str | None = None


def sync_catalog(
    *,
    stripe_secret_key: str,
    mode: Literal["test", "live"],
    scope: CatalogScope,
    dry_run: bool = False,
) -> StripeCatalogSyncResult:
    stripe.api_key = stripe_secret_key
    items: list[StripeCatalogItemResult] = []
    warnings: list[str] = []
    plan_price_ids: dict[str, str] = {}
    annual_plan_price_ids: dict[str, str] = {}
    commitment_price_ids: dict[str, str] = {}
    commitment_overage_price_id: str | None = None
    managed_products = _list_products()

    for definition in _catalog_definitions(scope):
        product = _find_managed_product(managed_products, definition)
        product_id = _string_value((product or {}).get("id"))
        product_created = False
        product_missing = product is None

        if product_missing and dry_run:
            items.append(
                StripeCatalogItemResult(
                    kind=definition.kind,
                    key=definition.key,
                    product_id=None,
                    price_id=None,
                    action="warning",
                    message="Dry run: managed product and price would be created.",
                )
            )
            continue

        if product_missing:
            product = _create_product(definition)
            product_id = _string_value(product.get("id"))
            managed_products.append(product)
            product_created = True

        prices = _list_prices_for_product(product_id or "")
        matching_price, stale_prices = _find_matching_price(prices, definition)
        price_id = _string_value((matching_price or {}).get("id"))
        action: CatalogAction
        message: str | None = None

        if matching_price is not None:
            action = "reused"
            if product_created:
                message = "Created managed product and reused an existing matching managed price."
            else:
                message = "Reused an existing matching managed price."
        elif dry_run:
            action = "warning"
            if stale_prices:
                message = "Dry run: a new canonical price would be created; existing managed prices do not match."
            else:
                message = "Dry run: a new canonical price would be created."
        else:
            created_price = _create_price(definition, product_id or "")
            price_id = _string_value(created_price.get("id"))
            action = "created"
            if stale_prices:
                message = "Created a new canonical price; existing managed prices do not match."
            elif product_created:
                message = "Created managed product and price."
            else:
                message = "Created a new canonical price."

        if stale_prices:
            warnings.append(
                f"{definition.kind}:{definition.key} has {len(stale_prices)} stale managed active price(s)."
            )

        items.append(
            StripeCatalogItemResult(
                kind=definition.kind,
                key=definition.key,
                product_id=product_id,
                price_id=price_id,
                action=action,
                message=message,
            )
        )
        if not price_id:
            continue
        if definition.kind == "plan":
            plan_price_ids[definition.key] = price_id
        elif definition.kind == "plan_annual":
            annual_plan_price_ids[definition.key] = price_id
        elif definition.kind == "commitment_fixed":
            commitment_price_ids[definition.key] = price_id
        else:
            commitment_overage_price_id = price_id

    return StripeCatalogSyncResult(
        mode=mode,
        dry_run=dry_run,
        items=items,
        plan_price_ids=plan_price_ids,
        annual_plan_price_ids=annual_plan_price_ids,
        commitment_price_ids=commitment_price_ids,
        commitment_overage_price_id=commitment_overage_price_id,
        warnings=warnings,
    )


def validate_catalog(
    *,
    stripe_secret_key: str,
    mode: Literal["test", "live"],
    configured_plan_price_ids: dict[str, str | None],
    configured_commitment_price_ids: dict[str, str | None],
    configured_commitment_overage_price_id: str | None,
    scope: CatalogScope,
    configured_annual_plan_price_ids: dict[str, str | None] | None = None,
) -> list[StripeCatalogValidationResult]:
    stripe.api_key = stripe_secret_key
    results: list[StripeCatalogValidationResult] = []
    annual_price_ids = configured_annual_plan_price_ids or {}

    configured_ids = {
        "plan": {plan.value: configured_plan_price_ids.get(plan.value) for plan in Plan},
        "plan_annual": {plan.value: annual_price_ids.get(plan.value) for plan in Plan},
        "commitment_fixed": {
            tier.value: configured_commitment_price_ids.get(tier.value) for tier in CommitmentTier
        },
        "commitment_overage": {
            "shared": configured_commitment_overage_price_id,
        },
    }

    for definition in _catalog_definitions(scope):
        configured_price_id = _string_value(
            configured_ids.get(definition.kind, {}).get(definition.key)
        )
        expected = _build_expected_shape(definition)
        if not configured_price_id:
            results.append(
                StripeCatalogValidationResult(
                    kind=definition.kind,
                    key=definition.key,
                    configured_price_id=None,
                    status="unconfigured",
                    message=f"No configured price ID for {mode} mode.",
                    expected=expected,
                )
            )
            continue

        try:
            price = _to_mapping(stripe.Price.retrieve(configured_price_id, expand=["product"]))
        except stripe.error.InvalidRequestError as exc:
            if not _is_missing_resource_error(exc):
                raise
            results.append(
                StripeCatalogValidationResult(
                    kind=definition.kind,
                    key=definition.key,
                    configured_price_id=configured_price_id,
                    status="missing",
                    message="Configured Stripe price was not found.",
                    expected=expected,
                )
            )
            continue

        actual = _build_actual_shape(price)
        if _price_matches_definition(price, definition):
            status: ValidationStatus = "valid"
            message = "Configured Stripe price matches the canonical catalog definition."
        else:
            status = "mismatch"
            message = "Configured Stripe price does not match the canonical catalog definition."

        results.append(
            StripeCatalogValidationResult(
                kind=definition.kind,
                key=definition.key,
                configured_price_id=configured_price_id,
                status=status,
                message=message,
                expected=expected,
                actual=actual,
            )
        )

    return results


def _catalog_definitions(scope: CatalogScope) -> list[_CatalogDefinition]:
    definitions: list[_CatalogDefinition] = []
    if scope in {"plans", "all"}:
        for plan_type in PUBLIC_PLAN_TYPES:
            entry = get_plan_catalog_entry(plan_type)
            product_name = f"Qiko Signal - {entry['name']}"
            product_metadata = _build_product_metadata("plan", plan_type)
            monthly_price_usd = get_plan_monthly_price_usd(plan_type)
            definitions.append(
                _CatalogDefinition(
                    kind="plan",
                    key=plan_type,
                    product_name=product_name,
                    product_metadata=product_metadata,
                    unit_amount=int(monthly_price_usd * 100),
                    recurring={"interval": "month", "usage_type": "licensed"},
                )
            )
            annual_unit_amount = _annual_unit_amount(monthly_price_usd)
            if annual_unit_amount <= 0:
                # A free plan has no annual option to drift out of step.
                continue
            # Both intervals hang off the one managed product per plan, so the
            # annual definition reuses the monthly product name and metadata.
            definitions.append(
                _CatalogDefinition(
                    kind="plan_annual",
                    key=plan_type,
                    product_name=product_name,
                    product_metadata=product_metadata,
                    unit_amount=annual_unit_amount,
                    recurring={"interval": "year", "usage_type": "licensed"},
                )
            )

    if scope in {"commitments", "all"}:
        for tier in CommitmentTier:
            tier_definition = COMMITMENT_TIER_DEFINITIONS[tier]
            definitions.append(
                _CatalogDefinition(
                    kind="commitment_fixed",
                    key=tier.value,
                    product_name=f"Qiko Signal - Credit Commitment ({tier_definition.label})",
                    product_metadata=_build_product_metadata("commitment", tier.value),
                    unit_amount=_decimal_to_cents(tier_definition.monthly_fee_usd),
                    recurring={"interval": "month", "usage_type": "licensed"},
                )
            )
        definitions.append(
            _CatalogDefinition(
                kind="commitment_overage",
                key="shared",
                product_name="Qiko Signal - Credit Commitment Overage",
                product_metadata=_build_product_metadata("commitment_overage", "shared"),
                unit_amount=_decimal_to_cents(_resolve_shared_overage_rate()),
                recurring={"interval": "month", "usage_type": "metered"},
                billing_scheme="per_unit",
            )
        )

    return definitions


def _annual_unit_amount(monthly_price_usd: int) -> int:
    """The annual amount in minor units, from the same list price as monthly.

    Derived rather than configured, so the annual interval cannot drift away
    from the catalogue the way a hand-maintained Stripe price did (SIGV2-1261).
    """
    if monthly_price_usd <= 0:
        return 0
    annual_price_usd = (
        Decimal(monthly_price_usd) * Decimal(12) * (Decimal(100) - Decimal(ANNUAL_DISCOUNT_PCT))
    ) / Decimal(100)
    return _decimal_to_cents(annual_price_usd)


def _resolve_shared_overage_rate() -> Decimal:
    rates = {definition.overage_rate for definition in COMMITMENT_TIER_DEFINITIONS.values()}
    if not rates:
        raise RuntimeError("No commitment tiers are configured for Stripe catalog sync.")
    if len(rates) != 1:
        raise RuntimeError("Commitment tiers must share one overage rate for Stripe catalog sync.")
    return next(iter(rates))


def _build_product_metadata(catalog_scope: str, catalog_key: str) -> dict[str, str]:
    return {
        "app": APP_TAG,
        "managed": MANAGED_TAG,
        "catalog_scope": catalog_scope,
        "catalog_key": catalog_key,
    }


def _build_expected_shape(definition: _CatalogDefinition) -> dict[str, object]:
    return {
        "product_name": definition.product_name,
        "product_metadata": dict(definition.product_metadata),
        "currency": BILLING_CURRENCY,
        "unit_amount": definition.unit_amount,
        "recurring": dict(definition.recurring),
        "billing_scheme": definition.billing_scheme or "per_unit",
    }


def _build_actual_shape(price: Mapping[str, Any]) -> dict[str, object]:
    product = _extract_product_mapping(price)
    recurring = _to_mapping(price.get("recurring"))
    return {
        "product_id": _string_value(product.get("id")),
        "product_name": _string_value(product.get("name")),
        "product_metadata": dict(_metadata_mapping(product)),
        "currency": _string_value(price.get("currency")),
        "unit_amount": _normalize_int(price.get("unit_amount")),
        "recurring": {
            "interval": _string_value(recurring.get("interval")),
            "usage_type": _string_value(recurring.get("usage_type")),
        },
        "billing_scheme": _string_value(price.get("billing_scheme")) or "per_unit",
        "active": bool(price.get("active")),
    }


def _list_products() -> list[dict[str, Any]]:
    payload = stripe.Product.list(active=True, limit=100)
    return [_to_plain_mapping(item) for item in _extract_data(payload)]


def _list_prices_for_product(product_id: str) -> list[dict[str, Any]]:
    payload = stripe.Price.list(product=product_id, active=True, limit=100)
    return [_to_plain_mapping(item) for item in _extract_data(payload)]


def _find_managed_product(
    managed_products: list[Mapping[str, Any]],
    definition: _CatalogDefinition,
) -> dict[str, Any] | None:
    for product in managed_products:
        if not _metadata_matches(_metadata_mapping(product), definition.product_metadata):
            continue
        return _to_plain_mapping(product)
    return None


def _find_matching_price(
    prices: list[Mapping[str, Any]],
    definition: _CatalogDefinition,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    stale_prices: list[dict[str, Any]] = []
    matching_price: dict[str, Any] | None = None

    for price in prices:
        price_mapping = _to_plain_mapping(price)
        if _price_shape_matches_definition(price_mapping, definition):
            matching_price = price_mapping
            break
        if not _price_interval_matches_definition(price_mapping, definition):
            # Monthly and annual share one product, so a price on the sibling
            # interval belongs to the sibling definition and is not stale here.
            continue
        stale_prices.append(price_mapping)

    return matching_price, stale_prices


def _price_interval_matches_definition(
    price: Mapping[str, Any],
    definition: _CatalogDefinition,
) -> bool:
    recurring = _to_mapping(price.get("recurring"))
    actual_interval = (_string_value(recurring.get("interval")) or "").lower()
    return actual_interval == definition.recurring["interval"]


def _price_matches_definition(
    price: Mapping[str, Any],
    definition: _CatalogDefinition,
) -> bool:
    product = _extract_product_mapping(price)
    product_metadata = _metadata_mapping(product)
    if not _price_shape_matches_definition(price, definition):
        return False
    if not _metadata_matches(product_metadata, definition.product_metadata):
        return False
    return True


def _price_shape_matches_definition(
    price: Mapping[str, Any],
    definition: _CatalogDefinition,
) -> bool:
    recurring = _to_mapping(price.get("recurring"))
    if not bool(price.get("active")):
        return False
    if (_string_value(price.get("currency")) or "").lower() != BILLING_CURRENCY:
        return False
    if _normalize_int(price.get("unit_amount")) != definition.unit_amount:
        return False
    if (_string_value(recurring.get("interval")) or "").lower() != definition.recurring["interval"]:
        return False
    if (_string_value(recurring.get("usage_type")) or "").lower() != definition.recurring[
        "usage_type"
    ]:
        return False
    actual_billing_scheme = (_string_value(price.get("billing_scheme")) or "per_unit").lower()
    expected_billing_scheme = definition.billing_scheme or "per_unit"
    if actual_billing_scheme != expected_billing_scheme:
        return False
    return True


def _create_product(definition: _CatalogDefinition) -> dict[str, Any]:
    return _to_plain_mapping(
        stripe.Product.create(
            name=definition.product_name,
            metadata=definition.product_metadata,
        )
    )


def _create_price(definition: _CatalogDefinition, product_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product": product_id,
        "currency": BILLING_CURRENCY,
        "unit_amount": definition.unit_amount,
        "recurring": dict(definition.recurring),
        "metadata": dict(definition.product_metadata),
    }
    if definition.billing_scheme:
        payload["billing_scheme"] = definition.billing_scheme
    return _to_plain_mapping(stripe.Price.create(**payload))


def _extract_data(payload: object) -> list[object]:
    mapping = _to_mapping(payload)
    data = mapping.get("data")
    if isinstance(data, list):
        return data
    return []


def _extract_product_mapping(price: Mapping[str, Any]) -> Mapping[str, Any]:
    product = price.get("product")
    return _to_mapping(product)


def _metadata_mapping(value: Mapping[str, Any] | object) -> Mapping[str, Any]:
    mapping = _to_mapping(value)
    metadata = mapping.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _metadata_matches(actual: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
    return all(_string_value(actual.get(key)) == value for key, value in expected.items())


def _to_plain_mapping(value: object) -> dict[str, Any]:
    mapping = _to_mapping(value)
    return {str(key): nested for key, nested in mapping.items()}


def _to_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict_recursive = getattr(value, "to_dict_recursive", None)
    if callable(to_dict_recursive):
        candidate = to_dict_recursive()
        if isinstance(candidate, Mapping):
            return candidate
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        candidate = to_dict()
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def _decimal_to_cents(value: Decimal) -> int:
    return int((value * Decimal("100")).quantize(Decimal("1")))


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_missing_resource_error(error: stripe.error.InvalidRequestError) -> bool:
    return getattr(error, "code", None) == "resource_missing"
