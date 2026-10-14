"""SIGV2-1008: evidence-backed unlinked brand mentions.

Reclaimable = a *publication* whose fetched page confirms the brand but
carries no outbound link to the target domain. Fetches go through the
existing SSRF-safe ``safe_sync_fetch`` path; failed, blocked, unfetched and
brand-unconfirmed pages stay ``unknown`` and are never counted as unlinked.
Uncited AI-response mentions are a different metric and are not counted here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base, get_db
from routers.monitoring_router import router as monitoring_router
from services.url_validation import SSRFBlockedError

FETCH_PATH = "services.project_offpage_mentions_service.safe_sync_fetch"

RECENT_TS = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

BRAND_PAGE_HTML = (
    "<html><body><article><h1>Best enterprise GEO tools</h1>"
    "<p>Off Page Project is a recommended platform for citation monitoring.</p>"
    "</article></body></html>"
)

LINKED_PAGE_HTML = (
    "<html><body><p>Off Page Project is great, "
    '<a href="https://offpage.example/features">see their features</a>.</p>'
    "</body></html>"
)

NO_BRAND_PAGE_HTML = (
    "<html><body><p>A roundup of analytics vendors with no target brand.</p>" "</body></html>"
)


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(monitoring_router)
    return app


def _build_client(
    *,
    plan_type: str = "plan_specialist",
    workspace_role: models.WorkspaceRole | None = None,
    foreign: bool = False,
) -> tuple[TestClient, FastAPI, object, models.User, models.Project]:
    app = _build_test_app()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        email=f"unlinked-{plan_type}-{workspace_role}@example.com",
        hashed_password="x",
        role="user",
        credits=250,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_unlinked_{user.id}",
            stripe_subscription_id=f"sub_unlinked_{user.id}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    if workspace_role is not None or foreign:
        owner = models.User(
            email=f"unlinked-owner-{user.id}@example.com",
            hashed_password="x",
            role="user",
            credits=250,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id=f"cus_unlinked_owner_{owner.id}",
                stripe_subscription_id=f"sub_unlinked_owner_{owner.id}",
                plan_type="plan_specialist",
                status="active",
            )
        )
        db.commit()
        owner_id = owner.id
    else:
        owner_id = user.id

    workspace = models.Workspace(name="Unlinked Workspace", owner_id=owner_id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    if workspace_role is not None:
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=user.id,
                role=workspace_role,
            )
        )
        db.commit()

    if foreign:
        foreign_workspace = models.Workspace(name="Foreign Workspace", owner_id=user.id)
        db.add(foreign_workspace)
        db.commit()

    project = models.Project(
        workspace_id=workspace.id,
        name="Off Page Project",
        domain_url="https://offpage.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app), app, db, user, project


def _cleanup(app: FastAPI, db) -> None:
    app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def _ingest(client: TestClient, project_id: int, mentions: list[dict]) -> dict:
    payload = {
        "source_type": "manual_import",
        "run_analysis": False,
        "skip_existing": True,
        "mentions": [
            {
                "snippet": "Off Page Project coverage.",
                "published_at": RECENT_TS,
                **mention,
            }
            for mention in mentions
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/monitoring/off-page-mentions/ingest",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _verify(client: TestClient, project_id: int, **payload) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/monitoring/off-page-mentions/verify-links",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _unlinked(client: TestClient, project_id: int, query: str = "") -> dict:
    response = client.get(
        f"/api/v1/projects/{project_id}/monitoring/off-page-mentions/unlinked{query}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fake_response(html: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, text=html)


def test_unlinked_mention_is_counted_and_listed_with_evidence() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/geo-tools"}],
        )
        with patch(FETCH_PATH, return_value=_fake_response(BRAND_PAGE_HTML)):
            result = _verify(client, project.id)
        assert result["checked"] == 1
        assert result["counts"]["unlinked"] == 1
        item = result["items"][0]
        assert item["link_state"] == "unlinked"
        assert item["link_checked_at"] is not None
        evidence = item["link_evidence"]
        assert evidence["method"] == "safe_sync_fetch"
        assert evidence["brand_matched"] is True
        assert evidence["matched_target_urls"] == []

        payload = _unlinked(client, project.id)
        assert payload["count"] == 1
        assert payload["states"]["unlinked"] == 1
        assert [entry["id"] for entry in payload["items"]] == [item["id"]]
    finally:
        _cleanup(app, db)


def test_linked_mention_is_not_reclaimable() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/linked"}],
        )
        with patch(FETCH_PATH, return_value=_fake_response(LINKED_PAGE_HTML)):
            result = _verify(client, project.id)
        assert result["counts"]["linked"] == 1
        item = result["items"][0]
        assert item["link_state"] == "linked"
        assert item["link_evidence"]["matched_target_urls"] == ["https://offpage.example/features"]

        payload = _unlinked(client, project.id)
        assert payload["count"] == 0
        assert payload["items"] == []
        assert payload["states"]["linked"] == 1
    finally:
        _cleanup(app, db)


def test_failed_fetch_is_unknown_not_unlinked() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/down"}],
        )
        with patch(
            FETCH_PATH,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            result = _verify(client, project.id)
        assert result["counts"]["unknown"] == 1
        item = result["items"][0]
        assert item["link_state"] == "unknown"
        assert item["link_evidence"]["outcome"] == "fetch_failed"

        payload = _unlinked(client, project.id)
        assert payload["count"] == 0
        assert payload["states"]["unknown"] == 1
    finally:
        _cleanup(app, db)


def test_http_error_fetch_is_unknown_not_unlinked() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/paywalled"}],
        )
        with patch(FETCH_PATH, return_value=_fake_response("Forbidden", 403)):
            result = _verify(client, project.id)
        assert result["items"][0]["link_state"] == "unknown"
        assert result["items"][0]["link_evidence"]["http_status"] == 403
        assert _unlinked(client, project.id)["count"] == 0
    finally:
        _cleanup(app, db)


def test_ssrf_blocked_fetch_is_unknown_not_unlinked() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://169.254.169.254/latest/meta-data"}],
        )
        with patch(
            FETCH_PATH,
            side_effect=SSRFBlockedError("Private or reserved IP address is not allowed"),
        ) as mock_fetch:
            result = _verify(client, project.id)
        assert mock_fetch.call_count == 1
        item = result["items"][0]
        assert item["link_state"] == "unknown"
        assert item["link_evidence"]["outcome"] == "fetch_blocked"
        assert _unlinked(client, project.id)["count"] == 0
    finally:
        _cleanup(app, db)


def test_page_without_brand_confirmation_is_unknown() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/ambiguous"}],
        )
        with patch(FETCH_PATH, return_value=_fake_response(NO_BRAND_PAGE_HTML)):
            result = _verify(client, project.id)
        item = result["items"][0]
        assert item["link_state"] == "unknown"
        assert item["link_evidence"]["outcome"] == "brand_not_confirmed"
        assert item["link_evidence"]["brand_matched"] is False
        assert _unlinked(client, project.id)["count"] == 0
    finally:
        _cleanup(app, db)


def test_mention_without_source_url_stays_unknown() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(client, project.id, [{"snippet": "No URL evidence at all."}])
        with patch(FETCH_PATH) as mock_fetch:
            result = _verify(client, project.id)
        mock_fetch.assert_not_called()
        item = result["items"][0]
        assert item["link_state"] == "unknown"
        assert item["link_evidence"]["outcome"] == "no_source_url"
        assert _unlinked(client, project.id)["count"] == 0
    finally:
        _cleanup(app, db)


def test_unchecked_mentions_are_unknown_not_unlinked() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/pending"}],
        )
        payload = _unlinked(client, project.id)
        assert payload["count"] == 0
        assert payload["items"] == []
        assert payload["states"]["unknown"] == 1
    finally:
        _cleanup(app, db)


def test_canonical_url_variants_dedupe_to_one_mention() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [
                {"mention_url": "https://www.pub.example/articles/geo-tools/"},
                {"mention_url": "http://pub.example/articles/geo-tools#comments"},
            ],
        )
        with patch(FETCH_PATH, return_value=_fake_response(BRAND_PAGE_HTML)):
            _verify(client, project.id)
        payload = _unlinked(client, project.id)
        assert payload["count"] == 1
        assert len(payload["items"]) == 1
    finally:
        _cleanup(app, db)


def test_repeated_ingestion_dedupes_same_external_id() -> None:
    client, app, db, _user, project = _build_client()
    try:
        mention = {
            "mention_url": "https://pub.example/articles/geo-tools",
            "external_id": "pub-1",
        }
        first = _ingest(client, project.id, [mention])
        second = _ingest(client, project.id, [mention])
        assert first["ingested_mentions"] == 1
        assert second["skipped_mentions"] == 1
        with patch(FETCH_PATH, return_value=_fake_response(BRAND_PAGE_HTML)):
            _verify(client, project.id)
        assert _unlinked(client, project.id)["count"] == 1
    finally:
        _cleanup(app, db)


def test_count_reconciles_with_paginated_list() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [
                {"mention_url": "https://pub.example/a"},
                {"mention_url": "https://pub.example/b"},
                {"mention_url": "https://pub.example/c"},
            ],
        )
        with patch(FETCH_PATH, return_value=_fake_response(BRAND_PAGE_HTML)):
            _verify(client, project.id)
        page_one = _unlinked(client, project.id, "?limit=2&offset=0")
        page_two = _unlinked(client, project.id, "?limit=2&offset=2")
        assert page_one["count"] == 3
        assert page_two["count"] == 3
        assert len(page_one["items"]) == 2
        assert len(page_two["items"]) == 1
        listed_ids = {item["id"] for item in page_one["items"] + page_two["items"]}
        assert len(listed_ids) == 3  # every counted mention appears exactly once
    finally:
        _cleanup(app, db)


def test_unlinked_count_ignores_other_projects_and_states() -> None:
    client, app, db, user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [
                {"mention_url": "https://pub.example/linked-page"},
                {"mention_url": "https://pub.example/unlinked-page"},
            ],
        )

        def _route_fetch(url: str, **kwargs) -> httpx.Response:
            if "unlinked-page" in url:
                return _fake_response(BRAND_PAGE_HTML)
            return _fake_response(LINKED_PAGE_HTML)

        with patch(FETCH_PATH, side_effect=_route_fetch):
            _verify(client, project.id)
        payload = _unlinked(client, project.id)
        assert payload["count"] == 1
        assert payload["items"][0]["mention_url"] == "https://pub.example/unlinked-page"
        assert payload["states"] == {"unlinked": 1, "linked": 1, "unknown": 0}
        assert "predicted" not in str(payload).lower()
        assert "uplift" not in str(payload).lower()
    finally:
        _cleanup(app, db)


def test_verify_endpoint_scopes_to_supplied_mention_ids() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [
                {"mention_url": "https://pub.example/one"},
                {"mention_url": "https://pub.example/two"},
            ],
        )
        mention_id = (
            db.query(models.ProjectOffPageMention.id)
            .filter(
                models.ProjectOffPageMention.project_id == project.id,
                models.ProjectOffPageMention.mention_url == "https://pub.example/two",
            )
            .scalar()
        )
        foreign_id = mention_id + 9999
        with patch(FETCH_PATH, return_value=_fake_response(BRAND_PAGE_HTML)):
            result = _verify(client, project.id, mention_ids=[mention_id, foreign_id])
        assert result["checked"] == 1  # foreign id silently excluded by project scope
        assert result["items"][0]["id"] == mention_id
    finally:
        _cleanup(app, db)


def test_readonly_member_can_read_but_not_verify() -> None:
    client, app, db, _user, project = _build_client(
        workspace_role=models.WorkspaceRole.VIEWER,
    )
    try:
        db.add(
            models.ProjectOffPageMention(
                project_id=project.id,
                snippet="Off Page Project coverage.",
                mention_url="https://pub.example/articles/ro",
                fingerprint_hash="ro-fingerprint",
                discovered_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        read_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/unlinked"
        )
        assert read_response.status_code == 200
        verify_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/verify-links",
            json={},
        )
        assert verify_response.status_code == 403
    finally:
        _cleanup(app, db)


def test_foreign_workspace_cannot_read_or_verify() -> None:
    client, app, db, _user, project = _build_client(foreign=True)
    try:
        db.add(
            models.ProjectOffPageMention(
                project_id=project.id,
                snippet="Off Page Project coverage.",
                mention_url="https://pub.example/articles/foreign",
                fingerprint_hash="foreign-fingerprint",
                discovered_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        read_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/unlinked"
        )
        assert read_response.status_code in (403, 404)
        verify_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/verify-links",
            json={},
        )
        assert verify_response.status_code in (403, 404)
    finally:
        _cleanup(app, db)


def test_unlinked_endpoint_plan_gate() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/unlinked"
        )
        assert response.status_code == 402
    finally:
        _cleanup(app, db)


def test_feed_items_expose_link_state_fields() -> None:
    client, app, db, _user, project = _build_client()
    try:
        _ingest(
            client,
            project.id,
            [{"mention_url": "https://pub.example/articles/feed"}],
        )
        feed = client.get(f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/feed")
        assert feed.status_code == 200
        item = feed.json()[0]
        assert item["link_state"] == "unknown"
        assert item["link_checked_at"] is None
        assert item["link_evidence"] == {}
    finally:
        _cleanup(app, db)
