"""SIGV2-1072 — recommendation chain defects.

1. Dismissal applied on every path that serves the Advisor plan
   (``get_audit_record``, ``get_project_latest_audit``, advisor-chat evidence).
2. ``source_recommendation_key`` derived server-side, never client-asserted.
3. Task sync reads ``recommendations.items`` — the same node the Advisor plan
   is built from.
4. Key digest covers raw input so distinct titles cannot collide; the data
   migration recomputes persisted keys and is idempotent.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from app.services.learnings_service import compute_action_fingerprint, record_decision
from database import Base
from routers.api_router import AdvisorChatRequest, advisor_chat, get_audit_record
from routers.workspace_router import (
    ProjectTaskCreateRequest,
    create_project_task,
    get_project_latest_audit,
)
from services.project_task_service import (
    _normalize_source_recommendation_key,
    extract_audit_recommendation_candidates,
    resolve_task_recommendation_key,
    sync_project_tasks,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20261007_010000_recompute_task_source_keys.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("sigv2_1072_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_project(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(
        email="chain-owner@example.com", hashed_password="x", role="user", credits=20
    )
    db.add(owner)
    db.flush()
    workspace = models.Workspace(name="Chain Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Client Chain",
        domain_url="https://client-chain.example",
        target_country="US",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def _report_with_recommendations(items: list[dict[str, object]]) -> dict:
    # Same proven shape as tests/test_audit_response_advisor.py: the normalized
    # report lands these in canonical recommendations.items, which is exactly
    # the node the Advisor plan (and now task sync) is built from.
    return {
        "metadata": {"audit_outcome": "completed"},
        "analysis": {"seo_score": 62, "geo_score": 55, "aeo_score": 40},
        "suggestions": items,
        "geo_score": 55,
        "seo_score": 62,
        "aeo_score": 40,
    }


def _report_with_items_node(items: list[dict[str, object]]) -> dict:
    return {
        "metadata": {"audit_outcome": "completed"},
        "recommendations": {"items": items},
        "geo_score": 55,
        "seo_score": 62,
        "aeo_score": 40,
    }


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    full_report: dict,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://client-chain.example",
        seo_score=62,
        geo_score=55,
        aeo_score=40,
        full_report=full_report,
        created_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _advisor_actions(report: dict) -> list[str]:
    advisor = report.get("metadata", {}).get("advisor") or {}
    return [a["action"] for a in advisor.get("actions", [])]


ITEM_A = {
    "action": "Add FAQPage schema to the pricing page",
    "estimated_effort": "low",
    "expected_score_impact": {"aeo": 15},
    "grounded_by_findings": ["aeo.no_faq_schema"],
    "derived_from": ["analysis.answerability"],
}
ITEM_B = {
    "action": "Rewrite the meta description",
    "estimated_effort": "low",
    "expected_score_impact": {"seo": 5},
    "grounded_by_findings": ["seo.meta_description"],
    "derived_from": ["analysis.seo"],
}


def _dismiss(db: Session, project_id: int, action_text: str, user_id: int) -> None:
    record_decision(
        db,
        project_id=project_id,
        action_fingerprint=compute_action_fingerprint(action_text),
        decision="dismissed",
        decided_by=user_id,
        action_label=action_text,
    )
    db.commit()


# ── Defect 1: dismissal honoured on every serve path ─────────────────────


def test_get_audit_record_suppresses_dismissed_action() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A, ITEM_B]),
        )
        _dismiss(db, project.id, ITEM_B["action"], owner.id)

        result = get_audit_record(audit.id, user=owner, db=db)
        actions = _advisor_actions(result["full_report"])
        assert ITEM_A["action"] in actions
        assert ITEM_B["action"] not in actions
    finally:
        _cleanup(db, engine)


def test_get_project_latest_audit_suppresses_dismissed_action() -> None:
    """Fails against pre-fix code: _normalize_project_audit_report never passed
    dismissed fingerprints, so the persisted plan came back unfiltered."""
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A, ITEM_B]),
        )
        _dismiss(db, project.id, ITEM_B["action"], owner.id)

        entry = get_project_latest_audit(
            project.id, user=owner, db=db, include_full_report=True, audit_type=None
        )
        assert entry is not None
        actions = _advisor_actions(entry["full_report"])
        assert ITEM_A["action"] in actions
        assert ITEM_B["action"] not in actions
    finally:
        _cleanup(db, engine)


def test_advisor_chat_sees_filtered_plan_and_persisted_report_untouched() -> None:
    """The chat evidence builder reads metadata.advisor from the report handed
    to it; the endpoint must hand it the dismissal-filtered plan without
    mutating the persisted payload."""
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id="cus_chain",
                plan_type="plan_standard",
                status="active",
            )
        )
        db.commit()
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A, ITEM_B]),
        )
        _dismiss(db, project.id, ITEM_B["action"], owner.id)

        captured: dict = {}

        def fake_answer(report, message, history=None):
            captured["report"] = report
            return {"reply": "ok", "citations": []}

        with patch("services.advisor_chat_service.answer", side_effect=fake_answer):
            with patch("services.advisor_chat_history_service.list_messages", return_value=[]):
                with patch(
                    "services.advisor_chat_history_service.append_message", return_value=None
                ):
                    advisor_chat(
                        audit.id,
                        payload=AdvisorChatRequest(message="what now?"),
                        user=owner,
                        db=db,
                    )

        actions = _advisor_actions(captured["report"])
        assert ITEM_A["action"] in actions
        assert ITEM_B["action"] not in actions
        # The persisted payload must not have been mutated in place.
        persisted_actions = _advisor_actions(audit.full_report)
        assert ITEM_B["action"] not in persisted_actions or persisted_actions == []
    finally:
        _cleanup(db, engine)


# ── Defect 2: server-derived provenance ──────────────────────────────────


def test_task_created_from_recommendation_gets_server_derived_key() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A]),
        )
        payload = ProjectTaskCreateRequest(
            title=ITEM_A["action"],
            source_audit_id=audit.id,
        )
        result = create_project_task(project.id, payload=payload, user=owner, db=db)
        task = db.query(models.ProjectTask).filter_by(id=result["id"]).one()
        assert task.origin == models.ProjectTaskOrigin.AUDIT_RECOMMENDATION
        expected = extract_audit_recommendation_candidates(audit)[0].key
        assert task.source_recommendation_key == expected
    finally:
        _cleanup(db, engine)


def test_unverifiable_client_key_is_not_trusted() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A]),
        )
        payload = ProjectTaskCreateRequest(
            title="Totally unrelated task",
            source_audit_id=audit.id,
            source_recommendation_key="technical:add-faqpage-schema:deadbeef1234",
        )
        result = create_project_task(project.id, payload=payload, user=owner, db=db)
        task = db.query(models.ProjectTask).filter_by(id=result["id"]).one()
        assert task.origin == models.ProjectTaskOrigin.MANUAL
        assert task.source_recommendation_key is None
    finally:
        _cleanup(db, engine)


def test_verifiable_client_key_round_trips() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A]),
        )
        candidates = extract_audit_recommendation_candidates(audit)
        assert candidates
        payload = ProjectTaskCreateRequest(
            title="Renamed but sourced",
            source_audit_id=audit.id,
            source_recommendation_key=candidates[0].key,
        )
        result = create_project_task(project.id, payload=payload, user=owner, db=db)
        task = db.query(models.ProjectTask).filter_by(id=result["id"]).one()
        assert task.origin == models.ProjectTaskOrigin.AUDIT_RECOMMENDATION
        assert task.source_recommendation_key == candidates[0].key
    finally:
        _cleanup(db, engine)


def test_key_without_source_audit_is_dropped() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        payload = ProjectTaskCreateRequest(
            title="Manual task",
            source_recommendation_key="general:whatever:abc123def456",
        )
        result = create_project_task(project.id, payload=payload, user=owner, db=db)
        task = db.query(models.ProjectTask).filter_by(id=result["id"]).one()
        assert task.origin == models.ProjectTaskOrigin.MANUAL
        assert task.source_recommendation_key is None
    finally:
        _cleanup(db, engine)


def test_resolve_task_recommendation_key_matches_title_casefolded() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A]),
        )
        key = resolve_task_recommendation_key(
            db,
            project_id=project.id,
            source_audit_id=audit.id,
            title="  add faqpage schema to the pricing page ",
        )
        assert key is not None
    finally:
        _cleanup(db, engine)


# ── Defect 3: sync reads recommendations.items ───────────────────────────


def test_sync_reads_recommendations_items_node() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_items_node([ITEM_A, ITEM_B]),
        )
        tasks = sync_project_tasks(db, project_id=project.id)
        titles = {task.title for task in tasks}
        assert ITEM_A["action"] in titles
        assert ITEM_B["action"] in titles
        assert len(tasks) == 2
    finally:
        _cleanup(db, engine)


def test_every_plan_action_has_one_board_task() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A, ITEM_B]),
        )
        tasks = sync_project_tasks(db, project_id=project.id)
        candidates = extract_audit_recommendation_candidates(audit)
        keys = {task.source_recommendation_key for task in tasks}
        assert keys == {c.key for c in candidates}
        assert len(tasks) == len(keys)
    finally:
        _cleanup(db, engine)


# ── Defect 4: digest covers raw input; migration recomputes ──────────────


def test_distinct_arabic_titles_get_distinct_keys_and_both_survive_sync() -> None:
    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_items_node(
                [
                    {
                        "action": "إصلاح A",
                        "estimated_effort": "low",
                        "expected_score_impact": {"seo": 5},
                        "grounded_by_findings": ["seo.a"],
                        "derived_from": ["analysis.seo"],
                    },
                    {
                        "action": "تحسين A",
                        "estimated_effort": "low",
                        "expected_score_impact": {"seo": 3},
                        "grounded_by_findings": ["seo.b"],
                        "derived_from": ["analysis.seo"],
                    },
                ]
            ),
        )
        tasks = sync_project_tasks(db, project_id=project.id)
        keys = {t.source_recommendation_key for t in tasks}
        assert len(tasks) == 2
        assert len(keys) == 2
        key_a = _normalize_source_recommendation_key(title="إصلاح A", category="Technical")
        key_b = _normalize_source_recommendation_key(title="تحسين A", category="Technical")
        assert key_a != key_b
    finally:
        _cleanup(db, engine)


def test_latin_titles_with_matching_slug_get_distinct_keys() -> None:
    key_a = _normalize_source_recommendation_key(title="Fix A!", category="Technical")
    key_b = _normalize_source_recommendation_key(title="Fix A?", category="Technical")
    assert key_a != key_b
    # Whitespace/case normalisation still folds true duplicates together.
    key_c = _normalize_source_recommendation_key(title="  FIX   A! ", category="Technical")
    assert key_c == key_a


def test_key_is_deterministic() -> None:
    a = _normalize_source_recommendation_key(
        title="Add FAQ schema", category="Technical", description="Ship it."
    )
    b = _normalize_source_recommendation_key(
        title="Add FAQ schema", category="Technical", description="Ship it."
    )
    assert a == b
    assert a.count(":") == 2


def test_migration_algorithm_matches_service() -> None:
    migration = _load_migration()
    cases = [
        ("إصلاح A", "Technical", None),
        ("Fix A!", "Technical", "Ship it."),
        ("  multi   space ", "Content", None),
        ("Plain", "General", ""),
    ]
    for title, category, description in cases:
        assert migration.recompute_key(title, category, description) == (
            _normalize_source_recommendation_key(
                title=title, category=category, description=description
            )
        )


def test_migration_recomputes_keys_and_is_idempotent() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            full_report=_report_with_recommendations([ITEM_A]),
        )
        migration = _load_migration()
        legacy_key = migration._legacy_key(ITEM_A["action"], "Technical", ITEM_A["action"])
        task = models.ProjectTask(
            project_id=project.id,
            source_audit_id=audit.id,
            title=ITEM_A["action"],
            description=ITEM_A["action"],
            category="Technical",
            status=models.ProjectTaskStatus.TODO,
            priority=models.ProjectTaskPriority.MEDIUM,
            origin=models.ProjectTaskOrigin.AUDIT_RECOMMENDATION,
            source_recommendation_key=legacy_key,
            sort_order=100,
        )
        db.add(task)
        db.commit()

        conn = engine.connect()
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
            # Idempotent: second pass recomputes the same value, no changes.
            migration.upgrade()

        db.expire_all()
        refreshed = db.query(models.ProjectTask).filter_by(id=task.id).one()
        expected = _normalize_source_recommendation_key(
            title=task.title, category="Technical", description=task.description
        )
        assert refreshed.source_recommendation_key == expected
        assert refreshed.source_recommendation_key != legacy_key
        conn.close()
    finally:
        _cleanup(db, engine)


def test_migration_leaves_null_keys_untouched() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db, engine = _build_db()
    try:
        owner, _ws, project = _seed_project(db)
        task = models.ProjectTask(
            project_id=project.id,
            title="Manual task",
            description=None,
            category="General",
            status=models.ProjectTaskStatus.TODO,
            priority=models.ProjectTaskPriority.MEDIUM,
            origin=models.ProjectTaskOrigin.MANUAL,
            source_recommendation_key=None,
            sort_order=100,
        )
        db.add(task)
        db.commit()

        conn = engine.connect()
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration = _load_migration()
            migration.upgrade()

        db.expire_all()
        refreshed = db.query(models.ProjectTask).filter_by(id=task.id).one()
        assert refreshed.source_recommendation_key is None
        conn.close()
    finally:
        _cleanup(db, engine)
