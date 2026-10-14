from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from admin import (
    ReportRetentionUpdateRequest,
    get_operations_status,
    update_report_retention_days,
)
from database import Base


def test_admin_can_update_report_retention_days() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    admin_user = models.User(
        email="admin-retention@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    try:
        initial = get_operations_status(admin_user, db)
        assert initial["report_retention_days"] in {30, 60, 90}

        updated = update_report_retention_days(
            request=ReportRetentionUpdateRequest(days=60),
            admin_user=admin_user,
            db=db,
        )
        assert updated["report_retention_days"] == 60

        with pytest.raises(HTTPException) as exc:
            update_report_retention_days(
                request=ReportRetentionUpdateRequest(days=45),
                admin_user=admin_user,
                db=db,
            )
        assert exc.value.status_code == 422
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
