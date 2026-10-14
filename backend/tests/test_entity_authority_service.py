import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.entity_authority_service import EntityAuthorityService


def _setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local()


def _seed_project(
    db,
    *,
    icp_roles: list[str] | None = None,
    usp: str | None = None,
) -> tuple[models.User, models.Project]:
    user = models.User(email="authority@example.com", hashed_password="x", role="user", credits=100)
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Authority Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Authority Project",
        domain_url="authority.example",
        icp_roles=icp_roles or [],
        usp=usp,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return user, project


def _add_audit_with_entities(
    db,
    *,
    user_id: int,
    project_id: int,
    entities: list[dict[str, object]],
    url: str = "https://authority.example",
    created_at: datetime | None = None,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=url,
        geo_score=70,
        seo_score=75,
        aeo_score=72,
        full_report={"analysis": {"entities_detected": entities}},
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _add_entity_fact(
    db,
    *,
    audit: models.Audit,
    entity_name: str,
    entity_key: str,
    relevance_score: float,
) -> None:
    site = db.query(models.Site).filter(models.Site.user_id == audit.user_id).first()
    if site is None:
        site = models.Site(
            user_id=audit.user_id, domain="authority.example", display_name="Authority"
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        audit.site_id = site.id
        db.commit()

    db.add(
        models.SiteEntityFact(
            site_id=site.id,
            audit_id=audit.id,
            entity_name=entity_name,
            entity_key=entity_key,
            entity_category="Concept",
            relevance_score=relevance_score,
            ai_importance=relevance_score,
            source="analysis.entities_detected",
            created_at=audit.created_at,
        )
    )
    db.commit()


def test_compute_score_handles_zero_audits() -> None:
    db = _setup_db()
    _user, project = _seed_project(db, icp_roles=["entity authority", "knowledge graph"])
    service = EntityAuthorityService()

    result = service.compute_score(db=db, project_id=project.id)
    db.commit()

    assert result.authority_score == 0.0
    assert result.coverage_score == 0.0
    assert result.depth_score == 0.0
    assert result.consistency_score == 0.0
    assert result.uniqueness_score == 0.0
    assert result.target_entity_count == 2
    assert result.detected_entity_count == 0
    assert result.gap_count == 2

    snapshots = (
        db.query(models.EntityAuthoritySnapshot)
        .filter(models.EntityAuthoritySnapshot.project_id == project.id)
        .all()
    )
    assert len(snapshots) == 1
    db.close()


def test_compute_score_returns_breakdown_and_gaps() -> None:
    db = _setup_db()
    user, project = _seed_project(
        db,
        icp_roles=["entity authority", "knowledge graph"],
        usp=None,
    )

    audit_1 = _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[
            {"name": "Entity Authority", "relevance_score": 88, "mention_count": 3},
            {"name": "Schema Markup", "relevance_score": 70, "mention_count": 1},
        ],
    )
    audit_2 = _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[
            {"name": "Entity Authority", "relevance_score": 90, "mention_count": 2},
        ],
    )
    _add_entity_fact(
        db,
        audit=audit_1,
        entity_name="Entity Authority",
        entity_key="entity authority",
        relevance_score=88.0,
    )
    _add_entity_fact(
        db,
        audit=audit_2,
        entity_name="Entity Authority",
        entity_key="entity authority",
        relevance_score=90.0,
    )

    service = EntityAuthorityService()
    result = service.compute_score(db=db, project_id=project.id)
    db.commit()

    assert result.target_entity_count == 2
    assert result.detected_entity_count >= 1
    assert result.gap_count == 1
    assert result.coverage_score == 50.0
    assert result.depth_score > 0
    assert result.consistency_score > 0
    assert result.authority_score > 0

    gaps = service.compute_gaps(db=db, project_id=project.id)
    assert len(gaps) == 1
    assert gaps[0].entity_key == "knowledge graph"
    db.close()


def test_compute_trend_returns_ordered_snapshots() -> None:
    db = _setup_db()
    user, project = _seed_project(db, icp_roles=["entity authority"])
    _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[{"name": "Entity Authority", "relevance_score": 80}],
    )

    service = EntityAuthorityService()
    first = service.compute_score(db=db, project_id=project.id)
    db.commit()
    second = service.compute_score(db=db, project_id=project.id)
    db.commit()

    trend = service.compute_trend(db=db, project_id=project.id, limit=12)
    assert len(trend) == 2
    assert trend[0].computed_at <= trend[-1].computed_at
    assert trend[0].authority_score == first.authority_score
    assert trend[-1].authority_score == second.authority_score
    db.close()


def test_build_project_graph_includes_missing_target_nodes() -> None:
    db = _setup_db()
    user, project = _seed_project(db, icp_roles=["entity authority", "knowledge graph"])
    _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[{"name": "Entity Authority", "relevance_score": 92}],
    )

    service = EntityAuthorityService()
    payload = service.build_project_graph(db=db, project_id=project.id)

    assert payload["project_id"] == project.id
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["edges"], list)
    missing = payload["missing_target_entities"]
    assert any(item["entity_key"] == "knowledge graph" for item in missing)
    assert any(bool(node.get("is_missing_target")) for node in payload["nodes"])
    db.close()


def test_build_project_graph_uses_latest_audits_when_limited() -> None:
    db = _setup_db()
    user, project = _seed_project(db, icp_roles=[])
    base_time = datetime(2026, 3, 1, tzinfo=timezone.utc)

    _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[{"name": "Old Entity", "relevance_score": 40}],
        created_at=base_time,
    )
    _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[{"name": "Mid Entity", "relevance_score": 60}],
        created_at=base_time.replace(day=2),
    )
    _add_audit_with_entities(
        db,
        user_id=user.id,
        project_id=project.id,
        entities=[{"name": "New Entity", "relevance_score": 80}],
        created_at=base_time.replace(day=3),
    )

    service = EntityAuthorityService()
    payload = service.build_project_graph(db=db, project_id=project.id, max_audits=2)
    node_names = {str(node["name"]) for node in payload["nodes"]}

    assert payload["audit_count"] == 2
    assert "New Entity" in node_names
    assert "Mid Entity" in node_names
    assert "Old Entity" not in node_names
    db.close()
