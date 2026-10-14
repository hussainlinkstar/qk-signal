import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

import models
from operational_settings import (
    get_credit_engine_policy_version,
    resolve_shadow_pricing_policy_version,
)
from services.ai_economics_ledger_service import record_billing_event_to_ledger
from services.billing_calculator import BillingComputation, calculate_dynamic_billing
from services.credit_commitment_service import (
    record_commitment_usage as record_credit_commitment_usage,
    refund_commitment_usage,
)
from services.pricing_policy_service import (
    AUDIT_TIER_ALIASES,
    calculate_audit_credit_cost_for_policy,
    get_pricing_policy,
    normalize_audit_tier as normalize_policy_audit_tier,
)

logger = logging.getLogger(__name__)

QUOTA_TIER_ENV_VAR = "AUDIT_QUOTA_TIERS"

AUDIT_RECORD_STATUS_DEGRADED = "degraded"
AUDIT_RECORD_STATUS_FAILED = "failed"

_DEFAULT_POLICY = get_pricing_policy()
PROVIDER_MULTIPLIER: dict[str, float] = {
    key: float(value) for key, value in _DEFAULT_POLICY.provider_multipliers.items()
}
TIER_BASE_CREDITS: dict[str, float] = {
    key: float(value) for key, value in _DEFAULT_POLICY.tier_multipliers.items()
}
TIER_ALIASES: dict[str, str] = dict(AUDIT_TIER_ALIASES)
SYNTHESIS_CREDIT_COST: int = int(_DEFAULT_POLICY.synthesis_credit_cost)
PROMPT_RECOMMENDATION_CREDIT_COST: int = int(_DEFAULT_POLICY.prompt_recommendation_credit_cost)


def is_billable_audit_outcome(full_report: dict | None) -> bool:
    """
    Determines if an audit result is considered 'billable' (successful or degraded).
    If the outcome is explicitly 'failed' or the report is missing, it is not billable.

    The audit pipeline records the resolved outcome in
    ``metadata.audit_outcome`` (see audit_runner._build_report), not in a
    top-level ``status`` field. The top-level ``status`` is still honored first
    for callers/records that set it, then we fall back to
    ``metadata.audit_outcome`` so that genuinely failed audits (e.g. total AI
    outage with no usable scores) are not charged.
    """
    if not full_report:
        return False
    status = full_report.get("status")
    if not status:
        metadata = full_report.get("metadata")
        if isinstance(metadata, dict):
            status = metadata.get("audit_outcome")
    return status != AUDIT_RECORD_STATUS_FAILED


def _parse_quota_tiers(raw_value: str | None) -> set[str]:
    if not raw_value:
        return set()
    normalized: set[str] = set()
    for tier in raw_value.split(","):
        cleaned = str(tier).strip().lower()
        if not cleaned:
            continue
        normalized.add(TIER_ALIASES.get(cleaned, cleaned))
    return normalized


def normalize_audit_tier(tier: str | None) -> str:
    return normalize_policy_audit_tier(tier)


def has_active_subscription(user: models.User) -> bool:
    subscription = user.subscription
    return bool(subscription and subscription.status == "active")


def tier_requires_quota(tier: str) -> bool:
    quota_tiers = _parse_quota_tiers(os.getenv(QUOTA_TIER_ENV_VAR))
    return normalize_audit_tier(tier) in quota_tiers


def should_decrement_credits(user: models.User, tier: str) -> bool:
    # Credits are always consumed, subscription unlocks features and
    # refreshes the wallet monthly, but every billable action deducts.
    return True


def calculate_audit_credit_cost_for_policy_version(
    *,
    policy_version: str | None,
    provider: str,
    tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
) -> int:
    return calculate_audit_credit_cost_for_policy(
        policy_version=policy_version,
        provider=provider,
        tier=tier,
        entities_count=entities_count,
        category=category,
        market=market,
    )


def calculate_audit_credit_cost(
    *,
    provider: str,
    tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
) -> int:
    return calculate_audit_credit_cost_for_policy_version(
        policy_version=None,
        provider=provider,
        tier=tier,
        entities_count=entities_count,
        category=category,
        market=market,
    )


def calculate_multi_model_credit_cost(
    *,
    selected_models: list[str],
    tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
) -> int:
    """Total cost for a multi-model consensus audit.

    Sum of each model's individual cost + a flat synthesis credit.
    """
    total = sum(
        calculate_audit_credit_cost(
            provider=model,
            tier=tier,
            entities_count=entities_count,
            category=category,
            market=market,
        )
        for model in selected_models
    )
    total += SYNTHESIS_CREDIT_COST
    return max(1, total)


def calculate_multi_model_credit_cost_for_policy_version(
    *,
    policy_version: str | None,
    selected_models: list[str],
    tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
) -> int:
    policy = get_pricing_policy(policy_version)
    total = sum(
        calculate_audit_credit_cost_for_policy_version(
            policy_version=policy.version,
            provider=model,
            tier=tier,
            entities_count=entities_count,
            category=category,
            market=market,
        )
        for model in selected_models
    )
    total += max(1, int(policy.synthesis_credit_cost))
    return max(1, total)


def decrement_credits_atomic(
    db: Session,
    user_id: int,
    amount: int,
    *,
    record_commitment: bool = True,
    allow_negative: bool = False,
) -> bool:
    normalized_amount = max(0, int(amount))
    if normalized_amount == 0:
        return True
    # Credits are internal soft limits (SIGV2-1024): internal accounting
    # callers pass allow_negative=True so a shortfall books a negative
    # balance instead of silently losing the charge. Customer-facing gates
    # keep the floor predicate and simply observe ``False``.
    predicate = (
        models.User.id == user_id
        if allow_negative
        else (models.User.id == user_id) & (models.User.credits >= normalized_amount)
    )
    result = db.execute(
        update(models.User).where(predicate).values(credits=models.User.credits - normalized_amount)
    )
    updated = (result.rowcount or 0) > 0
    if updated and record_commitment:
        record_credit_commitment_usage(db, user_id=user_id, amount=normalized_amount)
    if updated and allow_negative:
        _maybe_alert_negative_credit_balance(db, user_id=user_id)
    return updated


_NEGATIVE_BALANCE_ALERT_TTL_SECONDS = 30 * 24 * 60 * 60


def _maybe_alert_negative_credit_balance(db: Session, *, user_id: int) -> None:
    """Notify internal ops once per ~billing period when an internal credit
    balance drops below zero. Scans are the customer-facing brake, so this only
    observes provider spend; it must never fail the charge path."""
    try:
        balance = db.query(models.User.credits).filter(models.User.id == user_id).scalar()
        if balance is None or int(balance) >= 0:
            return
        user = db.query(models.User).filter(models.User.id == user_id).first()
        plan = getattr(user, "plan_type", None) if user is not None else None

        email_allowed = False
        try:
            from core.redis_client import get_sync_redis

            with get_sync_redis() as redis_client:
                email_allowed = bool(
                    redis_client.set(
                        f"internal_alert:negative_credits:{user_id}",
                        "1",
                        nx=True,
                        ex=_NEGATIVE_BALANCE_ALERT_TTL_SECONDS,
                    )
                )
        except Exception:
            logger.exception(
                "negative credit balance rate-limit check failed",
                extra={"user_id": user_id},
            )
        logger.warning(
            "Internal credit balance negative",
            extra={
                "user_id": user_id,
                "plan_type": plan,
                "credits": int(balance),
            },
        )

        if not email_allowed:
            return

        from core.config import settings

        admin_emails_raw = str(getattr(settings, "ADMIN_EMAILS", "") or "")
        admin_emails = [e.strip() for e in admin_emails_raw.split(",") if e.strip()]
        if not admin_emails:
            return
        from services.email_service import EmailService

        email_service = EmailService(db)
        for admin_email in admin_emails:
            email_service.queue_template_email(
                to_email=admin_email,
                template_name="admin_system_alert",
                subject="[WARNING] Internal credit balance negative",
                context={
                    "rule_name": "negative_credit_balance",
                    "severity": "warning",
                    "message": (
                        f"User {user_id} internal credit balance is {int(balance)} "
                        f"(plan {plan or 'unknown'})."
                    ),
                    "metric_key": "user_credit_balance",
                    "current_value": int(balance),
                    "threshold_value": 0,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                },
            )
    except Exception:
        logger.exception("negative credit balance alert failed", extra={"user_id": user_id})


def increment_credits_atomic(
    db: Session,
    user_id: int,
    amount: int,
    *,
    reverse_commitment_usage: bool = False,
) -> bool:
    normalized_amount = max(0, int(amount))
    if normalized_amount == 0:
        return True
    result = db.execute(
        update(models.User)
        .where(models.User.id == user_id)
        .values(credits=models.User.credits + normalized_amount)
    )
    updated = (result.rowcount or 0) > 0
    if updated and reverse_commitment_usage:
        refund_commitment_usage(db, user_id=user_id, amount=normalized_amount)
    return updated


def decrement_credit_atomic(db: Session, user_id: int) -> bool:
    return decrement_credits_atomic(db, user_id, 1)


def is_retryable_integrity_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = (
        "could not serialize",
        "serialization",
        "deadlock",
        "database is locked",
    )
    return any(marker in message for marker in retryable_markers)


def log_ai_credit_adjustment(
    db: Session,
    *,
    user_id: int,
    billing: BillingComputation,
    provider: str | None,
    reason_code: str,
) -> models.UserCreditAdjustment:
    payload = {
        "reason_code": reason_code,
        "provider": provider,
        "model_used": billing.model_name,
        "plan_type": billing.plan_type,
        "policy_version": billing.policy_version,
        "feature_key": billing.feature_key,
        "tier_class": billing.tier_class,
        "prompt_tokens": billing.prompt_tokens,
        "completion_tokens": billing.completion_tokens,
        "total_tokens": billing.total_tokens,
        "token_cost_usd": float(billing.token_cost_usd),
        # Primary EUR values (canonical, new code should use these)
        "base_cost_usd": float(billing.base_cost_usd),
        "target_retail_price_usd": float(billing.target_retail_price_usd),
        "credit_value_usd": float(billing.credit_value_usd),
        "real_cost_usd": float(billing.real_cost_usd),
        "implied_revenue_usd": float(billing.implied_revenue_usd),
        "margin_usd": float(billing.margin_usd),
        "margin_pct": float(billing.margin_pct) if billing.margin_pct is not None else None,
        "credits_deducted": billing.credits_to_deduct,
    }
    adjustment = models.UserCreditAdjustment(
        user_id=user_id,
        delta=-max(0, int(billing.credits_to_deduct)),
        reason=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    db.add(adjustment)
    return adjustment


def _recompute_billing_for_policy(
    *,
    billing: BillingComputation,
    policy_version: str,
    feature_key: str,
    tier_class: str,
    fallback_level: int,
    retry_count: int,
    orchestration_hops: int,
) -> BillingComputation:
    usage_payload = {
        "prompt_tokens": max(0, int(billing.prompt_tokens)),
        "completion_tokens": max(0, int(billing.completion_tokens)),
    }
    return calculate_dynamic_billing(
        model_name=billing.model_name,
        usage=usage_payload,
        plan_type=billing.plan_type,
        feature_key=feature_key,
        tier_class=tier_class,
        policy_version=policy_version,
        fallback_level=max(0, int(fallback_level)),
        retry_count=max(0, int(retry_count)),
        orchestration_hops=max(0, int(orchestration_hops)),
    )


def apply_dynamic_ai_credit_charge(
    db: Session,
    *,
    user: models.User,
    billing: BillingComputation,
    provider: str | None,
    reason_code: str,
    feature_key: str | None = None,
    tier_class: str | None = None,
    routing_profile: str | None = None,
    request_id: str | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
    fallback_level: int = 0,
    retry_count: int = 0,
    orchestration_hops: int = 0,
    payload: dict | None = None,
) -> int:
    resolved_feature_key = str(feature_key or billing.feature_key or reason_code or "generic.ai")
    resolved_tier_class = str(tier_class or billing.tier_class or "fast")
    resolved_fallback_level = max(0, int(max(fallback_level, billing.fallback_level)))
    resolved_retry_count = max(0, int(max(retry_count, billing.retry_count)))

    active_policy_version = get_credit_engine_policy_version(db)
    effective_billing = billing
    if billing.policy_version != active_policy_version:
        effective_billing = _recompute_billing_for_policy(
            billing=billing,
            policy_version=active_policy_version,
            feature_key=resolved_feature_key,
            tier_class=resolved_tier_class,
            fallback_level=resolved_fallback_level,
            retry_count=resolved_retry_count,
            orchestration_hops=orchestration_hops,
        )

    shadow_policy_version: str | None = None
    shadow_credits_charged: int | None = None
    shadow_policy_version = resolve_shadow_pricing_policy_version(
        db,
        active_policy_version=active_policy_version,
    )
    if shadow_policy_version is not None:
        shadow_billing = _recompute_billing_for_policy(
            billing=effective_billing,
            policy_version=shadow_policy_version,
            feature_key=resolved_feature_key,
            tier_class=resolved_tier_class,
            fallback_level=resolved_fallback_level,
            retry_count=resolved_retry_count,
            orchestration_hops=orchestration_hops,
        )
        shadow_credits_charged = max(0, int(shadow_billing.credits_to_deduct))

    credits_to_deduct = max(0, int(effective_billing.credits_to_deduct))
    if credits_to_deduct == 0:
        return 0

    decrement_credits_atomic(db, user.id, credits_to_deduct, allow_negative=True)

    log_ai_credit_adjustment(
        db,
        user_id=user.id,
        billing=effective_billing,
        provider=provider,
        reason_code=reason_code,
    )
    record_billing_event_to_ledger(
        db,
        billing=effective_billing,
        provider=provider,
        feature_key=resolved_feature_key,
        request_id=request_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user.id,
        routing_profile=routing_profile,
        shadow_policy_version=shadow_policy_version,
        shadow_credits_charged=shadow_credits_charged,
        payload=dict(payload or {}),
    )
    return credits_to_deduct
