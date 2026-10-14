"""Tests for PDF worker retry logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from job_models import PDFJobPayload


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = testing_session_local()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def user(db_session):
    user = models.User(
        email="pdf-test@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def job_payload():
    return PDFJobPayload(
        job_id="test-pdf-job-1",
        user_id=1,
        template_type="Technical",
        audit_ids=[1],
        options={},
        branding_config={},
    )


@pytest.fixture()
def payload_dict(job_payload):
    return job_payload.to_dict()


@pytest.fixture()
def mock_redis():
    client = AsyncMock()
    client.lpush = AsyncMock()
    return client


def _create_report_job(db_session, user, job_id="test-pdf-job-1", attempt_count=0, max_attempts=3):
    job = models.ComplexReportJob(
        id=job_id,
        user_id=user.id,
        status="queued",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_malformed_legacy_payload_marks_identifiable_job_failed(db_session, user):
    job = _create_report_job(db_session, user, job_id="legacy-report-id")
    payload = {
        "report_id": job.id,
        "user_id": user.id,
        "template_type": "Technical",
        "audit_ids": [1],
        "source": "external_api",
    }

    with patch("pdf_worker.SessionLocal", return_value=db_session):
        from pdf_worker import _mark_malformed_pdf_job_failed

        _mark_malformed_pdf_job_failed(
            payload,
            ValueError("PDF Payload missing required fields: job_id"),
        )

    failed_job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "legacy-report-id")
        .one()
    )
    assert failed_job.status == "failed"
    assert (
        failed_job.error == "Invalid PDF job payload: PDF Payload missing required fields: job_id"
    )
    assert failed_job.completed_at is not None


@pytest.mark.asyncio
async def test_transient_failure_requeues_job(
    db_session, user, job_payload, payload_dict, mock_redis
):
    """On transient failure, the job should be re-queued with incremented attempt_count."""
    _create_report_job(db_session, user, job_id=job_payload.job_id, attempt_count=0, max_attempts=3)

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("transient error")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(job_payload, payload_dict, mock_redis)

    job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == job_payload.job_id)
        .first()
    )

    assert job is not None
    assert job.status == "queued"
    assert job.attempt_count == 1
    assert job.error == "transient error"
    assert job.started_at is None

    mock_redis.lpush.assert_awaited_once()
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == "pdf_jobs"
    requeued_payload = json.loads(call_args[0][1])
    assert requeued_payload["job_id"] == job_payload.job_id

    mock_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_permanent_failure_after_max_attempts(
    db_session, user, job_payload, payload_dict, mock_redis
):
    """After max attempts are exhausted, the job should be permanently failed."""
    _create_report_job(db_session, user, job_id=job_payload.job_id, attempt_count=2, max_attempts=3)

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.asyncio.sleep", new_callable=AsyncMock),
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("permanent error")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(job_payload, payload_dict, mock_redis)

    job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == job_payload.job_id)
        .first()
    )

    assert job is not None
    assert job.status == "failed"
    assert job.attempt_count == 3
    assert job.error == "permanent error"
    assert job.completed_at is not None

    mock_redis.lpush.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_job_not_retried(db_session, user, job_payload, payload_dict, mock_redis):
    """A successful job should complete normally without triggering retry logic."""
    _create_report_job(db_session, user, job_id=job_payload.job_id, attempt_count=0, max_attempts=3)

    mock_audit = MagicMock()
    mock_audit.id = 1
    mock_audit.created_at = datetime.now(timezone.utc)
    mock_audit.full_report = {}
    mock_audit.project = None
    mock_audit.target_name = "Test"
    mock_audit.url = "https://example.com"
    mock_audit.audit_type = "geo"

    mock_gcs = MagicMock()
    mock_gcs.upload_file = MagicMock(return_value="gs://bucket/report.pdf")

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
        patch("pdf_worker.render_report_pdf", return_value=b"%PDF-fake"),
        patch("pdf_worker.get_storage_service", return_value=mock_gcs),
        patch("pdf_worker.resolve_pdf_export_filename", return_value="report.pdf"),
        patch("pdf_worker.settings") as mock_settings,
        patch.object(
            db_session.query(models.Audit).filter(models.Audit.id.in_([1])),
            "order_by",
            return_value=MagicMock(all=MagicMock(return_value=[mock_audit])),
        ),
    ):
        mock_settings.STORAGE_REPORTS_PREFIX = "reports"

        # We need to patch the db.query to return our mock audit
        original_query = db_session.query

        def patched_query(model):
            result = original_query(model)
            if model is models.Audit:
                mock_q = MagicMock()
                mock_q.filter.return_value = mock_q
                mock_q.order_by.return_value = mock_q
                mock_q.all.return_value = [mock_audit]
                mock_q.first.return_value = mock_audit
                return mock_q
            return result

        with patch.object(db_session, "query", side_effect=patched_query):
            from pdf_worker import process_pdf_job

            await process_pdf_job(job_payload, payload_dict, mock_redis)

    job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == job_payload.job_id)
        .first()
    )

    assert job is not None
    assert job.status == "succeeded"
    assert job.file_path == "gs://bucket/report.pdf"
    assert job.completed_at is not None
    assert job.attempt_count == 0

    mock_redis.lpush.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_exponential_backoff_delay(
    db_session, user, job_payload, payload_dict, mock_redis
):
    """Verify exponential backoff: attempt 2 should wait longer than attempt 1."""
    _create_report_job(db_session, user, job_id=job_payload.job_id, attempt_count=1, max_attempts=3)

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("retry error")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job, PDF_RETRY_BASE_DELAY_SECONDS

        await process_pdf_job(job_payload, payload_dict, mock_redis)

    # attempt_count is now 2 (was 1, incremented to 2). delay = base * 2^(attempt-1) = 5 * 2^1 = 10
    expected_delay = PDF_RETRY_BASE_DELAY_SECONDS * (2**1)
    mock_sleep.assert_awaited_once_with(expected_delay)

    job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == job_payload.job_id)
        .first()
    )
    assert job.status == "queued"
    assert job.attempt_count == 2
    mock_redis.lpush.assert_awaited_once()


@pytest.mark.asyncio
async def test_backoff_delay_is_capped(db_session, user, mock_redis):
    """Verify the backoff delay never exceeds PDF_RETRY_MAX_DELAY_SECONDS."""
    payload = PDFJobPayload(
        job_id="cap-test-job",
        user_id=user.id,
        template_type="Technical",
        audit_ids=[1],
        options={},
        branding_config={},
    )
    payload_dict = payload.to_dict()
    # High attempt_count to make raw backoff exceed the cap
    _create_report_job(db_session, user, job_id="cap-test-job", attempt_count=8, max_attempts=20)

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("cap error")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job, PDF_RETRY_MAX_DELAY_SECONDS

        await process_pdf_job(payload, payload_dict, mock_redis)

    actual_delay = mock_sleep.call_args[0][0]
    assert actual_delay <= PDF_RETRY_MAX_DELAY_SECONDS
    assert actual_delay == PDF_RETRY_MAX_DELAY_SECONDS  # 5 * 2^8 = 1280 > 60


@pytest.mark.asyncio
async def test_double_fault_logs_and_does_not_crash(
    db_session, user, job_payload, payload_dict, mock_redis
):
    """If the DB fails during retry handling, the worker should log and not crash."""
    _create_report_job(db_session, user, job_id=job_payload.job_id, attempt_count=0, max_attempts=3)

    def _fail_on_requery(*args, **kwargs):
        raise RuntimeError("DB connection lost")

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("initial error")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        # After the initial error, the handler does db.rollback() then re-queries.
        # We make the re-query fail to simulate a double fault.
        original_query = db_session.query

        call_count = {"n": 0}

        def _patched_query(model):
            call_count["n"] += 1
            # Let the first queries (status=running, etc.) succeed,
            # then fail on the re-query inside the except block
            if call_count["n"] > 2 and model is models.ComplexReportJob:
                raise RuntimeError("DB connection lost")
            return original_query(model)

        with (
            patch.object(db_session, "query", side_effect=_patched_query),
            patch.object(db_session, "rollback"),
        ):
            from pdf_worker import process_pdf_job

            # Should NOT raise — the double fault is caught internally
            await process_pdf_job(job_payload, payload_dict, mock_redis)
