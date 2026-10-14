from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from main import app, get_current_user, get_db
from middleware import maintenance as maintenance_module


def test_audit_response_exposes_aio_rollup_in_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="aio@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit = models.Audit(
        user_id=user.id,
        url="https://aio.example.com/",
        geo_score=60,
        seo_score=70,
        aeo_score=40,
        full_report={
            "analysis": {
                "seo_score": 70,
                "geo_score": 60,
                "aeo_score": 40,
                "summary": "rollup target",
            },
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    original_get_maintenance_state = maintenance_module._get_maintenance_state
    maintenance_module._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }

    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/audits/{audit.id}")

        assert response.status_code == 200
        payload = response.json()
        aio = payload["full_report"]["metadata"]["aio"]
        assert aio["aio_score"] == 50
        assert aio["scope"] == "website_and_brand"
    finally:
        maintenance_module._get_maintenance_state = original_get_maintenance_state
        app.dependency_overrides.clear()
        db.close()
