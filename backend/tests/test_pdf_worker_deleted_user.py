"""PDF worker behaviour when the job's user no longer exists.

SIGV2-1249: a job sits in the queue after its owner is deleted, so the worker
loads ``job_user = None`` and passed it straight into the entitlement re-check.
``PlanValidator.resolve_subscription_plan(None)`` falls back to the starter
plan, which grants ``has_pdf_audit_reports``, so a standard report for a
deleted account rendered and uploaded. The job must fail terminally instead,
with the same shape as the other terminal failures, and the worker must keep
draining the queue.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from job_models import PDFJobPayload

DELETED_USER_ID = 987654


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
def mock_redis():
    client = AsyncMock()
    client.lpush = AsyncMock()
    return client


def _orphan_job(db_session, job_id="orphan-pdf-job"):
    """A queued job whose owner row is gone, as after an account deletion."""
    job = models.ComplexReportJob(
        id=job_id,
        user_id=DELETED_USER_ID,
        status="queued",
        attempt_count=0,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _payload(job_id="orphan-pdf-job", template_type="Technical"):
    return PDFJobPayload(
        job_id=job_id,
        user_id=DELETED_USER_ID,
        template_type=template_type,
        audit_ids=[1],
        options={},
        branding_config={},
    )


@pytest.mark.asyncio
async def test_deleted_user_job_fails_terminally_without_rendering(db_session, mock_redis):
    _orphan_job(db_session)
    payload = _payload()

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.render_report_pdf") as mock_render,
        patch("pdf_worker.get_storage_service") as mock_storage,
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), mock_redis)

    job = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "orphan-pdf-job")
        .one()
    )
    from pdf_worker import DELETED_USER_JOB_ERROR

    assert job.status == "failed"
    assert job.error == DELETED_USER_JOB_ERROR
    assert job.completed_at is not None
    assert job.attempt_count == 0

    mock_render.assert_not_called()
    mock_storage.assert_not_called()
    mock_redis.lpush.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_user_job_does_not_reach_the_entitlement_check(db_session, mock_redis):
    """The None user must be rejected before the plan matrix sees it.

    ``has_feature(None, "has_pdf_audit_reports")`` returns True, so relying on
    the entitlement re-check is exactly the hole this closes.
    """
    _orphan_job(db_session)
    payload = _payload()

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.first_unmet_report_export_requirement") as mock_requirement,
        patch("pdf_worker.render_report_pdf"),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), mock_redis)

    mock_requirement.assert_not_called()


@pytest.mark.asyncio
async def test_deleted_user_job_is_logged_with_its_job_id(db_session, mock_redis, caplog):
    _orphan_job(db_session)
    payload = _payload()

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.render_report_pdf"),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
        caplog.at_level("WARNING", logger="pdf_worker"),
    ):
        from pdf_worker import process_pdf_job

        await process_pdf_job(payload, payload.to_dict(), mock_redis)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "orphan-pdf-job" in message and "user no longer exists" in message for message in messages
    )


@pytest.mark.asyncio
async def test_worker_keeps_draining_the_queue_after_a_deleted_user_job(db_session, mock_redis):
    """One orphaned job must not stop the worker: the next job still runs."""
    _orphan_job(db_session, job_id="orphan-first")

    live_user = models.User(
        email="pdf-still-here@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db_session.add(live_user)
    db_session.flush()
    live_user_id = live_user.id
    live_job = models.ComplexReportJob(
        id="live-second",
        user_id=live_user_id,
        status="queued",
        attempt_count=0,
        max_attempts=3,
    )
    db_session.add(live_job)
    db_session.commit()

    with (
        patch("pdf_worker.SessionLocal", return_value=db_session),
        patch("pdf_worker.render_report_pdf", side_effect=RuntimeError("render stopped here")),
        patch("pdf_worker.should_generate_ai_summary", return_value=False),
        patch("pdf_worker.asyncio.sleep", new_callable=AsyncMock),
    ):
        from pdf_worker import process_pdf_job

        orphan_payload = _payload(job_id="orphan-first")
        await process_pdf_job(orphan_payload, orphan_payload.to_dict(), mock_redis)

        live_payload = PDFJobPayload(
            job_id="live-second",
            user_id=live_user_id,
            template_type="Technical",
            audit_ids=[1],
            options={},
            branding_config={},
        )
        await process_pdf_job(live_payload, live_payload.to_dict(), mock_redis)

    orphan = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "orphan-first")
        .one()
    )
    second = (
        db_session.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "live-second")
        .one()
    )

    assert orphan.status == "failed"
    # The second job was picked up and processed: its render attempt failed, so
    # the retry path re-queued it (which clears started_at again).
    assert second.status == "queued"
    assert second.attempt_count == 1
    assert second.error == "render stopped here"
    mock_redis.lpush.assert_awaited_once()
