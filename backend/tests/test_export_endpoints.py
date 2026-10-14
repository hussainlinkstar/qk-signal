import csv
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import database
import main
import models
from database import Base
from middleware import maintenance as maintenance_module
from services.external_api_service import hash_api_key


class FakeRedis:
    """Synchronous fake mirroring the sync redis client used by the external
    API rate limiter (``get_sync_redis`` -> ``redis.from_url``)."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        value = int(self.counters.get(key, 0)) + 1
        self.counters[key] = value
        return value

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = int(seconds)
        return True

    def ttl(self, key: str) -> int:
        return int(self.ttls.get(key, -1))

    def close(self) -> None:
        return None


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(
    db: Session,
    *,
    email: str,
    credits: int = 50,
    plan_type: str = "plan_specialist",
    subscription_status: str = "active",
) -> models.User:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=credits,
        company_name="Agency Ops",
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type=plan_type,
            status=subscription_status,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _seed_api_key(
    db: Session,
    *,
    user: models.User,
    raw_key: str = "stx_live_0123456789abcdef0123456789abcd",
) -> models.ApiKey:
    api_key = models.ApiKey(
        user_id=user.id,
        name="Export Key",
        key_hash=hash_api_key(raw_key),
        key_prefix="stx_live_",
        key_last_four=raw_key[-4:],
        scopes=["audit:read", "audit:write"],
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def _build_client(db: Session, *, auth_user: models.User) -> TestClient:
    def override_get_db():
        yield db

    def override_current_user():
        return db.query(models.User).filter(models.User.id == auth_user.id).first()

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_current_user
    maintenance_module._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }
    return TestClient(main.app)


def _seed_workspace_project(
    db: Session,
    *,
    owner: models.User,
    name: str,
) -> models.Project:
    workspace = models.Workspace(name=f"{name} Workspace", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name=name,
        domain_url=f"https://{name.lower().replace(' ', '-')}.example",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _seed_workspace_member(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
) -> None:
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace_id,
            user_id=user_id,
            role=models.WorkspaceRole.EDITOR,
        )
    )
    db.commit()


def _seed_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    url: str,
    created_at: datetime,
    geo_score: float,
    seo_score: float,
    aeo_score: float,
    entities: list[str],
    recommendations: list[str],
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=url,
        geo_score=geo_score,
        seo_score=seo_score,
        aeo_score=aeo_score,
        created_at=created_at,
        full_report={
            "analysis": {
                "entities_detected": entities,
                "recommendations": recommendations,
            }
        },
        request_id=f"req-{user_id}-{project_id}-{created_at.timestamp()}",
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _parse_csv_rows(payload: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(payload)))


def test_project_scores_csv_exports_project_audits_with_derived_counts(monkeypatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        owner = _seed_user(db, email="owner@example.com")
        teammate = _seed_user(db, email="teammate@example.com")
        _seed_api_key(db, user=owner)
        client = _build_client(db, auth_user=owner)

        project = _seed_workspace_project(db, owner=owner, name="Client Alpha")
        other_project = _seed_workspace_project(db, owner=owner, name="Client Beta")
        _seed_workspace_member(db, workspace_id=project.workspace_id, user_id=teammate.id)

        canonical_audit = _seed_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://alpha.example/landing",
            created_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
            geo_score=75,
            seo_score=82,
            aeo_score=68,
            entities=["Entity One", "Entity Two"],
            recommendations=["Improve internal linking", "Add FAQ schema"],
        )
        canonical_audit.full_report = {
            "entities": ["Entity One", "Entity Two"],
            "recommendations": {
                "items": [
                    {"title": "Improve internal linking", "action": "Improve internal linking"},
                    {"title": "Add FAQ schema", "action": "Add FAQ schema"},
                ]
            },
        }
        db.add(canonical_audit)
        db.commit()
        _seed_audit(
            db,
            user_id=teammate.id,
            project_id=project.id,
            url="https://alpha.example/pricing",
            created_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
            geo_score=78,
            seo_score=80,
            aeo_score=71,
            entities=["Brand Alpha"],
            recommendations=["Tighten title tags", "Expand entity coverage", "Add citations"],
        )
        teammate_audit = (
            db.query(models.Audit)
            .filter(
                models.Audit.project_id == project.id,
                models.Audit.url == "https://alpha.example/pricing",
            )
            .first()
        )
        assert teammate_audit is not None
        teammate_audit.full_report = {
            "entities": ["Brand Alpha"],
            "prioritized_actions": [
                {"title": "Tighten title tags"},
                {"title": "Expand entity coverage"},
            ],
            "recommendations": [
                {"title": "Add citations", "action": "Add citations", "category": "authority"},
            ],
        }
        db.add(teammate_audit)
        db.commit()
        _seed_audit(
            db,
            user_id=owner.id,
            project_id=other_project.id,
            url="https://beta.example",
            created_at=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
            geo_score=60,
            seo_score=61,
            aeo_score=62,
            entities=["Should Not Export"],
            recommendations=["Ignore"],
        )

        monkeypatch.setattr(
            "services.external_api_service.redis.from_url", lambda *_args, **_kwargs: fake_redis
        )

        response = client.get(
            f"/api/v1/external/projects/{project.id}/scores/csv",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["X-RateLimit-Limit"] == "60"
        rows = _parse_csv_rows(response.text)
        assert len(rows) == 2
        assert [row["url"] for row in rows] == [
            "https://alpha.example/landing",
            "https://alpha.example/pricing",
        ]
        assert rows[0]["project_id"] == str(project.id)
        assert rows[0]["entity_count"] == "2"
        assert rows[0]["recommendation_count"] == "2"
        assert rows[1]["entity_count"] == "1"
        assert rows[1]["recommendation_count"] == "3"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_bulk_csv_export_filters_by_date_and_project_ids(monkeypatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        owner = _seed_user(db, email="owner@example.com")
        _seed_api_key(db, user=owner)
        client = _build_client(db, auth_user=owner)

        project_one = _seed_workspace_project(db, owner=owner, name="Client One")
        project_two = _seed_workspace_project(db, owner=owner, name="Client Two")

        _seed_audit(
            db,
            user_id=owner.id,
            project_id=project_one.id,
            url="https://one.example/march-1",
            created_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            geo_score=70,
            seo_score=71,
            aeo_score=72,
            entities=["One"],
            recommendations=["One Rec"],
        )
        _seed_audit(
            db,
            user_id=owner.id,
            project_id=project_one.id,
            url="https://one.example/march-2",
            created_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
            geo_score=73,
            seo_score=74,
            aeo_score=75,
            entities=["Two"],
            recommendations=["Two Rec"],
        )
        _seed_audit(
            db,
            user_id=owner.id,
            project_id=project_two.id,
            url="https://two.example/march-3",
            created_at=datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
            geo_score=76,
            seo_score=77,
            aeo_score=78,
            entities=["Three"],
            recommendations=["Three Rec"],
        )

        monkeypatch.setattr(
            "services.external_api_service.redis.from_url", lambda *_args, **_kwargs: fake_redis
        )

        response = client.get(
            "/api/v1/external/export",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
            params=[
                ("project_id", str(project_one.id)),
                ("project_id", str(project_two.id)),
                ("start_date", "2026-03-02"),
                ("end_date", "2026-03-03"),
            ],
        )

        assert response.status_code == 200
        rows = _parse_csv_rows(response.text)
        assert [row["url"] for row in rows] == [
            "https://one.example/march-2",
            "https://two.example/march-3",
        ]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_export_endpoint_rejects_plan_standard_plan(monkeypatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="starter@example.com", plan_type="plan_standard")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user)

        monkeypatch.setattr(
            "services.external_api_service.redis.from_url", lambda *_args, **_kwargs: fake_redis
        )

        response = client.get(
            "/api/v1/external/export",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PLAN_NOT_ELIGIBLE"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_export_endpoint_enforces_rate_limits(monkeypatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="rate-limit@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user)

        monkeypatch.setattr(
            "services.external_api_service.redis.from_url", lambda *_args, **_kwargs: fake_redis
        )

        last_response = None
        for _ in range(61):
            last_response = client.get(
                "/api/v1/external/export",
                headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
            )

        assert last_response is not None
        assert last_response.status_code == 429
        assert last_response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert last_response.headers["Retry-After"] == "60"
    finally:
        main.app.dependency_overrides.clear()


def test_project_buckets_aggregates_scores_by_product_bucket(monkeypatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        owner = _seed_user(db, email="owner-buckets@example.com")
        _seed_api_key(db, user=owner)
        client = _build_client(db, auth_user=owner)
        project = _seed_workspace_project(db, owner=owner, name="Bucket Co")

        def _add_audit(
            url: str, intent: str | None, query_category: str | None, score: float
        ) -> None:
            db.add(
                models.Audit(
                    user_id=owner.id,
                    project_id=project.id,
                    project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                    url=url,
                    geo_score=score,
                    seo_score=score,
                    aeo_score=score,
                    intent=intent,
                    query_category=query_category,
                    created_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
                    request_id=f"req-bkt-{url}",
                )
            )
            db.commit()

        _add_audit("https://x/brand", "navigational", None, 80)  # -> brand
        _add_audit("https://x/cmp", "transactional", "commercial_comparison", 60)  # -> comparison
        _add_audit("https://x/how", "informational", "instructional", 40)  # -> problem

        monkeypatch.setattr(
            "services.external_api_service.redis.from_url", lambda *_a, **_k: fake_redis
        )

        response = client.get(
            f"/api/v1/external/projects/{project.id}/buckets",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["project_id"] == project.id
        assert body["audits_analyzed"] == 3
        # canonical order Brand -> Category -> Problem -> Feature -> Comparison
        assert [b["bucket"] for b in body["buckets"]] == [
            "brand",
            "category",
            "problem",
            "feature",
            "comparison",
        ]
        buckets = {b["bucket"]: b for b in body["buckets"]}
        assert buckets["brand"]["score"] == 80.0 and buckets["brand"]["sample_size"] == 1
        assert buckets["comparison"]["score"] == 60.0 and buckets["comparison"]["sample_size"] == 1
        assert buckets["problem"]["score"] == 40.0 and buckets["problem"]["sample_size"] == 1
        assert buckets["category"]["score"] is None and buckets["category"]["sample_size"] == 0
        assert buckets["feature"]["score"] is None and buckets["feature"]["sample_size"] == 0
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)
