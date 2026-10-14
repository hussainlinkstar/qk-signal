from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.project_visibility_service import ProjectVisibilityService

try:
    from main import app, get_current_user, get_db
except (
    Exception
):  # pragma: no cover - allow service-level tests to run when app import graph is broken
    app = None
    get_current_user = None
    get_db = None


def _build_project_context(
    plan_type: str = "plan_specialist",
) -> tuple[sessionmaker, models.User, models.Project]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    user = models.User(
        email=f"visibility-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id=f"cus_{plan_type}",
        stripe_subscription_id=f"sub_{plan_type}",
        plan_type=plan_type,
        status="active",
    )
    db.add(subscription)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Visibility Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="northwind.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return db, user, project


def _build_client(
    plan_type: str = "plan_specialist",
) -> tuple[TestClient, sessionmaker, models.User, models.Project]:
    if app is None or get_db is None or get_current_user is None:
        pytest.skip("main app import unavailable in this test runtime")

    db, user, project = _build_project_context(plan_type=plan_type)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    return client, db, user, project


def _cleanup(db, engine) -> None:
    if app is not None:
        app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def test_visibility_query_crud_and_plan_limits() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        list_response = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries")
        assert list_response.status_code == 200
        assert list_response.json()["entitlements"]["max_queries"] == 25
        # SIGV2-1215: Copilot (``bing``) is withdrawn, so it is not offered.
        assert list_response.json()["entitlements"]["allowed_providers"] == [
            "perplexity",
            "xai",
            "deepseek",
        ]

        create_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software for smb",
                "query_type": "aeo",
                "providers": ["perplexity"],
            },
        )
        assert create_response.status_code == 201
        assert create_response.json()["providers"] == ["perplexity"]

        duplicate_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software for smb",
                "query_type": "aeo",
                "providers": ["perplexity"],
            },
        )
        assert duplicate_response.status_code == 409

        # SIGV2-1188: the roster is per plan now, so an engine Standard does not
        # include is refused as a plan limit (402), and a provider outside the
        # supported roster entirely is still rejected (422).
        plan_gated_provider_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software for midmarket",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert plan_gated_provider_response.status_code == 402

        unknown_provider_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software for enterprise",
                "query_type": "geo",
                "providers": ["not-an-engine"],
            },
        )
        assert unknown_provider_response.status_code == 422

        for index in range(2, 26):
            response = client.post(
                f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
                json={
                    "query_text": f"query {index}",
                    "query_type": "aeo",
                    "providers": ["perplexity"],
                },
            )
            assert response.status_code == 201

        limit_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "query 26",
                "query_type": "aeo",
                "providers": ["perplexity"],
            },
        )
        assert limit_response.status_code == 402
        assert "limit reached" in limit_response.json()["detail"].lower()

        created_query_id = create_response.json()["id"]
        patch_response = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{created_query_id}",
            json={"is_active": False},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["is_active"] is False

        delete_response = client.delete(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{created_query_id}",
        )
        assert delete_response.status_code == 204
    finally:
        _cleanup(db, db.get_bind())


def test_visibility_summary_and_trends_are_project_scoped() -> None:
    client, db, _user, project = _build_client(plan_type="plan_specialist")
    try:
        query_one = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity", "openai"],
            is_active=True,
        )
        query_two = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text="how to automate payroll",
            query_type="geo",
            providers=["perplexity"],
            is_active=True,
        )
        db.add_all([query_one, query_two])
        db.commit()

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        today = datetime.now(timezone.utc)

        batches = [
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="best payroll software",
                provider="perplexity",
                schedule_key="20260303",
                status="succeeded",
                score=0.0,
                created_at=yesterday,
                completed_at=yesterday,
            ),
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="best payroll software",
                provider="openai",
                schedule_key="20260303",
                status="succeeded",
                score=0.0,
                created_at=yesterday,
                completed_at=yesterday,
            ),
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="how to automate payroll",
                provider="perplexity",
                schedule_key="20260303",
                status="succeeded",
                score=100.0,
                created_at=yesterday,
                completed_at=yesterday,
            ),
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="best payroll software",
                provider="perplexity",
                schedule_key="20260304",
                status="succeeded",
                score=100.0,
                created_at=today,
                completed_at=today,
            ),
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="best payroll software",
                provider="openai",
                schedule_key="20260304",
                status="succeeded",
                score=0.0,
                created_at=today,
                completed_at=today,
            ),
            models.VisibilityRunBatch(
                project_id=project.id,
                topic="how to automate payroll",
                provider="perplexity",
                schedule_key="20260304",
                status="succeeded",
                score=100.0,
                created_at=today,
                completed_at=today,
            ),
        ]
        db.add_all(batches)
        db.commit()

        runs = [
            models.VisibilityRun(
                batch_id=batches[0].id,
                topic=batches[0].topic,
                provider=batches[0].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=[],
                parsed_citations=[],
                score=0.0,
                status="succeeded",
            ),
            models.VisibilityRun(
                batch_id=batches[1].id,
                topic=batches[1].topic,
                provider=batches[1].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=[],
                parsed_citations=[],
                score=0.0,
                status="succeeded",
            ),
            models.VisibilityRun(
                batch_id=batches[2].id,
                topic=batches[2].topic,
                provider=batches[2].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=["https://example.com/payroll-automation"],
                parsed_citations=["https://example.com/payroll-automation"],
                score=100.0,
                status="succeeded",
            ),
            models.VisibilityRun(
                batch_id=batches[3].id,
                topic=batches[3].topic,
                provider=batches[3].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=["https://example.com/payroll-software"],
                parsed_citations=["https://example.com/payroll-software"],
                score=100.0,
                status="succeeded",
            ),
            models.VisibilityRun(
                batch_id=batches[4].id,
                topic=batches[4].topic,
                provider=batches[4].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=[],
                parsed_citations=[],
                score=0.0,
                status="succeeded",
            ),
            models.VisibilityRun(
                batch_id=batches[5].id,
                topic=batches[5].topic,
                provider=batches[5].provider,
                prompt_template="default",
                prompt="Prompt",
                valid_citations=["https://example.com/payroll-automation"],
                parsed_citations=["https://example.com/payroll-automation"],
                score=100.0,
                status="succeeded",
            ),
        ]
        db.add_all(runs)
        db.commit()

        summary_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-summary"
        )
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()

        assert summary_payload["queries_configured"] == 2
        assert summary_payload["visibility_score"] == 66.67
        # SIGV2-1216: Specialist measures four engines, not five; ``google``
        # left the roster when the plan was repriced to $99. This fixture
        # records its cells on ``perplexity``, which the plan does measure, so
        # the arithmetic below is the summary's maths rather than the roster
        # filter's. An engine the plan has stopped measuring contributes no row
        # and no score at all; that is pinned by
        # ``tests/test_plan_unmeasured_engines.py``.
        assert summary_payload["entitlements"]["allowed_providers"] == [
            "openai",
            "perplexity",
            "xai",
            "deepseek",
        ]
        assert summary_payload["provider_breakdown"][0]["provider"] == "openai"
        assert summary_payload["provider_breakdown"][0]["visibility_score"] == 0.0
        assert summary_payload["provider_breakdown"][1]["provider"] == "perplexity"
        assert summary_payload["provider_breakdown"][1]["visibility_score"] == 100.0

        query_row = next(
            row
            for row in summary_payload["queries"]
            if row["query_text"] == "best payroll software"
        )
        # Canonical provider order, so ChatGPT's uncited cell comes before
        # Perplexity's cited one.
        assert [result["status"] for result in query_row["results"]] == ["not_cited", "cited"]

        trends_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-trends",
            params={"days": 30},
        )
        assert trends_response.status_code == 200
        trend_points = trends_response.json()["points"]
        assert len(trend_points) == 2
        assert trend_points[-1]["visibility_score"] == 66.67
        assert trend_points[0]["visibility_score"] == 33.33
    finally:
        _cleanup(db, db.get_bind())


def test_bridge_legacy_tracker_entries_backfills_queries_without_synthetic_batches() -> None:
    # Executive, not Specialist, since SIGV2-1216. The bridge writes its rows
    # against LEGACY_BRIDGE_PROVIDER (``google``) and refuses to bridge at all
    # on a plan that does not measure it, which is now every plan except
    # Executive. See the note on LEGACY_BRIDGE_PROVIDER.
    db, user, project = _build_project_context(plan_type="plan_executive")
    try:
        tracked_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.add_all(
            [
                models.AeoQueryTrackerEntry(
                    user_id=user.id,
                    context_key="northwind.example/blog",
                    query="best payroll software",
                    citation_hits=2,
                    tracked_at=tracked_at,
                ),
                models.GeoPromptTrackerEntry(
                    user_id=user.id,
                    context_key="northwind.example/pricing",
                    prompt="how to automate payroll",
                    citation_hits=0,
                    tracked_at=tracked_at,
                ),
            ]
        )
        db.commit()

        service = ProjectVisibilityService(db)
        first_bridge = service.bridge_legacy_tracker_entries(project=project)
        second_bridge = service.bridge_legacy_tracker_entries(project=project)

        assert first_bridge["queries_created"] >= 2
        assert first_bridge["batches_created"] == 0
        assert second_bridge["batches_created"] == 0

        bridged_batches = (
            db.query(models.VisibilityRunBatch)
            .filter(models.VisibilityRunBatch.project_id == project.id)
            .all()
        )
        assert bridged_batches == []

        bridged_queries = (
            db.query(models.ProjectVisibilityQuery)
            .filter(models.ProjectVisibilityQuery.project_id == project.id)
            .all()
        )
        assert any(query.query_text == "best payroll software" for query in bridged_queries)
        assert any(query.query_text == "how to automate payroll" for query in bridged_queries)

        summary = service.build_summary(project=project)
        assert summary["completed_checks"] == 0
        assert summary["pending_checks"] == 2
        assert summary["visibility_score"] is None
    finally:
        _cleanup(db, db.get_bind())


def test_visibility_summary_uses_primary_domain_batches_when_competitor_batches_exist() -> None:
    db, _user, project = _build_project_context(plan_type="plan_specialist")
    try:
        visibility_query = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text="best payroll software",
            query_type="aeo",
            providers=["perplexity"],
            is_active=True,
        )
        db.add(visibility_query)
        db.commit()

        now = datetime.now(timezone.utc)
        primary_batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="best payroll software",
            provider="perplexity",
            target_domain="northwind.example",
            schedule_key="primary-domain",
            status="succeeded",
            score=100.0,
            created_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=5),
        )
        competitor_batch = models.VisibilityRunBatch(
            project_id=project.id,
            topic="best payroll software",
            provider="perplexity",
            target_domain="competitor.example",
            schedule_key="competitor-domain",
            status="succeeded",
            score=0.0,
            created_at=now,
            completed_at=now,
        )
        db.add_all([primary_batch, competitor_batch])
        db.commit()
        db.refresh(primary_batch)
        db.refresh(competitor_batch)

        db.add_all(
            [
                models.VisibilityRun(
                    batch_id=primary_batch.id,
                    topic=primary_batch.topic,
                    provider=primary_batch.provider,
                    target_domain=primary_batch.target_domain,
                    prompt_template="default",
                    prompt="Prompt",
                    parsed_citations=["https://northwind.example/source"],
                    valid_citations=["https://northwind.example/source"],
                    score=100.0,
                    status="succeeded",
                ),
                models.VisibilityRun(
                    batch_id=competitor_batch.id,
                    topic=competitor_batch.topic,
                    provider=competitor_batch.provider,
                    target_domain=competitor_batch.target_domain,
                    prompt_template="default",
                    prompt="Prompt",
                    parsed_citations=[],
                    valid_citations=[],
                    score=0.0,
                    status="succeeded",
                ),
            ]
        )
        db.commit()

        summary = ProjectVisibilityService(db).build_summary(project=project)
        assert summary["visibility_score"] == 100.0
        assert summary["queries"][0]["results"][0]["status"] == "cited"
    finally:
        _cleanup(db, db.get_bind())


def test_prompt_limit_refusal_states_cap_usage_and_the_plan_that_raises_it() -> None:
    """SIGV2-1142: a refused prompt must say why, with numbers.

    The customer-facing failure was a refusal with no explanation, so the 402
    body has to carry the cap, the used count, what remains, and the plan that
    lifts the cap. The same four facts travel on the entitlement so the form
    can state them before anyone presses the button.
    """
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        entitlements = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries"
        ).json()["entitlements"]
        assert entitlements["plan_label"] == "Standard"
        assert entitlements["max_queries"] == 25
        assert entitlements["used_queries"] == 0
        assert entitlements["remaining_queries"] == 25
        assert entitlements["upgrade_plan"] == "plan_specialist"
        assert entitlements["upgrade_plan_label"] == "Specialist"
        assert entitlements["upgrade_max_queries"] == 50

        for index in range(25):
            created = client.post(
                f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
                json={
                    "query_text": f"prompt {index}",
                    "query_type": "aeo",
                    "providers": ["perplexity"],
                },
            )
            assert created.status_code == 201

        refused = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "one prompt too many",
                "query_type": "aeo",
                "providers": ["perplexity"],
            },
        )
        assert refused.status_code == 402
        detail = refused.json()["detail"]
        assert "Standard" in detail
        assert "25 prompts" in detail
        assert "25 are in use" in detail
        assert "0 remain" in detail
        assert "Specialist" in detail
        assert "50" in detail

        at_cap = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries").json()[
            "entitlements"
        ]
        assert at_cap["used_queries"] == 25
        assert at_cap["remaining_queries"] == 0
    finally:
        _cleanup(db, db.get_bind())


# ---------------------------------------------------------------------------
# SIGV2-1194: the wording of a tracked prompt is editable
#
# Until this ticket ``VisibilityQueryUpdate`` carried no ``query_text``, so a
# customer who wanted to refine a prompt during scan setup had to delete it and
# lose its measurement history. Every test below fails on the pre-fix code: the
# field was not accepted at all.
# ---------------------------------------------------------------------------


def test_editing_a_prompt_persists_the_new_wording() -> None:
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert created.status_code == 201, created.text
        query_id = created.json()["id"]

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "best payroll software for dental clinics"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["query_text"] == "best payroll software for dental clinics"

        listed = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries").json()[
            "queries"
        ]
        assert [row["query_text"] for row in listed] == ["best payroll software for dental clinics"]

        stored = db.query(models.ProjectVisibilityQuery).filter_by(id=query_id).one()
        assert stored.query_text == "best payroll software for dental clinics"
    finally:
        _cleanup(db, db.get_bind())


def test_an_edit_is_whitespace_normalised_exactly_as_creation_is() -> None:
    """An edit must not be able to land a row creation would have refused."""
    client, db, _user, project = _build_client()
    try:
        query_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "  best   payroll   software   for   smb \n"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["query_text"] == "best payroll software for smb"

        blank = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "   "},
        )
        assert blank.status_code == 422, blank.text

        too_long = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "x" * 501},
        )
        assert too_long.status_code == 422, too_long.text

        unchanged = db.query(models.ProjectVisibilityQuery).filter_by(id=query_id).one()
        assert unchanged.query_text == "best payroll software for smb"
    finally:
        _cleanup(db, db.get_bind())


def test_an_edit_cannot_duplicate_another_active_prompt() -> None:
    client, db, _user, project = _build_client()
    try:
        first_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]
        second_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "how to automate payroll",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]

        collision = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{second_id}",
            # Different capitalisation, same question. Creation refuses this, so
            # an edit has to refuse it the same way.
            json={"query_text": "Best Payroll Software"},
        )
        assert collision.status_code == 409, collision.text
        assert collision.json()["detail"] == "Visibility query already exists for this project"

        assert (
            db.query(models.ProjectVisibilityQuery).filter_by(id=second_id).one().query_text
            == "how to automate payroll"
        )

        # The prompt's own wording is not a collision with itself.
        same_text = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{first_id}",
            json={"query_text": "best payroll software"},
        )
        assert same_text.status_code == 200, same_text.text
    finally:
        _cleanup(db, db.get_bind())


def test_an_inferred_search_type_is_re_resolved_when_the_wording_changes() -> None:
    """A guess must not be left describing words that no longer exist.

    A prompt written before SIGV2-1186 has ``search_type`` NULL, so its type is
    inferred from its text on every read. Change the text and the inference has
    to be taken again, and written down.
    """
    client, db, _user, project = _build_client()
    try:
        legacy = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text="northwind for dental clinics",
            query_type="aeo",
            providers=["google"],
            is_active=True,
        )
        db.add(legacy)
        db.commit()
        db.refresh(legacy)
        assert legacy.search_type is None

        before = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries").json()[
            "queries"
        ][0]
        assert before["search_type"] == "category"
        assert before["search_type_source"] == "inferred"

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{legacy.id}",
            json={"query_text": "northwind vs globex"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["search_type"] == "comparison"
        assert edited.json()["search_type_source"] == "stored"
        assert edited.json()["search_type_suggested"] == "comparison"
    finally:
        _cleanup(db, db.get_bind())


def test_a_stored_type_nobody_chose_is_re_resolved_when_the_wording_changes() -> None:
    """SIGV2-1197: a text edit always re-resolves the type.

    Creating a prompt without a ``search_type`` stores the text-based
    suggestion (SIGV2-1186), so the row reads ``stored`` even though nobody
    chose it. Before this ticket the re-resolve was gated on the source being
    ``inferred``, which that create path makes almost always false, so editing
    the wording left a type describing words that no longer exist.
    """
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "northwind for dental clinics",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert created.status_code == 201, created.text
        query_id = created.json()["id"]
        # Nobody chose this: the create path wrote the suggestion down.
        assert created.json()["search_type"] == "category"
        assert created.json()["search_type_source"] == "stored"

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "northwind vs globex"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["query_text"] == "northwind vs globex"
        assert edited.json()["search_type_suggested"] == "comparison"
        assert edited.json()["search_type"] == "comparison"
        assert edited.json()["search_type_source"] == "stored"

        stored = db.query(models.ProjectVisibilityQuery).filter_by(id=query_id).one()
        assert stored.search_type == "comparison"
    finally:
        _cleanup(db, db.get_bind())


def test_an_explicit_search_type_in_the_same_request_beats_the_re_resolve() -> None:
    """Precedence is unchanged: a caller that states a type is deliberate."""
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "northwind vs globex",
                "query_type": "aeo",
                "providers": ["openai"],
                "search_type": "brand",
            },
        )
        assert created.status_code == 201, created.text
        query_id = created.json()["id"]
        assert created.json()["search_type"] == "brand"

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "how much does northwind cost", "search_type": "brand"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["query_text"] == "how much does northwind cost"
        # The new wording suggests "feature" and the re-resolve would have
        # written it; the explicit value sent in the same request wins.
        assert edited.json()["search_type_suggested"] == "feature"
        assert edited.json()["search_type"] == "brand"
        assert edited.json()["search_type_source"] == "stored"
    finally:
        _cleanup(db, db.get_bind())


def test_an_edit_can_change_the_wording_and_the_type_together() -> None:
    client, db, _user, project = _build_client()
    try:
        query_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "northwind vs globex",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "northwind for dental clinics", "search_type": "problem"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["query_text"] == "northwind for dental clinics"
        assert edited.json()["search_type"] == "problem"
    finally:
        _cleanup(db, db.get_bind())


def test_updating_only_providers_or_activation_is_unchanged_by_the_edit_path() -> None:
    """The other fields keep behaving exactly as they did before SIGV2-1194."""
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
                "search_type": "brand",
            },
        ).json()
        query_id = created["id"]

        providers_only = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"providers": ["openai", "perplexity"]},
        )
        assert providers_only.status_code == 200, providers_only.text
        assert providers_only.json()["providers"] == ["openai", "perplexity"]
        assert providers_only.json()["query_text"] == "best payroll software"
        assert providers_only.json()["search_type"] == "brand"
        assert providers_only.json()["is_active"] is True

        deactivated = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["is_active"] is False
        assert deactivated.json()["query_text"] == "best payroll software"
        assert deactivated.json()["providers"] == ["openai", "perplexity"]

        retyped = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_type": "geo"},
        )
        assert retyped.status_code == 200, retyped.text
        assert retyped.json()["query_type"] == "geo"
        assert retyped.json()["query_text"] == "best payroll software"

        bad_provider = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"providers": ["not-an-engine"]},
        )
        assert bad_provider.status_code == 422, bad_provider.text
    finally:
        _cleanup(db, db.get_bind())


# ---------------------------------------------------------------------------
# SIGV2-1197: ownership of a prompt follows its wording, and uniqueness is
# case-insensitive on both the create and the edit path.
# ---------------------------------------------------------------------------


def _add_generated_prompt(db, project, *, query_text: str) -> models.ProjectVisibilityQuery:
    generated = models.ProjectVisibilityQuery(
        project_id=project.id,
        query_text=query_text,
        query_type="aeo",
        search_type="category",
        origin="generated",
        providers=["google"],
        is_active=True,
    )
    db.add(generated)
    db.commit()
    db.refresh(generated)
    return generated


def test_rewriting_a_generated_prompt_makes_it_the_customers() -> None:
    """A row whose words the customer rewrote is no longer Signal's.

    The management surface badges the set as the untouched starter set or as
    the customer's own from exactly this field, so a ``generated`` row carrying
    the customer's wording is a false claim.
    """
    client, db, _user, project = _build_client()
    try:
        generated = _add_generated_prompt(db, project, query_text="northwind for dental clinics")
        before = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries").json()[
            "queries"
        ][0]
        assert before["origin"] == "generated"
        assert before["is_generated"] is True

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{generated.id}",
            json={"query_text": "northwind for veterinary clinics"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["origin"] == "customer"
        assert edited.json()["is_generated"] is False

        stored = db.query(models.ProjectVisibilityQuery).filter_by(id=generated.id).one()
        assert stored.origin == "customer"
    finally:
        _cleanup(db, db.get_bind())


def test_a_generated_prompt_keeps_its_origin_when_the_wording_does_not_change() -> None:
    """Only a real text change transfers ownership."""
    client, db, _user, project = _build_client()
    try:
        generated = _add_generated_prompt(db, project, query_text="northwind for dental clinics")
        url = f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{generated.id}"

        identical = client.patch(url, json={"query_text": "northwind for dental clinics"})
        assert identical.status_code == 200, identical.text
        assert identical.json()["origin"] == "generated"

        # Whitespace-only noise normalises to the same wording, so it is not a
        # change either.
        whitespace = client.patch(url, json={"query_text": "  northwind   for dental clinics "})
        assert whitespace.status_code == 200, whitespace.text
        assert whitespace.json()["origin"] == "generated"

        providers_only = client.patch(url, json={"providers": ["openai", "perplexity"]})
        assert providers_only.status_code == 200, providers_only.text
        assert providers_only.json()["origin"] == "generated"

        deactivated = client.patch(url, json={"is_active": False})
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["origin"] == "generated"

        retyped = client.patch(url, json={"search_type": "problem"})
        assert retyped.status_code == 200, retyped.text
        assert retyped.json()["origin"] == "generated"
        assert retyped.json()["search_type"] == "problem"

        stored = db.query(models.ProjectVisibilityQuery).filter_by(id=generated.id).one()
        assert stored.origin == "generated"
    finally:
        _cleanup(db, db.get_bind())


def test_a_prompt_the_customer_already_owns_stays_theirs_after_an_edit() -> None:
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["origin"] == "customer"
        query_id = created.json()["id"]

        edited = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"query_text": "best payroll software for smb"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["origin"] == "customer"
        assert edited.json()["is_generated"] is False
    finally:
        _cleanup(db, db.get_bind())


def test_creation_refuses_a_prompt_that_differs_only_in_capitalisation() -> None:
    """The same question asked twice is measured twice and charged twice."""
    client, db, _user, project = _build_client()
    try:
        first = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert first.status_code == 201, first.text

        duplicate = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "Best Payroll Software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["detail"] == "Visibility query already exists for this project"

        rows = db.query(models.ProjectVisibilityQuery).filter_by(project_id=project.id).all()
        assert len(rows) == 1
    finally:
        _cleanup(db, db.get_bind())


def test_creation_reactivates_a_case_only_match_instead_of_adding_a_second_row() -> None:
    """Reactivating an inactive match is deliberate; only the comparison changed."""
    client, db, _user, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert created.status_code == 201, created.text
        query_id = created.json()["id"]

        deactivated = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text

        revived = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "Best Payroll Software",
                "query_type": "geo",
                "providers": ["openai", "perplexity"],
            },
        )
        assert revived.status_code == 201, revived.text
        assert revived.json()["id"] == query_id
        assert revived.json()["is_active"] is True
        assert revived.json()["query_type"] == "geo"
        assert revived.json()["providers"] == ["openai", "perplexity"]

        rows = db.query(models.ProjectVisibilityQuery).filter_by(project_id=project.id).all()
        assert len(rows) == 1
    finally:
        _cleanup(db, db.get_bind())


def test_an_edit_cannot_duplicate_an_inactive_prompt() -> None:
    """Reactivating the inactive row later must not produce two identical prompts."""
    client, db, _user, project = _build_client()
    try:
        first_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "best payroll software",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]
        second_id = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "how to automate payroll",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        ).json()["id"]

        paused = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{first_id}",
            json={"is_active": False},
        )
        assert paused.status_code == 200, paused.text

        collision = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{second_id}",
            json={"query_text": "Best Payroll Software"},
        )
        assert collision.status_code == 409, collision.text
        assert collision.json()["detail"] == "Visibility query already exists for this project"

        assert (
            db.query(models.ProjectVisibilityQuery).filter_by(id=second_id).one().query_text
            == "how to automate payroll"
        )
    finally:
        _cleanup(db, db.get_bind())


def test_top_plan_refusal_does_not_promise_an_upgrade_that_does_not_exist() -> None:
    client, db, _user, project = _build_client(plan_type="plan_executive")
    try:
        entitlements = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries"
        ).json()["entitlements"]
        assert entitlements["plan_label"] == "Executive"
        assert entitlements["upgrade_plan"] is None
        assert entitlements["upgrade_plan_label"] is None
        assert entitlements["upgrade_max_queries"] is None

        detail = ProjectVisibilityService(db)._limit_detail("plan_executive", 200, 200)
        assert "Executive" in detail
        assert "upgrade" not in detail.lower()
    finally:
        _cleanup(db, db.get_bind())
