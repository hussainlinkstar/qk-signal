from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.project_visibility_service import compute_search_type_measurements
from services.query_taxonomy import (
    CANONICAL_SEARCH_TYPES,
    SEARCH_TYPE_BRAND,
    SEARCH_TYPE_CATEGORY,
    SEARCH_TYPE_COMPARISON,
    SEARCH_TYPE_FEATURE,
    SEARCH_TYPE_PROBLEM,
    aggregate_search_types,
)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_project(db) -> models.Project:
    user = models.User(
        email="realtypes@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # SIGV2-1216: an engine outside the project's plan roster contributes no
    # cell to any measurement, so the plan has to be stated. Without a
    # subscription this project resolves to Starter, whose roster is one
    # engine, and the ``google`` prompts below would be measuring that filter
    # instead of the search-type arithmetic these tests are about. Executive
    # is the only roster holding every offered engine. The filter itself is
    # pinned by ``tests/test_plan_unmeasured_engines.py``.
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_realtypes",
            stripe_subscription_id="sub_realtypes",
            plan_type="plan_executive",
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
    return project


def _add_query(db, project_id: int, text: str) -> models.ProjectVisibilityQuery:
    q = models.ProjectVisibilityQuery(
        project_id=project_id,
        query_text=text,
        query_type="aeo",
        providers=["google"],
        is_active=True,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def _add_batch(
    db,
    project_id: int,
    topic: str,
    score: float,
    *,
    citations: list[str] | None = None,
    answer: str | None = None,
    status: str = "completed",
) -> models.VisibilityRunBatch:
    batch = models.VisibilityRunBatch(
        project_id=project_id,
        topic=topic,
        provider="google",
        target_domain="example.com",
        schedule_key="manual",
        status=status,
        score=score,
        created_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    if citations is not None:
        db.add(
            models.VisibilityRun(
                batch_id=batch.id,
                topic=topic,
                provider="google",
                target_domain="example.com",
                prompt_template="default",
                prompt=topic,
                raw_response={"answer": answer if answer is not None else "An answer."},
                parsed_citations=list(citations),
                valid_citations=list(citations),
                status="succeeded",
                score=score,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        db.refresh(batch)
    return batch


def test_measurements_mean_scores_and_none_for_missing_types() -> None:
    db = _make_session()
    try:
        project = _seed_project(db)
        # comparison
        _add_query(db, project.id, "nike vs adidas comparison")
        _add_batch(db, project.id, "nike vs adidas comparison", 80.0)
        # feature (pricing)
        _add_query(db, project.id, "running shoe pricing")
        _add_batch(db, project.id, "running shoe pricing", 40.0)
        # problem (instructional) -- two queries to verify mean
        _add_query(db, project.id, "how to clean running shoes")
        _add_batch(db, project.id, "how to clean running shoes", 50.0)
        _add_query(db, project.id, "why do running shoes squeak")
        _add_batch(db, project.id, "why do running shoes squeak", 70.0)
        # category (plain)
        _add_query(db, project.id, "best running shoes")
        _add_batch(db, project.id, "best running shoes", 60.0)

        measurements = compute_search_type_measurements(db, project.id)

        assert set(measurements.keys()) == set(CANONICAL_SEARCH_TYPES)
        assert measurements[SEARCH_TYPE_COMPARISON]["score"] == 80.0
        assert measurements[SEARCH_TYPE_FEATURE]["score"] == 40.0
        assert measurements[SEARCH_TYPE_PROBLEM]["score"] == 60.0  # mean of 50 and 70
        assert measurements[SEARCH_TYPE_CATEGORY]["score"] == 60.0
        # No measured query maps to brand, so there is nothing to average and
        # nothing to count.
        assert measurements[SEARCH_TYPE_BRAND]["score"] is None
        assert measurements[SEARCH_TYPE_BRAND]["answer_ratio"] is None
    finally:
        db.close()


def test_answer_ratio_counts_answers_the_brand_appeared_in() -> None:
    db = _make_session()
    try:
        project = _seed_project(db)
        # Two problem-intent queries: one answer cites the site, one does not.
        _add_query(db, project.id, "how to clean running shoes")
        _add_batch(
            db,
            project.id,
            "how to clean running shoes",
            70.0,
            citations=["https://example.com/care-guide"],
        )
        _add_query(db, project.id, "why do running shoes squeak")
        _add_batch(
            db,
            project.id,
            "why do running shoes squeak",
            10.0,
            citations=["https://rival.example/squeak"],
        )

        measurements = compute_search_type_measurements(db, project.id)

        assert measurements[SEARCH_TYPE_PROBLEM]["answer_ratio"] == {
            "present": 1,
            "measured": 2,
        }
    finally:
        db.close()


def test_answer_ratio_counts_an_uncited_brand_mention_as_present() -> None:
    db = _make_session()
    try:
        project = _seed_project(db)
        # The answer names the site but cites nobody: brand_mention, which the
        # dashboard's Answer Presence row also counts as present.
        _add_query(db, project.id, "best running shoes")
        _add_batch(
            db,
            project.id,
            "best running shoes",
            30.0,
            citations=[],
            answer="For best running shoes, example.com is worth a look.",
        )

        measurements = compute_search_type_measurements(db, project.id)

        assert measurements[SEARCH_TYPE_CATEGORY]["answer_ratio"] == {
            "present": 1,
            "measured": 1,
        }
    finally:
        db.close()


def test_answer_ratio_excludes_pending_and_failed_checks() -> None:
    db = _make_session()
    try:
        project = _seed_project(db)
        # A queued check has not produced an answer yet; a failed one produced
        # no measurement at all. Neither may count toward the denominator,
        # because a denominator that includes them understates presence.
        _add_query(db, project.id, "best running shoes")
        _add_batch(db, project.id, "best running shoes", 0.0, status="running")
        _add_query(db, project.id, "top running shoes")
        _add_batch(db, project.id, "top running shoes", 0.0, status="failed")

        measurements = compute_search_type_measurements(db, project.id)

        assert measurements[SEARCH_TYPE_CATEGORY]["answer_ratio"] is None
        assert measurements[SEARCH_TYPE_CATEGORY]["score"] is None
    finally:
        db.close()


def test_answer_ratio_is_zero_over_n_not_none_when_answers_were_checked() -> None:
    db = _make_session()
    try:
        project = _seed_project(db)
        # A completed check with no citation and no mention is a real "we looked
        # and the brand was not there", so 0 of 1 is the honest ratio.
        _add_query(db, project.id, "best running shoes")
        _add_batch(db, project.id, "best running shoes", 0.0, citations=[])

        measurements = compute_search_type_measurements(db, project.id)

        assert measurements[SEARCH_TYPE_CATEGORY]["answer_ratio"] == {
            "present": 0,
            "measured": 1,
        }
    finally:
        db.close()


def test_measurements_defensive_no_project_or_rows() -> None:
    db = _make_session()
    try:
        # No project at all.
        measurements = compute_search_type_measurements(db, 999)
        assert set(measurements.keys()) == set(CANONICAL_SEARCH_TYPES)
        assert all(entry["score"] is None for entry in measurements.values())
        assert all(entry["answer_ratio"] is None for entry in measurements.values())

        # Project with no queries/rows.
        project = _seed_project(db)
        measurements = compute_search_type_measurements(db, project.id)
        assert all(entry["score"] is None for entry in measurements.values())
        assert all(entry["answer_ratio"] is None for entry in measurements.values())

        # None db / project_id.
        measurements = compute_search_type_measurements(None, None)
        assert all(entry["score"] is None for entry in measurements.values())
    finally:
        db.close()


def test_aggregate_marks_measured_types_and_carries_the_answer_ratio() -> None:
    measurements = {
        SEARCH_TYPE_BRAND: {"score": None, "answer_ratio": None},
        SEARCH_TYPE_CATEGORY: {"score": 12.0, "answer_ratio": {"present": 2, "measured": 9}},
        SEARCH_TYPE_PROBLEM: {"score": None, "answer_ratio": {"present": 0, "measured": 3}},
        SEARCH_TYPE_FEATURE: {"score": 90.0, "answer_ratio": None},
        SEARCH_TYPE_COMPARISON: {"score": 25.0, "answer_ratio": {"present": 1, "measured": 1}},
    }

    result = aggregate_search_types(measurements=measurements)
    by_id = {entry["id"]: entry for entry in result}

    assert [entry["id"] for entry in result] == CANONICAL_SEARCH_TYPES
    assert by_id[SEARCH_TYPE_COMPARISON]["premium"] is True

    assert by_id[SEARCH_TYPE_CATEGORY]["score"] == 12
    assert by_id[SEARCH_TYPE_CATEGORY]["source"] == "measured"
    assert by_id[SEARCH_TYPE_CATEGORY]["answer_ratio"] == {"present": 2, "measured": 9}
    assert by_id[SEARCH_TYPE_FEATURE]["score"] == 90
    assert by_id[SEARCH_TYPE_FEATURE]["source"] == "measured"
    assert by_id[SEARCH_TYPE_FEATURE]["answer_ratio"] is None

    # No measured score and no estimate in its place.
    assert by_id[SEARCH_TYPE_BRAND]["score"] is None
    assert by_id[SEARCH_TYPE_BRAND]["source"] == "unmeasured"
    # A type can have a counted answer ratio without a mean score.
    assert by_id[SEARCH_TYPE_PROBLEM]["score"] is None
    assert by_id[SEARCH_TYPE_PROBLEM]["source"] == "unmeasured"
    assert by_id[SEARCH_TYPE_PROBLEM]["answer_ratio"] == {"present": 0, "measured": 3}


def test_aggregate_without_measurements_is_all_unmeasured() -> None:
    result = aggregate_search_types()
    assert [entry["id"] for entry in result] == CANONICAL_SEARCH_TYPES
    for entry in result:
        assert entry["source"] == "unmeasured"
        assert entry["score"] is None
        assert entry["answer_ratio"] is None


def test_aggregate_never_estimates_a_type_from_audit_sub_scores() -> None:
    # The retired heuristic read these exact fields and mapped them onto the
    # five labels. A report carrying all of them must still produce five
    # unmeasured entries (SIGV2-1105).
    measurements = {
        SEARCH_TYPE_BRAND: {"score": None, "answer_ratio": None},
    }
    result = aggregate_search_types(measurements=measurements)
    assert all(entry["score"] is None for entry in result)
    assert all(entry["source"] == "unmeasured" for entry in result)


def test_aggregate_rejects_an_unsupportable_answer_ratio() -> None:
    measurements = {
        SEARCH_TYPE_BRAND: {"score": 40.0, "answer_ratio": {"present": 0, "measured": 0}},
        SEARCH_TYPE_CATEGORY: {"score": 40.0, "answer_ratio": {"present": 5, "measured": 2}},
        SEARCH_TYPE_PROBLEM: {"score": 40.0, "answer_ratio": {"measured": 4}},
        SEARCH_TYPE_FEATURE: {"score": 40.0, "answer_ratio": "4 of 10"},
        SEARCH_TYPE_COMPARISON: {"score": 40.0, "answer_ratio": {"present": -1, "measured": 4}},
    }
    result = aggregate_search_types(measurements=measurements)
    assert all(entry["answer_ratio"] is None for entry in result)


def test_aggregate_handles_malformed_measurements() -> None:
    for bad in (None, [], "nope", 42, {"brand": "broken"}, {"brand": {"score": "x"}}):
        result = aggregate_search_types(measurements=bad)
        assert [entry["id"] for entry in result] == CANONICAL_SEARCH_TYPES
        assert all(entry["score"] is None for entry in result)
