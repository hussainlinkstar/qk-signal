"""SIGV2-1228: the engine roster said every plan measures every engine.

``build_engine_roster`` enumerated ``offered_visibility_providers()`` and never
looked at the plan, so all seven offered engines were listed to every project
while Starter measures one, Standard three and Specialist five. A roster card
is a claim that the engine is measured (the rule SIGV2-1215 settled), so six of
Starter's seven cards claimed a measurement that will never be taken.

The decision was to keep the list and mark the rest: shrinking Starter to a
single row removes the only place a customer can see what the product covers,
and SIGV2-1221 settled that a plan-gated surface should say what unlocks it
rather than disappear. So an engine the plan does not measure is listed as
unavailable on this plan, with the plan that unlocks it named.

The hard part is what an unavailable row may carry: no number and no timestamp.
A ``last_measured_at`` beside a row the plan no longer measures reads as a
current measurement, which is exactly the claim SIGV2-1215 removed, and a zero
or a dash in a score slot would read as a measured score of nothing.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import models
from app.config.plans import PRIVATE_PLAN_IDS
from database import Base
from routers.monitoring_router import VisibilityEngineStatusResponse
from services.project_visibility_service import (
    OFFERED_VISIBILITY_PROVIDERS,
    REASON_NOT_MEASURED_ON_PLAN,
    VISIBILITY_PLAN_LIMITS,
    ProjectVisibilityService,
    plan_allowed_providers,
)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db, *, plan_type: str):
    user = models.User(
        email=f"roster-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{plan_type}",
            stripe_subscription_id=f"sub_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    workspace = models.Workspace(name="WS", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Proj",
        domain_url="https://example.com",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return user, project


def _record_measurement(db, project, *, provider: str) -> None:
    """A completed run for ``provider``, the kind a downgrade leaves behind.

    Every engine gets history here on purpose: the defect is only visible on a
    project that was measured on a richer plan, or by a one-off on-demand run,
    and then read on a plan whose roster is smaller.
    """
    now = datetime.now(timezone.utc) - timedelta(days=3)
    batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic="best payroll software",
        provider=provider,
        target_domain="example.com",
        schedule_key="202610010000",
        status="succeeded",
        score=90.0,
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    db.add(
        models.VisibilityRun(
            batch_id=batch.id,
            topic="best payroll software",
            provider=provider,
            target_domain="example.com",
            prompt_template="aeo_v1",
            prompt="best payroll software",
            raw_response={"model": "m", "engine_source": "openrouter_live"},
            parsed_citations=[],
            valid_citations=[],
            score=90.0,
            status="succeeded",
            started_at=now,
            completed_at=now,
        )
    )
    db.commit()


def _roster_for(db, plan: str, *, with_history: bool = False) -> list[dict]:
    _user, project = _seed_project(db, plan_type=plan)
    if with_history:
        for provider in OFFERED_VISIBILITY_PROVIDERS:
            _record_measurement(db, project, provider=provider)
    return ProjectVisibilityService(db).build_engine_roster(project)


# ---------------------------------------------------------------------------
# The list stays, the claim does not
# ---------------------------------------------------------------------------


def test_every_plan_still_lists_every_offered_engine() -> None:
    """Option 2: the surface of the product stays visible on every plan.

    The alternative, listing only what the plan measures, leaves a Starter
    customer with one row and no way to see what the product covers.
    """
    db = _make_session()
    try:
        for plan in VISIBILITY_PLAN_LIMITS:
            roster = _roster_for(db, plan)
            assert [entry["provider"] for entry in roster] == list(
                OFFERED_VISIBILITY_PROVIDERS
            ), plan
    finally:
        db.close()


def test_only_the_engines_the_plan_measures_are_marked_measured() -> None:
    """Checked against each plan's own roster, not only the rich ones.

    Starter is where the gap is widest: one measured engine against seven
    listed.
    """
    db = _make_session()
    try:
        for plan in VISIBILITY_PLAN_LIMITS:
            roster = _roster_for(db, plan)
            measured = {entry["provider"] for entry in roster if entry["measured_on_plan"]}
            assert measured == set(plan_allowed_providers(plan)), plan
    finally:
        db.close()


def test_starter_marks_six_of_its_seven_rows_unavailable() -> None:
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_starter")
        assert len(roster) == 7
        assert [entry["provider"] for entry in roster if entry["measured_on_plan"]] == [
            "perplexity"
        ]
        assert len([entry for entry in roster if not entry["measured_on_plan"]]) == 6
    finally:
        db.close()


# ---------------------------------------------------------------------------
# What an unavailable row may carry: nothing that reads as a measurement
# ---------------------------------------------------------------------------


def test_an_unmeasured_row_carries_no_number_and_no_timestamp() -> None:
    """The hard requirement of this ticket.

    The project below has a completed, scored measurement for all seven
    engines, so every row has a real timestamp available to print. Six of them
    must not print it: the plan is not re-measuring those engines, and a date
    beside them reads as a measurement that is still being taken.
    """
    db = _make_session()
    try:
        for plan in VISIBILITY_PLAN_LIMITS:
            roster = _roster_for(db, plan, with_history=True)
            for entry in roster:
                if entry["measured_on_plan"]:
                    continue
                assert entry["last_measured_at"] is None, (plan, entry["provider"])
                # No value in the row may be a number either: a 0 or a stale
                # score in any slot is the same false claim in a different
                # shape. Booleans are the flags themselves, not measurements.
                numeric = {
                    key: value
                    for key, value in entry.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                assert numeric == {}, (plan, entry["provider"], numeric)
    finally:
        db.close()


def test_a_measured_row_keeps_its_timestamp() -> None:
    """The suppression is scoped to the rows that need it.

    Hiding every timestamp would be the easy way to pass the test above and
    would remove a true, useful fact from the rows the plan does measure.
    """
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_starter", with_history=True)
        measured = [entry for entry in roster if entry["measured_on_plan"]]
        assert measured, "Starter measures one engine; it must still report its age"
        assert all(entry["last_measured_at"] for entry in measured)
    finally:
        db.close()


def test_an_unmeasured_row_states_a_machine_readable_reason() -> None:
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_standard")
        for entry in roster:
            if entry["measured_on_plan"]:
                assert entry["plan_unavailable_reason"] is None, entry["provider"]
            else:
                assert entry["plan_unavailable_reason"] == REASON_NOT_MEASURED_ON_PLAN, entry[
                    "provider"
                ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Say what unlocks it (SIGV2-1221's pattern)
# ---------------------------------------------------------------------------


def test_an_unmeasured_row_names_the_cheapest_plan_that_measures_it() -> None:
    db = _make_session()
    try:
        roster = {entry["provider"]: entry for entry in _roster_for(db, "plan_starter")}

        assert roster["deepseek"]["unlocks_on_plan"] == "plan_standard"
        assert roster["deepseek"]["unlocks_on_plan_label"] == "Standard"
        assert roster["xai"]["unlocks_on_plan"] == "plan_standard"
        # SIGV2-1216 removed google from the Specialist roster, so the cheapest
        # plan that still measures it is Executive.
        assert roster["google"]["unlocks_on_plan"] == "plan_executive"
        assert roster["google"]["unlocks_on_plan_label"] == "Executive"
        assert roster["openai"]["unlocks_on_plan"] == "plan_specialist"
        assert roster["anthropic"]["unlocks_on_plan"] == "plan_executive"
        assert roster["meta"]["unlocks_on_plan"] == "plan_executive"
        # A row the plan already measures has nothing to unlock.
        assert roster["perplexity"]["unlocks_on_plan"] is None
        assert roster["perplexity"]["unlocks_on_plan_label"] is None
    finally:
        db.close()


def test_the_private_trial_plan_is_never_named_as_the_unlock() -> None:
    """SIGV2-1150's rule: never tell a customer to buy a plan nobody can buy.

    The agency trial's roster is the same three engines as Standard and it
    outranks Starter by weight, so a naive "cheapest plan above this one"
    search finds it first.
    """
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_starter")
        named = {entry["unlocks_on_plan"] for entry in roster}
        assert named & PRIVATE_PLAN_IDS == set()
    finally:
        db.close()


def test_the_top_plan_has_nothing_to_unlock() -> None:
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_executive", with_history=True)
        assert all(entry["measured_on_plan"] for entry in roster)
        assert all(entry["unlocks_on_plan"] is None for entry in roster)
        assert all(entry["plan_unavailable_reason"] is None for entry in roster)
        assert all(entry["last_measured_at"] for entry in roster)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The API boundary has to carry the flag
# ---------------------------------------------------------------------------


def test_the_response_model_serves_every_field_the_roster_builds() -> None:
    """A field the response model omits is a field the customer never sees.

    ``VisibilityEntitlementsResponse`` types the roster, and Pydantic drops
    anything it does not declare, so the honesty flags would be built and then
    silently stripped at the boundary.
    """
    db = _make_session()
    try:
        roster = _roster_for(db, "plan_starter")
        declared = set(VisibilityEngineStatusResponse.model_fields)
        for entry in roster:
            assert set(entry) <= declared, set(entry) - declared
        for field in ("measured_on_plan", "plan_unavailable_reason", "unlocks_on_plan"):
            assert field in declared, field
    finally:
        db.close()


def test_the_entitlement_payload_carries_the_same_roster() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        entitlements = ProjectVisibilityService(db).resolve_entitlements(project)
        measured = {
            entry["provider"] for entry in entitlements["engines"] if entry["measured_on_plan"]
        }
        assert measured == set(entitlements["allowed_providers"])
    finally:
        db.close()
