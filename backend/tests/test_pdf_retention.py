from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from cron_sweeper import _cleanup_expired_report_jobs
from database import Base
from services.s3_storage_service import S3StorageService


def _seed_report_jobs(db: Session, old_file: Path, fresh_file: Path) -> tuple[str, str]:
    user = models.User(
        email="retention-user@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()

    now = datetime.now(timezone.utc)
    old_job_id = "report-old"
    fresh_job_id = "report-fresh"
    db.add(
        models.ComplexReportJob(
            id=old_job_id,
            user_id=user.id,
            status="succeeded",
            file_path=str(old_file),
            created_at=now - timedelta(days=40),
            completed_at=now - timedelta(days=40),
        )
    )
    db.add(
        models.ComplexReportJob(
            id=fresh_job_id,
            user_id=user.id,
            status="succeeded",
            file_path=str(fresh_file),
            created_at=now - timedelta(days=5),
            completed_at=now - timedelta(days=5),
        )
    )
    db.commit()
    return old_job_id, fresh_job_id


def test_cleanup_expired_report_jobs_marks_old_jobs_expired(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()

    # Report files must live inside the storage root; deletions outside it are
    # blocked by the path-traversal guard in S3StorageService._safe_local_path.
    storage_root = tmp_path / "generated_storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    old_file = storage_root / "complex-report-old.pdf"
    fresh_file = storage_root / "complex-report-fresh.pdf"
    old_file.write_bytes(b"old-pdf")
    fresh_file.write_bytes(b"fresh-pdf")

    old_job_id, fresh_job_id = _seed_report_jobs(db, old_file, fresh_file)

    storage_service = S3StorageService(bucket_name="", local_storage_root=storage_root)
    monkeypatch.setattr("cron_sweeper.get_storage_service", lambda: storage_service)
    monkeypatch.setattr("cron_sweeper.get_report_retention_days", lambda _db: 30)

    expired_jobs, deleted_files = _cleanup_expired_report_jobs(
        db,
        now=datetime.now(timezone.utc),
    )
    db.commit()

    old_job = (
        db.query(models.ComplexReportJob).filter(models.ComplexReportJob.id == old_job_id).first()
    )
    fresh_job = (
        db.query(models.ComplexReportJob).filter(models.ComplexReportJob.id == fresh_job_id).first()
    )

    assert expired_jobs == 1
    assert deleted_files >= 1
    assert old_job is not None and old_job.status == "expired"
    assert fresh_job is not None and fresh_job.status == "succeeded"
    assert old_file.exists() is False
    assert fresh_file.exists() is True

    db.close()
    Base.metadata.drop_all(bind=engine)
