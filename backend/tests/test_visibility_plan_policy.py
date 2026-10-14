"""SIGV2-1188: the per-plan measurement policy.

The ladder is settled as prompt cap + engine roster + sweep cadence per plan,
read from ``VISIBILITY_PLAN_LIMITS`` in one place. These tests pin the four
spend controls:

* the cap refuses the prompt over the line on every write path that reaches
  ``create_query`` (reactivation goes through the same ``_enforce_query_limit``),
* the sweep measures only the engines the plan includes, even when a stored
  prompt names one outside it,
* the sweep treats a project as due only once its plan's interval has elapsed
  since the last scheduled measurement,
* the scheduled sweep covers the project's own domain on that cadence and its
  competitor domains on their own, slower cadence (SIGV2-1208); a plan without
  competitor analysis keeps competitors out of the billed sweep entirely and
  measurable on-demand only,
* a downgrade keeps every prompt and every recorded measurement; the rows past
  the new cap are flagged rather than deleted.

The web-search tool default is also pinned: ``OPENROUTER_WEB_SEARCH_ENABLED``
is on only because this policy is what bounds its spend.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import models
from database import Base
from services.project_visibility_service import (
    ProjectVisibilityService,
    VISIBILITY_PLAN_LIMITS,
    plan_measurement_cadence,
)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db, *, plan_type: str, domain: str = "https://example.com"):
    user = models.User(
        email=f"policy-{plan_type}@example.com",
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
        domain_url=domain,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return user, project


def _add_prompt(
    db,
    project,
    *,
    query_text: str,
    providers: list[str] | None = None,
    is_active: bool = True,
) -> models.ProjectVisibilityQuery:
    """A prompt written straight to the table.

    Direct writes are deliberate: the roster check being tested must hold even
    for a stored prompt that names an engine the plan does not include, which
    the create path would refuse up front.
    """
    prompt = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text=query_text,
        query_type="aeo",
        search_type="category",
        providers=providers or ["perplexity"],
        is_active=is_active,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def _scheduled_batch(
    db,
    project,
    *,
    created_at: datetime,
    schedule_key: str = "202610010000",
    provider: str = "perplexity",
    target_domain: str = "example.com",
) -> models.VisibilityRunBatch:
    batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic="tracked prompt",
        provider=provider,
        target_domain=target_domain,
        schedule_key=schedule_key,
        status="succeeded",
        created_at=created_at,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _add_competitor(db, project, *, domain: str = "rival.example", name: str = "Rival") -> None:
    db.add(
        models.ProjectCompetitor(
            project_id=project.id,
            target_url=f"https://{domain}",
            normalized_domain=domain,
            display_name=name,
        )
    )
    db.commit()
    db.refresh(project)


def _load_jobs(db, *, scheduled: bool = True):
    import visibility_index_worker as worker

    return worker._load_project_visibility_jobs(db, scheduled=scheduled)


# ---------------------------------------------------------------------------
# Prompt cap: the one over the line is refused, per plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("plan_type", "cap"),
    [
        ("plan_starter", 10),
        ("plan_agency_trial", 25),
        ("plan_standard", 25),
        ("plan_specialist", 50),
        ("plan_executive", 200),
    ],
)
def test_the_cap_refuses_the_prompt_over_the_line(plan_type: str, cap: int) -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type=plan_type)
        for index in range(cap):
            _add_prompt(db, project, query_text=f"prompt {index}")

        service = ProjectVisibilityService(db)
        with pytest.raises(HTTPException) as excinfo:
            service.create_query(
                project=project,
                query_text="one prompt too many",
                query_type="aeo",
                providers=[],
            )

        assert excinfo.value.status_code == 402
        # The refusal states the cap and the plan that raises it (SIGV2-1142).
        assert str(cap) in excinfo.value.detail
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Engine roster: the plan decides what runs, not the stored row
# ---------------------------------------------------------------------------


def test_the_sweep_runs_only_the_engines_the_plan_includes() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        # A stored prompt naming an engine outside the Starter roster: the
        # sweep must drop google and keep only perplexity.
        _add_prompt(
            db,
            project,
            query_text="best payroll software",
            providers=["google", "perplexity"],
        )

        jobs = _load_jobs(db)

        assert jobs
        assert {provider for _pid, _uid, _t, provider, _d in jobs} == {"perplexity"}
    finally:
        db.close()


def test_a_stored_prompt_with_no_plan_engine_produces_no_jobs() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(db, project, query_text="enterprise payroll", providers=["anthropic"])

        assert _load_jobs(db) == []
    finally:
        db.close()


def test_the_roster_also_gates_the_prompt_triggered_refresh() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(
            db,
            project,
            query_text="best payroll software",
            providers=["openai", "perplexity"],
        )

        jobs = _load_jobs(db, scheduled=False)

        assert {provider for _pid, _uid, _t, provider, _d in jobs} == {"perplexity"}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cadence: a project is due only once its plan's interval has elapsed
# ---------------------------------------------------------------------------


def test_a_starter_project_is_not_due_before_its_weekly_interval() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(db, project, query_text="best payroll software")
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(days=2))

        assert _load_jobs(db) == []
    finally:
        db.close()


def test_a_starter_project_is_due_once_the_week_has_elapsed() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(db, project, query_text="best payroll software")
        _scheduled_batch(
            db, project, created_at=datetime.now(timezone.utc) - timedelta(days=7, hours=1)
        )

        assert _load_jobs(db) != []
    finally:
        db.close()


def test_a_standard_project_is_not_due_before_its_daily_interval() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_standard")
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(hours=2))

        assert _load_jobs(db) == []
    finally:
        db.close()


def test_a_standard_project_is_due_once_the_day_has_elapsed() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_standard")
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(hours=25))

        assert _load_jobs(db) != []
    finally:
        db.close()


def test_refresh_and_scan_batches_do_not_reset_the_cadence() -> None:
    """Only scheduled batches count: a prompt-triggered refresh ("queued") or a
    scan-linked batch must not push a weekly plan's next scheduled measurement
    out by another week."""
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(db, project, query_text="best payroll software")
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(days=8))
        # A fresh refresh batch an hour ago: cadence still measured from the
        # last SCHEDULED run, so the project stays due.
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            schedule_key="queued",
        )
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            schedule_key="volatility:20261006",
        )

        assert _load_jobs(db) != []
    finally:
        db.close()


def test_a_project_never_scheduled_is_due() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        _add_prompt(db, project, query_text="best payroll software")

        assert _load_jobs(db) != []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Competitor domains: their own slower cadence, and only where the plan
# includes competitor analysis (SIGV2-1208)
# ---------------------------------------------------------------------------


def test_a_plan_without_competitor_analysis_keeps_competitors_out_of_the_sweep() -> None:
    """Standard does not include competitor analysis, so its competitor rows
    stay on-demand only: there is no entitlement to pace."""
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_standard")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])

        scheduled_jobs = _load_jobs(db, scheduled=True)
        refresh_jobs = _load_jobs(db, scheduled=False)

        assert scheduled_jobs
        assert {domain for *_rest, domain in scheduled_jobs} == {"example.com"}
        # On-demand measurement (the prompt-triggered refresh) still covers the
        # competitor, so nothing the customer could do before is gone.
        assert {domain for *_rest, domain in refresh_jobs} == {
            "example.com",
            "rival.example",
        }
    finally:
        db.close()


def test_the_sweep_measures_competitors_on_a_plan_that_includes_them() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"example.com", "rival.example"}
    finally:
        db.close()


def test_competitors_are_not_remeasured_before_their_weekly_interval() -> None:
    """The own domain is every two days on Specialist (SIGV2-1216), the
    competitors weekly: once the own clock has elapsed and the weekly one has
    not, only the own domain comes back."""
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        two_days_ago = datetime.now(timezone.utc) - timedelta(hours=49)
        _scheduled_batch(db, project, created_at=two_days_ago, target_domain="example.com")
        _scheduled_batch(db, project, created_at=two_days_ago, target_domain="rival.example")

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"example.com"}
    finally:
        db.close()


def test_competitors_come_back_once_the_week_has_elapsed() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        last_week = datetime.now(timezone.utc) - timedelta(days=7, hours=1)
        _scheduled_batch(db, project, created_at=last_week, target_domain="example.com")
        _scheduled_batch(db, project, created_at=last_week, target_domain="rival.example")

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"example.com", "rival.example"}
    finally:
        db.close()


def test_a_weekly_competitor_run_does_not_delay_the_own_domain_run() -> None:
    """The two clocks are independent. A competitor batch an hour ago must not
    make the own domain look freshly measured, which is what a single
    project-wide clock would have done."""
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(hours=49),
            target_domain="example.com",
        )
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            target_domain="rival.example",
        )

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"example.com"}
    finally:
        db.close()


def test_a_competitor_only_window_does_not_remeasure_the_own_domain() -> None:
    """The mirror case: the own domain ran an hour ago and the competitors a
    fortnight ago, so only the competitors are due."""
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            target_domain="example.com",
        )
        _scheduled_batch(
            db,
            project,
            created_at=datetime.now(timezone.utc) - timedelta(days=14),
            target_domain="rival.example",
        )

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"rival.example"}
    finally:
        db.close()


def test_the_competitor_cadence_is_a_distinct_dial_in_the_same_table() -> None:
    from app.config.plans import can_use_feature
    from services.project_visibility_service import VISIBILITY_SWEEP_WEEKLY_SECONDS

    assert {
        plan: config["competitor_sweep_interval_seconds"]
        for plan, config in VISIBILITY_PLAN_LIMITS.items()
    } == {
        "plan_starter": None,
        "plan_agency_trial": VISIBILITY_SWEEP_WEEKLY_SECONDS,
        "plan_standard": None,
        "plan_specialist": VISIBILITY_SWEEP_WEEKLY_SECONDS,
        "plan_executive": VISIBILITY_SWEEP_WEEKLY_SECONDS,
    }
    # The dial and the entitlement must not drift apart: a cadence exists for
    # exactly the plans that sell competitor analysis.
    for plan, config in VISIBILITY_PLAN_LIMITS.items():
        assert (config["competitor_sweep_interval_seconds"] is not None) is can_use_feature(
            plan, "has_competitor_analysis"
        ), plan


def test_the_competitor_cadence_is_overridable_per_plan(monkeypatch) -> None:
    from services.project_visibility_service import (
        _competitor_sweep_override_warned,
        plan_competitor_sweep_interval_seconds,
    )

    _competitor_sweep_override_warned.clear()
    monkeypatch.setenv("VISIBILITY_SPECIALIST_COMPETITOR_SWEEP_SECONDS", str(72 * 3600))
    assert plan_competitor_sweep_interval_seconds("plan_specialist") == 72 * 3600
    # Unparseable and non-positive values fall back to the table default rather
    # than to "every tick".
    monkeypatch.setenv("VISIBILITY_SPECIALIST_COMPETITOR_SWEEP_SECONDS", "weekly-ish")
    assert plan_competitor_sweep_interval_seconds("plan_specialist") == 7 * 24 * 3600
    monkeypatch.setenv("VISIBILITY_SPECIALIST_COMPETITOR_SWEEP_SECONDS", "0")
    assert plan_competitor_sweep_interval_seconds("plan_specialist") == 7 * 24 * 3600
    monkeypatch.delenv("VISIBILITY_SPECIALIST_COMPETITOR_SWEEP_SECONDS")
    assert plan_competitor_sweep_interval_seconds("plan_specialist") == 7 * 24 * 3600


def test_an_override_cannot_grant_competitor_measurement_to_a_plan_without_it(
    monkeypatch,
) -> None:
    """Cadence is a cost dial, not an entitlement switch: a plan that does not
    include competitor analysis stays off the scheduled competitor sweep no
    matter what the env says."""
    from services.project_visibility_service import plan_competitor_sweep_interval_seconds

    monkeypatch.setenv("VISIBILITY_STANDARD_COMPETITOR_SWEEP_SECONDS", "3600")
    assert plan_competitor_sweep_interval_seconds("plan_standard") is None

    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_standard")
        _add_competitor(db, project)
        _add_prompt(db, project, query_text="best payroll software", providers=["xai"])

        jobs = _load_jobs(db, scheduled=True)

        assert {domain for *_rest, domain in jobs} == {"example.com"}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Downgrade: prompts and history survive; only the measured set shrinks
# ---------------------------------------------------------------------------


def test_a_downgrade_keeps_every_prompt_and_flags_the_over_cap_rows() -> None:
    db = _make_session()
    try:
        user, project = _seed_project(db, plan_type="plan_specialist")
        service = ProjectVisibilityService(db)
        prompts = [
            _add_prompt(
                db,
                project,
                query_text=f"prompt {index}",
                providers=["google", "perplexity"],
            )
            for index in range(12)
        ]
        # Old enough that a Starter project is due again on its weekly cadence.
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(days=8))

        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == user.id).one()
        )
        subscription.plan_type = "plan_starter"
        db.commit()

        # Nothing is deleted and no measurement is erased.
        assert (
            db.query(models.ProjectVisibilityQuery)
            .filter(models.ProjectVisibilityQuery.project_id == project.id)
            .count()
            == 12
        )
        assert db.query(models.VisibilityRunBatch).count() == 1

        # The measured set is the first 10 active prompts in creation order.
        measured = service.measured_query_ids(project=project)
        assert measured == {prompt.id for prompt in prompts[:10]}

        # The sweep (and the refresh) measure only the in-cap rows.
        jobs = _load_jobs(db)
        assert {topic for _pid, _uid, topic, _p, _d in jobs} == {
            f"prompt {index}" for index in range(10)
        }
    finally:
        db.close()


def test_serialize_marks_over_cap_rows_via_the_listing() -> None:
    """The surface needs a flag, not a disappearance: rows past the cap render
    as kept-but-unmeasured instead of vanishing or looking broken."""
    db = _make_session()
    try:
        user, project = _seed_project(db, plan_type="plan_specialist")
        for index in range(12):
            _add_prompt(db, project, query_text=f"prompt {index}", providers=["google"])

        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == user.id).one()
        )
        subscription.plan_type = "plan_starter"
        db.commit()

        service = ProjectVisibilityService(db)
        measured = service.measured_query_ids(project=project)
        serialized = [
            {
                **service.serialize_query(query),
                "exceeds_plan_cap": bool(query.is_active) and query.id not in measured,
            }
            for query in service.list_queries(project_id=project.id)
        ]
        assert [row["exceeds_plan_cap"] for row in serialized] == [False] * 10 + [True] * 2
        assert all(row["is_active"] for row in serialized)
    finally:
        db.close()


def test_serialize_names_the_engines_the_plan_stopped_measuring() -> None:
    """A prompt pinned to an engine outside the roster is not silently blank.

    SIGV2-1216 took Gemini off the Specialist roster, which leaves every
    prompt that named it with an empty measured roster: the sweep skips it and
    every aggregate drops it, so the row renders as a healthy prompt that
    never produces a result. ``unmeasured_providers`` is what lets the surface
    name the dead engine, and it is the difference between "nothing measured
    this" and "this engine is not on your plan".
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        dead = _add_prompt(db, project, query_text="gemini only prompt", providers=["google"])
        mixed = _add_prompt(
            db, project, query_text="gemini and openai", providers=["google", "openai"]
        )
        live = _add_prompt(db, project, query_text="openai only", providers=["openai"])

        service = ProjectVisibilityService(db)
        rows = {
            row["id"]: row
            for row in (service.serialize_query(query) for query in (dead, mixed, live))
        }

        # Fully dead: nothing left to measure, and the reason is named.
        assert rows[dead.id]["providers"] == []
        assert rows[dead.id]["unmeasured_providers"] == ["google"]
        # Partly dead: still measured on the engine the plan keeps, and the
        # one it dropped is still reported rather than quietly disappearing.
        assert rows[mixed.id]["providers"] == ["openai"]
        assert rows[mixed.id]["unmeasured_providers"] == ["google"]
        # Healthy rows carry an empty list, never a stray engine.
        assert rows[live.id]["providers"] == ["openai"]
        assert rows[live.id]["unmeasured_providers"] == []
    finally:
        db.close()


def test_serialize_does_not_report_a_withdrawn_engine_as_a_plan_gap() -> None:
    """Copilot is gone from the product, not missing from a plan.

    A withdrawn engine (SIGV2-1215) must not surface as "not measured on your
    plan", which would invite an upgrade that buys nothing: no plan measures
    it, so there is no plan to upgrade to.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_executive")
        prompt = _add_prompt(db, project, query_text="copilot prompt", providers=["bing"])

        row = ProjectVisibilityService(db).serialize_query(prompt)

        assert row["providers"] == []
        assert row["unmeasured_providers"] == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The ladder itself, and the flag it makes affordable
# ---------------------------------------------------------------------------


def test_the_ladder_is_the_settled_1188_table() -> None:
    assert {plan: config["max_queries"] for plan, config in VISIBILITY_PLAN_LIMITS.items()} == {
        "plan_starter": 10,
        "plan_agency_trial": 25,
        "plan_standard": 25,
        "plan_specialist": 50,
        "plan_executive": 200,
    }
    # SIGV2-1188 kept ``bing`` in every roster so a customer-visible engine
    # would not silently stop updating; SIGV2-1215 withdrew Copilot from the
    # product, so the row and the measurement went together and no roster
    # offers it any more.
    assert VISIBILITY_PLAN_LIMITS["plan_starter"]["allowed_providers"] == [
        "perplexity",
    ]
    assert VISIBILITY_PLAN_LIMITS["plan_agency_trial"]["allowed_providers"] == [
        "perplexity",
        "deepseek",
        "xai",
    ]
    assert VISIBILITY_PLAN_LIMITS["plan_executive"]["allowed_providers"] == [
        "perplexity",
        "deepseek",
        "xai",
        "google",
        "openai",
        "anthropic",
        "meta",
    ]
    assert VISIBILITY_PLAN_LIMITS["plan_starter"]["sweep_interval_seconds"] == 7 * 24 * 3600
    assert VISIBILITY_PLAN_LIMITS["plan_executive"]["sweep_interval_seconds"] == 24 * 3600


# ---------------------------------------------------------------------------
# SIGV2-1216: the Specialist row, repriced
# ---------------------------------------------------------------------------
# SIGV2-1211 cut Specialist from $399 to $99 and left this table alone, which
# took modelled measurement cost from about 20% of the price to about 81% of
# it. Two dials move here, both approved: the sweep goes to every two days and
# the roster drops to four engines. Nothing else about the plan changes.


def test_specialist_sweeps_every_two_days() -> None:
    assert VISIBILITY_PLAN_LIMITS["plan_specialist"]["sweep_interval_seconds"] == 48 * 3600


def test_specialist_measures_four_engines_without_gemini() -> None:
    """``google`` is the engine that leaves.

    At 150 input and 600 output tokens a cell, ``google/gemini-2.5-pro`` and
    ``openai/gpt-5`` cost 5.3 times the other three engines in this roster
    combined, so only one of those two can carry the reduction. ChatGPT is the
    engine a customer most expects to be measured, so Gemini is the one that
    goes.
    """
    assert VISIBILITY_PLAN_LIMITS["plan_specialist"]["allowed_providers"] == [
        "perplexity",
        "deepseek",
        "xai",
        "openai",
    ]


def test_the_specialist_sweep_does_not_run_gemini() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(
            db,
            project,
            query_text="best payroll software",
            providers=["google", "openai", "perplexity"],
        )

        jobs = _load_jobs(db)

        assert {provider for _pid, _uid, _t, provider, _d in jobs} == {"openai", "perplexity"}
    finally:
        db.close()


def test_a_specialist_project_is_not_due_before_its_two_day_interval() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, query_text="best payroll software")
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(hours=25))

        assert _load_jobs(db) == []
    finally:
        db.close()


def test_a_specialist_project_is_due_once_two_days_have_elapsed() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, query_text="best payroll software")
        _scheduled_batch(db, project, created_at=datetime.now(timezone.utc) - timedelta(hours=49))

        assert _load_jobs(db)
    finally:
        db.close()


def test_the_entitlement_states_the_two_day_cadence_rather_than_calling_it_daily() -> None:
    """A 48-hour sweep described as "daily" is a false freshness claim.

    ``measurement_cadence`` exists so a surface can state the cadence instead
    of implying one, so it has to name the interval the plan actually runs on.
    """
    db = _make_session()
    try:
        _user, specialist = _seed_project(db, plan_type="plan_specialist")
        entitlements = ProjectVisibilityService(db).resolve_entitlements(specialist)
        assert entitlements["sweep_interval_seconds"] == 48 * 3600
        assert entitlements["measurement_cadence"] == "every_2_days"
    finally:
        db.close()


def test_the_other_plans_keep_their_own_cadence_wording() -> None:
    db = _make_session()
    try:
        for plan, cadence in (
            ("plan_starter", "weekly"),
            ("plan_standard", "daily"),
            ("plan_executive", "daily"),
        ):
            _user, project = _seed_project(db, plan_type=plan)
            entitlements = ProjectVisibilityService(db).resolve_entitlements(project)
            assert entitlements["measurement_cadence"] == cadence, plan
    finally:
        db.close()


def test_an_override_above_a_week_names_its_own_day_count(monkeypatch) -> None:
    """ "weekly" for a 14-day sweep is the same overclaim "daily" was for 48h."""
    monkeypatch.setenv("VISIBILITY_SPECIALIST_SWEEP_SECONDS", str(14 * 86400))
    assert plan_measurement_cadence("plan_specialist") == "every_14_days"
    monkeypatch.setenv("VISIBILITY_SPECIALIST_SWEEP_SECONDS", str(8 * 86400))
    assert plan_measurement_cadence("plan_specialist") == "every_8_days"


def test_the_repricing_does_not_touch_the_other_plans() -> None:
    """SIGV2-1216 is a Specialist change. Standard, Starter and Executive keep
    the roster and the cadence SIGV2-1188 and SIGV2-1215 left them on."""
    assert VISIBILITY_PLAN_LIMITS["plan_standard"]["allowed_providers"] == [
        "perplexity",
        "deepseek",
        "xai",
    ]
    assert VISIBILITY_PLAN_LIMITS["plan_standard"]["sweep_interval_seconds"] == 24 * 3600
    assert VISIBILITY_PLAN_LIMITS["plan_agency_trial"]["sweep_interval_seconds"] == 24 * 3600
    assert VISIBILITY_PLAN_LIMITS["plan_specialist"]["max_queries"] == 50
    assert (
        VISIBILITY_PLAN_LIMITS["plan_specialist"]["competitor_sweep_interval_seconds"]
        == 7 * 24 * 3600
    )


def test_the_sweep_cadence_is_overridable_per_plan(monkeypatch) -> None:
    from services.project_visibility_service import (
        plan_sweep_interval_seconds,
        _sweep_override_warned,
    )

    _sweep_override_warned.clear()
    # A positive override wins without a deploy.
    monkeypatch.setenv("VISIBILITY_EXECUTIVE_SWEEP_SECONDS", str(48 * 3600))
    assert plan_sweep_interval_seconds("plan_executive") == 48 * 3600
    # An unparseable or non-positive value falls back to the table default,
    # never to "every tick".
    monkeypatch.setenv("VISIBILITY_EXECUTIVE_SWEEP_SECONDS", "soon")
    assert plan_sweep_interval_seconds("plan_executive") == 24 * 3600
    monkeypatch.setenv("VISIBILITY_EXECUTIVE_SWEEP_SECONDS", "0")
    assert plan_sweep_interval_seconds("plan_executive") == 24 * 3600
    monkeypatch.delenv("VISIBILITY_EXECUTIVE_SWEEP_SECONDS")
    assert plan_sweep_interval_seconds("plan_executive") == 24 * 3600


def test_web_search_defaults_on_now_that_the_policy_bounds_it() -> None:
    # The field default is pinned rather than the live settings object, so an
    # operator's local env cannot make this test lie.
    from core.config import Settings

    assert Settings.model_fields["OPENROUTER_WEB_SEARCH_ENABLED"].default is True


def test_an_empty_provider_request_takes_the_plans_own_engine() -> None:
    """A caller that does not name an engine must not have one guessed for it.

    The AEO and GEO prompt dialogs used to fall back to a hardcoded
    ``["google"]`` whenever the plan roster had not loaded yet. On a plan that
    does not measure Gemini, that creates a prompt nothing will ever measure:
    it renders as a healthy row, the sweep skips it, and its search-type card
    reads "No prompt data yet" while the prompt sits there. Five of the six
    prompts on the preprod project were stranded exactly this way.

    Sending no engines is now the honest request, and the backend answers it
    with the plan's own first engine, because the backend is the only side
    that knows the plan.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        service = ProjectVisibilityService(db)

        created = service.create_query(
            project=project,
            query_text="what is acme payroll",
            query_type="aeo",
            providers=[],
        )

        allowed = service.resolve_entitlements(project)["allowed_providers"]
        assert created.providers == allowed[:1]
        # Specialist does not measure Gemini, so nothing may have chosen it.
        assert "google" not in created.providers
    finally:
        db.close()
