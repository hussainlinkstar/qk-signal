import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.config.plans import (
    can_use_feature,
    get_plan_capabilities,
    resolve_entitled_subscription_plan,
)
from main import resolve_subscription_plan
from routers.workspace_router import _resolve_subscription_plan as resolve_workspace_plan


def _user_with_subscription(
    plan_type: str,
    status: str,
    *,
    trial_plan: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        subscription=SimpleNamespace(plan_type=plan_type, status=status),
        trial_plan=trial_plan,
    )


def test_resolve_subscription_plan_returns_free_when_user_missing() -> None:
    assert resolve_subscription_plan(None) == "plan_starter"


@pytest.mark.parametrize("status", ["active", "trialing", " ACTIVE ", "TRIALING"])
def test_resolve_subscription_plan_reads_entitled_paid_plan(status: str) -> None:
    user = _user_with_subscription("plan_specialist", status)

    assert resolve_subscription_plan(user) == "plan_specialist"


@pytest.mark.parametrize("plan_type", ["plan_specialist", "plan_executive"])
@pytest.mark.parametrize("status", ["pending", "past_due", "canceled"])
def test_resolve_subscription_plan_rejects_unentitled_paid_plan(
    plan_type: str,
    status: str,
) -> None:
    user = _user_with_subscription(plan_type, status)

    assert resolve_subscription_plan(user) == "plan_starter"


def test_pending_paid_plan_falls_back_to_trial_plan() -> None:
    user = _user_with_subscription(
        "plan_executive",
        "pending",
        trial_plan="plan_agency_trial",
    )

    assert resolve_subscription_plan(user) == "plan_agency_trial"


EXACT_CANONICAL_PLAN_TYPES = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)
NONCANONICAL_PLAN_TYPES = (
    " plan_executive",
    "plan_executive ",
    "Plan_Executive",
    "PLAN_EXECUTIVE",
    "plan_unlimited",
)
INVALID_MODEL_PLAN_TYPES = (
    *NONCANONICAL_PLAN_TYPES,
    pytest.param("", id="empty-string"),
    pytest.param(None, id="none"),
    pytest.param(42, id="integer"),
    pytest.param(True, id="boolean"),
    pytest.param(["plan_starter"], id="list"),
)


def test_entitled_subscription_helper_accepts_exact_canonical_plan() -> None:
    subscription = SimpleNamespace(plan_type="plan_specialist", status=" ACTIVE ")

    assert resolve_entitled_subscription_plan(subscription) == "plan_specialist"


@pytest.mark.parametrize("plan_type", EXACT_CANONICAL_PLAN_TYPES)
def test_subscription_constructor_accepts_exact_canonical_plan_type(plan_type: str) -> None:
    subscription = models.Subscription(
        stripe_customer_id=f"cus_constructor_{plan_type}",
        plan_type=plan_type,
        status="active",
    )

    assert subscription.plan_type == plan_type


@pytest.mark.parametrize("plan_type", EXACT_CANONICAL_PLAN_TYPES)
def test_subscription_assignment_accepts_exact_canonical_plan_type(plan_type: str) -> None:
    subscription = models.Subscription(
        stripe_customer_id="cus_assignment_canonical",
        plan_type="plan_starter",
        status="active",
    )

    subscription.plan_type = plan_type

    assert subscription.plan_type == plan_type


@pytest.mark.parametrize("plan_type", INVALID_MODEL_PLAN_TYPES)
def test_subscription_constructor_rejects_noncanonical_plan_type(plan_type: object) -> None:
    with pytest.raises(ValueError):
        models.Subscription(
            stripe_customer_id="cus_constructor_invalid",
            plan_type=plan_type,
            status="active",
        )


@pytest.mark.parametrize("plan_type", INVALID_MODEL_PLAN_TYPES)
def test_subscription_assignment_rejects_noncanonical_plan_type(plan_type: object) -> None:
    subscription = models.Subscription(
        stripe_customer_id="cus_assignment",
        plan_type="plan_executive",
        status="active",
    )

    with pytest.raises(ValueError):
        subscription.plan_type = plan_type


@pytest.mark.parametrize("plan_type", NONCANONICAL_PLAN_TYPES)
def test_entitled_subscription_helper_rejects_noncanonical_plan(plan_type: str) -> None:
    subscription = SimpleNamespace(plan_type=plan_type, status="active")

    assert resolve_entitled_subscription_plan(subscription) is None


@pytest.mark.parametrize(
    "plan_type",
    (*NONCANONICAL_PLAN_TYPES, "starter", "pro", "enterprise"),
)
def test_resolve_subscription_plan_rejects_noncanonical_plan_ids(plan_type: str) -> None:
    user = _user_with_subscription(plan_type, "active")

    assert resolve_subscription_plan(user) == "plan_starter"


def test_user_serialization_does_not_report_pending_premium_plan() -> None:
    user = models.User(
        id=1,
        email="pending@example.com",
        company_name="Pending User",
        role="user",
        subscription=models.Subscription(
            stripe_customer_id="cus_pending",
            plan_type="plan_executive",
            status="pending",
        ),
    )

    assert user.to_dict()["subscription_plan"] == "plan_starter"


def test_user_serialization_pending_paid_plan_falls_back_to_trial() -> None:
    user = models.User(
        id=2,
        email="trial@example.com",
        company_name="Trial User",
        role="user",
        trial_plan="plan_agency_trial",
        subscription=models.Subscription(
            stripe_customer_id="cus_trial_pending",
            plan_type="plan_executive",
            status="pending",
        ),
    )

    assert user.to_dict()["subscription_plan"] == "plan_agency_trial"


# ---------------------------------------------------------------------------
# SIGV2-1220: the workspace router had its own plan resolver, and it threw away
# an entitled `plan_agency_trial` subscription. A trial customer whose
# entitlement lives on the subscription row rather than the legacy
# `trial_plan` column resolved to Starter, so onboarding's competitor step
# answered "Competitive Intelligence is available on Specialist" to a trial the
# shared capability matrix grants it. Resolution now follows the shared billing
# rules; a non-entitled status still grants nothing.
# ---------------------------------------------------------------------------


def test_workspace_resolver_reads_an_active_trial_subscription() -> None:
    user = _user_with_subscription("plan_agency_trial", "active")

    assert resolve_workspace_plan(user) == "plan_agency_trial"


def test_workspace_resolver_grants_the_trial_its_matrix_capabilities() -> None:
    # The regression in one line: the trial matrix allows competitor analysis,
    # so the competitor guard must not refuse an active trial.
    assert get_plan_capabilities("plan_agency_trial")["has_competitor_analysis"] is True

    user = _user_with_subscription("plan_agency_trial", "active")

    assert can_use_feature(resolve_workspace_plan(user), "has_competitor_analysis") is True


@pytest.mark.parametrize("status", ["canceled", "past_due", "pending", "unpaid"])
def test_workspace_resolver_refuses_a_non_entitled_trial(status: str) -> None:
    user = _user_with_subscription("plan_agency_trial", status)

    assert resolve_workspace_plan(user) == "plan_starter"
    assert can_use_feature(resolve_workspace_plan(user), "has_competitor_analysis") is False


def test_workspace_resolver_refuses_an_expired_trial_transitioned_to_explorer() -> None:
    # trial_service moves an expired trial to the Starter plan on the
    # `trial_plan` column. With no entitled subscription the restriction holds.
    user = SimpleNamespace(subscription=None, trial_plan="plan_starter")

    assert resolve_workspace_plan(user) == "plan_starter"
    assert can_use_feature(resolve_workspace_plan(user), "has_competitor_analysis") is False


def test_workspace_resolver_matches_the_shared_resolver() -> None:
    """One resolver, one answer. The divergent copy is what caused the defect,
    so pin the two together across every plan and status combination."""
    for plan_type in EXACT_CANONICAL_PLAN_TYPES:
        for status in ("active", "trialing", "canceled", "pending"):
            for trial_plan in (None, "plan_agency_trial", "plan_starter"):
                user = _user_with_subscription(plan_type, status, trial_plan=trial_plan)
                assert resolve_workspace_plan(user) == resolve_subscription_plan(
                    user
                ), f"{plan_type}/{status}/{trial_plan}"
