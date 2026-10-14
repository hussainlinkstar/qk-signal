import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

from billing import Plan
from billing.base_checkout_service import (
    BaseCheckoutConflictError,
    BaseCheckoutValidationError,
    base_checkout_metadata,
    lock_base_checkout_attempt,
    resolve_base_checkout_attempt,
    validate_base_checkout_session,
)
from billing.router import (
    CheckoutSessionRequest,
    UpgradePreviewRequest,
    UpgradeRequest,
    _reconcile_base_checkout_session,
    create_checkout_session,
    execute_plan_change,
    preview_plan_change,
)
from database import Base
import models


class _FakeConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}

    def price_id_for(self, plan: Plan, interval: str = "month") -> str:
        return f"price_{plan.value}_{interval}"


class _FakeDb:
    pass


def _subscription(
    status: str,
    *,
    stripe_subscription_id: str | None = None,
    plan_type: str = "plan_standard",
    cancel_at_period_end: bool = False,
):
    return SimpleNamespace(
        status=status,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id="cus_existing",
        stripe_mode="test",
        plan_type=plan_type,
        cancel_at_period_end=cancel_at_period_end,
    )


def _user(subscription=None):
    return SimpleNamespace(
        id=7,
        email="user@example.com",
        external_id="external-7",
        subscription=subscription,
    )


def _install_locked_state(monkeypatch: pytest.MonkeyPatch, user, subscription) -> None:
    monkeypatch.setattr(
        "billing.router._lock_checkout_billing_state",
        lambda _db, *, user_id, authenticated_user: (user, subscription),
    )


def _install_side_effect_spies(monkeypatch: pytest.MonkeyPatch):
    calls = {"config": 0, "customer": 0, "checkout": 0}
    attempt = SimpleNamespace(
        id="bca_test",
        user_id=7,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
        status="pending",
        stripe_customer_id=None,
        stripe_session_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    def _config(*_args, **_kwargs):
        calls["config"] += 1
        return _FakeConfig()

    def _resolve_attempt(
        _db,
        *,
        user_id,
        stripe_mode,
        target_plan,
        billing_interval,
    ):
        attempt.user_id = user_id
        attempt.stripe_mode = stripe_mode
        attempt.target_plan = target_plan
        attempt.billing_interval = billing_interval
        return SimpleNamespace(attempt=attempt, created=True)

    def _customer(**_kwargs):
        calls["customer"] += 1
        return "cus_existing"

    def _link_customer(_db, *, attempt_id, stripe_customer_id, commit=True):
        attempt.stripe_customer_id = stripe_customer_id
        attempt.status = "customer_created"
        return attempt

    def _checkout(**kwargs):
        calls["checkout"] += 1
        return SimpleNamespace(
            id="cs_test",
            url="https://checkout.stripe.test/session",
            status="open",
            mode="subscription",
            customer=kwargs["customer"],
            metadata=kwargs["metadata"],
            client_reference_id=kwargs["client_reference_id"],
            livemode=False,
        )

    monkeypatch.setattr("billing.router.get_billing_config", _config)
    monkeypatch.setattr("billing.router.resolve_base_checkout_attempt", _resolve_attempt)
    monkeypatch.setattr("billing.router.ensure_stripe_customer", _customer)
    monkeypatch.setattr("billing.router.link_base_checkout_customer", _link_customer)
    monkeypatch.setattr(
        "billing.router.link_base_checkout_session",
        lambda _db, **_kwargs: attempt,
    )
    monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _checkout)
    return calls


@pytest.mark.parametrize("status", ["active", "trialing"])
@pytest.mark.parametrize("cancel_at_period_end", [False, True])
def test_checkout_rejects_entitled_subscription_before_stripe_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    cancel_at_period_end: bool,
) -> None:
    subscription = _subscription(
        status,
        stripe_subscription_id="sub_existing",
        cancel_at_period_end=cancel_at_period_end,
    )
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.SPECIALIST),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "base_subscription_checkout_conflict",
        "message": "You already have an active subscription. Use plan management to change your plan.",
        "current_plan": "plan_standard",
        "current_status": status,
        "route": "/billing/upgrade",
    }
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


@pytest.mark.parametrize("status", ["past_due", "unpaid", "incomplete", "paused"])
def test_checkout_rejects_recoverable_subscription_before_stripe_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    subscription = _subscription(status, stripe_subscription_id="sub_existing")
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.SPECIALIST),
            user=user,
            db=_FakeDb(),
        )

    detail = exc_info.value.detail
    assert exc_info.value.status_code == 409
    assert detail["code"] == "base_subscription_checkout_conflict"
    assert detail["message"] == (
        "Your subscription needs attention before starting a new checkout. "
        "Use billing recovery to continue."
    )
    assert detail["current_plan"] == "plan_standard"
    assert detail["current_status"] == status
    assert detail["route"] == "/billing/portal-session"
    assert "sub_existing" not in str(detail)
    assert "cus_existing" not in str(detail)
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_checkout_rejects_other_nonterminal_subscription_with_stripe_id(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    subscription = _subscription(status, stripe_subscription_id="sub_pending")
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "base_subscription_checkout_conflict"
    assert exc_info.value.detail["current_status"] == status
    assert exc_info.value.detail["route"] == "/billing/portal-session"
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


@pytest.mark.parametrize(
    "status",
    [None, "", "   "],
    ids=["missing", "blank", "whitespace"],
)
def test_checkout_rejects_missing_or_blank_status_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
    status: str | None,
) -> None:
    subscription = _subscription("pending", stripe_subscription_id=None)
    subscription.status = status
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "base_subscription_checkout_conflict"
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


def test_checkout_rejects_manual_active_entitlement_without_subscription_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = _subscription("active", stripe_subscription_id=None)
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.SPECIALIST),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["route"] == "/billing/upgrade"
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


@pytest.mark.parametrize(
    ("status", "stripe_subscription_id"),
    [("pending", None), ("canceled", "sub_old"), ("incomplete_expired", "sub_old")],
)
def test_checkout_allows_placeholder_and_terminal_subscription_states(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    stripe_subscription_id: str | None,
) -> None:
    subscription = _subscription(status, stripe_subscription_id=stripe_subscription_id)
    user = _user(subscription)
    _install_locked_state(monkeypatch, user, subscription)
    calls = _install_side_effect_spies(monkeypatch)

    result = create_checkout_session(
        http_request=None,
        request=CheckoutSessionRequest(plan=Plan.STANDARD),
        user=user,
        db=_FakeDb(),
    )

    assert result == {"id": "cs_test", "url": "https://checkout.stripe.test/session"}
    assert calls == {"config": 1, "customer": 1, "checkout": 1}


def test_checkout_allows_user_without_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    _install_locked_state(monkeypatch, user, None)
    calls = _install_side_effect_spies(monkeypatch)

    result = create_checkout_session(
        http_request=None,
        request=CheckoutSessionRequest(plan=Plan.STANDARD),
        user=user,
        db=_FakeDb(),
    )

    assert result["id"] == "cs_test"
    assert calls == {"config": 1, "customer": 1, "checkout": 1}


@pytest.mark.parametrize("plan", [Plan.AGENCY_TRIAL])
def test_checkout_rejects_private_and_contact_plans_before_stripe_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    plan: Plan,
) -> None:
    user = _user()
    _install_locked_state(monkeypatch, user, None)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=plan),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "self_service_checkout_unavailable",
        "message": "This plan is not available through self-service checkout. Please contact sales.",
        "current_plan": None,
        "current_status": None,
        "route": "/contact",
    }
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


@pytest.mark.parametrize(
    ("handler", "change_request"),
    [
        (
            preview_plan_change,
            UpgradePreviewRequest(target_plan=Plan.AGENCY_TRIAL, billing_interval="month"),
        ),
        (
            execute_plan_change,
            UpgradeRequest(target_plan=Plan.AGENCY_TRIAL, billing_interval="month"),
        ),
    ],
)
def test_plan_change_rejects_non_self_service_target_before_config_or_stripe(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    change_request,
) -> None:
    subscription = _subscription("active", stripe_subscription_id="sub_active")
    subscription.billing_interval = "month"
    user = _user(subscription)
    calls = _install_side_effect_spies(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        handler(http_request=None, request=change_request, user=user, db=_FakeDb())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


def test_checkout_honors_private_cta_from_canonical_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    _install_locked_state(monkeypatch, user, None)
    calls = _install_side_effect_spies(monkeypatch)
    monkeypatch.setattr(
        "billing.router.get_plan_catalog_entry",
        lambda _plan: {"cta": "private"},
    )

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "self_service_checkout_unavailable"
    assert calls == {"config": 0, "customer": 0, "checkout": 0}


def test_checkout_rechecks_entitlement_after_attempt_commit_before_stripe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = _subscription("pending", stripe_subscription_id=None)
    user = _user(subscription)
    lock_calls = 0
    side_effects = {"customer": 0, "checkout": 0}
    attempt = SimpleNamespace(
        id="bca_post_commit_guard",
        user_id=user.id,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
        status="pending",
        stripe_customer_id=None,
        stripe_session_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    def _locked_state(_db, *, user_id, authenticated_user):
        nonlocal lock_calls
        lock_calls += 1
        return user, subscription

    def _persist_attempt(*_args, **_kwargs):
        subscription.status = "active"
        subscription.stripe_subscription_id = "sub_activated_in_gap"
        return SimpleNamespace(attempt=attempt, created=True)

    def _customer(**_kwargs):
        side_effects["customer"] += 1
        return "cus_existing"

    def _checkout(**kwargs):
        side_effects["checkout"] += 1
        return SimpleNamespace(
            id="cs_post_commit_guard",
            url="https://checkout.stripe.test/post-commit",
            status="open",
            mode="subscription",
            customer=kwargs["customer"],
            metadata=kwargs["metadata"],
            client_reference_id=kwargs["client_reference_id"],
            livemode=False,
        )

    monkeypatch.setattr("billing.router._lock_checkout_billing_state", _locked_state)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda *_args, **_kwargs: _FakeConfig()
    )
    monkeypatch.setattr("billing.router.resolve_base_checkout_attempt", _persist_attempt)
    monkeypatch.setattr("billing.router.ensure_stripe_customer", _customer)
    monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _checkout)
    monkeypatch.setattr(
        "billing.router.link_base_checkout_customer",
        lambda *_args, **_kwargs: attempt,
    )
    monkeypatch.setattr(
        "billing.router.link_base_checkout_session",
        lambda *_args, **_kwargs: attempt,
    )

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=_FakeDb(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "base_subscription_checkout_conflict"
    assert lock_calls == 2
    assert side_effects == {"customer": 0, "checkout": 0}


def test_new_pending_attempt_is_terminalized_when_post_commit_guard_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        user = models.User(
            email="orphan-attempt@example.com",
            hashed_password="x",
            role="user",
            credits=10,
        )
        db.add(user)
        db.flush()
        subscription = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_orphan_attempt",
            stripe_mode="test",
            plan_type=Plan.STANDARD.value,
            status="pending",
        )
        db.add(subscription)
        db.commit()
        real_resolve = resolve_base_checkout_attempt

        def _resolve_then_activate(*args, **kwargs):
            resolution = real_resolve(*args, **kwargs)
            current_subscription = db.execute(
                select(models.Subscription).where(models.Subscription.user_id == user.id)
            ).scalar_one()
            current_subscription.status = "active"
            current_subscription.stripe_subscription_id = "sub_orphan_attempt"
            db.commit()
            return resolution

        monkeypatch.setattr(
            "billing.router.get_billing_config", lambda *_args, **_kwargs: _FakeConfig()
        )
        monkeypatch.setattr("billing.router.resolve_base_checkout_attempt", _resolve_then_activate)
        monkeypatch.setattr(
            "billing.router.ensure_stripe_customer",
            lambda **_kwargs: pytest.fail("Stripe customer side effect must not run"),
        )
        monkeypatch.setattr(
            "billing.router.stripe.checkout.Session.create",
            lambda **_kwargs: pytest.fail("Stripe Checkout side effect must not run"),
        )

        with pytest.raises(HTTPException) as exc_info:
            create_checkout_session(
                http_request=None,
                request=CheckoutSessionRequest(plan=Plan.STANDARD),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 409
        first_attempt = db.execute(select(models.BaseCheckoutAttempt)).scalar_one()
        assert first_attempt.status == "canceled"
        assert first_attempt.stripe_customer_id is None
        assert first_attempt.stripe_session_id is None

        subscription.status = "canceled"
        db.commit()
        replacement = real_resolve(
            db,
            user_id=user.id,
            stripe_mode="test",
            target_plan=Plan.SPECIALIST.value,
            billing_interval="year",
        )
        assert replacement.created is True
        assert replacement.attempt.id != first_attempt.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("old_status", ["canceled", "incomplete_expired"])
def test_ordinary_subscription_upsert_cannot_rebind_terminal_subscription_id(
    old_status: str,
) -> None:
    import billing_webhook_worker

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        user = models.User(
            email=f"ordinary-upsert-{old_status}@example.com",
            hashed_password="x",
            role="user",
            credits=10,
        )
        db.add(user)
        db.flush()
        subscription = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_terminal_upsert",
            stripe_subscription_id="sub_terminal_upsert_old",
            stripe_mode="test",
            plan_type=Plan.STANDARD.value,
            status=old_status,
            billing_interval="month",
        )
        db.add(subscription)
        db.commit()

        with pytest.raises(ValueError, match="subscription_id_reassignment_rejected"):
            billing_webhook_worker._upsert_subscription(
                db,
                user=user,
                stripe_customer_id="cus_terminal_upsert",
                stripe_subscription_id="sub_terminal_upsert_new",
                status="active",
                plan_type=Plan.SPECIALIST.value,
                current_period_end=datetime(2027, 7, 28, tzinfo=timezone.utc),
                cancel_at_period_end=False,
                billing_interval="year",
                stripe_mode="test",
            )
        db.rollback()
        db.refresh(subscription)

        assert subscription.stripe_subscription_id == "sub_terminal_upsert_old"
        assert subscription.stripe_customer_id == "cus_terminal_upsert"
        assert subscription.stripe_mode == "test"
        assert subscription.status == old_status
        assert subscription.plan_type == Plan.STANDARD.value
        assert subscription.billing_interval == "month"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_user_delete_removes_loaded_base_checkout_attempts() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        user = models.User(
            email="checkout-delete@example.com",
            hashed_password="x",
            role="user",
            credits=10,
        )
        db.add(user)
        db.flush()
        attempt = models.BaseCheckoutAttempt(
            id="bca_user_delete",
            user_id=user.id,
            stripe_mode="test",
            target_plan=Plan.STANDARD.value,
            billing_interval="month",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(attempt)
        db.commit()
        user_id = user.id

        assert user.base_checkout_attempts == [attempt]
        db.delete(user)
        db.commit()

        assert db.get(models.User, user_id) is None
        assert db.get(models.BaseCheckoutAttempt, attempt.id) is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_attempt_resolution_locks_user_subscription_then_attempt() -> None:
    attempt = SimpleNamespace(
        id="bca_lock_order",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
    )

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def scalar_one(self):
            return self.value

    class _RecordingDb:
        def __init__(self):
            self.entities = []

        def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            self.entities.append(entity)
            values = {
                models.User: SimpleNamespace(id=7),
                models.Subscription: None,
                models.BaseCheckoutAttempt: attempt,
            }
            return _Result(values[entity])

    db = _RecordingDb()

    resolution = resolve_base_checkout_attempt(
        db,
        user_id=7,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
    )

    assert resolution.created is False
    assert resolution.attempt is attempt
    assert db.entities == [models.User, models.Subscription, models.BaseCheckoutAttempt]


def test_attempt_resolution_reraises_integrity_error_without_attempt_recovery() -> None:
    injected_error = IntegrityError("INSERT", {}, RuntimeError("active attempt collision"))
    recovered_attempt = SimpleNamespace(
        id="bca_attempt_first_recovery",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
    )

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def scalar_one(self):
            return self.value

    class _FailingCommitDb:
        def __init__(self):
            self.rolled_back = False
            self.after_rollback = []

        def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if self.rolled_back:
                self.after_rollback.append(entity)
            values = {
                models.User: SimpleNamespace(id=7),
                models.Subscription: None,
                models.BaseCheckoutAttempt: (recovered_attempt if self.rolled_back else None),
            }
            return _Result(values[entity])

        def add(self, _attempt):
            return None

        def commit(self):
            raise injected_error

        def rollback(self):
            self.rolled_back = True

    db = _FailingCommitDb()
    caught = None

    try:
        resolve_base_checkout_attempt(
            db,
            user_id=7,
            stripe_mode="test",
            target_plan=Plan.STANDARD.value,
            billing_interval="month",
            now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        )
    except IntegrityError as error:
        caught = error

    assert caught is injected_error
    assert db.after_rollback == []


def test_durable_attempt_replay_reuses_identity_and_different_payload_conflicts() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with session_factory() as db:
            user = models.User(
                email="attempt-replay@example.com",
                hashed_password="x",
                role="user",
                credits=10,
            )
            db.add(user)
            db.commit()
            user_id = user.id
            first = resolve_base_checkout_attempt(
                db,
                user_id=user_id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                now=now,
            )

        with session_factory() as db:
            replay = resolve_base_checkout_attempt(
                db,
                user_id=user_id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                now=now + timedelta(hours=2),
            )
            assert replay.created is False
            assert replay.attempt.id == first.attempt.id
            assert db.execute(select(models.BaseCheckoutAttempt)).scalars().all() == [
                replay.attempt
            ]

            with pytest.raises(BaseCheckoutConflictError):
                resolve_base_checkout_attempt(
                    db,
                    user_id=user_id,
                    stripe_mode="test",
                    target_plan=Plan.SPECIALIST.value,
                    billing_interval="year",
                    now=now + timedelta(hours=3),
                )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_attempt_lock_refreshes_state_preloaded_before_concurrent_commit() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    stale_db = session_factory()
    updater_db = session_factory()
    try:
        user = models.User(
            email="stale-attempt-lock@example.com",
            hashed_password="x",
            role="user",
            credits=10,
        )
        stale_db.add(user)
        stale_db.flush()
        stale_db.add(
            models.BaseCheckoutAttempt(
                id="bca_stale_lock",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                status="customer_created",
                stripe_customer_id="cus_stale_lock",
                expires_at=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
            )
        )
        stale_db.commit()
        preloaded = stale_db.execute(
            select(models.BaseCheckoutAttempt).where(
                models.BaseCheckoutAttempt.id == "bca_stale_lock"
            )
        ).scalar_one()

        committed = updater_db.execute(
            select(models.BaseCheckoutAttempt).where(
                models.BaseCheckoutAttempt.id == "bca_stale_lock"
            )
        ).scalar_one()
        committed.status = "session_created"
        committed.stripe_session_id = "cs_committed_elsewhere"
        updater_db.commit()

        locked = lock_base_checkout_attempt(stale_db, attempt_id="bca_stale_lock")

        assert locked is preloaded
        assert locked.status == "session_created"
        assert locked.stripe_session_id == "cs_committed_elsewhere"
    finally:
        stale_db.close()
        updater_db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_elapsed_attempt_recovery_omits_stripe_session_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        user = models.User(
            email="elapsed-attempt@example.com",
            hashed_password="x",
            role="user",
            credits=10,
        )
        db.add(user)
        db.flush()
        attempt = models.BaseCheckoutAttempt(
            id="bca_elapsed_recovery",
            user_id=user.id,
            stripe_mode="test",
            target_plan=Plan.STANDARD.value,
            billing_interval="month",
            status="customer_created",
            stripe_customer_id="cus_elapsed_recovery",
            expires_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        )
        db.add(attempt)
        db.commit()
        captured = []

        monkeypatch.setattr(
            "billing.router.get_billing_config",
            lambda *_args, **_kwargs: _FakeConfig(),
        )
        monkeypatch.setattr(
            "billing.router.ensure_stripe_customer",
            lambda **_kwargs: "cus_elapsed_recovery",
        )

        def _create_checkout(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                id="cs_elapsed_recovery",
                url="https://checkout.stripe.test/elapsed-recovery",
                status="open",
                mode="subscription",
                customer=kwargs["customer"],
                metadata=kwargs["metadata"],
                client_reference_id=kwargs["client_reference_id"],
                livemode=False,
            )

        monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_checkout)

        result = create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=db,
        )
        recovered_attempts = db.execute(select(models.BaseCheckoutAttempt)).scalars().all()

        assert result == {
            "id": "cs_elapsed_recovery",
            "url": "https://checkout.stripe.test/elapsed-recovery",
        }
        assert len(captured) == 1
        assert captured[0]["idempotency_key"] == "base-checkout:bca_elapsed_recovery"
        assert [recovered.id for recovered in recovered_attempts] == ["bca_elapsed_recovery"]
        assert recovered_attempts[0].status == "session_created"
        assert "expires_at" not in captured[0]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("session_status", "expected_code"),
    [("complete", "base_checkout_processing"), ("expired", "base_checkout_expired")],
)
def test_closed_base_checkout_session_is_never_returned_as_reusable_url(
    monkeypatch: pytest.MonkeyPatch,
    session_status: str,
    expected_code: str,
) -> None:
    attempt = SimpleNamespace(
        id="bca_closed",
        user_id=7,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
        status="session_created",
        stripe_customer_id="cus_closed",
        stripe_session_id="cs_closed",
    )
    session = {
        "id": "cs_closed",
        "url": "https://checkout.stripe.test/closed",
        "status": session_status,
        "mode": "subscription",
        "customer": "cus_closed",
        "metadata": base_checkout_metadata(attempt),
        "client_reference_id": "7",
        "livemode": False,
    }
    expired_calls = []
    monkeypatch.setattr(
        "billing.router.expire_base_checkout_attempt",
        lambda *_args, **kwargs: expired_calls.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        _reconcile_base_checkout_session(
            _FakeDb(),
            attempt=attempt,
            session=session,
            require_open=True,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == expected_code
    assert expired_calls == (
        [{"attempt_id": "bca_closed", "stripe_session_id": "cs_closed"}]
        if session_status == "expired"
        else []
    )


def test_base_checkout_session_validation_rejects_unexpected_metadata() -> None:
    attempt = SimpleNamespace(
        id="bca_strict",
        user_id=7,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
        stripe_customer_id="cus_strict",
        stripe_session_id="cs_strict",
    )
    metadata = base_checkout_metadata(attempt)
    metadata["unexpected"] = "drop-me"

    with pytest.raises(BaseCheckoutValidationError):
        validate_base_checkout_session(
            {
                "id": "cs_strict",
                "url": "https://checkout.stripe.test/strict",
                "status": "open",
                "mode": "subscription",
                "customer": "cus_strict",
                "metadata": metadata,
                "client_reference_id": "7",
                "livemode": False,
            },
            attempt=attempt,
            require_open=True,
        )


def test_checkout_guard_observes_status_committed_after_authenticated_user_was_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    stale_db = session_factory()
    updater_db = session_factory()
    try:
        user = models.User(
            email="reload@example.com",
            hashed_password="x",
            role="user",
            credits=10,
            company_name="Reload Test",
        )
        stale_db.add(user)
        stale_db.flush()
        stale_db.add(
            models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_reload",
                stripe_subscription_id=None,
                stripe_mode="test",
                plan_type="plan_standard",
                status="pending",
            )
        )
        stale_db.commit()
        authenticated_user = stale_db.execute(
            select(models.User).where(models.User.id == user.id)
        ).scalar_one()
        assert authenticated_user.subscription.status == "pending"

        updater_subscription = updater_db.execute(
            select(models.Subscription).where(models.Subscription.user_id == user.id)
        ).scalar_one()
        updater_subscription.status = "active"
        updater_db.commit()

        calls = _install_side_effect_spies(monkeypatch)
        with pytest.raises(HTTPException) as exc_info:
            create_checkout_session(
                http_request=None,
                request=CheckoutSessionRequest(plan=Plan.SPECIALIST),
                user=authenticated_user,
                db=stale_db,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["current_status"] == "active"
        assert calls == {"config": 0, "customer": 0, "checkout": 0}
    finally:
        stale_db.close()
        updater_db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
