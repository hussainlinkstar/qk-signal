"""SIGV2-1216: an engine a plan stopped measuring shows no frozen number.

This ticket takes ``google`` (Gemini) out of the Specialist roster to bring the
plan's modelled measurement cost back inside its price. Removing an engine from
a roster is not only an arithmetic change: a project that was measured on that
engine keeps its recorded cells, and every per-engine surface in this service
is derived from the stored prompt rows rather than from the plan. Left alone,
a Specialist customer would keep a Gemini card showing the last score it ever
measured, frozen, while the sweep silently stopped refreshing it.

That is the same defect SIGV2-1215 removed for Copilot, one plan down: a
visible row that never updates, and an aggregate that keeps counting cells
nobody re-measures. So the rule is the same rule, scoped to the plan instead of
the product: an engine outside the project's plan roster is not measured, so no
surface may present a number for it, and no aggregate may count one.

What these tests pin:

* the plan's roster is the authority on what is measured, for every surface
  that reports a measurement: the per-engine breakdown, the project score, the
  trend series, Share of Voice, the per-search-type scores and a prompt's own
  engine list,
* the engine card payload says plainly which engines the plan measures, so a
  timestamp from before the change cannot read as a current measurement,
* history is re-read through the current roster, not cut at the change, so a
  Specialist series has no step in it at the point the roster shrank,
* nothing is deleted, and Executive still measures Gemini: this is scoped to
  the plan that stopped, not to the engine.

The deliberate boundary is at the bottom: an engine a plan has *never*
measured is still listed by ``build_engine_roster``, which is a separate
defect with its own ticket. This ticket fixes the frozen number, not the
aspirational list.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import models
from database import Base
from services.project_visibility_service import (
    OFFERED_VISIBILITY_PROVIDERS,
    VISIBILITY_PLAN_LIMITS,
    ProjectVisibilityService,
    compute_search_type_measurements,
    plan_allowed_providers,
    plan_unmeasured_providers,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The engine SIGV2-1216 takes off the Specialist roster.
DROPPED = "google"
# An engine Specialist keeps, so every assertion below can show the filter is
# per-engine rather than a blanket refusal.
KEPT = "perplexity"
TOPIC = "best payroll software"


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db, *, plan_type: str = "plan_specialist"):
    user = models.User(
        email=f"ladder-{plan_type}-{datetime.now(timezone.utc).timestamp()}@example.com",
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


def _add_prompt(db, project, *, providers: list[str], query_text: str = TOPIC):
    """A prompt stored with the engines it was created with.

    Written straight to the table on purpose: the create path already refuses
    an engine the plan does not allow, so the only way to reach the state this
    ticket is about is a row that predates the roster change.
    """
    prompt = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text=query_text,
        query_type="aeo",
        search_type="category",
        providers=providers,
        is_active=True,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def _record_measurement(
    db,
    project,
    *,
    provider: str,
    score: float,
    days_ago: int = 0,
    target_domain: str = "example.com",
    topic: str = TOPIC,
) -> models.VisibilityRunBatch:
    measured_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic=topic,
        provider=provider,
        target_domain=target_domain,
        schedule_key=f"{provider}-{days_ago}",
        status="succeeded",
        score=score,
        started_at=measured_at,
        completed_at=measured_at,
        created_at=measured_at,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    # The engine card reads its freshness off the runs, not the batch, so a
    # measurement without one would leave ``last_measured_at`` null and prove
    # nothing about a stale timestamp.
    db.add(
        models.VisibilityRun(
            batch_id=batch.id,
            topic=topic,
            provider=provider,
            target_domain=target_domain,
            prompt_template="visibility.default",
            prompt="who should I use for payroll",
            parsed_citations=[],
            valid_citations=[],
            score=score,
            status="succeeded",
            started_at=measured_at,
            completed_at=measured_at,
            created_at=measured_at,
        )
    )
    db.commit()
    db.refresh(batch)
    return batch


# ---------------------------------------------------------------------------
# The roster change itself
# ---------------------------------------------------------------------------


def test_specialist_no_longer_measures_gemini() -> None:
    assert DROPPED not in VISIBILITY_PLAN_LIMITS["plan_specialist"]["allowed_providers"]
    assert DROPPED in VISIBILITY_PLAN_LIMITS["plan_executive"]["allowed_providers"]
    # The complement is derived from the roster, never listed by hand, so it
    # cannot fall out of step with the table above.
    assert DROPPED in plan_unmeasured_providers("plan_specialist")
    assert DROPPED not in plan_unmeasured_providers("plan_executive")
    for plan in VISIBILITY_PLAN_LIMITS:
        measured = set(plan_allowed_providers(plan))
        unmeasured = set(plan_unmeasured_providers(plan))
        assert measured.isdisjoint(unmeasured), plan
        assert measured | unmeasured == set(OFFERED_VISIBILITY_PROVIDERS), plan


def test_the_engine_card_says_which_engines_the_plan_measures() -> None:
    """The card payload is where a timestamp could read as a live measurement.

    ``last_measured_at`` is suppressed on an unmeasured row, because a stale
    date next to an engine the plan no longer sweeps reads as a live
    measurement cadence it does not have.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=DROPPED, score=90.0)
        roster = ProjectVisibilityService(db).build_engine_roster(project)
        by_key = {entry["provider"]: entry for entry in roster}

        assert by_key[DROPPED]["measured_on_plan"] is False
        assert by_key[KEPT]["measured_on_plan"] is True
        # The recorded history survives in storage but is not served on a card
        # the plan no longer measures.
        assert by_key[DROPPED]["last_measured_at"] is None
    finally:
        db.close()


def test_executive_still_measures_gemini_on_every_surface() -> None:
    """Scoped to the plan that stopped, not to the engine.

    If this fails alongside the Specialist tests, the fix withdrew Gemini from
    the product instead of from one roster.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_executive")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=DROPPED, score=90.0)
        service = ProjectVisibilityService(db)

        roster = {entry["provider"]: entry for entry in service.build_engine_roster(project)}
        summary = service.build_summary(project=project)

        assert roster[DROPPED]["measured_on_plan"] is True
        assert DROPPED in summary["providers"]
        assert DROPPED in {row["provider"] for row in summary["provider_breakdown"]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# No frozen number on any surface
# ---------------------------------------------------------------------------


def test_a_stored_specialist_prompt_naming_gemini_renders_no_gemini_card() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=DROPPED, score=90.0)
        _record_measurement(db, project, provider=KEPT, score=10.0)

        summary = ProjectVisibilityService(db).build_summary(project=project)

        assert DROPPED not in summary["providers"]
        assert DROPPED not in {row["provider"] for row in summary["provider_breakdown"]}
        for query in summary["queries"]:
            assert DROPPED not in query["providers"]
            assert DROPPED not in {result["provider"] for result in query["results"]}
    finally:
        db.close()


def test_the_project_score_stops_counting_an_engine_the_plan_stopped_measuring() -> None:
    """SIGV2-1215's lesson, one plan down.

    A row that is not shown must not keep moving the number that is. Gemini
    scored 90 and Perplexity 10; once the plan stops measuring Gemini the
    project's score is Perplexity's alone, not the average of a live cell and
    a frozen one.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=DROPPED, score=90.0)
        _record_measurement(db, project, provider=KEPT, score=10.0)

        summary = ProjectVisibilityService(db).build_summary(project=project)

        assert summary["visibility_score"] == 10.0
        assert summary["completed_checks"] == 1
        assert summary["total_checks"] == 1
    finally:
        db.close()


def test_the_specialist_trend_has_no_gemini_line_and_no_step_where_the_roster_shrank() -> None:
    """History is re-read through the current roster rather than cut at the change.

    This is what keeps the series honest: every point is computed on the same
    set of engines, so the line moves level once and never shows a cliff that
    looks like a drop in performance. Perplexity went 10 then 20 across the two
    days; Gemini sat at 90 on both.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=KEPT, score=10.0, days_ago=2)
        _record_measurement(db, project, provider=KEPT, score=20.0, days_ago=1)
        _record_measurement(db, project, provider=DROPPED, score=90.0, days_ago=2)
        _record_measurement(db, project, provider=DROPPED, score=90.0, days_ago=1)

        trends = ProjectVisibilityService(db).build_trends(project=project, days=30)

        assert DROPPED not in trends["providers"]
        for point in trends["points"]:
            assert DROPPED not in point["providers"]
        assert [point["visibility_score"] for point in trends["points"]] == [10.0, 20.0]
    finally:
        db.close()


def test_share_of_voice_does_not_count_an_engine_the_plan_stopped_measuring() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        db.add(
            models.ProjectCompetitor(
                project_id=project.id,
                target_url="https://rival.example",
                normalized_domain="rival.example",
                display_name="Rival",
            )
        )
        db.commit()
        db.refresh(project)
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=KEPT, score=10.0)
        _record_measurement(db, project, provider=DROPPED, score=90.0)
        _record_measurement(
            db, project, provider=DROPPED, score=90.0, target_domain="rival.example"
        )
        service = ProjectVisibilityService(db)

        summary = service.build_comparative_summary(project=project, days=30)
        trends = service.build_comparative_trends(project=project, days=30)

        for domain, data in summary["domains"].items():
            assert DROPPED not in data["providers"], domain
        for domain, data in trends["domains"].items():
            for point in data["trend"]:
                assert DROPPED not in point["scores"], domain
    finally:
        db.close()


def test_the_per_search_type_score_excludes_an_engine_the_plan_stopped_measuring() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        _record_measurement(db, project, provider=KEPT, score=10.0)
        _record_measurement(db, project, provider=DROPPED, score=90.0)

        measurements = compute_search_type_measurements(db=db, project_id=project.id)

        assert measurements["category"]["score"] == 10.0
        assert measurements["category"]["answer_ratio"] == {"present": 0, "measured": 1}
    finally:
        db.close()


def test_the_prompt_listing_drops_an_engine_the_plan_stopped_measuring() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        prompt = _add_prompt(db, project, providers=[KEPT, DROPPED])
        service = ProjectVisibilityService(db)

        serialized = service.serialize_query(prompt)

        assert serialized["providers"] == [KEPT]
        # The stored row is untouched: the customer's selection is kept, so an
        # upgrade back to Executive restores the engine without re-entry.
        db.refresh(prompt)
        assert DROPPED in list(prompt.providers)
    finally:
        db.close()


def test_recorded_measurements_are_not_deleted() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_specialist")
        _add_prompt(db, project, providers=[KEPT, DROPPED])
        batch = _record_measurement(db, project, provider=DROPPED, score=90.0)

        ProjectVisibilityService(db).build_summary(project=project)

        stored = (
            db.query(models.VisibilityRunBatch)
            .filter(models.VisibilityRunBatch.id == batch.id)
            .one()
        )
        assert stored.provider == DROPPED
        assert stored.score == 90.0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The deliberate boundary
# ---------------------------------------------------------------------------


def test_an_engine_a_plan_never_measured_is_still_listed_on_its_own_ticket() -> None:
    """Recorded, not endorsed.

    ``build_engine_roster`` lists every offered engine on every plan, so
    Starter is listed seven engines while measuring one. That is a real defect
    and it predates this ticket: it affects every plan and it is about an
    aspirational list, not about a number frozen at its last value. It has its
    own ticket (SIGV2-1228). What this ticket guarantees is that each listed
    engine now says whether the plan measures it, which is the fact a surface
    needs in order to render the list honestly.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db, plan_type="plan_starter")
        roster = ProjectVisibilityService(db).build_engine_roster(project)

        assert [entry["provider"] for entry in roster] == list(OFFERED_VISIBILITY_PROVIDERS)
        measured = {entry["provider"] for entry in roster if entry["measured_on_plan"]}
        assert measured == set(plan_allowed_providers("plan_starter")) == {KEPT}
        # No number is attached to an engine the plan has never measured, so
        # nothing on those rows can go stale.
        assert all(
            entry["last_measured_at"] is None for entry in roster if not entry["measured_on_plan"]
        )
    finally:
        db.close()
