from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, get_args, get_type_hints
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import DateTime, String, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.config.plans import PRIVATE_PLAN_IDS
from billing import Plan
from billing.plan_change_service import (
    PlanChangeDecision,
    PlanChangeKind,
    classify_plan_change,
    clear_pending_plan_change,
    immediate_plan_change_idempotency_key,
    lock_subscription_for_plan_change,
    set_pending_plan_change,
)
from billing.router import create_portal_session, list_plans
from database import Base


def _assert_decision(
    decision: PlanChangeDecision,
    *,
    kind: PlanChangeKind,
    immediate: bool,
    current_plan: str,
    current_interval: str,
    target_plan: Plan,
    target_interval: str,
) -> None:
    assert isinstance(decision, PlanChangeDecision)
    assert decision.kind == kind
    assert decision.immediate is immediate
    assert decision.current_plan == current_plan
    assert decision.current_interval == current_interval
    assert decision.target_plan == target_plan
    assert decision.target_interval == target_interval


def test_same_plan_and_interval_is_invalid() -> None:
    with pytest.raises(ValueError, match="same_plan"):
        classify_plan_change("plan_standard", "month", Plan.STANDARD, "month")


@pytest.mark.parametrize(
    ("current_interval", "target_interval"), [("month", "year"), ("year", "month")]
)
def test_same_plan_interval_change_is_immediate(
    current_interval: str,
    target_interval: str,
) -> None:
    decision = classify_plan_change(
        "plan_standard", current_interval, Plan.STANDARD, target_interval
    )

    _assert_decision(
        decision,
        kind="interval_change",
        immediate=True,
        current_plan="plan_standard",
        current_interval=current_interval,
        target_plan=Plan.STANDARD,
        target_interval=target_interval,
    )


@pytest.mark.parametrize("target_interval", ["month", "year"])
def test_higher_tier_is_immediate_upgrade_including_interval_change(
    target_interval: str,
) -> None:
    decision = classify_plan_change("plan_standard", "month", Plan.SPECIALIST, target_interval)

    _assert_decision(
        decision,
        kind="upgrade",
        immediate=True,
        current_plan="plan_standard",
        current_interval="month",
        target_plan=Plan.SPECIALIST,
        target_interval=target_interval,
    )


def test_lower_tier_is_scheduled_downgrade() -> None:
    decision = classify_plan_change("plan_specialist", "year", Plan.STANDARD, "month")

    _assert_decision(
        decision,
        kind="downgrade",
        immediate=False,
        current_plan="plan_specialist",
        current_interval="year",
        target_plan=Plan.STANDARD,
        target_interval="month",
    )


def test_immediate_idempotency_key_is_stable_per_operation_and_distinct_across_operations() -> None:
    decision = classify_plan_change(
        "plan_standard",
        "month",
        Plan.STANDARD,
        "year",
    )

    first = immediate_plan_change_idempotency_key(
        subscription_id=17,
        stripe_mode="test",
        decision=decision,
        operation_id="pc_operation_one",
    )
    first_retry = immediate_plan_change_idempotency_key(
        subscription_id=17,
        stripe_mode="test",
        decision=decision,
        operation_id="pc_operation_one",
    )
    later_repeat = immediate_plan_change_idempotency_key(
        subscription_id=17,
        stripe_mode="test",
        decision=decision,
        operation_id="pc_operation_two",
    )

    assert first == first_retry
    assert first != later_repeat
    assert first.endswith(":pc_operation_one")
    assert later_repeat.endswith(":pc_operation_two")


def test_plan_change_decision_contract_is_explicit_and_typed() -> None:
    hints = get_type_hints(PlanChangeDecision)
    required_fields = {
        "kind",
        "immediate",
        "current_plan",
        "current_interval",
        "target_plan",
        "target_interval",
    }

    assert required_fields <= hints.keys()
    assert all(hints[field] is not Any for field in required_fields)
    assert hints["immediate"] is bool
    assert set(get_args(hints["kind"])) == {
        "upgrade",
        "downgrade",
        "interval_change",
    }


@pytest.fixture
def sqlite_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _subscription(**pending_fields: object) -> models.Subscription:
    values: dict[str, object] = {
        "stripe_customer_id": "cus_pending_plan_change",
        "stripe_subscription_id": "sub_pending_plan_change",
        "stripe_mode": "test",
        "plan_type": "plan_specialist",
        "status": "active",
        "billing_interval": "year",
    }
    values.update(pending_fields)
    return models.Subscription(**values)


def test_subscription_exposes_typed_pending_plan_change_fields() -> None:
    columns = models.Subscription.__table__.c

    assert isinstance(columns.stripe_schedule_id.type, String)
    assert columns.stripe_schedule_id.type.length == 255
    assert isinstance(columns.managed_plan_change_schedule_id.type, String)
    assert columns.managed_plan_change_schedule_id.type.length == 255
    assert columns.managed_plan_change_schedule_id.nullable is True
    assert isinstance(columns.pending_plan_type.type, String)
    assert isinstance(columns.pending_billing_interval.type, String)
    assert columns.pending_billing_interval.type.length == 8
    assert isinstance(columns.pending_change_effective_at.type, DateTime)
    assert columns.pending_change_effective_at.type.timezone is True


def test_subscription_exposes_nullable_plan_state_event_fence_and_persists_it_through_sqlite(
    sqlite_session: Session,
) -> None:
    column = models.Subscription.__table__.c.plan_state_event_created_at
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
    assert column.nullable is True

    fence = datetime(2027, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    subscription = _subscription(plan_state_event_created_at=fence)
    sqlite_session.add(subscription)
    sqlite_session.commit()
    subscription_id = subscription.id
    sqlite_session.expire_all()

    stored = sqlite_session.get(models.Subscription, subscription_id)
    assert stored is not None
    assert stored.plan_state_event_created_at is not None
    assert stored.plan_state_event_created_at.replace(tzinfo=timezone.utc) == fence


def test_subscription_persists_nullable_managed_plan_change_schedule_id(
    sqlite_session: Session,
) -> None:
    subscription = _subscription(managed_plan_change_schedule_id="sub_sched_managed_history")
    sqlite_session.add(subscription)
    sqlite_session.commit()
    subscription_id = subscription.id
    sqlite_session.expire_all()

    stored = sqlite_session.get(models.Subscription, subscription_id)
    assert stored is not None
    assert stored.managed_plan_change_schedule_id == "sub_sched_managed_history"
    stored.managed_plan_change_schedule_id = None
    sqlite_session.commit()
    sqlite_session.expire_all()

    cleared = sqlite_session.get(models.Subscription, subscription_id)
    assert cleared is not None
    assert cleared.managed_plan_change_schedule_id is None


def test_subscription_persists_and_clears_complete_pending_state(
    sqlite_session: Session,
) -> None:
    effective_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    subscription = _subscription(
        stripe_schedule_id="sub_sched_123",
        pending_plan_type="plan_standard",
        pending_billing_interval="month",
        pending_change_effective_at=effective_at,
    )
    sqlite_session.add(subscription)
    sqlite_session.commit()
    subscription_id = subscription.id
    sqlite_session.expire_all()

    stored = sqlite_session.get(models.Subscription, subscription_id)
    assert stored is not None
    assert stored.stripe_schedule_id == "sub_sched_123"
    assert stored.pending_plan_type == "plan_standard"
    assert stored.pending_billing_interval == "month"
    assert stored.pending_change_effective_at is not None
    assert stored.pending_change_effective_at.replace(tzinfo=timezone.utc) == effective_at

    stored.stripe_schedule_id = None
    stored.pending_plan_type = None
    stored.pending_billing_interval = None
    stored.pending_change_effective_at = None
    sqlite_session.commit()
    sqlite_session.expire_all()

    cleared = sqlite_session.get(models.Subscription, subscription_id)
    assert cleared is not None
    assert cleared.stripe_schedule_id is None
    assert cleared.pending_plan_type is None
    assert cleared.pending_billing_interval is None
    assert cleared.pending_change_effective_at is None


def test_incomplete_pending_state_violates_database_constraint(
    sqlite_session: Session,
) -> None:
    sqlite_session.add(_subscription(stripe_schedule_id="sub_sched_incomplete"))

    with pytest.raises(IntegrityError):
        sqlite_session.commit()


def _pending_state(subscription: models.Subscription) -> tuple[object, ...]:
    return (
        subscription.stripe_schedule_id,
        subscription.pending_plan_type,
        subscription.pending_billing_interval,
        subscription.pending_change_effective_at,
    )


def test_lock_subscription_force_refreshes_identity_and_uses_for_update(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effective_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    subscription = _subscription(
        stripe_schedule_id="sub_sched_original",
        pending_plan_type="plan_standard",
        pending_billing_interval="month",
        pending_change_effective_at=effective_at,
    )
    sqlite_session.add(subscription)
    sqlite_session.commit()

    with Session(sqlite_session.get_bind(), expire_on_commit=False) as replacement_db:
        replacement = replacement_db.get(models.Subscription, subscription.id)
        assert replacement is not None
        replacement.stripe_schedule_id = "sub_sched_replacement"
        replacement.pending_plan_type = "plan_starter"
        replacement.pending_billing_interval = "year"
        replacement.pending_change_effective_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        replacement_db.commit()

    assert subscription.stripe_schedule_id == "sub_sched_original"
    statements = []
    execute = sqlite_session.execute

    def capture_statement(statement, *args, **kwargs):
        statements.append(statement)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(sqlite_session, "execute", capture_statement)
    locked = lock_subscription_for_plan_change(sqlite_session, subscription.id)

    assert locked is subscription
    assert locked.stripe_schedule_id == "sub_sched_replacement"
    assert locked.pending_plan_type == "plan_starter"
    assert locked.pending_billing_interval == "year"
    assert len(statements) == 1
    assert statements[0].get_execution_options()["populate_existing"] is True
    assert statements[0]._for_update_arg is not None


def test_lock_subscription_fails_when_row_is_missing(sqlite_session: Session) -> None:
    with pytest.raises(ValueError, match="subscription_not_found"):
        lock_subscription_for_plan_change(sqlite_session, 999_999)


def test_set_pending_plan_change_sets_complete_state_without_committing(
    sqlite_session: Session,
) -> None:
    subscription = _subscription()
    sqlite_session.add(subscription)
    sqlite_session.commit()
    locked = lock_subscription_for_plan_change(sqlite_session, subscription.id)
    effective_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    set_pending_plan_change(
        locked,
        stripe_schedule_id="sub_sched_set",
        target_plan=Plan.STANDARD,
        target_interval="month",
        effective_at=effective_at,
    )

    assert _pending_state(locked) == (
        "sub_sched_set",
        "plan_standard",
        "month",
        effective_at,
    )
    sqlite_session.rollback()
    sqlite_session.expire_all()
    persisted = sqlite_session.get(models.Subscription, subscription.id)
    assert persisted is not None
    assert _pending_state(persisted) == (None, None, None, None)


@pytest.mark.parametrize(
    ("target_plan", "target_interval", "error"),
    [
        (Plan.AGENCY_TRIAL, "month", "invalid_target_plan"),
        (Plan.STANDARD, "week", "invalid_target_interval"),
    ],
)
def test_set_pending_plan_change_rejects_invalid_target_before_mutation(
    target_plan: Plan,
    target_interval: str,
    error: str,
) -> None:
    effective_at = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    subscription = _subscription(
        stripe_schedule_id="sub_sched_existing",
        pending_plan_type="plan_starter",
        pending_billing_interval="year",
        pending_change_effective_at=effective_at,
    )
    original_state = _pending_state(subscription)

    with pytest.raises(ValueError, match=error):
        set_pending_plan_change(
            subscription,
            stripe_schedule_id="sub_sched_invalid",
            target_plan=target_plan,
            target_interval=target_interval,
            effective_at=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
        )

    assert _pending_state(subscription) == original_state


def test_clear_pending_plan_change_clears_complete_matching_state() -> None:
    subscription = _subscription(
        stripe_schedule_id="sub_sched_clear",
        pending_plan_type="plan_standard",
        pending_billing_interval="month",
        pending_change_effective_at=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
    )

    cleared = clear_pending_plan_change(
        subscription,
        expected_schedule_id="sub_sched_clear",
        expected_plan=Plan.STANDARD,
        expected_interval="month",
    )

    assert cleared is True
    assert _pending_state(subscription) == (None, None, None, None)


@pytest.mark.parametrize(
    ("expected_schedule_id", "expected_plan", "expected_interval"),
    [
        ("sub_sched_stale", Plan.STANDARD, "month"),
        ("sub_sched_replacement", Plan.SPECIALIST, "month"),
        ("sub_sched_replacement", Plan.STANDARD, "year"),
    ],
)
def test_clear_pending_plan_change_preserves_replacement_on_stale_expectation(
    expected_schedule_id: str,
    expected_plan: Plan,
    expected_interval: str,
) -> None:
    replacement_effective_at = datetime(2027, 1, 1, 12, 0, tzinfo=timezone.utc)
    subscription = _subscription(
        stripe_schedule_id="sub_sched_replacement",
        pending_plan_type="plan_standard",
        pending_billing_interval="month",
        pending_change_effective_at=replacement_effective_at,
    )
    replacement_state = _pending_state(subscription)

    cleared = clear_pending_plan_change(
        subscription,
        expected_schedule_id=expected_schedule_id,
        expected_plan=expected_plan,
        expected_interval=expected_interval,
    )

    assert cleared is False
    assert _pending_state(subscription) == replacement_state


_RECONCILIATION_EFFECTIVE_AT = datetime(2027, 2, 1, 12, 0, tzinfo=timezone.utc)
_RECONCILIATION_EVENT = {
    "subscription_id": "sub_pending_plan_change",
    "customer_id": "cus_pending_plan_change",
    "stripe_mode": "test",
    "resolved_plan_type": "plan_standard",
    "billing_interval": "month",
    "schedule_id": "sub_sched_reconcile",
    "current_period_start": _RECONCILIATION_EFFECTIVE_AT,
}


def _stored_pending_subscription(sqlite_session: Session) -> models.Subscription:
    subscription = _subscription(
        stripe_schedule_id="sub_sched_reconcile",
        pending_plan_type="plan_standard",
        pending_billing_interval="month",
        pending_change_effective_at=_RECONCILIATION_EFFECTIVE_AT,
    )
    sqlite_session.add(subscription)
    sqlite_session.commit()
    subscription_id = subscription.id
    sqlite_session.expire_all()
    stored = sqlite_session.get(models.Subscription, subscription_id)
    assert stored is not None
    return stored


def _reconcile(
    subscription: models.Subscription,
    *,
    source_event_created_at: datetime,
    **overrides: object,
) -> bool:
    from billing.plan_change_service import reconcile_pending_plan_change

    event = {**_RECONCILIATION_EVENT, **overrides}
    return reconcile_pending_plan_change(
        subscription,
        source_event_created_at=source_event_created_at,
        current_period_start=event["current_period_start"],
        subscription_id=event["subscription_id"],
        customer_id=event["customer_id"],
        stripe_mode=event["stripe_mode"],
        resolved_plan_type=event["resolved_plan_type"],
        billing_interval=event["billing_interval"],
        schedule_id=event["schedule_id"],
    )


def _complete_plan_change_state(subscription: models.Subscription) -> tuple[object, ...]:
    return (
        subscription.plan_type,
        subscription.billing_interval,
        *_pending_state(subscription),
    )


def test_reconcile_matching_boundary_activates_even_when_event_delivery_is_delayed(
    sqlite_session: Session,
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)

    activated = _reconcile(
        subscription,
        source_event_created_at=_RECONCILIATION_EFFECTIVE_AT + timedelta(days=2),
        current_period_start=_RECONCILIATION_EFFECTIVE_AT,
    )

    assert activated is True
    assert _complete_plan_change_state(subscription) == (
        "plan_standard",
        "month",
        None,
        None,
        None,
        None,
    )
    assert subscription.managed_plan_change_schedule_id == "sub_sched_reconcile"

    sqlite_session.rollback()
    sqlite_session.expire_all()
    persisted = sqlite_session.get(models.Subscription, subscription.id)
    assert persisted is not None
    assert _complete_plan_change_state(persisted) == (
        "plan_specialist",
        "year",
        "sub_sched_reconcile",
        "plan_standard",
        "month",
        _RECONCILIATION_EFFECTIVE_AT.replace(tzinfo=None),
    )


@pytest.mark.parametrize(
    "current_period_start",
    [
        _RECONCILIATION_EFFECTIVE_AT - timedelta(microseconds=1),
        _RECONCILIATION_EFFECTIVE_AT + timedelta(seconds=1),
    ],
    ids=["before_boundary", "after_boundary"],
)
def test_reconcile_later_event_with_mismatched_period_start_preserves_pending_state(
    sqlite_session: Session,
    current_period_start: datetime,
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)
    original_state = _complete_plan_change_state(subscription)

    activated = _reconcile(
        subscription,
        source_event_created_at=_RECONCILIATION_EFFECTIVE_AT + timedelta(days=3),
        current_period_start=current_period_start,
    )

    assert activated is False
    assert _complete_plan_change_state(subscription) == original_state
    assert subscription.plan_type == "plan_specialist"
    assert subscription.billing_interval == "year"


@pytest.mark.parametrize(
    "overrides",
    [
        {"resolved_plan_type": "plan_starter"},
        {"billing_interval": "year"},
        {"schedule_id": "sub_sched_stale"},
        {"customer_id": "cus_stale"},
        {"subscription_id": "sub_stale"},
        {"stripe_mode": "live"},
    ],
    ids=["plan", "interval", "schedule", "customer", "subscription", "mode"],
)
def test_reconcile_identity_mismatch_fails_closed_and_preserves_pending_state(
    sqlite_session: Session,
    overrides: dict[str, object],
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)
    original_state = _complete_plan_change_state(subscription)

    activated = _reconcile(
        subscription,
        source_event_created_at=_RECONCILIATION_EFFECTIVE_AT + timedelta(hours=1),
        **overrides,
    )

    assert activated is False
    assert _complete_plan_change_state(subscription) == original_state


def test_reconcile_duplicate_delivery_after_pending_state_is_cleared_is_no_op(
    sqlite_session: Session,
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)
    source_event_created_at = _RECONCILIATION_EFFECTIVE_AT + timedelta(hours=1)
    assert (
        _reconcile(
            subscription,
            source_event_created_at=source_event_created_at,
        )
        is True
    )
    activated_state = _complete_plan_change_state(subscription)

    assert (
        _reconcile(
            subscription,
            source_event_created_at=source_event_created_at,
        )
        is False
    )
    assert _complete_plan_change_state(subscription) == activated_state
    assert subscription.managed_plan_change_schedule_id == "sub_sched_reconcile"


def test_reconcile_compares_aware_period_boundary_to_sqlite_datetime_safely(
    sqlite_session: Session,
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)
    assert subscription.pending_change_effective_at is not None
    assert subscription.pending_change_effective_at.tzinfo is None
    stripe_period_start = int(_RECONCILIATION_EFFECTIVE_AT.timestamp())
    current_period_start = datetime.fromtimestamp(stripe_period_start, tz=timezone.utc)
    assert current_period_start.tzinfo is timezone.utc

    assert (
        _reconcile(
            subscription,
            source_event_created_at=_RECONCILIATION_EFFECTIVE_AT + timedelta(hours=1),
            current_period_start=current_period_start,
        )
        is True
    )
    assert subscription.plan_type == "plan_standard"
    assert subscription.billing_interval == "month"
    assert _pending_state(subscription) == (None, None, None, None)
    assert subscription.managed_plan_change_schedule_id == "sub_sched_reconcile"


def test_reconcile_rejects_naive_source_event_timestamp_without_mutation(
    sqlite_session: Session,
) -> None:
    subscription = _stored_pending_subscription(sqlite_session)
    original_state = _complete_plan_change_state(subscription)

    with pytest.raises(ValueError, match="invalid_source_event_created_at"):
        _reconcile(
            subscription,
            source_event_created_at=_RECONCILIATION_EFFECTIVE_AT.replace(tzinfo=None),
        )

    assert _complete_plan_change_state(subscription) == original_state


class _OverviewBillingConfig:
    def __init__(self, stripe_mode: str = "test") -> None:
        self.stripe_mode = stripe_mode
        self.app_base_url = "https://app.example.test"
        self.mode_configs = {
            "test": SimpleNamespace(secret_key="sk_test_portal"),
            "live": SimpleNamespace(secret_key="sk_live_portal"),
        }
        self.default_price_lookups: list[tuple[Plan, str]] = []
        self.price_mode_lookups: list[tuple[str, Plan, str]] = []

    def price_id_for(self, plan: Plan, interval: str = "month") -> str:
        self.default_price_lookups.append((plan, interval))
        return self.price_id_for_mode(self.stripe_mode, plan, interval)

    def price_id_for_mode(
        self,
        mode: str,
        plan: Plan,
        interval: str = "month",
    ) -> str:
        self.price_mode_lookups.append((mode, plan, interval))
        if (mode, interval) not in {("live", "month"), ("test", "year")}:
            return ""
        return f"price_{mode}_{plan.value}_{interval}"


def _overview_user_with_pending_state(**pending_fields: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "plan_type": "plan_specialist",
        "status": "active",
        "billing_interval": "year",
        "stripe_mode": "test",
        "stripe_customer_id": "cus_overview_pending",
        "stripe_schedule_id": "sub_sched_overview_pending",
        "pending_plan_type": "plan_standard",
        "pending_billing_interval": "month",
        "pending_change_effective_at": datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    values.update(pending_fields)
    return SimpleNamespace(
        id=314,
        resolved_portal_only=False,
        subscription=SimpleNamespace(**values),
    )


_RESTRICTED_PORTAL_CONFIGURATION_METADATA = {"qiko_portal_configuration": "restricted_v1"}
_RESTRICTED_PORTAL_FEATURES = {
    "subscription_update": {"enabled": False},
    "subscription_cancel": {"enabled": False},
    "invoice_history": {"enabled": True},
    "payment_method_update": {"enabled": True},
}


def _portal_configuration(
    configuration_id: str,
    *,
    features: object = _RESTRICTED_PORTAL_FEATURES,
) -> dict[str, object]:
    return {
        "id": configuration_id,
        "active": True,
        "metadata": dict(_RESTRICTED_PORTAL_CONFIGURATION_METADATA),
        "features": features,
    }


def _stored_portal_user(sqlite_session: Session) -> models.User:
    user = models.User(
        email="restricted-portal@example.test",
        hashed_password="x",
        role="user",
        credits=5,
    )
    sqlite_session.add(user)
    sqlite_session.flush()
    sqlite_session.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_restricted_portal",
            stripe_subscription_id="sub_restricted_portal",
            stripe_mode="test",
            plan_type="plan_specialist",
            status="active",
            billing_interval="year",
        )
    )
    sqlite_session.commit()
    sqlite_session.refresh(user)
    assert user.subscription is not None
    return user


def _assert_subscription_lock_and_reload(statements: list[object]) -> None:
    subscription_locks = [
        statement
        for statement in statements
        if getattr(statement, "_for_update_arg", None) is not None
        and getattr(statement, "column_descriptions", None)
        and statement.column_descriptions[0].get("entity") is models.Subscription
    ]
    assert subscription_locks
    assert subscription_locks[-1].get_execution_options()["populate_existing"] is True


def _plan_from_overview(payload: dict[str, object], plan: Plan) -> dict[str, object]:
    plans = payload["plans"]
    assert isinstance(plans, list)
    return next(entry for entry in plans if entry["id"] == plan.value)


@pytest.mark.parametrize(
    ("runtime_mode", "subscription_mode", "available_interval"),
    [
        ("test", "live", "month"),
        ("live", "test", "year"),
    ],
    ids=["runtime_test_active_live", "runtime_live_active_test"],
)
def test_list_plans_uses_active_subscription_mode_for_interval_availability(
    monkeypatch: pytest.MonkeyPatch,
    runtime_mode: str,
    subscription_mode: str,
    available_interval: str,
) -> None:
    config = _OverviewBillingConfig(stripe_mode=runtime_mode)
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: config,
    )

    payload = list_plans(
        http_request=None,
        user=_overview_user_with_pending_state(stripe_mode=subscription_mode),
        db=None,
    )

    standard = _plan_from_overview(payload, Plan.STANDARD)
    expected_monthly_id = (
        f"price_{subscription_mode}_{Plan.STANDARD.value}_month"
        if available_interval == "month"
        else ""
    )
    expected_annual_id = (
        f"price_{subscription_mode}_{Plan.STANDARD.value}_year"
        if available_interval == "year"
        else ""
    )
    assert standard["price_id"] == expected_monthly_id
    assert standard["checkout_available"] is bool(expected_monthly_id)
    assert standard["annual_price_id"] == expected_annual_id
    assert standard["annual_checkout_available"] is bool(expected_annual_id)
    assert config.default_price_lookups == []
    assert config.price_mode_lookups
    assert {mode for mode, _plan, _interval in config.price_mode_lookups} == {subscription_mode}
    # The customer plans surface lists every sellable plan, so every sellable
    # plan's prices are resolved in the subscription's mode. Private plans are
    # not listed and their prices are not looked up.
    sellable = [plan for plan in Plan if plan.value not in PRIVATE_PLAN_IDS]
    assert {(plan, interval) for _mode, plan, interval in config.price_mode_lookups} >= {
        (plan, interval) for plan in sellable for interval in ("month", "year")
    }


@pytest.mark.parametrize(
    ("runtime_mode", "available_interval"),
    [("live", "month"), ("test", "year")],
)
def test_list_plans_without_active_subscription_uses_runtime_default_mode(
    monkeypatch: pytest.MonkeyPatch,
    runtime_mode: str,
    available_interval: str,
) -> None:
    config = _OverviewBillingConfig(stripe_mode=runtime_mode)
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: config,
    )
    user = SimpleNamespace(resolved_portal_only=False, subscription=None)

    payload = list_plans(http_request=None, user=user, db=None)

    standard = _plan_from_overview(payload, Plan.STANDARD)
    assert standard["checkout_available"] is (available_interval == "month")
    assert standard["annual_checkout_available"] is (available_interval == "year")
    assert config.price_mode_lookups
    assert {mode for mode, _plan, _interval in config.price_mode_lookups} == {runtime_mode}


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_list_plans_exposes_complete_pending_plan_change_contract(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )

    payload = list_plans(
        http_request=None,
        user=_overview_user_with_pending_state(status=status),
        db=None,
    )

    assert payload["status"] == status
    assert payload["current_plan"] == "plan_specialist"
    assert payload["pending_plan_change"] == {
        "target_plan": "plan_standard",
        "target_billing_interval": "month",
        "effective_at": "2027-03-01T12:00:00+00:00",
        "schedule_id": "sub_sched_overview_pending",
    }


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_portal_session_rejects_complete_pending_plan_change_before_stripe_call(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    configuration_list = MagicMock()
    configuration_create = MagicMock()
    portal_create = MagicMock()
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.list",
        configuration_list,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.create",
        configuration_create,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Session.create",
        portal_create,
    )
    user = _overview_user_with_pending_state(status=status)

    with pytest.raises(HTTPException) as exc_info:
        create_portal_session(http_request=None, user=user, db=None)

    assert exc_info.value.status_code == 409
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["code"] == "pending_plan_change_conflict"
    assert exc_info.value.detail["pending_plan_change"] == {
        "schedule_id": "sub_sched_overview_pending",
        "target_plan": "plan_standard",
        "target_billing_interval": "month",
        "effective_at": "2027-03-01T12:00:00+00:00",
    }
    configuration_list.assert_not_called()
    configuration_create.assert_not_called()
    portal_create.assert_not_called()


def test_portal_session_remains_available_without_pending_plan_change_and_reuses_validated_configuration(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration_id = "bpc_restricted_existing"
    foreign_configuration = _portal_configuration("bpc_foreign_restricted")
    foreign_configuration["metadata"] = {}
    configuration_list = MagicMock(
        return_value=SimpleNamespace(
            data=[foreign_configuration, _portal_configuration(configuration_id)]
        )
    )
    configuration_create = MagicMock()
    portal_create = MagicMock(
        return_value=SimpleNamespace(url="https://billing.example.test/session")
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.list",
        configuration_list,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.create",
        configuration_create,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Session.create",
        portal_create,
    )
    user = _stored_portal_user(sqlite_session)
    statements: list[object] = []
    execute = sqlite_session.execute

    def capture_statement(statement, *args, **kwargs):
        statements.append(statement)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(sqlite_session, "execute", capture_statement)

    payload = create_portal_session(
        http_request=None,
        user=user,
        db=sqlite_session,
    )

    assert payload == {"url": "https://billing.example.test/session"}
    _assert_subscription_lock_and_reload(statements)
    configuration_list.assert_called_once()
    configuration_create.assert_not_called()
    portal_create.assert_called_once()
    assert portal_create.call_args.kwargs["api_key"] == "sk_test_portal"
    assert portal_create.call_args.kwargs["customer"] == "cus_restricted_portal"
    assert portal_create.call_args.kwargs["return_url"] == (
        "https://app.example.test/dashboard/billing"
    )
    assert portal_create.call_args.kwargs["configuration"] == configuration_id


def test_portal_session_locks_subscription_and_creates_restricted_configuration(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration_id = "bpc_restricted_created"
    configuration_list = MagicMock(return_value=SimpleNamespace(data=[]))
    configuration_create = MagicMock(return_value=_portal_configuration(configuration_id))
    portal_create = MagicMock(
        return_value=SimpleNamespace(url="https://billing.example.test/restricted")
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.list",
        configuration_list,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.create",
        configuration_create,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Session.create",
        portal_create,
    )
    user = _stored_portal_user(sqlite_session)
    statements: list[object] = []
    execute = sqlite_session.execute

    def capture_statement(statement, *args, **kwargs):
        statements.append(statement)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(sqlite_session, "execute", capture_statement)

    payload = create_portal_session(http_request=None, user=user, db=sqlite_session)

    assert payload == {"url": "https://billing.example.test/restricted"}
    _assert_subscription_lock_and_reload(statements)
    configuration_list.assert_called_once()
    configuration_create.assert_called_once()
    create_kwargs = configuration_create.call_args.kwargs
    assert create_kwargs["features"] == _RESTRICTED_PORTAL_FEATURES
    assert create_kwargs["metadata"] == _RESTRICTED_PORTAL_CONFIGURATION_METADATA
    portal_create.assert_called_once()
    assert portal_create.call_args.kwargs["configuration"] == configuration_id


@pytest.mark.parametrize(
    "features",
    [
        {
            "subscription_update": {"enabled": False},
            "subscription_cancel": {"enabled": False},
            "payment_method_update": {"enabled": True},
        },
        {
            **_RESTRICTED_PORTAL_FEATURES,
            "subscription_update": {"enabled": True},
        },
        {
            **_RESTRICTED_PORTAL_FEATURES,
            "subscription_cancel": {"enabled": True},
        },
    ],
    ids=["malformed", "subscription_mutation_enabled", "cancellation_enabled"],
)
def test_portal_session_fails_closed_when_created_configuration_is_not_restricted(
    monkeypatch: pytest.MonkeyPatch,
    features: dict[str, object],
) -> None:
    configuration_create = MagicMock(
        return_value=_portal_configuration("bpc_unsafe", features=features)
    )
    portal_create = MagicMock()
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.list",
        MagicMock(return_value=SimpleNamespace(data=[])),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.create",
        configuration_create,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Session.create",
        portal_create,
    )
    user = _overview_user_with_pending_state(
        stripe_schedule_id=None,
        pending_plan_type=None,
        pending_billing_interval=None,
        pending_change_effective_at=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        create_portal_session(http_request=None, user=user, db=None)

    assert exc_info.value.status_code == 503
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["code"] == "billing_portal_configuration_invalid"
    configuration_create.assert_called_once()
    portal_create.assert_not_called()


def test_portal_session_reloads_locked_subscription_and_detects_new_pending_conflict(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _stored_portal_user(sqlite_session)
    assert user.subscription is not None
    assert user.subscription.stripe_schedule_id is None
    with Session(sqlite_session.get_bind(), expire_on_commit=False) as updater_db:
        replacement = updater_db.get(models.Subscription, user.subscription.id)
        assert replacement is not None
        replacement.stripe_schedule_id = "sub_sched_concurrent_portal"
        replacement.pending_plan_type = "plan_standard"
        replacement.pending_billing_interval = "month"
        replacement.pending_change_effective_at = datetime(2027, 4, 1, 12, 0, tzinfo=timezone.utc)
        updater_db.commit()

    configuration_list = MagicMock()
    configuration_create = MagicMock()
    portal_create = MagicMock()
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.list",
        configuration_list,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Configuration.create",
        configuration_create,
    )
    monkeypatch.setattr(
        "billing.router.stripe.billing_portal.Session.create",
        portal_create,
    )
    statements: list[object] = []
    execute = sqlite_session.execute

    def capture_statement(statement, *args, **kwargs):
        statements.append(statement)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(sqlite_session, "execute", capture_statement)

    with pytest.raises(HTTPException) as exc_info:
        create_portal_session(http_request=None, user=user, db=sqlite_session)

    assert exc_info.value.status_code == 409
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["code"] == "pending_plan_change_conflict"
    assert exc_info.value.detail["pending_plan_change"] == {
        "schedule_id": "sub_sched_concurrent_portal",
        "target_plan": "plan_standard",
        "target_billing_interval": "month",
        "effective_at": "2027-04-01T12:00:00",
    }
    _assert_subscription_lock_and_reload(statements)
    configuration_list.assert_not_called()
    configuration_create.assert_not_called()
    portal_create.assert_not_called()


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_list_plans_hides_complete_pending_plan_change_for_terminal_subscription(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )

    payload = list_plans(
        http_request=None,
        user=_overview_user_with_pending_state(status=status),
        db=None,
    )

    assert payload["status"] == status
    assert payload["current_plan"] is None
    assert payload["pending_plan_change"] is None


@pytest.mark.parametrize(
    "pending_fields",
    [
        {
            "stripe_schedule_id": None,
            "pending_plan_type": None,
            "pending_billing_interval": None,
            "pending_change_effective_at": None,
        },
        {"stripe_schedule_id": None},
        {"pending_plan_type": None},
        {"pending_billing_interval": None},
        {"pending_change_effective_at": None},
    ],
    ids=[
        "absent",
        "missing_schedule",
        "missing_plan",
        "missing_interval",
        "missing_effective_at",
    ],
)
def test_list_plans_returns_null_for_incomplete_pending_plan_change_state(
    monkeypatch: pytest.MonkeyPatch,
    pending_fields: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "billing.router.get_billing_config",
        lambda _request, _db=None: _OverviewBillingConfig(),
    )

    payload = list_plans(
        http_request=None,
        user=_overview_user_with_pending_state(**pending_fields),
        db=None,
    )

    assert payload["pending_plan_change"] is None
