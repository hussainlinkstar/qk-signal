"""Workspace capability override policy (SIGV2-1147).

Before this policy existed, ``PlanValidator.has_feature`` read only the plan
matrix while overrides were read by ``get_effective_capability``, which had no
production caller at all. An administrator could therefore write a
``WorkspaceCapabilityOverride`` row for any of the 48 capability keys and
nothing in the product would ever consult it: no error, no log, and nothing on
the admin surface to say the row was inert.

These tests pin both halves of the rule:
  * an override for a capability in ``OVERRIDABLE_CAPABILITIES`` takes effect
    at the gate, and
  * an override for anything else is refused at the admin surface, with the
    reason it would have had no effect.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.config.plans import CANONICAL_PLAN_TYPES, CAPABILITY_MATRIX
from app.services.compliance.plan_validator import (
    OVERRIDABLE_CAPABILITIES,
    PLAN_KEYED_GATE_CAPABILITIES,
    PLAN_SCOPED_LIMIT_CAPABILITIES,
    PRICING_METADATA_CAPABILITIES,
    UNGATED_CAPABILITIES,
    UNIVERSALLY_GRANTED_CAPABILITIES,
    PlanValidator,
    capability_override_policy,
    describe_override_enforcement,
    is_overridable_capability,
)
from database import Base

# A capability of each kind, named once so the assertions below read as the
# rule rather than as a list of strings.
AN_OVERRIDABLE_CAPABILITY = "can_use_slack_integration"
A_PLAN_KEYED_CAPABILITY = "has_competitor_analysis"
# SIGV2-1120 retired has_custom_ai_model_routing, which used to stand in for
# the ungated bucket here. has_dedicated_infrastructure is the same shape: in
# UNGATED_CAPABILITIES, false on every plan, and read by no runtime gate.
AN_UNGATED_CAPABILITY = "has_dedicated_infrastructure"
A_LIMIT_CAPABILITY = "max_sites"
A_PRICING_CAPABILITY = "monthly_price_usd"
A_UNIVERSAL_CAPABILITY = "has_pdf_audit_reports"

ALL_CAPABILITY_KEYS = frozenset(next(iter(CAPABILITY_MATRIX.values()), {}))

_BUCKETS = {
    "pricing_metadata": PRICING_METADATA_CAPABILITIES,
    "plan_scoped_limit": PLAN_SCOPED_LIMIT_CAPABILITIES,
    "ungated": UNGATED_CAPABILITIES,
    "plan_keyed_gate": PLAN_KEYED_GATE_CAPABILITIES,
    "universally_granted": UNIVERSALLY_GRANTED_CAPABILITIES,
    "overridable": OVERRIDABLE_CAPABILITIES,
}


# ---------------------------------------------------------------------------
# The classification must stay exhaustive
# ---------------------------------------------------------------------------


class TestPolicyCoversEveryCapability:
    """A capability nobody classified must not silently become overridable."""

    def test_buckets_partition_the_capability_matrix(self):
        union: set[str] = set()
        for name, bucket in _BUCKETS.items():
            overlap = union & set(bucket)
            assert not overlap, f"'{name}' overlaps an earlier bucket: {sorted(overlap)}"
            union |= set(bucket)

        unclassified = ALL_CAPABILITY_KEYS - union
        assert not unclassified, (
            "New capability keys must be classified for override enforcement in "
            f"plan_validator.py: {sorted(unclassified)}"
        )
        stale = union - ALL_CAPABILITY_KEYS
        assert not stale, f"Capability keys no longer in the plan matrix: {sorted(stale)}"

    def test_every_capability_has_a_verdict_and_a_reason(self):
        policy = capability_override_policy()
        assert set(policy) == ALL_CAPABILITY_KEYS
        for key, verdict in policy.items():
            assert verdict.capability == key
            assert verdict.reason.strip(), f"'{key}' has a verdict with no stated reason"

    def test_an_unknown_capability_is_never_overridable(self):
        verdict = describe_override_enforcement("has_a_capability_no_plan_defines")
        assert verdict.is_enforced is False
        assert "no gate" in verdict.reason


class TestOverridableSetIsSelfConsistent:
    """The escape hatch may only contain capabilities an override can move."""

    @pytest.mark.parametrize("capability", sorted(OVERRIDABLE_CAPABILITIES))
    def test_overridable_capabilities_are_boolean_on_every_plan(self, capability: str):
        for plan in CANONICAL_PLAN_TYPES:
            value = CAPABILITY_MATRIX[plan][capability]
            assert isinstance(value, bool), f"{plan}.{capability} is not boolean"

    @pytest.mark.parametrize("capability", sorted(OVERRIDABLE_CAPABILITIES))
    def test_overridable_capabilities_are_withheld_by_some_plan(self, capability: str):
        withheld = [
            plan for plan in CANONICAL_PLAN_TYPES if CAPABILITY_MATRIX[plan][capability] is not True
        ]
        assert withheld, (
            f"'{capability}' is granted by every plan, so an override cannot widen "
            "anything and it does not belong in OVERRIDABLE_CAPABILITIES"
        )

    @pytest.mark.parametrize("capability", sorted(UNIVERSALLY_GRANTED_CAPABILITIES))
    def test_universally_granted_capabilities_really_are_universal(self, capability: str):
        for plan in CANONICAL_PLAN_TYPES:
            assert CAPABILITY_MATRIX[plan][capability] is True, (
                f"{plan} withholds '{capability}', so it is no longer universally "
                "granted and needs reclassifying"
            )


class TestEnforcementVerdictPerKind:
    """One capability of each kind, with the reason an admin will be shown."""

    def test_overridable_capability_is_enforced(self):
        verdict = describe_override_enforcement(AN_OVERRIDABLE_CAPABILITY)
        assert verdict.is_enforced is True
        assert is_overridable_capability(AN_OVERRIDABLE_CAPABILITY) is True

    @pytest.mark.parametrize(
        "capability",
        [
            A_PLAN_KEYED_CAPABILITY,
            AN_UNGATED_CAPABILITY,
            A_LIMIT_CAPABILITY,
            A_PRICING_CAPABILITY,
            A_UNIVERSAL_CAPABILITY,
        ],
    )
    def test_non_overridable_capability_is_refused_with_a_reason(self, capability: str):
        verdict = describe_override_enforcement(capability)
        assert verdict.is_enforced is False
        assert is_overridable_capability(capability) is False
        assert len(verdict.reason) > 20, "the admin needs to be told why, not just no"


# ---------------------------------------------------------------------------
# The gate: an enforced override actually changes the decision
# ---------------------------------------------------------------------------


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _seed_owner_on_plan(db: Session, plan_type: str) -> models.User:
    """Create a user entitled to ``plan_type`` who owns one workspace."""
    user = models.User(email="owner@example.test", hashed_password="x", role="user", credits=0)
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="override_policy_test_customer",
            plan_type=plan_type,
            status="active",
        )
    )
    db.add(models.Workspace(name="Owned Workspace", owner_id=user.id))
    db.flush()
    return user


def _grant(
    db: Session,
    user: models.User,
    capability: str,
    *,
    value: object = True,
    expires_at: datetime | None = None,
) -> models.WorkspaceCapabilityOverride:
    workspace = db.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
    assert workspace is not None
    override = models.WorkspaceCapabilityOverride(
        workspace_id=workspace.id,
        capability_key=capability,
        override_value=value,
        reason="Negotiated deal",
        expires_at=expires_at,
    )
    db.add(override)
    db.flush()
    return override


@pytest.fixture()
def db_session():
    db, engine = _build_db()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


class TestOverrideTakesEffectAtTheGate:
    """The defect: the gate could not see the row the admin had written."""

    def test_plan_withholds_the_capability_without_an_override(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        assert CAPABILITY_MATRIX["plan_standard"][AN_OVERRIDABLE_CAPABILITY] is False
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is False

    def test_active_override_grants_the_capability(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, AN_OVERRIDABLE_CAPABILITY)

        # No session is passed: the gate resolves the one the user is attached
        # to, which is what every existing call site provides implicitly.
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is True

    def test_override_is_resolved_from_an_explicitly_passed_session(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, AN_OVERRIDABLE_CAPABILITY)
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY, db=db_session) is True

    def test_unexpired_override_grants_and_expired_one_does_not(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        override = _grant(
            db_session,
            user,
            AN_OVERRIDABLE_CAPABILITY,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is True

        override.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.flush()
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is False

    def test_override_on_another_owners_workspace_does_not_leak(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        stranger = models.User(
            email="stranger@example.test", hashed_password="x", role="user", credits=0
        )
        db_session.add(stranger)
        db_session.flush()
        db_session.add(models.Workspace(name="Other Workspace", owner_id=stranger.id))
        db_session.flush()
        _grant(db_session, stranger, AN_OVERRIDABLE_CAPABILITY)

        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is False

    def test_a_non_true_value_is_not_a_grant(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, AN_OVERRIDABLE_CAPABILITY, value="yes")
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is False

    def test_a_plan_that_grants_the_capability_needs_no_override(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_specialist")
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is True

    def test_override_on_a_non_overridable_capability_is_ignored(self, db_session: Session):
        """Belt and braces: the admin surface refuses these, legacy rows exist."""
        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, A_PLAN_KEYED_CAPABILITY)
        assert PlanValidator().has_feature(user, A_PLAN_KEYED_CAPABILITY) is False

        _grant(db_session, user, AN_UNGATED_CAPABILITY)
        assert PlanValidator().has_feature(user, AN_UNGATED_CAPABILITY) is False


class TestGateWithoutASession:
    """A gate must never raise or hang because no session is reachable."""

    def test_detached_user_falls_back_to_the_plan_matrix(self):
        user = models.User(email="detached@example.test", hashed_password="x", role="user")
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is False

    def test_none_user_falls_back_to_the_plan_matrix(self):
        assert PlanValidator().has_feature(None, AN_OVERRIDABLE_CAPABILITY) is False

    def test_object_with_no_session_falls_back_to_the_plan_matrix(self):
        class PlanOnlyPrincipal:
            id = 7
            subscription = None
            trial_plan = None

        assert PlanValidator().has_feature(PlanOnlyPrincipal(), AN_OVERRIDABLE_CAPABILITY) is False


class TestAdminSurfaceRefusesAnInertOverride:
    """Requirement 2: the surface refuses the row rather than accepting it silently."""

    @staticmethod
    def _create(db: Session, actor: models.User, capability: str, value: object = True):
        import admin

        workspace = db.query(models.Workspace).filter(models.Workspace.owner_id == actor.id).first()
        assert workspace is not None
        body = admin.OverrideCreate(
            workspace_id=workspace.id,
            capability_key=capability,
            override_value=value,
            reason="Negotiated deal",
        )
        return admin.admin_create_override(body, actor, db)

    def test_an_overridable_capability_is_accepted(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        created = self._create(db_session, user, AN_OVERRIDABLE_CAPABILITY)
        assert created["capability_key"] == AN_OVERRIDABLE_CAPABILITY
        assert created["is_enforced"] is True
        # And the gate now agrees, which is the whole point of SIGV2-1147.
        assert PlanValidator().has_feature(user, AN_OVERRIDABLE_CAPABILITY) is True

    @pytest.mark.parametrize(
        "capability",
        [
            A_PLAN_KEYED_CAPABILITY,
            AN_UNGATED_CAPABILITY,
            A_LIMIT_CAPABILITY,
            A_PRICING_CAPABILITY,
            A_UNIVERSAL_CAPABILITY,
        ],
    )
    def test_a_non_overridable_capability_is_refused(self, db_session: Session, capability: str):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        value: object = 99 if capability in (A_LIMIT_CAPABILITY, A_PRICING_CAPABILITY) else True

        with pytest.raises(HTTPException) as excinfo:
            self._create(db_session, user, capability, value)

        assert excinfo.value.status_code == 400
        assert "no effect" in str(excinfo.value.detail)
        assert db_session.query(models.WorkspaceCapabilityOverride).count() == 0

    def test_a_revoking_value_is_refused(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        with pytest.raises(HTTPException) as excinfo:
            self._create(db_session, user, AN_OVERRIDABLE_CAPABILITY, False)
        assert excinfo.value.status_code == 400
        assert "only grant" in str(excinfo.value.detail)

    def test_an_unknown_capability_is_still_refused(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        with pytest.raises(HTTPException) as excinfo:
            self._create(db_session, user, "has_a_capability_no_plan_defines")
        assert excinfo.value.status_code == 400
        assert "Unknown capability key" in str(excinfo.value.detail)

    def test_a_legacy_unenforced_row_is_reported_as_having_no_effect(self, db_session: Session):
        """Rows written before the policy stay visible, labelled inert."""
        import admin

        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, A_PLAN_KEYED_CAPABILITY)

        listed = admin.admin_list_overrides(user, db_session)["overrides"]
        assert len(listed) == 1
        assert listed[0]["capability_key"] == A_PLAN_KEYED_CAPABILITY
        assert listed[0]["is_enforced"] is False
        assert listed[0]["enforcement_reason"]

    def test_effective_capabilities_do_not_move_for_an_unenforced_row(self, db_session: Session):
        import admin

        user = _seed_owner_on_plan(db_session, "plan_standard")
        _grant(db_session, user, A_PLAN_KEYED_CAPABILITY)
        workspace = (
            db_session.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
        )

        payload = admin.admin_effective_capabilities(workspace.id, user, db_session)
        entry = next(c for c in payload["capabilities"] if c["key"] == A_PLAN_KEYED_CAPABILITY)
        assert entry["is_overridden"] is True
        assert entry["is_enforced"] is False
        assert (
            entry["effective_value"] == CAPABILITY_MATRIX["plan_standard"][A_PLAN_KEYED_CAPABILITY]
        )
        assert entry["enforcement_reason"]

    def test_plans_endpoint_publishes_the_policy(self, db_session: Session):
        import admin

        user = _seed_owner_on_plan(db_session, "plan_standard")
        response = admin.admin_get_plans(user, db_session)
        assert sorted(response.overridable_capability_keys) == sorted(OVERRIDABLE_CAPABILITIES)
        assert AN_OVERRIDABLE_CAPABILITY not in response.override_refusal_reasons
        for capability in (A_PLAN_KEYED_CAPABILITY, A_LIMIT_CAPABILITY, A_PRICING_CAPABILITY):
            assert response.override_refusal_reasons[capability]


class TestGetEffectiveCapabilityHonoursThePolicy:
    """The admin-facing resolver must not report an entitlement gates refuse."""

    def test_enforced_capability_reflects_the_override(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        override = _grant(db_session, user, AN_OVERRIDABLE_CAPABILITY)
        resolved = PlanValidator().get_effective_capability(
            db_session,
            "plan_standard",
            AN_OVERRIDABLE_CAPABILITY,
            workspace_id=override.workspace_id,
        )
        assert resolved is True

    def test_non_overridable_capability_keeps_the_plan_value(self, db_session: Session):
        user = _seed_owner_on_plan(db_session, "plan_standard")
        override = _grant(db_session, user, A_LIMIT_CAPABILITY, value=99)
        resolved = PlanValidator().get_effective_capability(
            db_session,
            "plan_standard",
            A_LIMIT_CAPABILITY,
            workspace_id=override.workspace_id,
        )
        assert resolved == CAPABILITY_MATRIX["plan_standard"][A_LIMIT_CAPABILITY]
