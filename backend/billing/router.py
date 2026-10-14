from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Literal, Mapping
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
import stripe

import models
from app.config.plans import (
    INTERNAL_CAPABILITY_KEYS,
    PRIVATE_PLAN_IDS,
    UNPUBLISHED_CAPABILITY_KEYS,
    diff_capabilities,
    get_plan_catalog_entry,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from services.public_plan_catalog import WITHHELD_PUBLIC_CAPABILITY_KEYS
from auth.security import get_current_user_from_token as get_current_user
from billing import CommitmentTier, Plan, load_billing_config
from billing.base_checkout_service import (
    BaseCheckoutConflictError,
    BaseCheckoutValidationError,
    base_checkout_idempotency_key,
    base_checkout_metadata,
    cancel_untouched_base_checkout_attempt,
    expire_base_checkout_attempt,
    link_base_checkout_customer,
    link_base_checkout_session,
    lock_base_checkout_attempt,
    resolve_base_checkout_attempt,
    stripe_customer_idempotency_key,
    validate_base_checkout_session,
)
from billing.plan_change_service import (
    PlanChangeDecision,
    attach_current_schedule_phase,
    build_downgrade_schedule_spec,
    classify_plan_change,
    downgrade_plan_change_metadata,
    downgrade_schedule_idempotency_key,
    downgrade_schedule_operation_id,
    downgrade_schedule_phases,
    immediate_plan_change_idempotency_key,
    immediate_plan_change_metadata,
    is_configured_downgrade_schedule,
    lock_subscription_for_plan_change,
    pending_plan_change_identity,
    resolve_immediate_plan_change_state,
    schedule_release_idempotency_key,
    set_pending_plan_change,
    stripe_schedule_id,
    validate_configured_downgrade_schedule,
    validate_current_stripe_subscription,
    validate_immediate_plan_change,
    validate_owned_active_schedule,
    validate_pending_schedule,
    validate_plan_change_schedule_owner,
    validate_released_schedule,
)
from database import get_db
from app.i18n import translate_backend_message
from billing.usage_analytics import (
    build_plan_recommendation,
    build_usage_analytics,
    should_show_scan_warning,
)
from core.public_site_cors import apply_public_site_cors
from services.credit_commitment_service import (
    extract_commitment_subscription_items,
    get_active_commitment_cycle,
    get_user_commitment,
    is_commitment_eligible,
    list_commitment_tiers,
    resolve_commitment_lock_reason,
    resolve_commitment_tier_definition,
    resolve_current_plan_type,
    serialize_commitment_status,
)
from services.public_plan_catalog import (
    PUBLIC_PLAN_CATALOG_TTL_SECONDS,
    enforce_public_plan_catalog_rate_limit,
    get_public_plan_catalog,
)
from services.workspace_rbac import require_not_portal_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])
IDEMPOTENCY_BUCKET_SECONDS = 3600

SUPPORTED_BILLING_INTERVALS = ("month", "year")
DEFAULT_BILLING_INTERVAL = "month"


def normalized_billing_interval(sub: Any) -> str:
    """Return a subscription's billing interval coerced to a supported value.

    The `subscriptions.billing_interval` column has no CHECK constraint, so a
    manually created, seeded or legacy row can hold a value the billing API
    never accepts. Serving it verbatim breaks the plan change flow, so an
    unsupported value degrades to the monthly default and is logged with the
    subscription id to make the offending row findable.
    """
    if sub is None:
        return DEFAULT_BILLING_INTERVAL
    stored = getattr(sub, "billing_interval", None)
    if stored in SUPPORTED_BILLING_INTERVALS:
        return stored
    logger.warning(
        "Unsupported subscription billing interval: subscription_id=%s stored=%r "
        "normalized=%s code=billing_interval_normalized",
        getattr(sub, "id", None),
        stored,
        DEFAULT_BILLING_INTERVAL,
    )
    return DEFAULT_BILLING_INTERVAL


def build_idempotency_key(*, user_id: int, action: str, plan_type: str) -> str:
    bucket = int(datetime.now(timezone.utc).timestamp() // IDEMPOTENCY_BUCKET_SECONDS)
    return f"{user_id}:{action}:{plan_type}:{bucket}"


class CheckoutSessionRequest(BaseModel):
    plan: Plan
    billing_interval: Literal["month", "year"] = "month"


class CommitmentCheckoutRequest(BaseModel):
    tier: CommitmentTier


class CommitmentChangeRequest(BaseModel):
    tier: CommitmentTier


class UpgradePreviewRequest(BaseModel):
    target_plan: Plan
    billing_interval: Literal["month", "year"]


class UpgradeRequest(BaseModel):
    target_plan: Plan
    billing_interval: Literal["month", "year"]


def get_billing_config(request: Request | None = None, db: Session | None = None):
    config = load_billing_config(db=db)
    if not config.billing_enabled:
        raise HTTPException(
            status_code=503,
            detail=translate_backend_message(
                "errors.billing_disabled",
                "Billing is currently disabled.",
                request=request,
            ),
        )
    if not config.stripe_secret_key:
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.stripe_config_missing",
                "Stripe configuration is missing.",
                request=request,
            ),
        )
    return config


def ensure_stripe_customer(
    *,
    user: models.User,
    db: Session,
    plan: Plan,
    idempotency_key: str | None = None,
    api_key: str | None = None,
    stripe_mode: str | None = None,
    commit: bool = True,
) -> str:
    subscription = None
    if hasattr(db, "query"):
        subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.user_id == user.id)
            .one_or_none()
        )
    if subscription is None:
        subscription = user.subscription

    if subscription and subscription.stripe_customer_id:
        if subscription.stripe_mode == stripe_mode:
            return subscription.stripe_customer_id
        if subscription.stripe_mode not in (None, stripe_mode):
            raise HTTPException(status_code=409, detail="Stripe customer mode conflict.")
        if not api_key or stripe_mode not in {"test", "live"}:
            raise HTTPException(status_code=503, detail="Stripe customer mode is unavailable.")
        try:
            stripe.Customer.retrieve(subscription.stripe_customer_id, api_key=api_key)
            subscription.stripe_mode = stripe_mode
            if commit:
                db.commit()
            else:
                db.flush()
            return subscription.stripe_customer_id
        except stripe.error.InvalidRequestError as error:
            if getattr(error, "code", None) != "resource_missing":
                raise
            if subscription.status in {"active", "trialing"}:
                raise HTTPException(
                    status_code=409, detail="Active Stripe customer could not be reconciled."
                ) from error
            subscription.stripe_customer_id = ""

    customer_create_params: dict[str, Any] = {
        "email": user.email,
        "metadata": {
            "user_id": str(user.id),
            "external_id": user.external_id or "",
        },
    }
    if idempotency_key:
        customer_create_params["idempotency_key"] = idempotency_key
    if api_key:
        customer_create_params["api_key"] = api_key
    customer = stripe.Customer.create(**customer_create_params)

    if subscription:
        subscription.stripe_customer_id = customer.id
        if stripe_mode is not None:
            subscription.stripe_mode = stripe_mode
    else:
        subscription = models.Subscription(
            user_id=user.id,
            stripe_customer_id=customer.id,
            stripe_mode=stripe_mode,
            plan_type=plan.value,
            status="pending",
        )
        db.add(subscription)

    if commit:
        db.commit()
        db.refresh(subscription)
    else:
        db.flush()
    return subscription.stripe_customer_id


def _api_key_for_mode(config: Any, stripe_mode: str | None) -> str:
    mode_config = config.mode_configs.get(stripe_mode)
    secret = mode_config.secret_key if mode_config is not None else None
    if not secret:
        raise HTTPException(status_code=503, detail="Top-up purchase service is unavailable.")
    return secret


def _stripe_object_value(value: object, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _retrieve_checkout_if_status_missing(session: object, *, api_key: str) -> object:
    if _stripe_object_value(session, "status") is not None:
        return session
    session_id = _stripe_object_value(session, "id")
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        return session
    return stripe.checkout.Session.retrieve(session_id, api_key=api_key)


def is_missing_customer_error(error: stripe.error.InvalidRequestError) -> bool:
    return bool(
        getattr(error, "param", None) == "customer"
        and getattr(error, "code", None) == "resource_missing"
    )


def reset_stripe_customer(
    *,
    user: models.User,
    db: Session,
    plan: Plan,
    idempotency_key: str | None = None,
    api_key: str | None = None,
    stripe_mode: str | None = None,
    commit: bool = True,
) -> str:
    subscription = None
    if hasattr(db, "query"):
        subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.user_id == user.id)
            .one_or_none()
        )
    if subscription is None:
        subscription = user.subscription

    if subscription:
        subscription.stripe_customer_id = ""
        if commit:
            db.commit()
            db.refresh(subscription)
        else:
            db.flush()
    return ensure_stripe_customer(
        user=user,
        db=db,
        plan=plan,
        idempotency_key=idempotency_key,
        api_key=api_key,
        stripe_mode=stripe_mode,
        commit=commit,
    )


def require_stripe_customer(user: models.User, request: Request | None = None) -> str:
    if user.subscription and user.subscription.stripe_customer_id:
        return user.subscription.stripe_customer_id
    raise HTTPException(
        status_code=400,
        detail=translate_backend_message(
            "errors.stripe_customer_missing",
            "Stripe customer not found for user.",
            request=request,
        ),
    )


def serialize_invoice_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    return normalized


def serialize_stripe_timestamp(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def resolve_user_plan(user: models.User) -> Plan:
    normalized_plan = resolve_plan_alias(resolve_entitled_subscription_plan(user))
    if not normalized_plan:
        return Plan.STANDARD
    return Plan(normalized_plan)


def _serialize_commitment_surface(
    db: Session,
    *,
    user: models.User,
) -> dict[str, Any]:
    commitment = get_user_commitment(db, user_id=user.id, include_inactive=True)
    cycle = get_active_commitment_cycle(db, commitment_id=commitment.id) if commitment else None
    return {
        "eligible": is_commitment_eligible(user),
        "locked_reason": resolve_commitment_lock_reason(user),
        "current_plan": resolve_current_plan_type(user),
        "commitment": serialize_commitment_status(commitment, cycle=cycle),
    }


@router.get("/plans")
def list_plans(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    _ = db
    config = get_billing_config(http_request, db)
    sub = user.subscription
    is_active_sub = sub and sub.status in ("active", "trialing")
    current_plan = resolve_plan_alias(sub.plan_type) if is_active_sub else None
    current_status = sub.status if sub else None
    current_billing_interval = (
        normalized_billing_interval(sub) if is_active_sub else DEFAULT_BILLING_INTERVAL
    )
    portal_available = bool(sub and sub.stripe_customer_id)

    def plan_price_id(plan: Plan, interval: str = "month") -> str:
        subscription_mode = getattr(sub, "stripe_mode", None) if sub is not None else None
        if is_active_sub and subscription_mode in {"test", "live"}:
            return config.price_id_for_mode(subscription_mode, plan, interval)
        return config.price_id_for(plan, interval)

    pending_plan_change = None
    if is_active_sub and sub is not None:
        pending_values = (
            getattr(sub, "stripe_schedule_id", None),
            getattr(sub, "pending_plan_type", None),
            getattr(sub, "pending_billing_interval", None),
            getattr(sub, "pending_change_effective_at", None),
        )
        if all(value is not None for value in pending_values):
            schedule_id, target_plan, target_interval, effective_at = pending_values
            pending_plan_change = {
                "target_plan": target_plan,
                "target_billing_interval": target_interval,
                "effective_at": effective_at.isoformat(),
                "schedule_id": schedule_id,
            }

    def customer_plan_entry(plan: Plan) -> dict[str, Any]:
        entry = get_plan_catalog_entry(plan.value)
        capabilities = entry.get("capabilities")
        if isinstance(capabilities, dict):
            # Credits are the internal cost unit (SIGV2-1102); withdrawn and
            # unpublished capabilities are live entitlement gates but must not
            # be advertised on the customer plans surface (SIGV2-1167, 1206).
            entry = {
                **entry,
                "capabilities": {
                    key: value
                    for key, value in capabilities.items()
                    if key not in INTERNAL_CAPABILITY_KEYS
                    and key not in UNPUBLISHED_CAPABILITY_KEYS
                    and key not in WITHHELD_PUBLIC_CAPABILITY_KEYS
                },
            }
        return entry

    return {
        "plans": [
            {
                "price_id": plan_price_id(plan),
                "annual_price_id": plan_price_id(plan, "year"),
                "checkout_available": bool(plan_price_id(plan)),
                "annual_checkout_available": bool(plan_price_id(plan, "year")),
                **customer_plan_entry(plan),
            }
            for plan in Plan
            if plan.value not in PRIVATE_PLAN_IDS
        ],
        "current_plan": current_plan,
        "status": current_status,
        "billing_interval": current_billing_interval,
        "pending_plan_change": pending_plan_change,
        "portal_available": portal_available,
    }


# Plans excluded from public (unauthenticated) listing
_PRIVATE_PLANS = PRIVATE_PLAN_IDS


_TERMINAL_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}
_ENTITLED_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def _lock_checkout_billing_state(
    db: Session,
    *,
    user_id: int,
    authenticated_user: models.User | None = None,
) -> tuple[models.User, models.Subscription | None]:
    if not hasattr(db, "execute"):
        if authenticated_user is None:
            raise RuntimeError("A database session is required to create a checkout session.")
        return authenticated_user, getattr(authenticated_user, "subscription", None)

    locked_user = db.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one_or_none()
    if locked_user is None:
        raise HTTPException(status_code=401, detail="Authenticated user no longer exists.")

    subscription = db.execute(
        select(models.Subscription)
        .where(models.Subscription.user_id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one_or_none()
    return locked_user, subscription


def _subscription_checkout_context(
    subscription: models.Subscription | None,
) -> tuple[str | None, str | None]:
    if subscription is None:
        return None, None
    raw_plan = getattr(subscription, "plan_type", None)
    current_plan = resolve_plan_alias(raw_plan) or raw_plan
    raw_status = getattr(subscription, "status", None)
    current_status = raw_status.strip().lower() if isinstance(raw_status, str) else None
    return current_plan, current_status


def _raise_for_subscription_checkout_conflict(
    subscription: models.Subscription | None,
) -> None:
    current_plan, current_status = _subscription_checkout_context(subscription)
    if subscription is None:
        return

    if current_status in _ENTITLED_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "base_subscription_checkout_conflict",
                "message": "You already have an active subscription. Use plan management to change your plan.",
                "current_plan": current_plan,
                "current_status": current_status,
                "route": "/billing/upgrade",
            },
        )

    stripe_subscription_id = getattr(subscription, "stripe_subscription_id", None)
    has_stripe_subscription = bool(
        isinstance(stripe_subscription_id, str) and stripe_subscription_id.strip()
    )
    if current_status in _TERMINAL_SUBSCRIPTION_STATUSES:
        return
    if current_status == "pending" and not has_stripe_subscription:
        return

    raise HTTPException(
        status_code=409,
        detail={
            "code": "base_subscription_checkout_conflict",
            "message": (
                "Your subscription needs attention before starting a new checkout. "
                "Use billing recovery to continue."
            ),
            "current_plan": current_plan,
            "current_status": current_status,
            "route": "/billing/portal-session",
        },
    )


def _raise_for_non_self_service_plan(
    plan: Plan,
    subscription: models.Subscription | None,
    *,
    as_current_plan: bool = False,
) -> None:
    """Refuse self-service checkout/plan-change for a plan that requires it.

    Two different ideas used to share one flag (SIGV2-1236): "not purchasable
    by anyone, in any direction" (``_PRIVATE_PLANS``, e.g. Agency Trial) and
    "negotiated/contact-priced, so not available as a *new* self-service
    selection" (a catalog ``cta`` of ``contact``/``private``, e.g. Executive).
    A plan in ``_PRIVATE_PLANS`` is blocked unconditionally - nobody may move
    onto or off of it through self-service. A contact-CTA plan is blocked
    only when it is being *selected* (``as_current_plan=False``): a customer
    already on a negotiated price must still be able to leave it without
    talking to sales, so callers pass ``as_current_plan=True`` when checking
    the subscription's existing plan rather than the requested target.
    """
    if plan.value in _PRIVATE_PLANS:
        requires_contact = True
    elif as_current_plan:
        requires_contact = False
    else:
        catalog_entry = get_plan_catalog_entry(plan.value)
        catalog_cta = catalog_entry.get("cta")
        requires_contact = isinstance(catalog_cta, str) and catalog_cta.strip().lower() in {
            "contact",
            "private",
        }
    if not requires_contact:
        return

    current_plan, current_status = _subscription_checkout_context(subscription)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "self_service_checkout_unavailable",
            "message": "This plan is not available through self-service checkout. Please contact sales.",
            "current_plan": current_plan,
            "current_status": current_status,
            "route": "/contact",
        },
    )


@router.get("/plans/public")
async def list_plans_public(
    http_request: Request,
    response: Response,
):
    """Return the public plan catalog without authentication, for pricing pages.

    Public contract, so the payload is an explicit output allowlist built in
    ``services/public_plan_catalog.py``: private plans, the internal capability
    matrix, and Stripe-configuration state never reach it. The response is
    rate limited per IP, cached (Redis with an in-process fallback), and
    readable cross-origin only by the configured marketing-site origins.

    ``features_matrix`` publishes the plan entitlement rows (SIGV2-1107): a
    capability key, its minimum plan id, and customer-facing copy. It is the
    only truthful source for "does this plan include X"; a plan's ``features``
    array is marketing highlights and omits capabilities the plan has.
    """
    await enforce_public_plan_catalog_rate_limit(http_request)
    payload = await get_public_plan_catalog()
    response.headers["Cache-Control"] = f"public, max-age={PUBLIC_PLAN_CATALOG_TTL_SECONDS}"
    apply_public_site_cors(http_request, response)
    return payload


@router.get("/commitment-tiers")
def get_commitment_tiers(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    _ = http_request
    payload = _serialize_commitment_surface(db, user=user)
    payload["tiers"] = list_commitment_tiers()
    return payload


@router.get("/commitment")
def get_commitment_status(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    _ = http_request
    return _serialize_commitment_surface(db, user=user)


def _reconcile_base_checkout_session(
    db: Session,
    *,
    attempt: models.BaseCheckoutAttempt,
    session: object,
    require_open: bool,
) -> tuple[str, str]:
    session_id, checkout_url, session_status = validate_base_checkout_session(
        session,
        attempt=attempt,
        require_open=require_open,
    )
    if session_status == "open" and checkout_url is not None:
        return session_id, checkout_url
    if session_status == "complete":
        if attempt.stripe_session_id is None:
            link_base_checkout_session(
                db,
                attempt_id=attempt.id,
                stripe_customer_id=attempt.stripe_customer_id,
                stripe_session_id=session_id,
                commit=False,
            )
            db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "base_checkout_processing",
                "message": "Checkout completed and subscription activation is processing.",
                "route": "/billing/checkout-session",
            },
        )
    expire_base_checkout_attempt(
        db,
        attempt_id=attempt.id,
        stripe_session_id=session_id,
    )
    raise HTTPException(
        status_code=409,
        detail={
            "code": "base_checkout_expired",
            "message": "The previous checkout expired. Retry to start a new checkout.",
            "route": "/billing/checkout-session",
        },
    )


@router.post("/checkout-session")
def create_checkout_session(
    http_request: Request,
    request: CheckoutSessionRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    user, subscription = _lock_checkout_billing_state(
        db,
        user_id=user.id,
        authenticated_user=user,
    )
    _raise_for_subscription_checkout_conflict(subscription)
    _raise_for_non_self_service_plan(request.plan, subscription)

    config = get_billing_config(http_request, db)
    price_id = config.price_id_for(request.plan, request.billing_interval)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.billing_plan_unavailable",
                "Selected plan is not configured for checkout.",
                request=http_request,
            ),
        )

    try:
        resolution = resolve_base_checkout_attempt(
            db,
            user_id=user.id,
            stripe_mode=config.stripe_mode,
            target_plan=request.plan.value,
            billing_interval=request.billing_interval,
        )
    except BaseCheckoutConflictError as error:
        current_plan, current_status = _subscription_checkout_context(subscription)
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.error_code,
                "message": str(error),
                "current_plan": current_plan,
                "current_status": current_status,
                "route": "/billing/checkout-session",
            },
        ) from error

    attempt = resolution.attempt
    user, subscription = _lock_checkout_billing_state(
        db,
        user_id=user.id,
        authenticated_user=user,
    )
    if hasattr(db, "execute"):
        attempt = lock_base_checkout_attempt(db, attempt_id=attempt.id)
    try:
        _raise_for_subscription_checkout_conflict(subscription)
    except HTTPException:
        if resolution.created and hasattr(db, "execute"):
            cancel_untouched_base_checkout_attempt(db, attempt_id=attempt.id)
        raise
    api_key = _api_key_for_mode(config, attempt.stripe_mode)
    if attempt.status == "session_created" and attempt.stripe_session_id:
        try:
            session = stripe.checkout.Session.retrieve(
                attempt.stripe_session_id,
                api_key=api_key,
            )
            session_id, checkout_url = _reconcile_base_checkout_session(
                db,
                attempt=attempt,
                session=session,
                require_open=True,
            )
        except (BaseCheckoutValidationError, stripe.error.StripeError) as error:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "base_checkout_recovery_failed",
                    "message": "Unable to safely recover the existing checkout session.",
                },
            ) from error
        return {"id": session_id, "url": checkout_url}

    customer_key = stripe_customer_idempotency_key(
        user_id=user.id,
        stripe_mode=attempt.stripe_mode,
    )
    customer_id = ensure_stripe_customer(
        user=user,
        db=db,
        plan=request.plan,
        idempotency_key=customer_key,
        api_key=api_key,
        stripe_mode=attempt.stripe_mode,
        commit=False,
    )
    attempt = link_base_checkout_customer(
        db,
        attempt_id=attempt.id,
        stripe_customer_id=customer_id,
        commit=False,
    )

    billing_base_url = f"{config.app_base_url.rstrip('/')}/dashboard/billing"
    checkout_metadata = base_checkout_metadata(attempt)

    def _create_session(stripe_customer_id: str):
        return stripe.checkout.Session.create(
            api_key=api_key,
            idempotency_key=base_checkout_idempotency_key(attempt.id),
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{billing_base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{billing_base_url}/cancel",
            metadata=checkout_metadata,
            client_reference_id=str(user.id),
            # SIGV2-1132: without this the promotion-code field never renders,
            # so any code we issue is unredeemable on this route. Stripe rejects
            # a session that carries both this and `discounts`, so no checkout
            # path here may pre-apply a coupon.
            allow_promotion_codes=True,
        )

    try:
        session = _create_session(customer_id)
    except stripe.error.InvalidRequestError as error:
        if not is_missing_customer_error(error):
            raise
        logger.warning(
            "Stripe customer missing for user %s; regenerating customer and retrying checkout.",
            user.id,
        )
        customer_id = reset_stripe_customer(
            user=user,
            db=db,
            plan=request.plan,
            idempotency_key=customer_key,
            api_key=api_key,
            stripe_mode=attempt.stripe_mode,
            commit=False,
        )
        attempt = link_base_checkout_customer(
            db,
            attempt_id=attempt.id,
            stripe_customer_id=customer_id,
            allow_replacement=True,
            commit=False,
        )
        session = _create_session(customer_id)

    try:
        session = _retrieve_checkout_if_status_missing(session, api_key=api_key)
        session_id, checkout_url = _reconcile_base_checkout_session(
            db,
            attempt=attempt,
            session=session,
            require_open=False,
        )
        link_base_checkout_session(
            db,
            attempt_id=attempt.id,
            stripe_customer_id=customer_id,
            stripe_session_id=session_id,
            commit=False,
        )
        if hasattr(db, "commit"):
            db.commit()
    except BaseCheckoutValidationError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": error.error_code,
                "message": "Stripe returned an invalid checkout session.",
            },
        ) from error

    return {"id": session_id, "url": checkout_url}


# ---------------------------------------------------------------------------
# Plan Upgrade / Downgrade
# ---------------------------------------------------------------------------


def _require_active_subscription(user: models.User, http_request: Request) -> models.Subscription:
    """Return the user's active subscription or raise 400."""
    sub = user.subscription
    if not sub or sub.status not in ("active", "trialing"):
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.no_active_subscription",
                "You must have an active subscription to change plans.",
                request=http_request,
            ),
        )
    return sub


def _classify_plan_change_or_400(
    current_plan: str,
    current_interval: str,
    target_plan: Plan,
    target_interval: str,
    http_request: Request | None,
):
    try:
        return classify_plan_change(
            current_plan,
            current_interval,
            target_plan,
            target_interval,
        )
    except ValueError as error:
        if str(error) == "same_plan":
            detail = translate_backend_message(
                "errors.same_plan",
                "You are already on this plan and billing interval.",
                request=http_request,
            )
        else:
            detail = translate_backend_message(
                "errors.invalid_billing_interval",
                "The billing interval is invalid.",
                request=http_request,
            )
        raise HTTPException(status_code=400, detail=detail) from error


@router.post("/upgrade-preview")
def preview_plan_change(
    http_request: Request,
    request: UpgradePreviewRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a proration estimate for a plan change without executing it."""
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    sub = _require_active_subscription(user, http_request)
    current_plan_str = resolve_plan_alias(sub.plan_type) or sub.plan_type
    _raise_for_non_self_service_plan(Plan(current_plan_str), sub, as_current_plan=True)
    _raise_for_non_self_service_plan(request.target_plan, sub)
    config = get_billing_config(http_request, db)
    current_interval = normalized_billing_interval(sub)

    decision = _classify_plan_change_or_400(
        current_plan_str,
        current_interval,
        request.target_plan,
        request.billing_interval,
        http_request,
    )

    target_price_id = config.price_id_for_mode(
        sub.stripe_mode,
        request.target_plan,
        request.billing_interval,
    )
    if not target_price_id:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.billing_plan_unavailable",
                "The target plan is not available for checkout.",
                request=http_request,
            ),
        )

    feature_diff = diff_capabilities(current_plan_str, request.target_plan.value)

    # Build proration preview
    proration_amount_usd: float | None = None
    next_billing_date: str | None = None
    immediate_charge = decision.immediate

    if not sub.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe subscription found. Please contact support.",
        )
    if sub.stripe_subscription_id:
        api_key = _api_key_for_mode(config, sub.stripe_mode)
        try:
            stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id, api_key=api_key)
            current_plan = Plan(current_plan_str)
            current_price_id = config.price_id_for_mode(
                sub.stripe_mode,
                current_plan,
                current_interval,
            )
            if not current_price_id:
                raise ValueError("current_price_unavailable")
            current_state = validate_current_stripe_subscription(
                stripe_sub,
                subscription_id=sub.stripe_subscription_id,
                customer_id=sub.stripe_customer_id,
                status=sub.status,
                price_id=current_price_id,
                billing_interval=current_interval,
            )
            managed_schedule_id = sub.managed_plan_change_schedule_id
            if managed_schedule_id is None and current_state.schedule_id is not None:
                raise ValueError("unexpected_attached_schedule")
            if managed_schedule_id is not None:
                if current_state.schedule_id not in {None, managed_schedule_id}:
                    raise ValueError("unexpected_attached_schedule")
                schedule = stripe.SubscriptionSchedule.retrieve(
                    managed_schedule_id,
                    api_key=api_key,
                )
                schedule_status = validate_pending_schedule(
                    schedule,
                    schedule_id=managed_schedule_id,
                    subscription_id=sub.stripe_subscription_id,
                    customer_id=sub.stripe_customer_id,
                )
                validate_plan_change_schedule_owner(
                    schedule,
                    subscription_record_id=sub.id,
                )
                expected_schedule_status = (
                    "active" if current_state.schedule_id == managed_schedule_id else "released"
                )
                if schedule_status != expected_schedule_status:
                    raise ValueError("unexpected_managed_schedule_status")

            if decision.immediate:
                upcoming = stripe.Invoice.upcoming(
                    api_key=api_key,
                    customer=sub.stripe_customer_id,
                    subscription=sub.stripe_subscription_id,
                    subscription_items=[
                        {
                            "id": current_state.item_id,
                            "price": target_price_id,
                            "quantity": current_state.quantity,
                        }
                    ],
                    subscription_proration_date=int(datetime.now(timezone.utc).timestamp()),
                )
                proration_amount_usd = round(upcoming.amount_due / 100, 2)

            if stripe_sub.get("current_period_end"):
                next_billing_date = datetime.fromtimestamp(
                    stripe_sub["current_period_end"], tz=timezone.utc
                ).isoformat()
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "invalid_current_subscription",
                    "message": "The current subscription could not be validated for a plan change.",
                },
            ) from exc
        except stripe.error.StripeError as exc:
            logger.warning(
                "Stripe proration preview failed: user_id=%s error_class=%s code=proration_preview_failed",
                user.id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "proration_preview_failed",
                    "message": "Unable to load the plan change preview. Please try again.",
                },
            ) from exc

    current_entry = get_plan_catalog_entry(current_plan_str)
    target_entry = get_plan_catalog_entry(request.target_plan.value)

    return {
        "direction": decision.kind,
        "current_billing_interval": current_interval,
        "target_billing_interval": request.billing_interval,
        "current_plan": {
            "id": current_plan_str,
            "name": current_entry.get("name", current_plan_str),
        },
        "target_plan": {
            "id": request.target_plan.value,
            "name": target_entry.get("name", request.target_plan.value),
        },
        "proration_amount_usd": proration_amount_usd,
        "immediate_charge": immediate_charge,
        "next_billing_date": next_billing_date,
        "feature_diff": feature_diff,
        "scan_adjustment": {
            "current_scans_per_month": current_entry.get("capabilities", {}).get("max_audits", 0),
            "target_scans_per_month": target_entry.get("capabilities", {}).get("max_audits", 0),
        },
    }


def _release_managed_plan_change_schedule(
    *,
    sub: models.Subscription,
    api_key: str,
) -> str | None:
    schedule_id = sub.managed_plan_change_schedule_id
    if not schedule_id:
        return None
    schedule = stripe.SubscriptionSchedule.retrieve(schedule_id, api_key=api_key)
    schedule_status = validate_pending_schedule(
        schedule,
        schedule_id=schedule_id,
        subscription_id=sub.stripe_subscription_id,
        customer_id=sub.stripe_customer_id,
    )
    validate_plan_change_schedule_owner(
        schedule,
        subscription_record_id=sub.id,
    )
    if schedule_status == "active":
        released = stripe.SubscriptionSchedule.release(
            schedule_id,
            api_key=api_key,
            idempotency_key=schedule_release_idempotency_key(schedule_id),
        )
        validate_released_schedule(
            released,
            schedule_id=schedule_id,
            subscription_id=sub.stripe_subscription_id,
            customer_id=sub.stripe_customer_id,
        )
        validate_plan_change_schedule_owner(
            released,
            subscription_record_id=sub.id,
        )
    return schedule_id


def _execute_scheduled_downgrade(
    *,
    http_request: Request | None,
    user: models.User,
    sub: models.Subscription,
    decision: PlanChangeDecision,
    target_price_id: str,
    config: Any,
    db: Session,
) -> datetime:
    original_pending_state = (
        sub.stripe_schedule_id,
        sub.pending_plan_type,
        sub.pending_billing_interval,
        sub.pending_change_effective_at,
    )
    original_managed_schedule_id = sub.managed_plan_change_schedule_id
    try:
        api_key = _api_key_for_mode(config, sub.stripe_mode)
        managed_schedule_id = _release_managed_plan_change_schedule(
            sub=sub,
            api_key=api_key,
        )
        if managed_schedule_id is not None:
            sub.managed_plan_change_schedule_id = None
        current_plan = Plan(decision.current_plan)
        current_price_id = config.price_id_for_mode(
            sub.stripe_mode,
            current_plan,
            decision.current_interval,
        )
        if not current_price_id:
            raise ValueError("current_price_unavailable")

        stripe_sub = stripe.Subscription.retrieve(
            sub.stripe_subscription_id,
            api_key=_api_key_for_mode(config, sub.stripe_mode),
        )
        current_state = validate_current_stripe_subscription(
            stripe_sub,
            subscription_id=sub.stripe_subscription_id,
            customer_id=sub.stripe_customer_id,
            status=sub.status,
            price_id=current_price_id,
            billing_interval=decision.current_interval,
        )
        metadata = downgrade_plan_change_metadata(
            user_id=user.id,
            subscription_record_id=sub.id,
            decision=decision,
        )
        schedule_spec = build_downgrade_schedule_spec(
            current_state,
            target_price_id=target_price_id,
            target_interval=decision.target_interval,
            metadata=metadata,
        )
        pending_identity = pending_plan_change_identity(sub)
        previous_pending_plan = pending_identity[1].value if pending_identity else None
        previous_pending_interval = pending_identity[2] if pending_identity else None
        operation_id = downgrade_schedule_operation_id(
            subscription_id=sub.id,
            stripe_mode=sub.stripe_mode,
            decision=decision,
            current_period_end=current_state.current_period_end,
            previous_pending_plan=previous_pending_plan,
            previous_pending_interval=previous_pending_interval,
        )
        attached_schedule_id = current_state.schedule_id
        if pending_identity is None:
            schedule = None
            schedule_metadata = None
            if attached_schedule_id is not None:
                schedule = stripe.SubscriptionSchedule.retrieve(
                    attached_schedule_id,
                    api_key=api_key,
                    expand=["phases.items.price"],
                )
                validate_owned_active_schedule(
                    schedule,
                    schedule_id=attached_schedule_id,
                    subscription_id=sub.stripe_subscription_id,
                    customer_id=sub.stripe_customer_id,
                )
                schedule_metadata = (
                    schedule.get("metadata") if isinstance(schedule, Mapping) else None
                )
                if isinstance(schedule_metadata, Mapping) and schedule_metadata.get(
                    "qiko_schedule_kind"
                ):
                    validate_plan_change_schedule_owner(
                        schedule,
                        subscription_record_id=sub.id,
                        target_plan=decision.target_plan,
                        target_interval=decision.target_interval,
                    )
                    schedule_id = attached_schedule_id
            if schedule is None or not (
                isinstance(schedule_metadata, Mapping)
                and schedule_metadata.get("qiko_schedule_kind")
            ):
                created_schedule = stripe.SubscriptionSchedule.create(
                    from_subscription=sub.stripe_subscription_id,
                    api_key=api_key,
                    idempotency_key=downgrade_schedule_idempotency_key(
                        action="create",
                        subscription_id=sub.id,
                        stripe_mode=sub.stripe_mode,
                        decision=decision,
                        operation_id=operation_id,
                    ),
                )
                schedule_id = stripe_schedule_id(created_schedule)
                if attached_schedule_id is not None and schedule_id != attached_schedule_id:
                    raise ValueError("attached_schedule_replay_mismatch")
                if schedule is None:
                    schedule = stripe.SubscriptionSchedule.retrieve(
                        schedule_id,
                        api_key=api_key,
                        expand=["phases.items.price"],
                    )
                    validate_owned_active_schedule(
                        schedule,
                        schedule_id=schedule_id,
                        subscription_id=sub.stripe_subscription_id,
                        customer_id=sub.stripe_customer_id,
                    )
        else:
            schedule_id = pending_identity[0]
            if schedule_id != attached_schedule_id:
                raise ValueError("local_schedule_mismatch")
            schedule = stripe.SubscriptionSchedule.retrieve(
                schedule_id,
                api_key=api_key,
                expand=["phases.items.price"],
            )
            validate_owned_active_schedule(
                schedule,
                schedule_id=schedule_id,
                subscription_id=sub.stripe_subscription_id,
                customer_id=sub.stripe_customer_id,
            )
            validate_plan_change_schedule_owner(
                schedule,
                subscription_record_id=sub.id,
            )
        schedule_spec = attach_current_schedule_phase(schedule_spec, schedule)
        if not is_configured_downgrade_schedule(
            schedule,
            schedule_id=schedule_id,
            spec=schedule_spec,
        ):
            schedule = stripe.SubscriptionSchedule.modify(
                schedule_id,
                api_key=api_key,
                phases=downgrade_schedule_phases(schedule_spec),
                end_behavior="release",
                metadata=metadata,
                proration_behavior="none",
                expand=["phases.items.price"],
                idempotency_key=downgrade_schedule_idempotency_key(
                    action="modify",
                    subscription_id=sub.id,
                    stripe_mode=sub.stripe_mode,
                    decision=decision,
                    operation_id=operation_id,
                ),
            )
            validate_configured_downgrade_schedule(
                schedule,
                schedule_id=schedule_id,
                spec=schedule_spec,
            )

        effective_at = datetime.fromtimestamp(
            schedule_spec.current_period_end,
            tz=timezone.utc,
        )
        if managed_schedule_id is not None:
            sub.managed_plan_change_schedule_id = None
        set_pending_plan_change(
            sub,
            stripe_schedule_id=schedule_id,
            target_plan=decision.target_plan,
            target_interval=decision.target_interval,
            effective_at=effective_at,
        )
        sub.plan_state_event_created_at = datetime.now(timezone.utc)
        db.commit()
        return effective_at
    except Exception as error:
        (
            sub.stripe_schedule_id,
            sub.pending_plan_type,
            sub.pending_billing_interval,
            sub.pending_change_effective_at,
        ) = original_pending_state
        sub.managed_plan_change_schedule_id = original_managed_schedule_id
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()
        logger.error(
            "Stripe scheduled downgrade failed: user_id=%s error_class=%s code=plan_change_failed",
            user.id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.stripe_plan_change_failed",
                "Unable to process the plan change. Please try again.",
                request=http_request,
            ),
        ) from error


@router.post("/upgrade")
def execute_plan_change(
    http_request: Request,
    request: UpgradeRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute a plan upgrade (immediate) or downgrade (scheduled for period end)."""
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    sub = _require_active_subscription(user, http_request)
    current_plan_str = resolve_plan_alias(sub.plan_type) or sub.plan_type
    _raise_for_non_self_service_plan(Plan(current_plan_str), sub, as_current_plan=True)
    _raise_for_non_self_service_plan(request.target_plan, sub)
    config = get_billing_config(http_request, db)
    current_interval = normalized_billing_interval(sub)

    decision = _classify_plan_change_or_400(
        current_plan_str,
        current_interval,
        request.target_plan,
        request.billing_interval,
        http_request,
    )
    if db is not None and hasattr(db, "execute"):
        try:
            sub = lock_subscription_for_plan_change(db, sub.id)
        except ValueError as error:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            raise HTTPException(
                status_code=400,
                detail="The active subscription could not be found.",
            ) from error
        if sub.user_id != user.id or sub.status not in {"active", "trialing"}:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            raise HTTPException(status_code=400, detail="The subscription is not active.")
        current_plan_str = resolve_plan_alias(sub.plan_type) or sub.plan_type
        _raise_for_non_self_service_plan(Plan(current_plan_str), sub, as_current_plan=True)
        current_interval = normalized_billing_interval(sub)
        decision = _classify_plan_change_or_400(
            current_plan_str,
            current_interval,
            request.target_plan,
            request.billing_interval,
            http_request,
        )

    pending_identity = pending_plan_change_identity(sub)
    if decision.immediate and pending_identity is not None:
        schedule_id, pending_plan, pending_interval = pending_identity
        effective_at = sub.pending_change_effective_at
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pending_plan_change_conflict",
                "message": "A plan change is already scheduled.",
                "requested_change_kind": decision.kind,
                "pending_plan_change": {
                    "schedule_id": schedule_id,
                    "target_plan": pending_plan.value,
                    "target_billing_interval": pending_interval,
                    "effective_at": effective_at.isoformat(),
                },
            },
        )

    target_price_id = config.price_id_for_mode(
        sub.stripe_mode,
        request.target_plan,
        request.billing_interval,
    )
    if not target_price_id:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.billing_plan_unavailable",
                "The target plan is not available for checkout.",
                request=http_request,
            ),
        )
    if not sub.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.no_stripe_subscription",
                "No Stripe subscription found. Please contact support.",
                request=http_request,
            ),
        )

    api_key = _api_key_for_mode(config, sub.stripe_mode)
    if not decision.immediate:
        effective_at = _execute_scheduled_downgrade(
            http_request=http_request,
            user=user,
            sub=sub,
            decision=decision,
            target_price_id=target_price_id,
            config=config,
            db=db,
        )
        return {
            "direction": decision.kind,
            "previous_plan": current_plan_str,
            "new_plan": request.target_plan.value,
            "current_billing_interval": decision.current_interval,
            "target_billing_interval": decision.target_interval,
            "immediate": False,
            "effective_date": effective_at.isoformat(),
            "message": (
                f"Your plan will change to {request.target_plan.value.replace('_', ' ').title()} "
                "at the end of your current billing period."
            ),
        }

    operation_id = f"pc_{uuid4().hex}"
    _operation_started_at = datetime.now(timezone.utc)
    original_managed_schedule_id = sub.managed_plan_change_schedule_id
    try:
        current_plan = Plan(current_plan_str)
        current_price_id = config.price_id_for_mode(
            sub.stripe_mode,
            current_plan,
            current_interval,
        )
        if not current_price_id:
            raise ValueError("current_price_unavailable")
        metadata = immediate_plan_change_metadata(user_id=user.id, decision=decision)
        stripe_sub = stripe.Subscription.retrieve(
            sub.stripe_subscription_id,
            api_key=api_key,
        )
        current_state, already_applied = resolve_immediate_plan_change_state(
            stripe_sub,
            subscription_id=sub.stripe_subscription_id,
            customer_id=sub.stripe_customer_id,
            current_status=sub.status,
            current_price_id=current_price_id,
            current_interval=current_interval,
            target_price_id=target_price_id,
            target_interval=request.billing_interval,
            metadata=metadata,
        )
        managed_schedule_id = original_managed_schedule_id
        if managed_schedule_id is None and current_state.schedule_id is not None:
            raise ValueError("unexpected_attached_schedule")
        if managed_schedule_id is not None:
            if current_state.schedule_id not in {None, managed_schedule_id}:
                raise ValueError("unexpected_attached_schedule")
            _release_managed_plan_change_schedule(sub=sub, api_key=api_key)
            sub.managed_plan_change_schedule_id = None
            if current_state.schedule_id == managed_schedule_id:
                stripe_sub = stripe.Subscription.retrieve(
                    sub.stripe_subscription_id,
                    api_key=api_key,
                )
                current_state, already_applied = resolve_immediate_plan_change_state(
                    stripe_sub,
                    subscription_id=sub.stripe_subscription_id,
                    customer_id=sub.stripe_customer_id,
                    current_status=sub.status,
                    current_price_id=current_price_id,
                    current_interval=current_interval,
                    target_price_id=target_price_id,
                    target_interval=request.billing_interval,
                    metadata=metadata,
                )
        if current_state.schedule_id is not None:
            raise ValueError("unexpected_attached_schedule")
        if already_applied:
            validated_status = current_state.status
            validated_interval = current_state.billing_interval
            validated_period_end = current_state.current_period_end
        else:
            updated_sub = stripe.Subscription.modify(
                sub.stripe_subscription_id,
                api_key=api_key,
                items=[
                    {
                        "id": current_state.item_id,
                        "price": target_price_id,
                        "quantity": current_state.quantity,
                    }
                ],
                proration_behavior="always_invoice",
                payment_behavior="error_if_incomplete",
                metadata=metadata,
                idempotency_key=immediate_plan_change_idempotency_key(
                    subscription_id=sub.id,
                    stripe_mode=sub.stripe_mode,
                    decision=decision,
                    operation_id=operation_id,
                ),
            )
            validated = validate_immediate_plan_change(
                updated_sub,
                subscription_id=sub.stripe_subscription_id,
                customer_id=sub.stripe_customer_id,
                target_price_id=target_price_id,
                target_interval=request.billing_interval,
                expected_quantity=current_state.quantity,
                metadata=metadata,
            )
            validated_status = validated.status
            validated_interval = validated.billing_interval
            validated_period_end = validated.current_period_end
        sub.plan_type = request.target_plan.value
        sub.billing_interval = validated_interval
        sub.status = validated_status
        sub.current_period_end = datetime.fromtimestamp(
            validated_period_end,
            tz=timezone.utc,
        )
        sub.plan_state_event_created_at = datetime.now(timezone.utc)
        if managed_schedule_id is not None:
            sub.managed_plan_change_schedule_id = None
        db.commit()
    except Exception as error:
        sub.managed_plan_change_schedule_id = original_managed_schedule_id
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()
        logger.error(
            "Stripe plan change failed: user_id=%s error_class=%s code=plan_change_failed",
            user.id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.stripe_plan_change_failed",
                "Unable to process the plan change. Please try again.",
                request=http_request,
            ),
        ) from error

    logger.info(
        "Plan %s completed for user %s: %s -> %s",
        decision.kind,
        user.id,
        current_plan_str,
        request.target_plan.value,
    )
    return {
        "direction": decision.kind,
        "previous_plan": current_plan_str,
        "new_plan": request.target_plan.value,
        "current_billing_interval": decision.current_interval,
        "target_billing_interval": decision.target_interval,
        "immediate": True,
        "effective_date": None,
        "message": (
            f"Your plan has been changed to {request.target_plan.value.replace('_', ' ').title()}."
        ),
    }


@router.post("/commitment-checkout")
def create_commitment_checkout_session(
    http_request: Request,
    request: CommitmentCheckoutRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    config = get_billing_config(http_request, db)
    if not is_commitment_eligible(user):
        raise HTTPException(
            status_code=403,
            detail=resolve_commitment_lock_reason(user)
            or "Audit commitments are not available for this account.",
        )

    existing_commitment = get_user_commitment(db, user_id=user.id)
    if existing_commitment is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have an active audit commitment.",
        )

    tier_definition = resolve_commitment_tier_definition(request.tier)
    if tier_definition is None:
        raise HTTPException(status_code=400, detail="Unsupported commitment tier.")

    commitment_price_id = config.commitment_price_id_for(request.tier)
    overage_price_id = config.commitment_overage_price_id or ""
    if not commitment_price_id or not overage_price_id:
        raise HTTPException(
            status_code=400,
            detail="Commitment checkout is not configured for the current billing environment.",
        )

    resolved_plan = resolve_user_plan(user)
    api_key = _api_key_for_mode(config, config.stripe_mode)
    customer_idempotency_key = stripe_customer_idempotency_key(
        user_id=user.id,
        stripe_mode=config.stripe_mode,
    )
    customer_id = ensure_stripe_customer(
        user=user,
        db=db,
        plan=resolved_plan,
        idempotency_key=customer_idempotency_key,
        api_key=api_key,
        stripe_mode=config.stripe_mode,
    )
    billing_base_url = f"{config.app_base_url.rstrip('/')}/dashboard/billing"

    def _create_session(stripe_customer_id: str):
        metadata = {
            "type": "credit_commitment",
            "user_id": str(user.id),
            "tier": tier_definition.tier.value,
            "committed_credits": str(tier_definition.committed_credits),
        }
        return stripe.checkout.Session.create(
            api_key=api_key,
            idempotency_key=build_idempotency_key(
                user_id=user.id,
                action="commitment_checkout",
                plan_type=tier_definition.tier.value,
            ),
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[
                {"price": commitment_price_id, "quantity": 1},
                {"price": overage_price_id},
            ],
            success_url=f"{billing_base_url}?commitment=success",
            cancel_url=f"{billing_base_url}?commitment=cancelled",
            metadata=metadata,
            subscription_data={"metadata": metadata},
            client_reference_id=str(user.id),
            # SIGV2-1132: kept identical to the subscription route. A code that
            # works on one checkout and silently fails on another cannot be
            # explained to a customer; scoping which products a code applies to
            # belongs on the coupon, not here.
            allow_promotion_codes=True,
        )

    try:
        session = _create_session(customer_id)
    except stripe.error.InvalidRequestError as error:
        if not is_missing_customer_error(error):
            raise

        logger.warning(
            "Stripe customer missing for user %s; regenerating customer and retrying commitment checkout.",
            user.id,
        )
        customer_id = reset_stripe_customer(
            user=user,
            db=db,
            plan=resolved_plan,
            idempotency_key=customer_idempotency_key,
            api_key=api_key,
            stripe_mode=config.stripe_mode,
        )
        session = _create_session(customer_id)

    return {
        "checkout_url": session.url,
        "tier": tier_definition.tier.value,
        "monthly_fee_usd": tier_definition.monthly_fee_usd,
        "committed_credits": tier_definition.committed_credits,
    }


@router.post("/commitment-cancel")
def cancel_commitment(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    config = get_billing_config(http_request, db)
    commitment = get_user_commitment(db, user_id=user.id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="No active audit commitment found.")

    api_key = _api_key_for_mode(config, commitment.stripe_mode)
    subscription = stripe.Subscription.modify(
        commitment.stripe_subscription_id,
        api_key=api_key,
        cancel_at_period_end=True,
    )
    commitment.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    if subscription.get("current_period_end"):
        commitment.current_cycle_end = datetime.fromtimestamp(
            int(subscription["current_period_end"]),
            tz=timezone.utc,
        )
    db.commit()
    db.refresh(commitment)
    cycle = get_active_commitment_cycle(db, commitment_id=commitment.id)
    return {
        "message": "Your commitment will cancel at the end of the current cycle.",
        "commitment": serialize_commitment_status(commitment, cycle=cycle),
    }


@router.post("/commitment-change")
def change_commitment_tier(
    http_request: Request,
    request: CommitmentChangeRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    config = get_billing_config(http_request, db)
    commitment = get_user_commitment(db, user_id=user.id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="No active audit commitment found.")
    api_key = _api_key_for_mode(config, commitment.stripe_mode)
    if commitment.cancel_at_period_end:
        raise HTTPException(
            status_code=409,
            detail="You cannot change tiers while cancellation is already scheduled.",
        )

    next_tier = resolve_commitment_tier_definition(request.tier)
    if next_tier is None:
        raise HTTPException(status_code=400, detail="Unsupported commitment tier.")
    if next_tier.tier.value == commitment.tier:
        raise HTTPException(status_code=400, detail="You are already on that commitment tier.")

    next_price_id = config.commitment_price_id_for_mode(
        commitment.stripe_mode,
        request.tier,
    )
    if not next_price_id:
        raise HTTPException(
            status_code=400,
            detail="The selected commitment tier is not configured in the current billing environment.",
        )

    fixed_item_id = commitment.stripe_commitment_subscription_item_id
    if not fixed_item_id:
        subscription_payload = stripe.Subscription.retrieve(
            commitment.stripe_subscription_id, api_key=api_key
        )
        fixed_item_id, overage_item_id = extract_commitment_subscription_items(
            subscription_payload,
            db=db,
            config=config,
        )
        if fixed_item_id:
            commitment.stripe_commitment_subscription_item_id = fixed_item_id
        if overage_item_id:
            commitment.stripe_overage_subscription_item_id = overage_item_id
    if not commitment.stripe_commitment_subscription_item_id:
        raise HTTPException(
            status_code=502,
            detail="Unable to schedule the tier change because the Stripe subscription items could not be resolved.",
        )

    stripe.Subscription.modify(
        commitment.stripe_subscription_id,
        api_key=api_key,
        items=[
            {
                "id": commitment.stripe_commitment_subscription_item_id,
                "price": next_price_id,
            }
        ],
        proration_behavior="none",
    )

    commitment.pending_tier = next_tier.tier.value
    commitment.pending_committed_credits = next_tier.committed_credits
    commitment.pending_rate_per_credit = next_tier.rate_per_credit
    commitment.pending_monthly_fee_usd = (
        next_tier.monthly_fee_usd
    )  # DB column is legacy-named _usd, stores EUR
    commitment.pending_change_effective_at = commitment.current_cycle_end
    db.commit()
    db.refresh(commitment)
    cycle = get_active_commitment_cycle(db, commitment_id=commitment.id)
    return {
        "message": "Your new tier is scheduled for the next billing cycle.",
        "commitment": serialize_commitment_status(commitment, cycle=cycle),
    }


_RESTRICTED_PORTAL_CONFIGURATION_METADATA = {"qiko_portal_configuration": "restricted_v1"}
_RESTRICTED_PORTAL_FEATURES = {
    "subscription_update": {"enabled": False},
    "subscription_cancel": {"enabled": False},
    "invoice_history": {"enabled": True},
    "payment_method_update": {"enabled": True},
}


def _validate_restricted_portal_configuration(configuration: object) -> str:
    configuration_id = _stripe_object_value(configuration, "id")
    active = _stripe_object_value(configuration, "active")
    metadata = _stripe_object_value(configuration, "metadata")
    features = _stripe_object_value(configuration, "features")
    if not isinstance(configuration_id, str) or not configuration_id.startswith("bpc_"):
        raise ValueError("invalid_portal_configuration_id")
    if active is not True or not isinstance(metadata, Mapping) or not isinstance(features, Mapping):
        raise ValueError("invalid_portal_configuration")
    if any(
        metadata.get(key) != value
        for key, value in _RESTRICTED_PORTAL_CONFIGURATION_METADATA.items()
    ):
        raise ValueError("invalid_portal_configuration_owner")
    for feature_name, expected in _RESTRICTED_PORTAL_FEATURES.items():
        feature = features.get(feature_name)
        if not isinstance(feature, Mapping) or feature.get("enabled") is not expected["enabled"]:
            raise ValueError("invalid_portal_configuration_features")
    return configuration_id


def _restricted_portal_configuration_id(*, api_key: str, stripe_mode: str) -> str:
    configurations = stripe.billing_portal.Configuration.list(
        api_key=api_key,
        active=True,
        limit=100,
    )
    data = _stripe_object_value(configurations, "data")
    if not isinstance(data, (list, tuple)):
        raise ValueError("invalid_portal_configuration_list")
    for configuration in data:
        metadata = _stripe_object_value(configuration, "metadata")
        if isinstance(metadata, Mapping) and all(
            metadata.get(key) == value
            for key, value in _RESTRICTED_PORTAL_CONFIGURATION_METADATA.items()
        ):
            return _validate_restricted_portal_configuration(configuration)
    created = stripe.billing_portal.Configuration.create(
        api_key=api_key,
        features=_RESTRICTED_PORTAL_FEATURES,
        metadata=_RESTRICTED_PORTAL_CONFIGURATION_METADATA,
        idempotency_key=build_idempotency_key(
            user_id=0,
            action=f"restricted_portal_configuration_v1_{stripe_mode}",
            plan_type="billing_portal",
        ),
    )
    return _validate_restricted_portal_configuration(created)


@router.post("/portal-session")
def create_portal_session(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    sub = user.subscription
    if sub is not None and db is not None and hasattr(db, "execute"):
        try:
            sub = lock_subscription_for_plan_change(db, sub.id)
        except ValueError as error:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            raise HTTPException(
                status_code=400, detail="The subscription could not be found."
            ) from error
        if sub.user_id != user.id:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            raise HTTPException(status_code=403, detail="The subscription is not available.")
    pending_identity = pending_plan_change_identity(sub) if sub is not None else None
    if sub is not None and sub.status in {"active", "trialing"} and pending_identity is not None:
        schedule_id, target_plan, target_interval = pending_identity
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pending_plan_change_conflict",
                "message": "A plan change is already scheduled.",
                "pending_plan_change": {
                    "schedule_id": schedule_id,
                    "target_plan": target_plan.value,
                    "target_billing_interval": target_interval,
                    "effective_at": sub.pending_change_effective_at.isoformat(),
                },
            },
        )
    config = get_billing_config(http_request, db)
    customer_id = sub.stripe_customer_id if sub is not None else None
    if not customer_id:
        customer_id = require_stripe_customer(user, http_request)
    stripe_mode = sub.stripe_mode if sub is not None else None
    api_key = _api_key_for_mode(config, stripe_mode)
    try:
        portal_configuration_id = _restricted_portal_configuration_id(
            api_key=api_key,
            stripe_mode=stripe_mode or config.stripe_mode,
        )
    except (ValueError, stripe.error.StripeError) as error:
        logger.error(
            "Stripe billing portal configuration validation failed: user_id=%s error_class=%s code=billing_portal_configuration_invalid",
            user.id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "billing_portal_configuration_invalid",
                "message": "Billing portal access is temporarily unavailable.",
            },
        ) from error
    return_url = f"{config.app_base_url.rstrip('/')}/dashboard/billing"
    session = stripe.billing_portal.Session.create(
        api_key=api_key,
        idempotency_key=build_idempotency_key(
            user_id=user.id,
            action="portal_session",
            plan_type=(user.subscription.plan_type if user.subscription else "unknown"),
        ),
        customer=customer_id,
        return_url=return_url,
        configuration=portal_configuration_id,
    )
    return {"url": session.url}


@router.get("/invoices")
def list_invoices(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1, le=100),
    starting_after: str | None = Query(default=None),
):
    require_not_portal_only(user, detail="Client portal users cannot access billing.")
    config = get_billing_config(http_request, db)
    customer_id = require_stripe_customer(user, http_request)
    api_key = _api_key_for_mode(
        config, user.subscription.stripe_mode if user.subscription else None
    )
    try:
        invoices = stripe.Invoice.list(
            api_key=api_key,
            customer=customer_id,
            limit=limit or 25,
            starting_after=starting_after,
        )
    except stripe.error.StripeError as error:
        logger.warning(
            "Stripe invoice history unavailable: user_id=%s error_class=%s",
            user.id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "invoice_history_unavailable",
                "message": "Invoice history is temporarily unavailable.",
            },
        ) from error
    next_starting_after = invoices.data[-1].id if invoices.data else None
    return {
        "invoices": [
            {
                "date": serialize_stripe_timestamp(getattr(invoice, "created", None)),
                "amounts": {
                    "amount_due": invoice.amount_due,
                    "amount_paid": invoice.amount_paid,
                    "amount_remaining": invoice.amount_remaining,
                },
                "currency": invoice.currency,
                "status": invoice.status,
                "hosted_invoice_url": serialize_invoice_url(invoice.hosted_invoice_url),
                "invoice_pdf": serialize_invoice_url(invoice.invoice_pdf),
            }
            for invoice in invoices.data
        ],
        "has_more": invoices.has_more,
        "next_starting_after": next_starting_after,
    }


# ---------------------------------------------------------------------------
#  Usage analytics & plan recommendation
# ---------------------------------------------------------------------------


@router.get("/usage-analytics")
def get_usage_analytics(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=7, le=90),
):
    """Return credit usage history, burn rate, projections, and breakdown."""
    require_not_portal_only(user, detail="Client portal users cannot access usage analytics.")
    return build_usage_analytics(db, user, days=days)


@router.get("/plan-recommendation")
def get_plan_recommendation(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Suggest optimal plan based on actual usage patterns."""
    require_not_portal_only(user, detail="Client portal users cannot access plan recommendations.")
    from billing.usage_analytics import aggregate_daily_scans

    daily_scans = aggregate_daily_scans(db, user.id, days=30)
    recommendation = build_plan_recommendation(db, user, daily_scans)
    return {"recommendation": recommendation}


@router.get("/scan-warning")
def get_scan_warning(
    http_request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if user should see a low scan allowance warning."""
    require_not_portal_only(user, detail="Client portal users cannot access scan warnings.")
    from services.scan_allowance_service import scan_allowance_snapshot

    return should_show_scan_warning(user, scan_allowance_snapshot(db, user))
