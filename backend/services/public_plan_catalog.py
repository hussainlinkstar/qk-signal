"""Plan catalog projection served to the unauthenticated marketing pricing page.

The marketing site (a separate app, cross origin in preprod) reads this instead
of hardcoding prices, so the payload has to be a deliberate public contract
rather than whatever the internal catalog happens to contain.

Design constraints, because the surface is public, unauthenticated and cacheable:

* Output allowlist: fields are projected one by one through
  ``PUBLIC_PLAN_FIELDS``. The internal ``capabilities`` matrix (48 gating flags,
  several of which describe unshipped work) and the Stripe-configuration derived
  ``checkout_available`` flags are never exposed. Nothing is spread from the
  catalog entry, so a later catalog addition cannot leak by accident.
* Entitlements are published as a separate, deliberately curated
  ``features_matrix`` (SIGV2-1107): one row per capability the site may state,
  carrying the minimum plan that includes it and customer-facing copy. It is
  not the capability matrix with a nicer name: internal keys, anything
  credit-denominated and the capabilities withdrawn from customer surfaces are
  excluded, and a capability with no curated label is dropped rather than
  labelled from its flag name.
* Private plans are excluded through ``PRIVATE_PLAN_IDS``.
* No database access: the payload is built from in-process plan configuration,
  so an anonymous request cannot cause a DB read or a Stripe config load.
* Cached: one payload per TTL is shared across processes through Redis, with an
  in-process fallback, following ``services/serpapi_health.py``. A Redis outage
  degrades to the local cache and then to a local rebuild; it can neither
  amplify load nor fail the request.
* Never stale: the cache key ends in a fingerprint of the plan configuration
  that produced the payload, so a build with a different price reads a
  different key instead of inheriting the old answer. The TTL therefore only
  caps how long one copy lives, it is not a price staleness window.
* Poisoning resistant: the cache key carries no request input, and a cached
  entry is discarded unless its shape still matches the field allowlist and the
  expected plan set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Final

from app.config.plans import (
    CAPABILITY_DESCRIPTIONS,
    INTERNAL_CAPABILITY_KEYS,
    UNPUBLISHED_CAPABILITY_KEYS,
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    PUBLIC_PLAN_TYPES,
    build_plan_feature_list,
    can_use_feature,
    get_plan_capabilities,
    get_plan_catalog_entry,
    get_plan_weight,
    is_custom_priced,
)
from billing.config import ANNUAL_DISCOUNT_PCT
from core.config import settings
from core.redis_client import get_async_redis

logger = logging.getLogger(__name__)


# Every field an anonymous pricing card is allowed to see, and nothing else.
#
# ``has_custom_pricing`` and ``cta`` were added by SIGV2-1211 so a negotiated
# plan can be published as "Contact Us" rather than as a figure. The field
# name is deliberate rather than tidy: the marketing site already recognises
# ``has_custom_pricing`` in its own custom-pricing key list and already
# renders "Custom" with a contact CTA when it sees it alongside a null amount,
# so Executive reads correctly on qiko.ai with no change needed in that repo.
PUBLIC_PLAN_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "description",
    "highlight",
    "color",
    "monthly_price_usd",
    "annual_price_usd",
    "has_custom_pricing",
    "cta",
    "max_sites",
    "max_audits",
    "features",
)
PUBLIC_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "plans",
    "annual_discount_pct",
    "features_matrix",
    "catalog_version",
)
# Every field a published entitlement row is allowed to carry.
PUBLIC_FEATURE_MATRIX_FIELDS: Final[tuple[str, ...]] = ("key", "label", "min_plan_id")

# Capabilities withheld from the published entitlement matrix because the
# product stopped offering them to customers, not because they are unlabelled.
#
# Jake withdrew these four from the in-app plan comparison on 6 Oct
# (SIGV2-1167) as not offered or not yet active. Publishing them on the
# marketing site while the app has stopped advertising them would make the
# website contradict the product, and a prospect is the person least able to
# check the claim.
#
# This is a publishing decision for this endpoint only. All four are still live
# entitlement gates (SIGV2-1168): the keys stay in ``CAPABILITY_MATRIX``, stay
# in ``MINIMUM_PLAN_BY_FEATURE``, and keep granting exactly what they granted.
WITHHELD_PUBLIC_CAPABILITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "can_use_slack_integration",
        "can_use_teams_integration",
        "has_dedicated_strategist",
        "has_done_for_you_execution",
    }
)

# Public copy overrides for rows whose CAPABILITY_DESCRIPTIONS entry is written
# for an admin audience and leaks implementation detail a prospect should never
# see. ``has_live_engine_tracking``'s admin label names the vendor that carries
# the measurement ("via OpenRouter"); the public row states the capability only.
# Membership here changes copy only: the row still has to pass
# ``_is_publishable_capability``.
PUBLIC_CAPABILITY_LABEL_OVERRIDES: Final[dict[str, str]] = {
    "has_live_engine_tracking": "Live engine visibility tracking",
}

# The catalog changes only on deploy, and the fingerprint in the cache key
# means a build with different prices cannot read the previous build's entry,
# so this TTL is not a price staleness window: it only caps how long one copy
# lives. Five minutes is also what the endpoint advertises to browsers and
# CDNs, which is short enough that a visitor cannot be quoted a materially old
# price and long enough to collapse a burst of pricing-page traffic.
PUBLIC_PLAN_CATALOG_TTL_SECONDS: Final[int] = 300
_CACHE_KEY_PREFIX: Final[str] = "public_plan_catalog:v1:"
_REDIS_SOCKET_TIMEOUT: Final[float] = 1.0

# Per-IP ceiling for the unauthenticated endpoint. A human loading the pricing
# page issues one request; this leaves room for shared egress IPs while still
# bounding a scraper.
_DEFAULT_RATE_LIMIT: Final[int] = 60
_DEFAULT_RATE_WINDOW_SECONDS: Final[int] = 60
RATE_LIMIT_KEY_PREFIX: Final[str] = "plans_public"

_local_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _as_int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _public_plan(plan_id: str) -> dict[str, Any]:
    """Project one catalog entry onto the public field allowlist."""
    entry = get_plan_catalog_entry(plan_id)
    capabilities = get_plan_capabilities(plan_id)
    features = entry.get("features")
    if not isinstance(features, list):
        features = build_plan_feature_list(plan_id)

    # A negotiated plan publishes no figure at all (SIGV2-1211). ``None``
    # rather than ``0``: the marketing site treats a zero amount as free and
    # would advertise the most expensive plan as the cheapest. It falls back
    # to "Custom" when the amount is absent and ``has_custom_pricing`` is set,
    # which is why both travel together.
    custom_priced = is_custom_priced(plan_id)
    monthly_price = None if custom_priced else _as_int(capabilities.get("monthly_price_usd"))

    projected: dict[str, Any] = {
        "id": plan_id,
        "name": str(entry.get("name") or ""),
        "description": str(entry.get("description") or ""),
        "highlight": str(entry.get("highlight") or ""),
        "color": str(entry.get("color") or ""),
        "monthly_price_usd": monthly_price,
        "annual_price_usd": _as_optional_float(entry.get("annual_price_usd")),
        "has_custom_pricing": custom_priced,
        "cta": str(entry.get("cta") or ""),
        "max_sites": _as_int(capabilities.get("max_sites")),
        "max_audits": _as_int(capabilities.get("max_audits")),
        "features": [str(feature) for feature in features],
    }
    # Explicit projection: only allowlisted keys survive, in a stable order.
    return {field: projected[field] for field in PUBLIC_PLAN_FIELDS}


def _plans_in_entitlement_order() -> tuple[str, ...]:
    """Public plans cheapest first, by plan weight rather than dict order.

    The payload publishes a minimum plan id, so a consumer resolves a row by
    position in this ladder. Sorting by ``get_plan_weight`` keeps the published
    order and the entitlement comparison the same thing.
    """
    return tuple(sorted(PUBLIC_PLAN_TYPES, key=get_plan_weight))


def _is_publishable_capability(key: str) -> bool:
    """Whether a capability key may be stated on the public pricing surface."""
    # Internal accounting keys. SIGV2-1149 removed ``credits_per_month`` from
    # this exact payload because credits are the internal cost unit and
    # customers are never told about them; scans are what they are told.
    if key in INTERNAL_CAPABILITY_KEYS:
        return False
    # Belt and braces over the line above: a credit quantity under any other
    # spelling is refused too, so a new key cannot reach the pricing page in
    # the window before someone remembers to declare it internal.
    if "credit" in key.lower():
        return False
    # Withdrawn from customer surfaces (SIGV2-1167). Entitlement gates are
    # unaffected, see ``WITHHELD_PUBLIC_CAPABILITY_KEYS``.
    if key in WITHHELD_PUBLIC_CAPABILITY_KEYS:
        return False
    # Not an offerable MVP feature at all (SIGV2-1206): CMS push, the lead
    # widget, the standalone entity-authority offer, and the Coming Soon
    # workflow automation flag and quota.
    if key in UNPUBLISHED_CAPABILITY_KEYS:
        return False
    # No curated description means no customer-facing copy exists, and a
    # titled flag name is not copy, so the row is dropped rather than
    # invented.
    if key not in CAPABILITY_DESCRIPTIONS:
        return False
    return True


def _minimum_public_plan_for(key: str) -> str | None:
    """Cheapest public plan whose entitlement actually includes ``key``.

    Resolved through ``can_use_feature``, which reads
    ``MINIMUM_PLAN_BY_FEATURE`` and the plan weights, so a published row cannot
    state something the runtime gate would refuse. ``None`` means no public
    plan has it, which is true of the matrix flags describing unshipped work.

    A plan's ``features`` array must never be used for this. Those are
    marketing highlights: Specialist's omits PDF reports while the gate grants
    them from Starter, so inferring absence from it would publish the opposite
    of the truth (SIGV2-1107).
    """
    for plan_id in _plans_in_entitlement_order():
        if can_use_feature(plan_id, key):
            return plan_id
    return None


def build_public_features_matrix() -> list[dict[str, str]]:
    """Build the published entitlement matrix. Pure, no I/O."""
    matrix: list[dict[str, str]] = []
    for key in sorted(MINIMUM_PLAN_BY_FEATURE):
        if not _is_publishable_capability(key):
            continue
        # Overrides first (admin copy that names internals), then the curated
        # description map. _is_publishable_capability already required
        # membership, so the titled-key fallback in
        # customer_facing_capability_label can never produce this row's copy.
        label = PUBLIC_CAPABILITY_LABEL_OVERRIDES.get(key) or CAPABILITY_DESCRIPTIONS[key]
        # No customer-facing label means no customer-facing copy exists, and
        # an internal flag name is not copy, so the row is dropped rather than
        # invented.
        if not label:
            continue
        min_plan_id = _minimum_public_plan_for(key)
        if min_plan_id is None:
            continue
        row = {"key": key, "label": label, "min_plan_id": min_plan_id}
        # Explicit projection, same discipline as the plan fields above.
        matrix.append({field: row[field] for field in PUBLIC_FEATURE_MATRIX_FIELDS})
    return matrix


def catalog_version() -> str:
    """Fingerprint of every input that determines the public payload.

    It goes into the cache key, so an entry written by a build with different
    prices, plans, published fields or entitlements is unreachable rather than
    stale. It is computed from configuration only, never from request data.

    The entitlement matrix is folded in whole rather than by name: that is what
    makes a moved minimum plan, a reworded label, a new exclusion, and the
    addition of the field itself all produce a different key. Building it is
    pure dictionary work on in-process configuration.
    """
    canonical = json.dumps(
        {
            "capabilities": {plan: get_plan_capabilities(plan) for plan in PUBLIC_PLAN_TYPES},
            "presentation": {plan: PLAN_PRESENTATION.get(plan, {}) for plan in PUBLIC_PLAN_TYPES},
            "annual_discount_pct": int(ANNUAL_DISCOUNT_PCT),
            "fields": PUBLIC_PLAN_FIELDS,
            "payload_fields": PUBLIC_PAYLOAD_FIELDS,
            "features_matrix": build_public_features_matrix(),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_public_plan_catalog() -> dict[str, Any]:
    """Build the public payload from local configuration. No I/O, never raises."""
    payload: dict[str, Any] = {
        "plans": [_public_plan(plan_id) for plan_id in _plans_in_entitlement_order()],
        "annual_discount_pct": int(ANNUAL_DISCOUNT_PCT),
        "features_matrix": build_public_features_matrix(),
        "catalog_version": catalog_version(),
    }
    # Explicit projection: only allowlisted keys survive, in a stable order.
    return {field: payload[field] for field in PUBLIC_PAYLOAD_FIELDS}


def _validate_cached_payload(cached: Any, version: str) -> dict[str, Any] | None:
    """Accept a cached payload only if it still matches the public contract.

    Redis is shared infrastructure, so a cached value is treated as untrusted
    input: an off-contract shape, an unexpected plan set, or a version that
    does not belong to this build discards the entry instead of publishing it.
    """
    if not isinstance(cached, dict):
        return None
    if tuple(cached.keys()) != PUBLIC_PAYLOAD_FIELDS:
        return None
    if cached.get("catalog_version") != version:
        return None
    expected_plans = _plans_in_entitlement_order()
    plans = cached.get("plans")
    if not isinstance(plans, list) or len(plans) != len(expected_plans):
        return None
    for plan, expected_id in zip(plans, expected_plans):
        if not isinstance(plan, dict) or tuple(plan.keys()) != PUBLIC_PLAN_FIELDS:
            return None
        if plan.get("id") != expected_id:
            return None
    if not isinstance(cached.get("annual_discount_pct"), int):
        return None
    # Stricter than the fields above on purpose: an entitlement row is a public
    # claim about what a plan includes, and rebuilding it is pure in-process
    # work, so there is no reason to trust a cached copy of it at all. A
    # crafted row (an invented minimum plan, a reinstated withdrawn feature, a
    # credit unit) is discarded even when it arrives under the current version.
    if cached.get("features_matrix") != build_public_features_matrix():
        return None
    return cached


def _read_local_cache(version: str) -> dict[str, Any] | None:
    entry = _local_cache.get(version)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at <= time.monotonic():
        _local_cache.pop(version, None)
        return None
    return payload


def _write_local_cache(version: str, payload: dict[str, Any]) -> None:
    # Only the current configuration is ever of interest, so the cache is reset
    # instead of accumulating an entry per historical version.
    _local_cache.clear()
    _local_cache[version] = (time.monotonic() + PUBLIC_PLAN_CATALOG_TTL_SECONDS, payload)


async def _read_shared_cache(version: str) -> dict[str, Any] | None:
    try:
        async with get_async_redis(
            socket_timeout=_REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
        ) as redis_client:
            raw = await redis_client.get(f"{_CACHE_KEY_PREFIX}{version}")
    except Exception:
        logger.debug("public plan catalog: shared cache read failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        cached = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return _validate_cached_payload(cached, version)


async def _write_shared_cache(version: str, payload: dict[str, Any]) -> None:
    try:
        async with get_async_redis(
            socket_timeout=_REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
        ) as redis_client:
            await redis_client.set(
                f"{_CACHE_KEY_PREFIX}{version}",
                json.dumps(payload),
                ex=PUBLIC_PLAN_CATALOG_TTL_SECONDS,
            )
    except Exception:
        logger.debug("public plan catalog: shared cache write failed", exc_info=True)


async def get_public_plan_catalog() -> dict[str, Any]:
    """Return the cached public plan payload, rebuilding it when needed."""
    version = catalog_version()

    cached = _read_local_cache(version)
    if cached is not None:
        return cached

    cached = await _read_shared_cache(version)
    if cached is not None:
        _write_local_cache(version, cached)
        return cached

    payload = build_public_plan_catalog()
    _write_local_cache(version, payload)
    await _write_shared_cache(version, payload)
    return payload


def reset_public_plan_catalog_cache() -> None:
    """Drop the in-process copy. Used by tests and by admin cache refresh."""
    _local_cache.clear()


async def enforce_public_plan_catalog_rate_limit(request: Any) -> None:
    """Apply the shared IP rate limiter under this endpoint's own key prefix."""
    # Imported lazily: the limiter lives in the audit router, and the billing
    # router must not depend on that module at import time.
    from routers.api_router import (
        _resolve_client_ip,
        enforce_rate_limit,
        parse_rate_limit_config,
    )

    configured_limit, configured_window = parse_rate_limit_config(
        getattr(settings, "RATE_LIMIT_PLANS_PUBLIC", None),
        default_limit=_DEFAULT_RATE_LIMIT,
        default_window_seconds=_DEFAULT_RATE_WINDOW_SECONDS,
    )
    await enforce_rate_limit(
        key_prefix=RATE_LIMIT_KEY_PREFIX,
        identifier=_resolve_client_ip(request),
        limit=configured_limit,
        window_seconds=configured_window,
        too_many_requests_detail="Too Many Requests",
    )
