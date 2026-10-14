"""SIGV2-1215: Copilot (``bing``) leaves the product.

``bing`` was the only provider outside ``LIVE_MEASURABLE_PROVIDERS`` and the
only key with a ``LIVE_UNAVAILABLE_REASONS`` entry: there is no public consumer
API for Copilot answers, so it could only ever run on the controlled Bedrock
proxy model, which is not Copilot. Jake took it out of the product on
28 September. SIGV2-1188 kept it in every plan roster on purpose, so that it
would not become a visible row that silently never updates; this ticket
withdraws the row and the measurement together.

What these tests pin:

* no plan offers it, so no surface can present it as a selectable engine,
* nothing customer-facing enumerates it: not the entitlement roster, not the
  engine roster, not the per-engine breakdown, not the trend series, not a
  prompt's own provider list, even when a stored prompt still names it,
* the measurement stops with the row: the scheduled sweep does not run it,
* the provider, its label and its Bedrock proxy mapping all survive, so the
  withdrawal is one flag away from being undone the day a real Copilot API
  exists,
* recorded measurements are not deleted.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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
    LIVE_MEASURABLE_PROVIDERS,
    LIVE_UNAVAILABLE_REASONS,
    OFFERED_VISIBILITY_PROVIDERS,
    SUPPORTED_VISIBILITY_PROVIDERS,
    VISIBILITY_PLAN_LIMITS,
    VISIBILITY_PROVIDER_LABELS,
    WITHDRAWN_VISIBILITY_PROVIDERS,
    ProjectVisibilityService,
)

WITHDRAWN = "bing"


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db, *, plan_type: str = "plan_executive"):
    user = models.User(
        email=f"copilot-{plan_type}@example.com",
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


def _add_prompt(db, project, *, providers: list[str], query_text: str = "best payroll software"):
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


def _record_measurement(db, project, *, provider: str = WITHDRAWN) -> models.VisibilityRunBatch:
    """A completed historical measurement, the kind this ticket must not delete."""
    now = datetime.now(timezone.utc)
    batch = models.VisibilityRunBatch(
        project_id=project.id,
        topic="best payroll software",
        provider=provider,
        target_domain="example.com",
        schedule_key="202609200000",
        status="succeeded",
        score=42.0,
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


# ---------------------------------------------------------------------------
# The withdrawal itself
# ---------------------------------------------------------------------------


def test_copilot_is_recorded_as_withdrawn() -> None:
    assert WITHDRAWN_VISIBILITY_PROVIDERS == (WITHDRAWN,)
    # The vocabulary is unchanged: the provider still exists, so recorded rows
    # and the proxy path keep resolving.
    assert WITHDRAWN in SUPPORTED_VISIBILITY_PROVIDERS
    assert VISIBILITY_PROVIDER_LABELS[WITHDRAWN] == "Copilot"
    # Offered is supported minus withdrawn, in the canonical order.
    assert OFFERED_VISIBILITY_PROVIDERS == tuple(
        provider for provider in SUPPORTED_VISIBILITY_PROVIDERS if provider != WITHDRAWN
    )
    # Every remaining offered engine has a live measurement path, which is the
    # whole reason this one goes: it never had one.
    assert set(OFFERED_VISIBILITY_PROVIDERS) == set(LIVE_MEASURABLE_PROVIDERS)
    assert set(LIVE_UNAVAILABLE_REASONS) == {WITHDRAWN}


def test_no_plan_offers_copilot() -> None:
    for plan, config in VISIBILITY_PLAN_LIMITS.items():
        assert WITHDRAWN not in config["allowed_providers"], plan


def test_the_entitlement_roster_does_not_offer_copilot() -> None:
    db = _make_session()
    try:
        for plan in VISIBILITY_PLAN_LIMITS:
            _user, project = _seed_project(db, plan_type=plan)
            entitlements = ProjectVisibilityService(db).resolve_entitlements(project)
            assert WITHDRAWN not in entitlements["allowed_providers"], plan
            assert WITHDRAWN not in entitlements["estimated_cost_per_check"], plan
    finally:
        db.close()


def test_the_engine_roster_does_not_render_a_copilot_card() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        roster = ProjectVisibilityService(db).build_engine_roster(project)

        assert [entry["provider"] for entry in roster] == list(OFFERED_VISIBILITY_PROVIDERS)
        assert WITHDRAWN not in {entry["provider"] for entry in roster}
        # Every card left claims live measurement, so no card advertises an
        # engine measured through a proxy.
        assert all(entry["live_measurement"] == "available" for entry in roster)
        assert all(entry["live_unavailable_reason"] is None for entry in roster)
    finally:
        db.close()


def test_a_stored_prompt_naming_copilot_renders_no_copilot_row() -> None:
    """The row goes even for a prompt written while it was still offered.

    A prompt row, its per-engine cells and the summary's provider breakdown are
    all derived from the stored provider list, so without this the engine would
    linger on exactly the customers who had selected it.
    """
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])
        service = ProjectVisibilityService(db)

        summary = service.build_summary(project=project)

        assert WITHDRAWN not in summary["providers"]
        assert WITHDRAWN not in {row["provider"] for row in summary["provider_breakdown"]}
        for query in summary["queries"]:
            assert WITHDRAWN not in query["providers"]
            assert WITHDRAWN not in {result["provider"] for result in query["results"]}
    finally:
        db.close()


def test_the_trend_series_carries_no_copilot_line() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])
        _record_measurement(db, project)

        trends = ProjectVisibilityService(db).build_trends(project=project, days=30)

        assert WITHDRAWN not in trends["providers"]
        for point in trends["points"]:
            assert WITHDRAWN not in point["providers"]
    finally:
        db.close()


def test_share_of_voice_does_not_count_a_withdrawn_engine() -> None:
    """The comparative surface divides this domain's citations by every
    domain's, so a Copilot cell left in the denominator would keep moving a
    number the customer reads long after the engine was withdrawn."""
    db = _make_session()
    try:
        _user, project = _seed_project(db)
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
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])
        _record_measurement(db, project, provider="perplexity")
        _record_measurement(db, project, provider=WITHDRAWN)
        service = ProjectVisibilityService(db)

        summary = service.build_comparative_summary(project=project, days=30)
        trends = service.build_comparative_trends(project=project, days=30)

        for domain, data in summary["domains"].items():
            assert WITHDRAWN not in data["providers"], domain
        for domain, data in trends["domains"].items():
            for point in data["trend"]:
                assert WITHDRAWN not in point["scores"], domain
    finally:
        db.close()


def test_the_prompt_listing_drops_copilot_from_a_stored_row() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        prompt = _add_prompt(db, project, providers=["perplexity", WITHDRAWN])
        service = ProjectVisibilityService(db)

        serialized = service.serialize_query(prompt)

        assert serialized["providers"] == ["perplexity"]
        # The stored row is untouched: this is a display withdrawal, not a
        # rewrite of the customer's data.
        db.refresh(prompt)
        assert WITHDRAWN in list(prompt.providers)
    finally:
        db.close()


def test_a_request_for_copilot_alone_is_refused_rather_than_silently_measured() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)

        with pytest.raises(HTTPException) as excinfo:
            service.create_query(
                project=project,
                query_text="best payroll software",
                query_type="aeo",
                providers=[WITHDRAWN],
            )

        assert excinfo.value.status_code == 422
        assert "Copilot" in excinfo.value.detail
    finally:
        db.close()


def test_a_request_naming_copilot_alongside_a_live_engine_keeps_the_live_one() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        service = ProjectVisibilityService(db)

        created = service.create_query(
            project=project,
            query_text="best payroll software",
            query_type="aeo",
            providers=[WITHDRAWN, "perplexity"],
        )

        assert list(created.providers) == ["perplexity"]
    finally:
        db.close()


def test_the_scheduled_sweep_does_not_measure_copilot() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])

        import visibility_index_worker as worker

        jobs = worker._load_project_visibility_jobs(db, scheduled=True)

        assert jobs
        assert WITHDRAWN not in {provider for _pid, _uid, _topic, provider, _domain in jobs}
    finally:
        db.close()


def test_the_prompt_triggered_refresh_does_not_measure_copilot_either() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])

        import visibility_index_worker as worker

        jobs = worker._load_project_visibility_jobs(db, scheduled=False)

        assert jobs
        assert WITHDRAWN not in {provider for _pid, _uid, _topic, provider, _domain in jobs}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# What must survive
# ---------------------------------------------------------------------------


def test_recorded_copilot_measurements_are_not_deleted() -> None:
    db = _make_session()
    try:
        _user, project = _seed_project(db)
        _add_prompt(db, project, providers=["perplexity", WITHDRAWN])
        batch = _record_measurement(db, project)

        ProjectVisibilityService(db).build_summary(project=project)

        stored = (
            db.query(models.VisibilityRunBatch)
            .filter(models.VisibilityRunBatch.id == batch.id)
            .one()
        )
        assert stored.provider == WITHDRAWN
        assert stored.score == 42.0
    finally:
        db.close()


def test_the_bedrock_proxy_mapping_for_copilot_survives() -> None:
    """The measurement path is kept, not deleted: the withdrawal is a product
    decision that must be reversible without rebuilding the plumbing."""
    from core.config import Settings

    assert WITHDRAWN in Settings().BEDROCK_MEASUREMENT_MODEL_MAP
    # It is still absent from the OpenRouter map, which is the fact that
    # started all of this.
    assert WITHDRAWN not in Settings().OPENROUTER_MEASUREMENT_MODEL_MAP


def test_clearing_the_flag_restores_the_engine(monkeypatch) -> None:
    """One flag, nothing else, decides whether the engine is offered.

    This is the restore path: if a real Copilot API appears, the provider comes
    back by emptying ``WITHDRAWN_VISIBILITY_PROVIDERS`` and putting it back in
    the plan rosters, without reinstating any display code.
    """
    import services.project_visibility_service as service_module

    monkeypatch.setattr(service_module, "WITHDRAWN_VISIBILITY_PROVIDERS", ())

    assert service_module._ordered_providers([WITHDRAWN, "perplexity"]) == [
        WITHDRAWN,
        "perplexity",
    ]

    db = _make_session()
    try:
        _user, project = _seed_project(db)
        roster = service_module.ProjectVisibilityService(db).build_engine_roster(project)
        assert WITHDRAWN in {entry["provider"] for entry in roster}
    finally:
        db.close()
