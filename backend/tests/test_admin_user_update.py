from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from admin import AdminUserUpdateRequest, admin_get_plans, update_admin_user
from app.config.plans import PUBLIC_PLAN_TYPES
from database import Base


def test_update_admin_user_plan_marks_existing_subscription_active() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    admin_user = models.User(
        email="admin@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    managed_user = models.User(
        email="user@example.com",
        hashed_password="x",
        role="user",
        credits=1,
        notifications_enabled=True,
    )
    db.add_all([admin_user, managed_user])
    db.commit()
    db.refresh(admin_user)
    db.refresh(managed_user)

    subscription = models.Subscription(
        user_id=managed_user.id,
        stripe_customer_id="admin_manual_customer",
        plan_type="plan_standard",
        status="pending",
        cancel_at_period_end=True,
    )
    db.add(subscription)
    db.commit()

    response = update_admin_user(
        user_id=managed_user.id,
        payload=AdminUserUpdateRequest(plan_type="plan_executive"),
        admin_user=admin_user,
        db=db,
    )

    assert response["user"]["plan"] == "plan_executive"

    db.refresh(subscription)
    assert subscription.plan_type == "plan_executive"
    assert subscription.status == "active"
    assert subscription.cancel_at_period_end is False

    db.close()


@pytest.fixture
def managed_users():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    admin_user = models.User(email="admin@example.test", hashed_password="x", role="admin")
    user = models.User(
        email="managed@example.test",
        hashed_password="x",
        role="user",
        credits=40,
        notifications_enabled=True,
    )
    db.add_all([admin_user, user])
    db.commit()
    try:
        yield db, admin_user, user
    finally:
        db.close()
        engine.dispose()


def test_admin_plan_catalog_contains_only_active_public_packages(managed_users) -> None:
    db, admin_user, _user = managed_users

    response = admin_get_plans(admin_user=admin_user, db=db)

    assert {key: plan.display_name for key, plan in response.plans.items()} == {
        "plan_starter": "Starter",
        "plan_standard": "Standard",
        "plan_specialist": "Specialist",
        "plan_executive": "Executive",
    }


def test_frontend_public_packages_match_backend_public_catalog() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/planCapabilities.ts"
    ).read_text()
    declaration = re.search(r"export const PUBLIC_PLAN_TYPES = \[(.*?)\] as const", source, re.S)

    assert declaration is not None
    assert re.findall(r'"(plan_[a-z_]+)"', declaration.group(1)) == list(PUBLIC_PLAN_TYPES)


@pytest.mark.parametrize("request_field", ["plan", "plan_type"])
def test_admin_cannot_assign_a_new_agency_trial(managed_users, request_field) -> None:
    db, admin_user, user = managed_users

    with pytest.raises(HTTPException) as exc_info:
        update_admin_user(
            user_id=user.id,
            payload=AdminUserUpdateRequest(**{request_field: "plan_agency_trial"}),
            admin_user=admin_user,
            db=db,
        )

    assert exc_info.value.status_code in {400, 410, 422}
    assert db.query(models.Subscription).filter_by(user_id=user.id).count() == 0
    db.refresh(user)
    assert user.trial_plan is None
    assert user.credits == 40


@pytest.mark.parametrize("with_subscription", [False, True])
def test_unrelated_admin_edit_preserves_a_legacy_trial(managed_users, with_subscription) -> None:
    db, admin_user, user = managed_users
    now = datetime.now(timezone.utc)
    user.trial_plan = "plan_agency_trial"
    user.trial_started_at = now - timedelta(days=3)
    user.trial_ends_at = now + timedelta(days=11)
    user.trial_audits_used = 2
    subscription = None
    if with_subscription:
        subscription = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_legacy_trial_fixture",
            plan_type="plan_agency_trial",
            status="active",
            cancel_at_period_end=True,
        )
        db.add(subscription)
    db.commit()
    db.refresh(user)
    before = (user.trial_plan, user.trial_started_at, user.trial_ends_at, user.trial_audits_used)

    update_admin_user(
        user_id=user.id,
        payload=AdminUserUpdateRequest(role="moderator", notifications_enabled=False),
        admin_user=admin_user,
        db=db,
    )

    db.refresh(user)
    assert user.role == "moderator"
    assert user.notifications_enabled is False
    assert user.credits == 40
    assert (
        user.trial_plan,
        user.trial_started_at,
        user.trial_ends_at,
        user.trial_audits_used,
    ) == before
    if subscription is not None:
        db.refresh(subscription)
        assert subscription.plan_type == "plan_agency_trial"
        assert subscription.status == "active"
        assert subscription.cancel_at_period_end is True
    else:
        assert db.query(models.Subscription).filter_by(user_id=user.id).count() == 0


def test_explicit_starter_replaces_legacy_trial_without_reducing_credits(managed_users):
    db, admin_user, user = managed_users
    user.trial_plan = "plan_agency_trial"
    db.commit()

    update_admin_user(
        user_id=user.id,
        payload=AdminUserUpdateRequest(plan_type="plan_starter"),
        admin_user=admin_user,
        db=db,
    )
    db.refresh(user)

    assert user.trial_plan == "plan_starter"
    assert user.credits == 40
    assert db.query(models.Subscription).filter_by(user_id=user.id).count() == 0
