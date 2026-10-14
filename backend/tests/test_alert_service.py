from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services import alert_service


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email="alerts@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(workspace_id=workspace.id, name="Project Alpha")
    db.add(project)
    db.commit()
    db.refresh(project)

    return db, engine, project


def test_evaluate_ai_visibility_score_triggers_metric_rule(monkeypatch) -> None:
    db, engine, project = _build_db()
    try:
        rule = models.AlertRule(
            project_id=project.id,
            metric="ai_visibility_score",
            condition="below",
            threshold=70,
            email_to="ops@example.com",
            is_active=True,
        )
        db.add(rule)
        db.commit()

        monkeypatch.setattr(
            alert_service.ProjectVisibilityService,
            "build_summary",
            lambda self, project: {
                "visibility_score": 52.0,
                "trend_delta": -18.0,
            },
        )

        queued_events: list[str] = []

        class FakeNotificationRouter:
            def __init__(self, _db):
                pass

            def dispatch_event(self, **kwargs):
                queued_events.append(kwargs["event_key"])
                return {"email": "queued"}

        monkeypatch.setattr(alert_service, "NotificationRouter", FakeNotificationRouter)
        monkeypatch.setattr(
            alert_service, "evaluate_workflows_for_event", lambda *args, **kwargs: None
        )

        alert_service.evaluate_alerts_for_project(db, project.id)

        logs = db.query(models.AlertLog).filter(models.AlertLog.rule_id == rule.id).all()
        assert len(logs) == 1
        assert "AIO Score dropped" in logs[0].message
        assert queued_events == ["alert.visibility_score_drop"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_evaluate_off_page_mentions_drop_triggers_metric_rule(monkeypatch) -> None:
    db, engine, project = _build_db()
    try:
        rule = models.AlertRule(
            project_id=project.id,
            metric="aeo_mention_drop",
            condition="drops_by",
            threshold=10,
            email_to="ops@example.com",
            is_active=True,
        )
        db.add(rule)
        db.commit()

        monkeypatch.setattr(
            alert_service.ProjectOffPageMentionsService,
            "build_summary",
            lambda self, project, days=30: {
                "no_data": False,
                "off_page_aeo_score": 61.5,
                "trend_delta": -14.2,
            },
        )

        queued_events: list[str] = []

        class FakeNotificationRouter:
            def __init__(self, _db):
                pass

            def dispatch_event(self, **kwargs):
                queued_events.append(kwargs["event_key"])
                return {"email": "queued"}

        monkeypatch.setattr(alert_service, "NotificationRouter", FakeNotificationRouter)
        monkeypatch.setattr(
            alert_service, "evaluate_workflows_for_event", lambda *args, **kwargs: None
        )

        alert_service.evaluate_alerts_for_project(db, project.id)

        logs = db.query(models.AlertLog).filter(models.AlertLog.rule_id == rule.id).all()
        assert len(logs) == 1
        assert "Off-page visibility score dropped by" in logs[0].message
        assert queued_events == ["alert.aeo_mention_drop"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# SIGV2-1280: the evaluator was unreachable, and three of six metrics looked
# for a job status nothing writes.
# ---------------------------------------------------------------------------


def test_the_scheduler_actually_reaches_the_evaluator() -> None:
    """The defect was reachability, not logic.

    `evaluate_alerts_for_project` worked. Nothing called it. Customers created
    rules through the dashboard and through the public API, the rules were
    stored and read back to them, and no alert could ever fire. The two tests
    above pass on that, because calling the function directly in a test is
    exactly what hides the fact that nothing else does.

    So this asserts the wiring: the sweep the scheduler calls must find a
    project that has an active rule.
    """
    # Read the scheduler rather than importing it. Importing `cron_sweeper`
    # pulls in its module-level setup, and a test that leaves a signal handler
    # or a client behind is a test that can hang the suite at exit. The source
    # is enough to prove the wiring, which is the whole claim here.
    scheduler = (Path(__file__).resolve().parents[1] / "cron_sweeper.py").read_text(
        encoding="utf-8"
    )
    assert "from services.alert_service import evaluate_due_project_alerts" in scheduler
    assert "evaluate_due_project_alerts(db)" in scheduler

    db, _engine, project = _build_db()
    try:
        db.add(
            models.AlertRule(
                project_id=project.id,
                metric="seo_score",
                condition="below",
                threshold=50.0,
                email_to="alerts@example.com",
                is_active=True,
            )
        )
        db.commit()

        assert alert_service.evaluate_due_project_alerts(db) == 1
    finally:
        db.close()


def test_an_inactive_rule_does_not_make_a_project_due() -> None:
    db, _engine, project = _build_db()
    try:
        db.add(
            models.AlertRule(
                project_id=project.id,
                metric="seo_score",
                condition="below",
                threshold=50.0,
                email_to="alerts@example.com",
                is_active=False,
            )
        )
        db.commit()

        assert alert_service.evaluate_due_project_alerts(db) == 0
    finally:
        db.close()


def test_a_failing_project_does_not_stop_the_sweep(monkeypatch) -> None:
    """A sweep that aborts halfway starves every project after the bad one.

    That is the same silence this work exists to end, so the failure is
    logged and the sweep continues.
    """
    db, _engine, project = _build_db()
    try:
        for _ in range(2):
            db.add(
                models.AlertRule(
                    project_id=project.id,
                    metric="seo_score",
                    condition="below",
                    threshold=50.0,
                    email_to="alerts@example.com",
                    is_active=True,
                )
            )
        other = models.Project(workspace_id=project.workspace_id, name="Project Beta")
        db.add(other)
        db.commit()
        db.refresh(other)
        db.add(
            models.AlertRule(
                project_id=other.id,
                metric="seo_score",
                condition="below",
                threshold=50.0,
                email_to="alerts@example.com",
                is_active=True,
            )
        )
        db.commit()

        seen: list[int] = []

        def _boom(_db, project_id):
            seen.append(project_id)
            if project_id == project.id:
                raise RuntimeError("one project is broken")

        monkeypatch.setattr(alert_service, "evaluate_alerts_for_project", _boom)

        # Two distinct projects are due; one raises, the other still runs.
        assert alert_service.evaluate_due_project_alerts(db) == 1
        assert sorted(seen) == sorted([project.id, other.id])
    finally:
        db.close()


def test_score_evaluators_read_the_table_the_scores_live_in() -> None:
    """The three audit-backed evaluators queried the wrong model entirely.

    They filtered `AuditJob` on the status "completed", which nothing writes,
    so they matched nothing and returned. Correcting only the status moved the
    failure one line down: `AuditJob` has no `seo_score`, `geo_score` or
    `aeo_score` at all. Those columns are on `Audit`, and a row there is only
    written once an audit has succeeded.

    Caught on preprod, not here, because a unit test that never creates a job
    never reaches the attribute access.
    """
    import inspect

    source = inspect.getsource(alert_service)
    assert "models.AuditJob" not in source
    assert source.count("db.query(models.Audit)") == 3


def test_a_score_below_the_threshold_triggers(monkeypatch) -> None:
    """End to end through the sweep, on the real models."""
    db, _engine, project = _build_db()
    try:
        db.add(
            models.Audit(
                user_id=1,
                project_id=project.id,
                geo_score=10.0,
                seo_score=12.0,
                aeo_score=14.0,
            )
        )
        db.add(
            models.AlertRule(
                project_id=project.id,
                metric="seo_score",
                condition="below",
                threshold=50.0,
                email_to="alerts@example.com",
                is_active=True,
            )
        )
        db.commit()

        triggered: list[tuple[float, str]] = []
        monkeypatch.setattr(
            alert_service,
            "record_alert_trigger",
            lambda _db, _rule, value, message: triggered.append((value, message)),
        )

        assert alert_service.evaluate_due_project_alerts(db) == 1
        assert len(triggered) == 1
        value, message = triggered[0]
        assert value == 12.0
        assert "12.0" in message
    finally:
        db.close()


def test_a_score_above_the_threshold_stays_quiet(monkeypatch) -> None:
    db, _engine, project = _build_db()
    try:
        db.add(
            models.Audit(
                user_id=1, project_id=project.id, geo_score=90.0, seo_score=92.0, aeo_score=94.0
            )
        )
        db.add(
            models.AlertRule(
                project_id=project.id,
                metric="seo_score",
                condition="below",
                threshold=50.0,
                email_to="alerts@example.com",
                is_active=True,
            )
        )
        db.commit()

        triggered: list[object] = []
        monkeypatch.setattr(
            alert_service,
            "record_alert_trigger",
            lambda *a, **k: triggered.append(a),
        )

        assert alert_service.evaluate_due_project_alerts(db) == 1
        assert triggered == []
    finally:
        db.close()
