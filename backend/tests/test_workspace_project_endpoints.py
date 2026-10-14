from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from routers.workspace_router import (
    AeoQueryTrackerItemPayload,
    AeoQueryTrackerUpsertRequest,
    MagicLinkCreateRequest,
    OAuthConnectionUpsertRequest,
    ProjectCreateRequest,
    ProjectSmartProfileGenerateRequest,
    ProjectDataSourceUpsertRequest,
    ProjectUpdateRequest,
    WorkspaceMemberRoleUpdateRequest,
    WorkspaceMemberUpsertRequest,
    delete_project_data_source,
    WorkspaceUpdateRequest,
    consume_magic_link,
    create_magic_link,
    generate_project_smart_profile,
    get_aeo_query_tracker,
    create_project_in_current_workspace,
    _apply_magic_link_connection,
    get_project_data_source_catalog,
    get_project_magic_link_status,
    get_project,
    get_project_latest_audit,
    get_project_latest_audit_selection,
    list_project_data_sources,
    list_project_audits,
    get_current_workspace,
    get_magic_link_status,
    list_current_workspace_projects,
    list_current_workspace_members,
    remove_current_workspace_member,
    list_workspace_oauth_connections,
    upsert_project_data_source,
    update_project,
    update_current_workspace,
    update_current_workspace_member_role,
    upsert_aeo_query_tracker,
    upsert_current_workspace_member,
    upsert_workspace_oauth_connection,
    _extract_latest_audit_evidence,
)


def _build_db() -> tuple[Session, sessionmaker, Engine, models.User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="workspace-user@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, testing_session_local, engine, user


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _set_subscription(db: Session, user: models.User, plan_type: str) -> None:
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{plan_type}_{user.id}",
            stripe_subscription_id=f"sub_{plan_type}_{user.id}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()


def test_workspace_current_and_project_crud_flow() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        _set_subscription(db, user, "plan_specialist")

        workspace_payload = get_current_workspace(user=user, db=db)
        assert workspace_payload["role"] == "ADMIN"
        assert workspace_payload["project_count"] == 0

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Alpha",
                domain_url="client-alpha.example",
                target_country="ro",
                language="ro",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])
        assert created_project["domain_url"] == "https://client-alpha.example"

        updated_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Client Beta", domain_url="client-beta.example"),
            user=user,
            db=db,
        )
        assert updated_project["name"] == "Client Beta"

        patched = update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(
                icp_roles=["CEO", "CTO"],
                pain_points="Legacy stack, weak indexing, low trust signals",
                usp="Only ISO-certified GEO stack",
                competitors=["https://comp-a.example", "https://comp-b.example"],
                priority_pulse_tags=["GEO", "AEO"],
                sme_profiles=["https://linkedin.com/in/expert"],
            ),
            user=user,
            db=db,
        )
        assert patched["icp_roles"] == ["CEO", "CTO"]
        assert patched["priority_pulse_tags"] == ["GEO", "AEO"]

        listed = list_current_workspace_projects(user=user, db=db)
        assert len(listed) == 2
    finally:
        _cleanup(db, engine)


def test_update_project_blocks_competitive_settings_for_ineligible_plan() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        _set_subscription(db, user, "plan_standard")

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Starter Client", domain_url="starter-client.example"
            ),
            user=user,
            db=db,
        )

        with pytest.raises(HTTPException) as exc_info:
            update_project(
                project_id=int(created_project["id"]),
                payload=ProjectUpdateRequest(
                    competitors=["https://comp-a.example"],
                    auto_competitor_audits_enabled=True,
                    competitive_digest_frequency="weekly",
                ),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 402
        assert "Competitive Intelligence" in str(exc_info.value.detail)
    finally:
        _cleanup(db, engine)


def test_generate_project_smart_profile_updates_fields_and_deducts_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="AI Smart Profile",
                domain_url="ai-smart.example",
                target_country="RO",
                language="en",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        import routers.workspace_router as workspace_router_module
        from services import smart_profile_service

        def _stub_bedrock_generate_text(system: str, user_prompt: str, **kwargs):
            assert "AI Smart Profile" in user_prompt
            return (
                '{"icp_roles":["CEO","CMO"],'
                '"pain_points":"Low AI answer visibility and weak entity trust.",'
                '"usp":"Entity-first GEO framework with measurable answer share.",'
                '"priority_pulse_tags":["GEO","AEO","Entity Graph"],'
                '"sme_profiles":["LinkedIn: Geo Strategist"]}'
            )

        # SIGV2-1252: the Bedrock seam lives in the ai-service layer, not in the
        # router, so the stub is installed on the service module.
        monkeypatch.setattr(
            smart_profile_service,
            "bedrock_available",
            lambda: True,
            raising=True,
        )
        monkeypatch.setattr(
            smart_profile_service,
            "bedrock_generate_text",
            _stub_bedrock_generate_text,
            raising=True,
        )
        monkeypatch.setattr(
            workspace_router_module,
            "_build_grounded_smart_profile_sources",
            lambda project, db_session: (
                {
                    "project": {
                        "name": project.name,
                        "domain_url": project.domain_url,
                        "target_country": project.target_country,
                        "language": project.language,
                        "competitors": [],
                    },
                    "domain_snapshot": {
                        "title": "AI Smart Profile",
                        "meta_description": "GEO/AEO services",
                        "headings": ["Growth"],
                        "body_excerpt": "Agency focused on GEO and AEO",
                    },
                    "latest_audit": {},
                },
                ["project_profile_fields", "project_domain_snapshot"],
            ),
            raising=True,
        )

        response = generate_project_smart_profile(
            project_id=project_id,
            payload=ProjectSmartProfileGenerateRequest(overwrite_existing=True),
            user=user,
            db=db,
        )

        db.refresh(user)
        assert user.credits == 4
        assert response.project.icp_roles == ["CEO", "CMO"]
        assert response.project.pain_points is not None
        assert "visibility" in response.project.pain_points
        assert response.project.usp is not None
        assert "Entity-first" in response.project.usp
        assert response.project.priority_pulse_tags == ["GEO", "AEO", "Entity Graph"]
        assert response.project.sme_profiles == ["LinkedIn: Geo Strategist"]
        assert "pain_points" in response.generated_fields
        assert "project_domain_snapshot" in response.grounded_sources
    finally:
        _cleanup(db, engine)


def test_generate_project_smart_profile_succeeds_without_available_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SIGV2-1024: an exhausted internal wallet must not block generation; the
    # internal balance simply goes negative.
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="No Credits Profile",
                domain_url="no-credits.example",
                target_country="RO",
                language="en",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])
        user.credits = 0
        db.commit()
        db.refresh(user)

        import routers.workspace_router as workspace_router_module
        from services import smart_profile_service

        monkeypatch.setattr(
            smart_profile_service,
            "bedrock_available",
            lambda: True,
            raising=True,
        )
        monkeypatch.setattr(
            smart_profile_service,
            "bedrock_generate_text",
            lambda system, user_prompt, **kwargs: (
                '{"icp_roles":["CEO"],'
                '"pain_points":"Low visibility.",'
                '"usp":"Entity-first GEO.",'
                '"priority_pulse_tags":["GEO"],'
                '"sme_profiles":[]}'
            ),
            raising=True,
        )
        monkeypatch.setattr(
            workspace_router_module,
            "_build_grounded_smart_profile_sources",
            lambda project, db_session: (
                {
                    "project": {
                        "name": project.name,
                        "domain_url": project.domain_url,
                        "target_country": project.target_country,
                        "language": project.language,
                        "competitors": [],
                    },
                    "domain_snapshot": {},
                    "latest_audit": {},
                },
                ["project_profile_fields"],
            ),
            raising=True,
        )

        response = generate_project_smart_profile(
            project_id=project_id,
            payload=ProjectSmartProfileGenerateRequest(overwrite_existing=True),
            user=user,
            db=db,
        )

        db.refresh(user)
        assert user.credits == -1
        assert response.project.icp_roles == ["CEO"]
    finally:
        _cleanup(db, engine)


def test_aeo_query_tracker_persists_and_returns_items() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        response = upsert_aeo_query_tracker(
            payload=AeoQueryTrackerUpsertRequest(
                context_url="https://example.com/blog/article?ref=ads",
                items=[
                    AeoQueryTrackerItemPayload(query="best ai seo strategy", citation_hits=3),
                    AeoQueryTrackerItemPayload(query="Best AI SEO strategy", citation_hits=5),
                    AeoQueryTrackerItemPayload(
                        query="how to improve llm citations", citation_hits=1
                    ),
                ],
            ),
            user=user,
            db=db,
        )

        assert response["context_key"] == "example.com/blog/article"
        assert len(response["items"]) == 2
        assert response["items"][0]["citation_hits"] in {1, 3, 5}

        loaded = get_aeo_query_tracker(
            context_url="https://example.com/blog/article",
            user=user,
            db=db,
        )
        assert loaded["context_key"] == "example.com/blog/article"
        assert len(loaded["items"]) == 2
        assert {item["query"] for item in loaded["items"]} == {
            "best ai seo strategy",
            "how to improve llm citations",
        }
    finally:
        _cleanup(db, engine)


def test_aeo_query_tracker_is_scoped_by_context() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        upsert_aeo_query_tracker(
            payload=AeoQueryTrackerUpsertRequest(
                context_url="https://alpha.example",
                items=[AeoQueryTrackerItemPayload(query="alpha query", citation_hits=2)],
            ),
            user=user,
            db=db,
        )
        upsert_aeo_query_tracker(
            payload=AeoQueryTrackerUpsertRequest(
                context_url="https://beta.example",
                items=[AeoQueryTrackerItemPayload(query="beta query", citation_hits=4)],
            ),
            user=user,
            db=db,
        )

        alpha = get_aeo_query_tracker(context_url="https://alpha.example", user=user, db=db)
        beta = get_aeo_query_tracker(context_url="https://beta.example", user=user, db=db)

        assert len(alpha["items"]) == 1
        assert alpha["items"][0]["query"] == "alpha query"
        assert len(beta["items"]) == 1
        assert beta["items"][0]["query"] == "beta query"
    finally:
        _cleanup(db, engine)


def test_generate_project_smart_profile_requires_mandatory_project_fields() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Missing Required Inputs",
                domain_url="missing-required.example",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        with pytest.raises(HTTPException) as exc_info:
            generate_project_smart_profile(
                project_id=project_id,
                payload=ProjectSmartProfileGenerateRequest(overwrite_existing=True),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 400
        assert "Target Market (ISO)" in str(exc_info.value.detail)
    finally:
        _cleanup(db, engine)


def test_extract_latest_audit_evidence_includes_summary_recommendations_and_entities() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Evidence Rich Project",
                domain_url="evidence-rich.example",
                target_country="RO",
                language="en",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        db.add(
            models.Audit(
                user_id=user.id,
                project_id=project_id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url="https://evidence-rich.example",
                geo_score=67.0,
                seo_score=73.0,
                aeo_score=70.0,
                full_report={
                    "analysis": {
                        "summary": "The site has strong product authority but weak citation consistency.",
                        "recommendations": [
                            "Add authoritative citations for top commercial pages.",
                            "Expand FAQ schema on transactional templates.",
                        ],
                        "entities_detected": ["Entity One", "Entity Two"],
                    },
                    "prioritized_actions": [
                        {"title": "Improve internal linking to service hubs"},
                    ],
                    "metadata": {"audit_outcome": "completed"},
                },
            )
        )
        db.commit()

        evidence = _extract_latest_audit_evidence(db, project_id)

        assert evidence["summary"].startswith("The site has strong product authority")
        assert "Improve internal linking to service hubs" in evidence["recommendations"]
        assert (
            "Add authoritative citations for top commercial pages." in evidence["recommendations"]
        )
        assert evidence["entities_detected"] == ["Entity One", "Entity Two"]
    finally:
        _cleanup(db, engine)


def test_extract_latest_audit_evidence_supports_canonical_recommendation_items() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Canonical Evidence Project",
                domain_url="canonical-evidence.example",
                target_country="RO",
                language="en",
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        db.add(
            models.Audit(
                user_id=user.id,
                project_id=project_id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url="https://canonical-evidence.example",
                geo_score=71.0,
                seo_score=74.0,
                aeo_score=72.0,
                full_report={
                    "recommendations": {
                        "items": [
                            {
                                "title": "Expand comparison pages with structured data",
                                "action": "Expand comparison pages with structured data",
                            },
                            {
                                "title": "Strengthen FAQ answer blocks",
                                "action": "Strengthen FAQ answer blocks",
                            },
                        ]
                    },
                    "entities": ["Canonical Entity", "Second Entity"],
                    "metadata": {"audit_outcome": "completed"},
                },
            )
        )
        db.commit()

        evidence = _extract_latest_audit_evidence(db, project_id)

        assert evidence["recommendations"][:2] == [
            "Expand comparison pages with structured data",
            "Strengthen FAQ answer blocks",
        ]
        assert evidence["entities_detected"] == ["Canonical Entity", "Second Entity"]
    finally:
        _cleanup(db, engine)


def test_workspace_oauth_connection_upsert_encrypts_tokens_at_rest() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        response = upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="plain-access-token",
                refresh_token="plain-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )
        assert response.provider == "google"
        assert response.has_refresh_token is True
        assert response.access_token_preview is not None
        assert response.access_token_preview.startswith("plai")

        row = db.execute(text("SELECT access_token FROM oauth_connections LIMIT 1")).fetchone()
        assert row is not None
        assert row[0] != "plain-access-token"

        listed = list_workspace_oauth_connections(user=user, db=db)
        connected = [row for row in listed if row.connected]
        assert len(connected) == 1
        assert connected[0].provider == "google"

        bing_response = upsert_workspace_oauth_connection(
            provider="bing",
            payload=OAuthConnectionUpsertRequest(
                access_token="bing-access-token",
                refresh_token=None,
                scope="openid profile email offline_access",
                token_type="Bearer",
            ),
            user=user,
            db=db,
        )
        assert bing_response.provider == "bing"

        listed = list_workspace_oauth_connections(user=user, db=db)
        connected = [row for row in listed if row.connected]
        assert len(connected) == 2
        providers = {row.provider for row in connected}
        assert providers == {"google", "bing"}
        # Unconnected providers are still listed so the UI can distinguish
        # "not configured" from "not connected".
        assert {row.provider for row in listed} == {"google", "bing", "jira"}
    finally:
        _cleanup(db, engine)


def test_oauth_connections_report_configured_from_env(monkeypatch) -> None:
    from core.config import settings

    db, _session_factory, engine, user = _build_db()
    try:
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", None)
        monkeypatch.setattr(settings, "JIRA_CLIENT_ID", "jira-id")
        monkeypatch.setattr(settings, "JIRA_CLIENT_SECRET", "jira-secret")

        listed = list_workspace_oauth_connections(user=user, db=db)
        by_provider = {row.provider: row for row in listed}

        # Missing env -> configured False, connected False: the UI must not
        # offer a connect affordance that cannot complete.
        assert by_provider["google"].configured is False
        assert by_provider["google"].connected is False
        assert by_provider["jira"].configured is True
    finally:
        _cleanup(db, engine)


def test_project_data_sources_mapping_flow() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Data Sources", domain_url="client-ds.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        initial_sources = list_project_data_sources(project_id=project_id, user=user, db=db)
        assert len(initial_sources) == 3
        assert all(source.id is None for source in initial_sources)
        gsc_initial = next(
            source for source in initial_sources if source.source_type == "google_search_console"
        )
        assert gsc_initial.workspace_provider_connected is False

        with pytest.raises(HTTPException):
            upsert_project_data_source(
                project_id=project_id,
                source_type="google_search_console",
                payload=ProjectDataSourceUpsertRequest(
                    binding_mode="workspace",
                    source_id="sc-domain:example.com",
                    source_label="Example GSC",
                    is_active=True,
                ),
                user=user,
                db=db,
            )

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        mapped = upsert_project_data_source(
            project_id=project_id,
            source_type="google_search_console",
            payload=ProjectDataSourceUpsertRequest(
                binding_mode="workspace",
                source_id="sc-domain:example.com",
                source_label="Example GSC",
                is_active=True,
            ),
            user=user,
            db=db,
        )
        assert mapped.id is not None
        assert mapped.provider == "google"
        assert mapped.workspace_provider_connected is True
        assert mapped.oauth_connection_id is not None

        listed_after = list_project_data_sources(project_id=project_id, user=user, db=db)
        gsc_after = next(
            source for source in listed_after if source.source_type == "google_search_console"
        )
        assert gsc_after.id is not None
        assert gsc_after.source_id == "sc-domain:example.com"

        delete_project_data_source(
            project_id=project_id,
            source_type="google_search_console",
            user=user,
            db=db,
        )
        listed_after_delete = list_project_data_sources(project_id=project_id, user=user, db=db)
        gsc_deleted = next(
            source
            for source in listed_after_delete
            if source.source_type == "google_search_console"
        )
        assert gsc_deleted.id is None
    finally:
        _cleanup(db, engine)


def test_project_data_source_catalog_flow() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Catalog", domain_url="client-catalog.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        without_provider = get_project_data_source_catalog(
            project_id=project_id,
            source_type="google_search_console",
            user=user,
            db=db,
        )
        assert without_provider.workspace_provider_connected is False
        assert without_provider.error == "workspace_provider_not_connected"

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        import routers.workspace_router as workspace_router_module

        original_fetch = workspace_router_module._fetch_source_catalog_items
        try:
            workspace_router_module._fetch_source_catalog_items = (
                lambda source_type, access_token: [
                    workspace_router_module.ProjectDataSourceCatalogItemResponse(
                        id="sc-domain:example.com",
                        label="sc-domain:example.com",
                        description="siteOwner",
                    )
                ]
            )

            with_provider = get_project_data_source_catalog(
                project_id=project_id,
                source_type="google_search_console",
                user=user,
                db=db,
            )
            assert with_provider.workspace_provider_connected is True
            assert with_provider.error is None
            assert (
                "https://www.googleapis.com/auth/webmasters.readonly"
                in with_provider.required_scopes
            )
            assert "gsc.read" in with_provider.granted_scopes
            assert with_provider.missing_scopes == []
            assert len(with_provider.items) == 1
            assert with_provider.items[0].id == "sc-domain:example.com"
        finally:
            workspace_router_module._fetch_source_catalog_items = original_fetch
    finally:
        _cleanup(db, engine)


def test_project_data_source_catalog_flow_for_ga4_and_bing() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Multi Catalog", domain_url="client-catalog-multi.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )
        upsert_workspace_oauth_connection(
            provider="bing",
            payload=OAuthConnectionUpsertRequest(
                access_token="bing-access-token",
                refresh_token="bing-refresh-token",
                scope="webmaster.manage",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        import routers.workspace_router as workspace_router_module

        original_fetch = workspace_router_module._fetch_source_catalog_items
        try:

            def _mock_fetch(source_type, access_token):
                if source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4:
                    return [
                        workspace_router_module.ProjectDataSourceCatalogItemResponse(
                            id="properties/12345",
                            label="Client GA4 (12345)",
                            description="Google Analytics Property",
                        )
                    ]
                if source_type == models.ProjectDataSourceType.BING_WEBMASTER:
                    return [
                        workspace_router_module.ProjectDataSourceCatalogItemResponse(
                            id="https://client-catalog-multi.example/",
                            label="https://client-catalog-multi.example/",
                            description="siteOwner",
                        )
                    ]
                return []

            workspace_router_module._fetch_source_catalog_items = _mock_fetch

            ga4_catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="google_analytics_4",
                user=user,
                db=db,
            )
            assert ga4_catalog.provider == "google"
            assert ga4_catalog.workspace_provider_connected is True
            assert ga4_catalog.error is None
            assert len(ga4_catalog.items) == 1
            assert ga4_catalog.items[0].id == "properties/12345"
            assert (
                "https://www.googleapis.com/auth/analytics.readonly" in ga4_catalog.required_scopes
            )

            bing_catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="bing_webmaster",
                user=user,
                db=db,
            )
            assert bing_catalog.provider == "bing"
            assert bing_catalog.workspace_provider_connected is True
            assert bing_catalog.error is None
            assert len(bing_catalog.items) == 1
            assert bing_catalog.items[0].id == "https://client-catalog-multi.example/"
            assert "webmaster.manage" in bing_catalog.required_scopes
        finally:
            workspace_router_module._fetch_source_catalog_items = original_fetch
    finally:
        _cleanup(db, engine)


def test_project_data_source_catalog_returns_provider_error_message() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Catalog Error", domain_url="client-catalog-error.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        import routers.workspace_router as workspace_router_module

        original_fetch = workspace_router_module._fetch_source_catalog_items
        try:

            def _mock_fetch(source_type, access_token):
                raise RuntimeError("catalog provider timeout")

            workspace_router_module._fetch_source_catalog_items = _mock_fetch

            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="google_search_console",
                user=user,
                db=db,
            )
            assert catalog.workspace_provider_connected is True
            assert catalog.items == []
            assert catalog.error == "catalog provider timeout"
            assert "https://www.googleapis.com/auth/webmasters.readonly" in catalog.required_scopes
        finally:
            workspace_router_module._fetch_source_catalog_items = original_fetch
    finally:
        _cleanup(db, engine)


def test_project_data_source_catalog_retries_after_google_token_refresh() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Catalog Refresh", domain_url="client-catalog-refresh.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-stale-token",
                refresh_token="google-refresh-token",
                scope="gsc.read ga4.read",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        import routers.workspace_router as workspace_router_module

        original_fetch = workspace_router_module._fetch_source_catalog_items
        import app.services.google_oauth_service as google_oauth_module

        original_refresh = google_oauth_module.refresh_google_oauth_connection
        try:
            refresh_calls = {"count": 0}

            def _mock_fetch(source_type, access_token):
                if access_token == "google-stale-token":
                    raise RuntimeError(
                        "GA4 catalog fetch failed: Request had invalid authentication credentials."
                    )
                return [
                    workspace_router_module.ProjectDataSourceCatalogItemResponse(
                        id="properties/371236862",
                        label="Client GA4 (371236862)",
                        description="UTC · USD",
                    )
                ]

            def _mock_refresh(db_session, connection):
                refresh_calls["count"] += 1
                connection.access_token = "google-fresh-token"
                db_session.commit()
                db_session.refresh(connection)
                return connection

            workspace_router_module._fetch_source_catalog_items = _mock_fetch
            google_oauth_module.refresh_google_oauth_connection = _mock_refresh

            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="google_analytics_4",
                user=user,
                db=db,
            )
            assert refresh_calls["count"] == 1
            assert catalog.error is None
            assert len(catalog.items) == 1
            assert catalog.items[0].id == "properties/371236862"
        finally:
            workspace_router_module._fetch_source_catalog_items = original_fetch
            google_oauth_module.refresh_google_oauth_connection = original_refresh
    finally:
        _cleanup(db, engine)


def test_project_data_source_scope_validation_blocks_workspace_mapping() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Scope Validation", domain_url="scope-validation.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        upsert_workspace_oauth_connection(
            provider="google",
            payload=OAuthConnectionUpsertRequest(
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="openid email profile",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )

        catalog = get_project_data_source_catalog(
            project_id=project_id,
            source_type="google_search_console",
            user=user,
            db=db,
        )
        assert catalog.workspace_provider_connected is True
        assert catalog.error is not None
        assert catalog.error.startswith("insufficient_scope")
        assert "https://www.googleapis.com/auth/webmasters.readonly" in catalog.missing_scopes

        with pytest.raises(HTTPException) as exc_info:
            upsert_project_data_source(
                project_id=project_id,
                source_type="google_search_console",
                payload=ProjectDataSourceUpsertRequest(
                    binding_mode="workspace",
                    source_id="sc-domain:example.com",
                    source_label="Example GSC",
                    is_active=True,
                ),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 400
        assert "missing required scopes" in str(exc_info.value.detail)
    finally:
        _cleanup(db, engine)


def test_magic_link_generation_and_consume_lifecycle() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Client With Link", domain_url="client-link.example"),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        created_link = create_magic_link(
            project_id=project_id,
            payload=MagicLinkCreateRequest(expires_in_hours=2),
            user=user,
            db=db,
        )
        assert "/connect/" in created_link.link_url
        assert created_link.is_used is False

        status_before = get_magic_link_status(token=created_link.token, db=db)
        assert status_before.valid is True
        assert status_before.project_id == project_id
        assert status_before.connection_state == "pending"

        consumed = consume_magic_link(token=created_link.token, db=db)
        assert consumed.consumed is True
        assert consumed.consumed_at is not None

        status_after = get_magic_link_status(token=created_link.token, db=db)
        assert status_after.valid is False
        assert status_after.is_used is True
        assert status_after.connection_state == "used"
    finally:
        _cleanup(db, engine)


def test_magic_link_oauth_connection_flow_maps_project_sources() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client OAuth Link", domain_url="https://client-oauth.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])
        created_link = create_magic_link(
            project_id=project_id,
            payload=MagicLinkCreateRequest(expires_in_hours=2),
            user=user,
            db=db,
        )

        link_row = (
            db.query(models.MagicLink)
            .filter(models.MagicLink.unique_token == created_link.token)
            .first()
        )
        project_row = db.query(models.Project).filter(models.Project.id == project_id).first()
        assert link_row is not None
        assert project_row is not None

        import routers.workspace_router as workspace_router_module

        original_fetch = workspace_router_module._fetch_source_catalog_items
        try:

            def _mock_fetch(source_type, access_token):
                if source_type == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE:
                    return [
                        workspace_router_module.ProjectDataSourceCatalogItemResponse(
                            id="https://client-oauth.example/",
                            label="https://client-oauth.example/",
                            description="siteOwner",
                        )
                    ]
                if source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4:
                    return [
                        workspace_router_module.ProjectDataSourceCatalogItemResponse(
                            id="properties/12345",
                            label="Client OAuth GA4 (12345)",
                            description=None,
                        )
                    ]
                return []

            workspace_router_module._fetch_source_catalog_items = _mock_fetch

            _apply_magic_link_connection(
                db=db,
                link=link_row,
                project=project_row,
                provider=models.OAuthProvider.GOOGLE,
                token_payload={
                    "access_token": "client-google-access-token",
                    "refresh_token": "client-google-refresh-token",
                    "token_type": "Bearer",
                    "scope": (
                        "openid email profile "
                        "https://www.googleapis.com/auth/webmasters.readonly "
                        "https://www.googleapis.com/auth/analytics.readonly"
                    ),
                    "userinfo": {"email": "client-owner@example.com", "sub": "google-sub-1"},
                },
            )
        finally:
            workspace_router_module._fetch_source_catalog_items = original_fetch

        status_public = get_magic_link_status(token=created_link.token, db=db)
        assert status_public.connection_state == "connected"
        assert any(
            provider.provider == "google" and provider.connected
            for provider in status_public.providers
        )

        status_project = get_project_magic_link_status(project_id=project_id, user=user, db=db)
        assert status_project.status == "connected"
        assert any(
            provider.provider == "google" and provider.connected
            for provider in status_project.providers
        )

        project_connections = (
            db.query(models.ProjectOAuthConnection)
            .filter(models.ProjectOAuthConnection.project_id == project_id)
            .all()
        )
        assert len(project_connections) == 1
        assert project_connections[0].provider == models.OAuthProvider.GOOGLE

        data_sources = (
            db.query(models.ProjectDataSource)
            .filter(models.ProjectDataSource.project_id == project_id)
            .all()
        )
        source_types = {row.source_type for row in data_sources}
        assert models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE in source_types
        assert models.ProjectDataSourceType.GOOGLE_ANALYTICS_4 in source_types
        assert all(
            row.binding_mode == models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK
            for row in data_sources
        )
        assert all(row.project_oauth_connection_id is not None for row in data_sources)
    finally:
        _cleanup(db, engine)


def test_magic_link_pending_even_when_project_has_existing_provider_connection() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Existing Provider", domain_url="https://existing-provider.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        first_link = create_magic_link(
            project_id=project_id,
            payload=MagicLinkCreateRequest(expires_in_hours=2),
            user=user,
            db=db,
        )
        first_link_row = (
            db.query(models.MagicLink)
            .filter(models.MagicLink.unique_token == first_link.token)
            .first()
        )
        project_row = db.query(models.Project).filter(models.Project.id == project_id).first()
        assert first_link_row is not None
        assert project_row is not None

        _apply_magic_link_connection(
            db=db,
            link=first_link_row,
            project=project_row,
            provider=models.OAuthProvider.GOOGLE,
            token_payload={
                "access_token": "existing-google-access-token",
                "refresh_token": "existing-google-refresh-token",
                "token_type": "Bearer",
                "scope": (
                    "openid email profile "
                    "https://www.googleapis.com/auth/webmasters.readonly "
                    "https://www.googleapis.com/auth/analytics.readonly"
                ),
                "userinfo": {"email": "owner@example.com", "sub": "google-sub-existing"},
            },
        )

        second_link = create_magic_link(
            project_id=project_id,
            payload=MagicLinkCreateRequest(expires_in_hours=2),
            user=user,
            db=db,
        )
        second_status = get_magic_link_status(token=second_link.token, db=db)

        assert second_status.connection_state == "pending"
        assert second_status.valid is True
        assert any(
            provider.provider == "google" and provider.connected
            for provider in second_status.providers
        )
    finally:
        _cleanup(db, engine)


def test_project_magic_link_status_excludes_expired_links_from_open_count() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Expired Links", domain_url="https://expired-links.example"
            ),
            user=user,
            db=db,
        )
        project_id = int(created_project["id"])

        expired_link = models.MagicLink(
            project_id=project_id,
            unique_token="expired-open-link-token",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            is_used=False,
        )
        db.add(expired_link)
        db.commit()

        status_payload = get_project_magic_link_status(project_id=project_id, user=user, db=db)
        assert status_payload.status == "expired"
        assert status_payload.open_magic_link_count == 0
    finally:
        _cleanup(db, engine)


def test_workspace_member_management_flow() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        invited_user = models.User(
            email="workspace-editor@example.com",
            hashed_password="x",
            role="user",
            credits=5,
            notifications_enabled=True,
        )
        db.add(invited_user)
        db.commit()
        db.refresh(invited_user)

        owner_workspace = get_current_workspace(user=owner_user, db=db)
        assert owner_workspace["is_owner"] is True

        upsert_current_workspace_member(
            payload=WorkspaceMemberUpsertRequest(
                email=invited_user.email,
                role="EDITOR",
            ),
            user=owner_user,
            db=db,
        )

        members = list_current_workspace_members(user=owner_user, db=db)
        assert len(members) == 2
        assert members[1].email == invited_user.email
        assert members[1].role == "EDITOR"

        updated = update_current_workspace_member_role(
            member_user_id=invited_user.id,
            payload=WorkspaceMemberRoleUpdateRequest(role="VIEWER"),
            user=owner_user,
            db=db,
        )
        assert updated.role == "VIEWER"

        invited_workspace = get_current_workspace(user=invited_user, db=db)
        assert invited_workspace["id"] == owner_workspace["id"]
        assert invited_workspace["is_owner"] is False
        assert invited_workspace["role"] == "VIEWER"

        remove_current_workspace_member(
            member_user_id=invited_user.id,
            user=owner_user,
            db=db,
        )
        members_after = list_current_workspace_members(user=owner_user, db=db)
        assert len(members_after) == 1
    finally:
        _cleanup(db, engine)


def test_workspace_can_be_renamed_by_owner() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        initial = get_current_workspace(user=owner_user, db=db)
        assert "Workspace" in str(initial["name"])

        updated = update_current_workspace(
            payload=WorkspaceUpdateRequest(name="Pixel Artisan Agency"),
            user=owner_user,
            db=db,
        )
        assert updated["name"] == "Pixel Artisan Agency"
    finally:
        _cleanup(db, engine)


def test_project_response_includes_latest_project_audit_scores() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Metrics", domain_url="client-metrics.example"
            ),
            user=owner_user,
            db=db,
        )
        project_id = int(created_project["id"])
        project_row = db.query(models.Project).filter(models.Project.id == project_id).first()
        assert project_row is not None

        first_audit = models.Audit(
            user_id=owner_user.id,
            project_id=project_id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://client-metrics.example",
            geo_score=40.0,
            seo_score=55.0,
            aeo_score=50.0,
            full_report={"metadata": {"audit_outcome": "completed"}},
        )
        second_audit = models.Audit(
            user_id=owner_user.id,
            project_id=project_id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://client-metrics.example",
            geo_score=68.0,
            seo_score=72.0,
            aeo_score=70.0,
            full_report={"metadata": {"audit_outcome": "completed"}},
        )
        db.add_all([first_audit, second_audit])
        db.commit()

        project_payload = get_project(project_id=project_id, user=owner_user, db=db)
        assert project_payload["audit_count"] == 2
        assert project_payload["latest_seo_score"] == pytest.approx(72.0)
        assert project_payload["latest_geo_score"] == pytest.approx(68.0)
        assert project_payload["latest_aeo_score"] == pytest.approx(70.0)

        listed_projects = list_current_workspace_projects(user=owner_user, db=db)
        listed_payload = next(
            (project for project in listed_projects if int(project["id"]) == project_id),
            None,
        )
        assert listed_payload is not None
        assert listed_payload["latest_seo_score"] == pytest.approx(72.0)
        assert listed_payload["latest_geo_score"] == pytest.approx(68.0)
        assert listed_payload["latest_aeo_score"] == pytest.approx(70.0)
    finally:
        _cleanup(db, engine)


def test_project_audit_history_endpoints_return_project_scoped_data() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Client Audit Feed", domain_url="client-audit-feed.example"
            ),
            user=owner_user,
            db=db,
        )
        project_id = int(created_project["id"])

        other_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Client Other", domain_url="client-other.example"),
            user=owner_user,
            db=db,
        )
        other_project_id = int(other_project["id"])

        db.add_all(
            [
                models.Audit(
                    user_id=owner_user.id,
                    project_id=project_id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    audit_type=models.AuditType.STANDARD,
                    url="https://client-audit-feed.example",
                    geo_score=42.0,
                    seo_score=60.0,
                    aeo_score=58.0,
                    full_report={
                        "metadata": {"audit_outcome": "completed"},
                        "scores": {"seo": 60, "geo": 42, "aeo": 58},
                    },
                ),
                models.Audit(
                    user_id=owner_user.id,
                    project_id=project_id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    audit_type=models.AuditType.DEEP,
                    url="https://client-audit-feed.example",
                    geo_score=66.0,
                    seo_score=74.0,
                    aeo_score=71.0,
                    full_report={
                        "metadata": {"audit_outcome": "completed"},
                        "scores": {"seo": 74, "geo": 66, "aeo": 71},
                    },
                ),
                models.Audit(
                    user_id=owner_user.id,
                    project_id=other_project_id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    audit_type=models.AuditType.DEEP,
                    url="https://client-other.example",
                    geo_score=51.0,
                    seo_score=53.0,
                    aeo_score=49.0,
                    full_report={"metadata": {"audit_outcome": "completed"}},
                ),
            ]
        )
        db.commit()

        history = list_project_audits(
            project_id=project_id,
            user=owner_user,
            db=db,
            limit=10,
            include_full_report=False,
            audit_type=None,
        )
        assert len(history) == 2
        assert history[0]["project_id"] == project_id
        assert history[0]["site_id"] is None
        assert history[0]["full_report"] is None
        assert history[0]["audit_type"] == "DEEP"
        assert history[1]["audit_type"] == "STANDARD"

        smart_only = list_project_audits(
            project_id=project_id,
            user=owner_user,
            db=db,
            limit=10,
            include_full_report=False,
            audit_type="DEEP",
        )
        assert len(smart_only) == 1
        assert smart_only[0]["audit_type"] == "DEEP"

        latest = get_project_latest_audit(
            project_id=project_id,
            user=owner_user,
            db=db,
            include_full_report=True,
            audit_type=None,
        )
        assert latest is not None
        assert latest["project_id"] == project_id
        assert latest["site_id"] is None
        assert latest["audit_type"] == "DEEP"
        assert latest["full_report"] is not None
        assert (
            str(latest["full_report"]["site"]["url"]).rstrip("/")
            == "https://client-audit-feed.example"
        )
    finally:
        _cleanup(db, engine)


def test_project_audit_history_is_accessible_for_workspace_member() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        member_user = models.User(
            email="workspace-audit-member@example.com",
            hashed_password="x",
            role="user",
            credits=5,
            notifications_enabled=True,
        )
        db.add(member_user)
        db.commit()
        db.refresh(member_user)

        workspace_payload = get_current_workspace(user=owner_user, db=db)
        workspace_id = int(workspace_payload["id"])
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace_id,
                user_id=member_user.id,
                role=models.WorkspaceRole.EDITOR,
            )
        )
        db.commit()

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Client Shared", domain_url="client-shared.example"),
            user=owner_user,
            db=db,
        )
        project_id = int(created_project["id"])

        db.add(
            models.Audit(
                user_id=owner_user.id,
                project_id=project_id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                audit_type=models.AuditType.DEEP,
                url="https://client-shared.example",
                geo_score=70.0,
                seo_score=73.0,
                aeo_score=76.0,
                full_report={"metadata": {"audit_outcome": "completed"}},
            )
        )
        db.commit()

        member_latest = get_project_latest_audit(
            project_id=project_id,
            user=member_user,
            db=db,
            include_full_report=False,
            audit_type=None,
        )
        assert member_latest is not None
        assert member_latest["audit_type"] == "DEEP"
    finally:
        _cleanup(db, engine)


def test_get_project_includes_backend_feature_access() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        db.add(
            models.Subscription(
                user_id=owner_user.id,
                stripe_customer_id="cus_plan_standard",
                stripe_subscription_id="sub_plan_standard",
                plan_type="plan_standard",
                status="active",
            )
        )
        db.commit()

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(
                name="Feature Access", domain_url="feature-access.example"
            ),
            user=owner_user,
            db=db,
        )

        project_payload = get_project(
            project_id=int(created_project["id"]),
            user=owner_user,
            db=db,
        )
        feature_access = project_payload["feature_access"]
        assert feature_access["monitoring"]["allowed"] is True
        assert feature_access["automations"]["allowed"] is False
        assert feature_access["automations"]["status_code"] == 402
        assert "Specialist" in str(feature_access["automations"]["detail"])
        # SIGV2-1134: the Advisor action plan is served as its own entitlement,
        # granted from Standard up, so the dashboard preview and the plan page
        # read one key instead of disagreeing about which plan sells the plan.
        assert feature_access["advisor_recommendations"]["allowed"] is True
        assert feature_access["advisor_recommendations"]["required_plan"] is None
    finally:
        _cleanup(db, engine)


def test_project_latest_audit_selection_returns_no_matching_aeo_audit() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        db.add(
            models.Subscription(
                user_id=owner_user.id,
                stripe_customer_id="cus_plan_specialist",
                stripe_subscription_id="sub_plan_specialist",
                plan_type="plan_specialist",
                status="active",
            )
        )
        db.commit()

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Selection Project", domain_url="selection.example"),
            user=owner_user,
            db=db,
        )
        project_id = int(created_project["id"])

        audit = models.Audit(
            user_id=owner_user.id,
            project_id=project_id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            audit_type=models.AuditType.STANDARD,
            url="https://selection.example",
            geo_score=64.0,
            seo_score=72.0,
            aeo_score=61.0,
            full_report={"metadata": {"audit_outcome": "completed"}},
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit)
        db.commit()

        selection = get_project_latest_audit_selection(
            project_id=project_id,
            module="aeo",
            user=owner_user,
            db=db,
            include_full_report=True,
        )
        assert selection.status == "no_matching_audit"
        assert selection.selected_audit is None
        assert selection.latest_audit is not None
        assert selection.latest_audit.audit_type == "STANDARD"
        assert selection.recommended_audit_type == "DEEP"
    finally:
        _cleanup(db, engine)


def test_project_latest_audit_selection_marks_stale_geo_data() -> None:
    db, _session_factory, engine, owner_user = _build_db()
    try:
        db.add(
            models.Subscription(
                user_id=owner_user.id,
                stripe_customer_id="cus_plan_specialist_geo",
                stripe_subscription_id="sub_plan_specialist_geo",
                plan_type="plan_specialist",
                status="active",
            )
        )
        db.commit()

        created_project = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="Geo Freshness", domain_url="geo-freshness.example"),
            user=owner_user,
            db=db,
        )
        project_id = int(created_project["id"])

        db.add_all(
            [
                models.Audit(
                    user_id=owner_user.id,
                    project_id=project_id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    audit_type=models.AuditType.DEEP,
                    url="https://geo-freshness.example",
                    geo_score=71.0,
                    seo_score=74.0,
                    aeo_score=69.0,
                    full_report={"metadata": {"audit_outcome": "completed"}},
                    created_at=datetime.now(timezone.utc) - timedelta(days=21),
                ),
                models.Audit(
                    user_id=owner_user.id,
                    project_id=project_id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    audit_type=models.AuditType.STANDARD,
                    url="https://geo-freshness.example",
                    geo_score=75.0,
                    seo_score=78.0,
                    aeo_score=70.0,
                    full_report={"metadata": {"audit_outcome": "completed"}},
                    created_at=datetime.now(timezone.utc) - timedelta(days=2),
                ),
            ]
        )
        db.commit()

        selection = get_project_latest_audit_selection(
            project_id=project_id,
            module="geo",
            user=owner_user,
            db=db,
            include_full_report=False,
        )
        assert selection.status == "stale"
        assert selection.selected_audit is not None
        assert selection.selected_audit.audit_type == "DEEP"
        assert selection.selected_audit_age_days is not None
        assert selection.selected_audit_age_days >= 14
        assert selection.latest_audit is not None
        assert selection.latest_audit.audit_type == "STANDARD"
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# SIGV2-1207: the workspace OAuth start flow could not know which workspace the
# customer was in. The connect action is a full browser navigation, so no
# X-Workspace-Id header can ride along, and the resolver fell back to the
# user's OLDEST owned workspace - Khuzaima's Google connection landed on
# workspace 9 while all seven of his projects live in workspace 11. An
# explicit workspace_id on the start request now carries the choice through
# the redirect, and the catalog tells the customer when the account they need
# is already connected on another of their workspaces.
# ---------------------------------------------------------------------------


class _FakeOAuthStartRequest:
    """Just enough Request for _start_workspace_oauth_flow: a session dict and
    url_for for the callback URI builder."""

    def __init__(self, workspace_id: int | None = None) -> None:
        self.session: dict[str, dict[str, int]] = {}
        self.query_params: dict[str, str] = {}
        if workspace_id is not None:
            self.query_params["workspace_id"] = str(workspace_id)

    def url_for(self, name: str, **_params) -> str:
        return f"https://backend.test/{name}"


class _FakeOAuthClient:
    async def authorize_redirect(self, request, redirect_uri, **_kwargs):
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="https://provider.test/authorize", status_code=307)


def _make_owned_workspace(db: Session, user: models.User, name: str) -> models.Workspace:
    workspace = models.Workspace(name=name, owner_id=user.id)
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
    return workspace


def _run_oauth_start(
    monkeypatch,
    db: Session,
    user: models.User,
    workspace_id: int | None = None,
) -> _FakeOAuthStartRequest:
    import asyncio

    import routers.workspace_router as workspace_router_module

    request = _FakeOAuthStartRequest(workspace_id=workspace_id)
    monkeypatch.setattr(
        workspace_router_module.oauth, "create_client", lambda _name: _FakeOAuthClient()
    )
    monkeypatch.setattr(
        workspace_router_module, "_oauth_provider_configured", lambda _provider: True
    )

    kwargs: dict[str, object] = {}
    if workspace_id is not None:
        kwargs["workspace_id"] = workspace_id

    asyncio.run(
        workspace_router_module._start_workspace_oauth_flow(
            request=request,  # type: ignore[arg-type]
            db=db,
            user=user,
            provider="google",
            callback_route_name="workspace_google_oauth_callback",
            authorize_kwargs={"scope": "openid"},
            **kwargs,  # type: ignore[arg-type]
        )
    )
    return request


def test_oauth_start_without_workspace_id_keeps_landing_on_oldest_owned_workspace(
    monkeypatch,
) -> None:
    """Absent parameter means unchanged behaviour: the default resolution."""
    db, _session_factory, engine, user = _build_db()
    try:
        oldest = _make_owned_workspace(db, user, "Oldest Workspace")
        newest = _make_owned_workspace(db, user, "Newest Workspace")
        assert newest.id > oldest.id

        request = _run_oauth_start(monkeypatch, db, user)

        payload = request.session["workspace_google_oauth"]
        assert payload["workspace_id"] == oldest.id
        assert payload["user_id"] == user.id
    finally:
        _cleanup(db, engine)


def test_oauth_start_honours_an_explicit_workspace_id(monkeypatch) -> None:
    """The bug: projects in the newer workspace, connection landed on the
    oldest. With the id on the request it lands where the customer is."""
    db, _session_factory, engine, user = _build_db()
    try:
        _oldest = _make_owned_workspace(db, user, "Oldest Workspace")
        newest = _make_owned_workspace(db, user, "Newest Workspace")

        request = _run_oauth_start(monkeypatch, db, user, workspace_id=newest.id)

        payload = request.session["workspace_google_oauth"]
        assert payload["workspace_id"] == newest.id
        assert payload["user_id"] == user.id
    finally:
        _cleanup(db, engine)


def test_oauth_start_refuses_a_workspace_the_user_cannot_access(monkeypatch) -> None:
    """An inaccessible id is refused, never silently swapped for a workspace
    the user does own - that silent substitution is the defect being fixed."""
    db, _session_factory, engine, user = _build_db()
    try:
        _owned = _make_owned_workspace(db, user, "Own Workspace")
        other_owner = models.User(
            email="other-owner@example.com",
            hashed_password="x",
            role="user",
        )
        db.add(other_owner)
        db.commit()
        db.refresh(other_owner)
        foreign = _make_owned_workspace(db, other_owner, "Foreign Workspace")

        with pytest.raises(HTTPException) as excinfo:
            _run_oauth_start(monkeypatch, db, user, workspace_id=foreign.id)
        assert excinfo.value.status_code == 403
    finally:
        _cleanup(db, engine)


def test_oauth_start_still_requires_workspace_admin_role(monkeypatch) -> None:
    """Membership is not enough: the existing admin requirement still applies
    to an explicitly requested workspace."""
    db, _session_factory, engine, user = _build_db()
    try:
        owner = models.User(
            email="admin-owner@example.com",
            hashed_password="x",
            role="user",
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        shared = _make_owned_workspace(db, owner, "Shared Workspace")
        db.add(
            models.WorkspaceUser(
                workspace_id=shared.id,
                user_id=user.id,
                role=models.WorkspaceRole.VIEWER,
            )
        )
        db.commit()

        with pytest.raises(HTTPException) as excinfo:
            _run_oauth_start(monkeypatch, db, user, workspace_id=shared.id)
        assert excinfo.value.status_code == 403
        assert "admin" in str(excinfo.value.detail).lower()
    finally:
        _cleanup(db, engine)


def test_catalog_reports_a_connection_held_on_another_workspace() -> None:
    """Khuzaima's case: the project's workspace has no Google connection, but
    he holds a healthy one on another workspace he owns. The catalog must say
    so instead of presenting a bare 'connect an account'."""
    db, _session_factory, engine, user = _build_db()
    try:
        connected_ws = _make_owned_workspace(db, user, "Connected Workspace")
        project_ws = _make_owned_workspace(db, user, "Project Workspace")
        project = models.Project(
            workspace_id=project_ws.id,
            name="Project In Newer Workspace",
            domain_url="other-ws-catalog.example",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        db.add(
            models.OAuthConnection(
                workspace_id=connected_ws.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                token_type="Bearer",
                scope="https://www.googleapis.com/auth/analytics.readonly",
            )
        )
        db.commit()

        catalog = get_project_data_source_catalog(
            project_id=project.id,
            source_type="google_analytics_4",
            user=user,
            db=db,
        )
        assert catalog.workspace_provider_connected is False
        assert catalog.error == "workspace_provider_not_connected"
        assert catalog.connected_on_other_workspace is True
    finally:
        _cleanup(db, engine)


def test_catalog_reports_no_connection_anywhere_when_none_exists() -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        project_ws = _make_owned_workspace(db, user, "Project Workspace")
        project = models.Project(
            workspace_id=project_ws.id,
            name="Project Nowhere Connected",
            domain_url="no-ws-catalog.example",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        catalog = get_project_data_source_catalog(
            project_id=project.id,
            source_type="google_analytics_4",
            user=user,
            db=db,
        )
        assert catalog.workspace_provider_connected is False
        assert catalog.connected_on_other_workspace is False
    finally:
        _cleanup(db, engine)


def test_catalog_does_not_count_a_connection_on_a_foreign_workspace() -> None:
    """Only workspaces the user actually has access to count."""
    db, _session_factory, engine, user = _build_db()
    try:
        other_owner = models.User(
            email="foreign-owner@example.com",
            hashed_password="x",
            role="user",
        )
        db.add(other_owner)
        db.commit()
        db.refresh(other_owner)
        foreign_ws = _make_owned_workspace(db, other_owner, "Foreign Workspace")
        project_ws = _make_owned_workspace(db, user, "Project Workspace")
        project = models.Project(
            workspace_id=project_ws.id,
            name="Project Foreign Connection",
            domain_url="foreign-ws-catalog.example",
        )
        db.add(project)
        db.add(
            models.OAuthConnection(
                workspace_id=foreign_ws.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="google-access-token",
                refresh_token="google-refresh-token",
            )
        )
        db.commit()
        db.refresh(project)

        catalog = get_project_data_source_catalog(
            project_id=project.id,
            source_type="google_analytics_4",
            user=user,
            db=db,
        )
        assert catalog.workspace_provider_connected is False
        assert catalog.connected_on_other_workspace is False
    finally:
        _cleanup(db, engine)
