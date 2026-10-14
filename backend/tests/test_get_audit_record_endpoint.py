from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from routers.api_router import get_audit_record


def test_get_audit_record_returns_completed_audit_with_full_report() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="record@example.com",
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
        url="https://example.com/",
        geo_score=74,
        seo_score=88,
        aeo_score=69,
        full_report={
            "schema_version": "2.0",
            "site": {"url": "https://example.com/"},
            "scores": {"seo": 88, "geo": 74, "aeo": 69, "overall": 77},
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    payload = get_audit_record(audit_id=audit.id, user=user, db=db)
    assert payload["id"] == audit.id
    assert payload["status"] == "completed"
    assert payload["geo_score"] == 74
    assert payload["seo_score"] == 88
    assert payload["aeo_score"] == 69
    assert payload["full_report"]["site"]["url"] == "https://example.com/"
    db.close()
