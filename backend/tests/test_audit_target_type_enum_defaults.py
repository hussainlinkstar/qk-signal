from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base


def _build_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_audit_table_server_default_uses_enum_name() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        user = models.User(
            email="audit-default@example.com",
            hashed_password="hashed-password",
            role="user",
            auth_provider="local",
            provider_subject="audit-default-subject",
            external_id="audit-default-external",
        )
        db.add(user)
        db.flush()

        db.execute(
            text(
                """
                INSERT INTO audits (
                    user_id,
                    "type",
                    url,
                    geo_score,
                    seo_score,
                    aeo_score,
                    full_report
                ) VALUES (
                    :user_id,
                    :audit_type,
                    :url,
                    :geo_score,
                    :seo_score,
                    :aeo_score,
                    :full_report
                )
                """
            ),
            {
                "user_id": user.id,
                "audit_type": "FAST",
                "url": "https://example.com",
                "geo_score": 0.0,
                "seo_score": 0.0,
                "aeo_score": 0.0,
                "full_report": "{}",
            },
        )
        db.commit()

        audit = db.query(models.Audit).first()
        assert audit is not None
        assert audit.audit_target_type == models.AuditTargetType.WEBSITE
    finally:
        db.close()


def test_audit_job_table_server_default_uses_enum_name() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        user = models.User(
            email="job-default@example.com",
            hashed_password="hashed-password",
            role="user",
            auth_provider="local",
            provider_subject="job-default-subject",
            external_id="job-default-external",
        )
        db.add(user)
        db.flush()

        db.execute(
            text(
                """
                INSERT INTO audit_jobs (
                    id,
                    user_id,
                    status,
                    url
                ) VALUES (
                    :id,
                    :user_id,
                    :status,
                    :url
                )
                """
            ),
            {
                "id": "job-default-1",
                "user_id": user.id,
                "status": "queued",
                "url": "https://example.com",
            },
        )
        db.commit()

        audit_job = db.query(models.AuditJob).first()
        assert audit_job is not None
        assert audit_job.audit_target_type == models.AuditTargetType.WEBSITE
    finally:
        db.close()
