"""SIGV2-1186 end to end: base prompts at creation, stored types, visible coverage.

Three claims are pinned here, in the shapes the API actually serves them.

1. A project created through the normal path ends up with all five canonical
   search types covered, by prompts that are attributable as generated.
2. A prompt's *stored* search type is what scoring buckets it under, beating the
   text-based inference that used to be the only answer available.
3. Coverage is served with the prompt list, before any scan runs, with the
   suggestion that would fill each gap.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services import project_visibility_service
from services.base_prompt_service import build_coverage, ensure_base_prompts
from services.project_visibility_service import (
    ORIGIN_GENERATED,
    compute_search_type_measurements,
)
from services.query_taxonomy import CANONICAL_SEARCH_TYPES, suggest_search_type

try:
    from main import app, get_current_user, get_db
except Exception:  # pragma: no cover - service-level tests still run
    app = None
    get_current_user = None
    get_db = None


def _build_context(
    plan_type: str = "plan_specialist",
    *,
    with_project: bool = True,
) -> tuple[sessionmaker, models.User, models.Workspace, models.Project | None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email=f"base-prompts-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=25,
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
    db.refresh(user)

    workspace = models.Workspace(name="Base Prompt Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=user.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    db.commit()

    project = None
    if with_project:
        project = models.Project(
            workspace_id=workspace.id,
            name="Northwind",
            domain_url="northwind.example",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

    return db, user, workspace, project


def _build_client(
    plan_type: str = "plan_specialist",
    *,
    with_project: bool = True,
):
    if app is None or get_db is None or get_current_user is None:
        pytest.skip("main app import unavailable in this test runtime")

    db, user, workspace, project = _build_context(plan_type=plan_type, with_project=with_project)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, user, workspace, project


def _cleanup(db) -> None:
    if app is not None:
        app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


# ---------------------------------------------------------------------------
# 1. A project created through the normal path covers all five types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SIGV2-1288 changes what a bare project gets, and these tests record why.
#
# Five types, two jobs. Brand, Feature and Comparison are brand-anchored: the
# question is what the engines say about the customer, so their name belongs in
# it. Category and Problem are discovery: the question is whether an engine
# volunteers them to somebody who has not heard of them.
#
# A discovery prompt carrying the brand name cannot measure discovery. It has
# already supplied the answer, so the score that comes back is recall of a name
# we handed over. Edward caught it on a consultancy: "This is NAMING Tessiant,
# the prompt is what problems does it solve".
#
# Without a category or an audience there is no honest discovery question to
# write, and inventing one is not available: you cannot ask "what are the best
# X providers" without knowing X. So a bare project now gets the three prompts
# that can be written, and the coverage surface offers the other two as a
# fill-in-the-blank the customer finishes in one edit.
#
# Three covered types and two acknowledged gaps beats five types where two
# carry a number that means nothing.
# ---------------------------------------------------------------------------


def test_project_created_through_the_api_covers_the_three_writable_types() -> None:
    client, db, _user, _workspace, _project = _build_client(
        plan_type="plan_specialist", with_project=False
    )
    try:
        response = client.post(
            "/api/v1/workspaces/current/projects",
            json={"name": "Northwind", "domain_url": "https://northwind.example"},
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]

        listed = client.get(f"/api/v1/projects/{project_id}/monitoring/visibility-queries")
        assert listed.status_code == 200, listed.text
        payload = listed.json()

        coverage = {entry["id"]: entry for entry in payload["coverage"]}
        assert [entry["id"] for entry in payload["coverage"]] == CANONICAL_SEARCH_TYPES

        for search_type in ("brand", "feature", "comparison"):
            assert coverage[search_type]["covered"] is True, search_type
            assert coverage[search_type]["prompt_count"] >= 1
            # A covered type has nothing left to suggest.
            assert coverage[search_type]["suggested_prompt"] is None

        # The two discovery types have nothing to anchor on yet, so they are an
        # acknowledged gap with a question the customer finishes.
        for search_type in ("category", "problem"):
            assert coverage[search_type]["covered"] is False, search_type
            assert coverage[search_type]["prompt_count"] == 0
            suggestion = coverage[search_type]["suggested_prompt"]
            assert suggestion
            assert "Northwind" not in suggestion
            assert "[" in suggestion

        # And the brand in the prompts is the domain's, not the project label.
        texts = " ".join(entry["query_text"] for entry in payload["queries"])
        assert "Northwind" in texts

        # Every prompt is attributable as generated, carries its own stored
        # type, and the stored type is what the API reports.
        assert len(payload["queries"]) == 3
        stored_types = set()
        for query in payload["queries"]:
            assert query["origin"] == ORIGIN_GENERATED
            assert query["is_generated"] is True
            assert query["search_type_source"] == "stored"
            assert query["search_type"] in CANONICAL_SEARCH_TYPES
            stored_types.add(query["search_type"])
        assert stored_types == {"brand", "feature", "comparison"}
    finally:
        _cleanup(db)


def test_generated_prompts_count_against_the_plan_cap_and_never_exceed_it() -> None:
    # plan_standard tracks 25 prompts (SIGV2-1188); five generated ones must
    # leave twenty.
    client, db, _user, _workspace, _project = _build_client(
        plan_type="plan_standard", with_project=False
    )
    try:
        response = client.post(
            "/api/v1/workspaces/current/projects",
            json={"name": "Northwind"},
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]

        listed = client.get(f"/api/v1/projects/{project_id}/monitoring/visibility-queries").json()
        entitlements = listed["entitlements"]
        assert entitlements["max_queries"] == 25
        assert (
            entitlements["used_queries"] == 3
        )  # SIGV2-1288: three writable types on a bare project, not five.
        assert entitlements["remaining_queries"] == 22
    finally:
        _cleanup(db)


def test_a_locked_plan_gets_no_generated_prompts_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A plan that tracks no prompts must not be handed an allowance it does not
    # include. Project creation still succeeds; generation reports why.
    monkeypatch.setitem(
        project_visibility_service.VISIBILITY_PLAN_LIMITS,
        "plan_starter",
        {
            "max_queries": 0,
            "allowed_providers": list(project_visibility_service.SUPPORTED_VISIBILITY_PROVIDERS),
        },
    )
    db, _user, _workspace, project = _build_context(plan_type="plan_starter")
    try:
        result = ensure_base_prompts(db, project=project, request_refresh=False)
        assert result["created"] == []
        assert result["reason"] == "plan_locked"
        assert all(entry["covered"] is False for entry in result["coverage"])
        assert db.query(models.ProjectVisibilityQuery).count() == 0
    finally:
        _cleanup(db)


def test_a_cap_below_five_is_filled_in_canonical_order_and_not_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Documented consequence, not an accident: the base set is five prompts, so
    # a plan whose cap is below five cannot cover all five types. The prompts it
    # does get follow canonical order, and the cap is never exceeded.
    monkeypatch.setitem(
        project_visibility_service.VISIBILITY_PLAN_LIMITS,
        "plan_starter",
        {
            "max_queries": 2,
            "allowed_providers": list(project_visibility_service.SUPPORTED_VISIBILITY_PROVIDERS),
        },
    )
    db, _user, _workspace, project = _build_context(plan_type="plan_starter")
    try:
        result = ensure_base_prompts(db, project=project, request_refresh=False)
        # Canonical order, skipping the two that cannot be written yet.
        assert [row.search_type for row in result["created"]] == ["brand", "feature"]
        assert result["reason"] == "created"
        assert db.query(models.ProjectVisibilityQuery).count() == 2

        # Re-running does not creep past the cap.
        again = ensure_base_prompts(db, project=project, request_refresh=False)
        assert again["created"] == []
        assert again["reason"] == "cap_reached"
        assert db.query(models.ProjectVisibilityQuery).count() == 2
    finally:
        _cleanup(db)


def test_the_starter_cap_covers_the_base_set_with_headroom() -> None:
    # SIGV2-1188 settled the ladder: Starter tracks 10 prompts, so the five
    # generated base prompts leave five slots for the customer's own. The cap
    # must stay at least the size of the base set or a new Starter project
    # could not be seeded at all.
    starter_cap = project_visibility_service.VISIBILITY_PLAN_LIMITS["plan_starter"]["max_queries"]
    assert starter_cap == 10
    assert starter_cap >= len(CANONICAL_SEARCH_TYPES)


def test_ensure_base_prompts_is_idempotent() -> None:
    db, _user, _workspace, project = _build_context()
    try:
        first = ensure_base_prompts(db, project=project, request_refresh=False)
        assert (
            len(first["created"]) == 3
        )  # SIGV2-1288: three writable types on a bare project, not five.
        assert first["reason"] == "created"

        second = ensure_base_prompts(db, project=project, request_refresh=False)
        assert second["created"] == []
        assert second["reason"] == "already_covered"
        assert (
            db.query(models.ProjectVisibilityQuery).count() == 3
        )  # SIGV2-1288: three writable types on a bare project, not five.
    finally:
        _cleanup(db)


def test_generation_only_fills_the_types_the_customer_has_not_covered() -> None:
    db, _user, _workspace, project = _build_context()
    try:
        # The customer's own comparison prompt. Its text happens to trip the
        # comparison pattern, but what matters is the stored type.
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="northwind vs globex",
                query_type="aeo",
                search_type="comparison",
                origin="customer",
                providers=["google"],
                is_active=True,
            )
        )
        db.commit()

        result = ensure_base_prompts(db, project=project, request_refresh=False)
        created_types = {row.search_type for row in result["created"]}
        # Category and Problem are not written on a bare project, so the
        # gap this fills is Brand and Feature (SIGV2-1288).
        assert created_types == {"brand", "feature"}
        assert "comparison" not in created_types

        comparison = next(entry for entry in result["coverage"] if entry["id"] == "comparison")
        assert comparison["prompt_count"] == 1
        assert comparison["covered"] is True
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# 2. The stored type beats the inference, in the scoring path
# ---------------------------------------------------------------------------


def test_scoring_buckets_a_prompt_by_its_stored_type_not_its_words() -> None:
    db, _user, _workspace, project = _build_context()
    try:
        # The text says nothing about a customer problem, so the inference files
        # it under Category. The customer declared Problem.
        text = "northwind for dental clinics"
        assert suggest_search_type(text) == "category"

        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text=text,
                query_type="aeo",
                search_type="problem",
                origin="customer",
                providers=["google"],
                is_active=True,
            )
        )
        db.commit()

        coverage = {entry["id"]: entry for entry in build_coverage(db, project=project)}
        assert coverage["problem"]["prompt_count"] == 1
        assert coverage["problem"]["covered"] is True
        assert coverage["category"]["prompt_count"] == 0
        assert coverage["category"]["covered"] is False

        # The same precedence inside the measurement aggregator: the type with
        # the tracked prompt is Problem, so Problem is the one a queued run can
        # fill, and Category is not.
        measurements = compute_search_type_measurements(db, project.id)
        assert set(measurements) == set(CANONICAL_SEARCH_TYPES)
        assert measurements["problem"]["score"] is None
        assert measurements["category"]["score"] is None
    finally:
        _cleanup(db)


def test_a_prompt_with_no_stored_type_keeps_the_old_inferred_answer() -> None:
    # Every row written before the migration has search_type NULL. Nothing may
    # change for it until it is retyped.
    db, _user, _workspace, project = _build_context()
    try:
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="northwind vs globex",
                query_type="aeo",
                search_type=None,
                origin=None,
                providers=["google"],
                is_active=True,
            )
        )
        db.commit()

        coverage = {entry["id"]: entry for entry in build_coverage(db, project=project)}
        assert coverage["comparison"]["prompt_count"] == 1
        assert coverage["comparison"]["covered"] is True
    finally:
        _cleanup(db)


def test_the_customer_can_retype_a_prompt_and_the_bucket_moves() -> None:
    client, db, _user, _workspace, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "northwind vs globex",
                "query_type": "aeo",
                "providers": ["openai"],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        # No type was sent, so the suggestion was stored. It is now the row's
        # own property, not something re-derived on every read.
        assert body["search_type"] == "comparison"
        assert body["search_type_source"] == "stored"
        assert body["search_type_suggested"] == "comparison"
        assert body["is_generated"] is False
        query_id = body["id"]

        retyped = client.patch(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{query_id}",
            json={"search_type": "problem"},
        )
        assert retyped.status_code == 200, retyped.text
        assert retyped.json()["search_type"] == "problem"
        assert retyped.json()["search_type_source"] == "stored"
        # The text still suggests comparison; the stored value wins anyway.
        assert retyped.json()["search_type_suggested"] == "comparison"

        coverage = {
            entry["id"]: entry
            for entry in client.get(
                f"/api/v1/projects/{project.id}/monitoring/visibility-queries"
            ).json()["coverage"]
        }
        assert coverage["problem"]["covered"] is True
        assert coverage["comparison"]["covered"] is False
    finally:
        _cleanup(db)


def test_an_unrecognised_search_type_is_refused_not_silently_replaced() -> None:
    client, db, _user, _workspace, project = _build_client()
    try:
        response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries",
            json={
                "query_text": "northwind pricing",
                "query_type": "aeo",
                "providers": ["openai"],
                "search_type": "aeo",
            },
        )
        assert response.status_code == 422, response.text
        assert "Unsupported search type" in response.text
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# 3. Coverage is visible before a scan runs
# ---------------------------------------------------------------------------


def test_coverage_offers_the_prompt_that_would_fill_each_gap() -> None:
    client, db, _user, _workspace, project = _build_client()
    try:
        payload = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-queries").json()
        coverage = {entry["id"]: entry for entry in payload["coverage"]}
        assert len(coverage) == 5
        for entry in coverage.values():
            assert entry["covered"] is False
            assert entry["prompt_count"] == 0
            suggestion = entry["suggested_prompt"]
            assert suggestion
            # SIGV2-1288: a brand-anchored type names the brand. A
            # discovery type must not, and where nothing anchors it, it is
            # offered as a question the customer finishes in one edit.
            if entry["id"] in ("category", "problem"):
                assert "Northwind" not in suggestion
                assert "[" in suggestion
            else:
                assert "Northwind" in suggestion
        assert coverage["comparison"]["premium"] is True
    finally:
        _cleanup(db)


def test_generate_base_endpoint_fills_the_gaps_and_reports_coverage() -> None:
    client, db, _user, _workspace, project = _build_client()
    try:
        response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/generate-base"
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["reason"] == "created"
        assert (
            len(body["created"]) == 3
        )  # SIGV2-1288: three writable types on a bare project, not five.
        assert {entry["search_type"] for entry in body["created"]} == {
            "brand",
            "feature",
            "comparison",
        }
        assert all(entry["is_generated"] is True for entry in body["created"])
        # SIGV2-1288: the endpoint fills what it can honestly write. The two
        # discovery types stay uncovered on a bare project, with a question
        # the customer finishes rather than one that names them to the
        # engine and then measures whether the engine repeats it back.
        covered = {entry["id"] for entry in body["coverage"] if entry["covered"]}
        assert covered == {"brand", "feature", "comparison"}
        assert (
            body["entitlements"]["used_queries"] == 3
        )  # SIGV2-1288: three writable types on a bare project, not five.

        again = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/generate-base"
        )
        assert again.status_code == 201, again.text
        assert again.json()["reason"] == "already_covered"
        assert again.json()["created"] == []
    finally:
        _cleanup(db)


def test_the_customer_can_delete_a_generated_prompt() -> None:
    client, db, _user, _workspace, project = _build_client()
    try:
        created = client.post(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/generate-base"
        ).json()["created"]
        generated_id = created[0]["id"]
        deleted = client.delete(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries/{generated_id}"
        )
        assert deleted.status_code == 204, deleted.text
        remaining = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-queries"
        ).json()
        assert (
            len(remaining["queries"]) == 2
        )  # SIGV2-1288: three writable types on a bare project, not five.
        assert sum(1 for entry in remaining["coverage"] if entry["covered"]) == 2
    finally:
        _cleanup(db)
