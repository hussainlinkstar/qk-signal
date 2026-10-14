"""SIGV2-1265: stored Search Console and Bing rows must reach the audit.

Before this, ``project_gsc_page_metrics`` and ``project_bing_metrics`` were
written by their monitoring endpoints and read by nobody: the audit received
binding facts only (mode, has_external_data), so a connected customer's audit
rested on the same evidence as an unconnected one.

The two datasets stay separate and are never merged or presented as each
other, and an empty dataset is reported with a reason rather than as zero
traffic.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from services.audit_data_sources import resolve_project_audit_data_sources
from services.audit_search_metrics import (
    SEARCH_METRICS_WINDOW_DAYS,
    load_project_search_metrics,
)


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _cleanup(db: Session) -> None:
    engine = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_project(db: Session) -> models.Project:
    user = models.User(email="metrics@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Agency", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Client",
        domain_url="https://client.example",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _bind(
    db: Session,
    project: models.Project,
    *,
    source_type: models.ProjectDataSourceType,
    provider: models.OAuthProvider,
    source_id: str,
) -> models.ProjectDataSource:
    connection = models.OAuthConnection(
        workspace_id=project.workspace_id,
        provider=provider,
        access_token="token",
        refresh_token="refresh",
        scope="scope",
    )
    db.add(connection)
    db.flush()
    source = models.ProjectDataSource(
        project_id=project.id,
        provider=provider,
        source_type=source_type,
        binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
        source_id=source_id,
        source_label=source_id,
        is_active=True,
        oauth_connection_id=connection.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _gsc_row(project_id: int, *, day: date, page: str, clicks: float, impressions: float):
    return models.ProjectGSCPageMetric(
        project_id=project_id,
        property="sc-domain:client.example",
        page=page,
        date=day,
        clicks=clicks,
        impressions=impressions,
        position=4.0,
    )


def _bing_row(project_id: int, *, day: date, dimension_type: str, dimension: str):
    return models.ProjectBingMetric(
        project_id=project_id,
        site_url="https://client.example/",
        dimension_type=dimension_type,
        dimension=dimension,
        date=day,
        clicks=3.0,
        impressions=30.0,
        avg_click_position_raw=18,
        avg_impression_position_raw=17,
    )


def test_stored_search_console_rows_become_a_usable_aggregate() -> None:
    db = _build_db()
    try:
        project = _seed_project(db)
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            provider=models.OAuthProvider.GOOGLE,
            source_id="sc-domain:client.example",
        )
        today = date.today()
        db.add_all(
            [
                _gsc_row(project.id, day=today, page="/a", clicks=10.0, impressions=100.0),
                _gsc_row(
                    project.id,
                    day=today - timedelta(days=1),
                    page="/b",
                    clicks=5.0,
                    impressions=50.0,
                ),
            ]
        )
        db.commit()

        metrics = load_project_search_metrics(db, project_id=project.id)
        gsc = metrics["google_search_console"]

        assert gsc["available"] is True
        assert gsc["property"] == "sc-domain:client.example"
        assert gsc["clicks"] == 15.0
        assert gsc["impressions"] == 150.0
        assert gsc["pages"] == 2
        assert gsc["period"] == {
            "start": (today - timedelta(days=1)).isoformat(),
            "end": today.isoformat(),
        }
        assert gsc["top_pages"][0]["page"] == "/a"
    finally:
        _cleanup(db)


def test_bing_rows_stay_separate_and_never_claim_a_position() -> None:
    db = _build_db()
    try:
        project = _seed_project(db)
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.BING_WEBMASTER,
            provider=models.OAuthProvider.BING,
            source_id="https://client.example/",
        )
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            provider=models.OAuthProvider.GOOGLE,
            source_id="sc-domain:client.example",
        )
        today = date.today()
        db.add_all(
            [
                _bing_row(project.id, day=today, dimension_type="site", dimension=""),
                _bing_row(project.id, day=today, dimension_type="query", dimension="qiko signal"),
                _bing_row(project.id, day=today, dimension_type="page", dimension="/a"),
                _gsc_row(project.id, day=today, page="/a", clicks=10.0, impressions=100.0),
            ]
        )
        db.commit()

        metrics = load_project_search_metrics(db, project_id=project.id)
        bing = metrics["bing_webmaster"]
        gsc = metrics["google_search_console"]

        assert bing["available"] is True
        assert bing["site_url"] == "https://client.example/"
        # Site-level rows only: query and page rows repeat the same traffic.
        assert bing["clicks"] == 3.0
        assert bing["impressions"] == 30.0
        assert bing["queries"] == 1
        assert bing["position"]["status"] == "unavailable"
        assert bing["position"]["reason"] == "bing_position_scale_unverified"
        assert "position" not in bing or bing["position"].get("value") is None
        # The two datasets never fold into each other.
        assert gsc["clicks"] == 10.0
        assert bing["clicks"] == 3.0
    finally:
        _cleanup(db)


def test_absence_is_reported_with_a_reason_not_as_zero_traffic() -> None:
    db = _build_db()
    try:
        project = _seed_project(db)
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.BING_WEBMASTER,
            provider=models.OAuthProvider.BING,
            source_id="https://client.example/",
        )

        metrics = load_project_search_metrics(db, project_id=project.id)

        assert metrics["bing_webmaster"] == {
            "available": False,
            "reason": "no_stored_rows",
        }
        assert metrics["google_search_console"] == {
            "available": False,
            "reason": "no_active_binding",
        }
    finally:
        _cleanup(db)


def test_rows_older_than_the_window_are_excluded() -> None:
    db = _build_db()
    try:
        project = _seed_project(db)
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            provider=models.OAuthProvider.GOOGLE,
            source_id="sc-domain:client.example",
        )
        stale_day = date.today() - timedelta(days=SEARCH_METRICS_WINDOW_DAYS + 5)
        db.add(_gsc_row(project.id, day=stale_day, page="/old", clicks=99.0, impressions=990.0))
        db.commit()

        metrics = load_project_search_metrics(db, project_id=project.id)

        assert metrics["google_search_console"]["available"] is False
        assert metrics["google_search_console"]["reason"] == "no_stored_rows"
    finally:
        _cleanup(db)


def test_audit_data_source_context_carries_the_metrics() -> None:
    db = _build_db()
    try:
        project = _seed_project(db)
        _bind(
            db,
            project,
            source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            provider=models.OAuthProvider.GOOGLE,
            source_id="sc-domain:client.example",
        )
        db.add(
            _gsc_row(project.id, day=date.today(), page="/a", clicks=10.0, impressions=100.0),
        )
        db.commit()

        context, _warnings = resolve_project_audit_data_sources(db, project_id=project.id)

        assert context["search_metrics"]["google_search_console"]["clicks"] == 10.0
        assert context["search_metrics"]["window_days"] == SEARCH_METRICS_WINDOW_DAYS
    finally:
        _cleanup(db)


def test_unified_truth_context_cites_the_stored_metrics_as_t1_evidence() -> None:
    from services.unified_truth_context_service import UnifiedTruthContextService

    service = UnifiedTruthContextService(db=None)
    context = service.build_context(
        project_id=None,
        audit_target_type="website",
        target_name="Client",
        target_url="https://client.example",
        category="technical",
        market="uk",
        source_content="",
        data_source_context={
            "mode": "workspace",
            "search_metrics": {
                "window_days": SEARCH_METRICS_WINDOW_DAYS,
                "google_search_console": {
                    "available": True,
                    "property": "sc-domain:client.example",
                    "clicks": 15.0,
                    "impressions": 150.0,
                    "pages": 2,
                    "period": {"start": "2026-09-12", "end": "2026-10-09"},
                    "top_pages": [{"page": "/a", "clicks": 10.0, "impressions": 100.0}],
                    "position": {"status": "available", "value": 4.0},
                },
                "bing_webmaster": {
                    "available": True,
                    "site_url": "https://client.example/",
                    "clicks": 3.0,
                    "impressions": 30.0,
                    "queries": 1,
                    "pages": 1,
                    "period": {"start": "2026-10-09", "end": "2026-10-09"},
                    "top_queries": [{"query": "qiko signal", "clicks": 3.0, "impressions": 30.0}],
                    "position": {
                        "status": "unavailable",
                        "reason": "bing_position_scale_unverified",
                    },
                },
            },
        },
    )

    insights = context["technical_agent_insights"]
    by_id = {item["source_id"]: item for item in insights}

    gsc_insight = by_id["search-console-performance"]
    assert gsc_insight["trust_tier"] == "T1"
    assert "15" in gsc_insight["insight_text"]
    assert "150" in gsc_insight["insight_text"]
    assert any(
        ref["source_type"] == "project_gsc_page_metrics" for ref in gsc_insight["evidence_refs"]
    )

    bing_insight = by_id["bing-webmaster-performance"]
    assert bing_insight["trust_tier"] == "T1"
    assert "Bing" in bing_insight["insight_text"]
    assert any(
        ref["source_type"] == "project_bing_metrics" for ref in bing_insight["evidence_refs"]
    )
    # Bing's position scale is undocumented, so no audit sentence may state one.
    assert "position" not in bing_insight["insight_text"].lower()


def test_a_connected_source_with_no_rows_is_said_out_loud() -> None:
    from services.unified_truth_context_service import UnifiedTruthContextService

    service = UnifiedTruthContextService(db=None)
    context = service.build_context(
        project_id=None,
        audit_target_type="website",
        target_name="Client",
        target_url="https://client.example",
        category="technical",
        market="uk",
        source_content="",
        data_source_context={
            "mode": "workspace",
            "search_metrics": {
                "window_days": SEARCH_METRICS_WINDOW_DAYS,
                "google_search_console": {"available": False, "reason": "no_stored_rows"},
                "bing_webmaster": {"available": False, "reason": "no_active_binding"},
            },
        },
    )

    texts = [item["insight_text"] for item in context["technical_agent_insights"]]
    assert any("no stored Search Console rows" in text for text in texts)
    # A provider that was never connected is not worth an absence sentence.
    assert not any("Bing" in text for text in texts)
