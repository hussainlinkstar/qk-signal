import asyncio
import json
import logging
import signal
from datetime import datetime, timezone

from core.env_bootstrap import bootstrap_environment
from core.redis_client import get_async_redis_client
from sqlalchemy.orm import Session
from observability import configure_logging, init_tracing

bootstrap_environment()

import models
from core.config import settings
from database import SessionLocal
from job_models import PDFJobPayload, parse_pdf_job_payload
from services.s3_storage_service import get_storage_service
from services.pdf_reports.filenames import resolve_pdf_export_filename
from services.pdf_reports.assembler import resolve_effective_export_manifest
from services.pdf_reports.report_suite_service import (
    build_report_summary_text,
    render_report_pdf,
    should_generate_ai_summary,
)
from services.report_export_policy import first_unmet_report_export_requirement

logger = logging.getLogger("pdf_worker")

PDF_QUEUE_NAME = "pdf_jobs"
HEARTBEAT_INTERVAL_SECONDS = 15
MAX_PDF_RETRY_ATTEMPTS = 3
PDF_RETRY_BASE_DELAY_SECONDS = 5
PDF_RETRY_MAX_DELAY_SECONDS = 60
DELETED_USER_JOB_ERROR = "Report owner no longer exists."

active_jobs = set()
shutdown_requested = False


async def update_heartbeats():
    """Periodic task to update last_heartbeat for active jobs."""
    while not shutdown_requested:
        if active_jobs:
            db: Session = SessionLocal()
            try:
                db.query(models.ComplexReportJob).filter(
                    models.ComplexReportJob.id.in_(active_jobs)
                ).update({"last_heartbeat": datetime.now(timezone.utc)})
                db.commit()
            except Exception:
                logger.exception("Failed to update heartbeats")
            finally:
                db.close()
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def _mark_malformed_pdf_job_failed(payload: object, error: Exception) -> bool:
    if not isinstance(payload, dict):
        return False

    raw_job_id = payload.get("job_id") or payload.get("report_id")
    job_id = str(raw_job_id).strip() if raw_job_id is not None else ""
    if not job_id:
        return False

    db: Session = SessionLocal()
    try:
        job = db.query(models.ComplexReportJob).filter(models.ComplexReportJob.id == job_id).first()
        if not job:
            logger.error("Malformed PDF payload references unknown job %s", job_id)
            return False
        job.status = "failed"
        job.error = f"Invalid PDF job payload: {error}"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.error("Marked PDF job %s failed because its payload was invalid", job_id)
        return True
    except Exception:
        db.rollback()
        logger.exception("Failed to mark malformed PDF job %s as failed", job_id)
        return False
    finally:
        db.close()


async def process_pdf_job(job_payload: PDFJobPayload, payload_dict: dict, redis_client):
    job_id = job_payload.job_id
    active_jobs.add(job_id)
    logger.info(f"Starting PDF job: {job_id}")

    db: Session = SessionLocal()
    try:
        # Update job status to running
        job = db.query(models.ComplexReportJob).filter(models.ComplexReportJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in DB")
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.last_heartbeat = datetime.now(timezone.utc)
        db.commit()

        # Re-check the export entitlement at render time: the enqueue check is
        # stale once queued, and a downgraded plan must not produce the PDF.
        # Resolve the manifest exactly once so the policy and the renderer
        # evaluate the same manifest (empty stored manifests re-derive, e.g.
        # template_type="Comparative" must not bypass the gate).
        job_user = db.query(models.User).filter(models.User.id == job.user_id).first()
        if job_user is None:
            # The account was deleted after the job was queued. Fail terminally
            # here rather than letting the entitlement re-check decide: the plan
            # matrix resolves a missing user to the starter plan, which grants
            # has_pdf_audit_reports, so a standard report would still render
            # (SIGV2-1249).
            job.status = "failed"
            job.error = DELETED_USER_JOB_ERROR
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning(
                "PDF job %s failed: user no longer exists (user_id=%s)",
                job_id,
                job.user_id,
            )
            return

        resolved_export_manifest = resolve_effective_export_manifest(
            export_manifest=job.export_manifest or job_payload.export_manifest,
            options=job_payload.options,
            template_type=job_payload.template_type,
            branding_config=job_payload.branding_config,
        )
        unmet_requirement = first_unmet_report_export_requirement(
            job_user, resolved_export_manifest
        )
        if unmet_requirement is not None:
            # Permanent authorization failure: fail now, do not re-queue and
            # do not emit a degraded PDF.
            job.status = "failed"
            job.error = unmet_requirement.detail
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning(
                f"PDF job {job_id} failed entitlement re-check: " f"{unmet_requirement.feature_key}"
            )
            return

        # Gather audit data
        audits = (
            db.query(models.Audit)
            .filter(models.Audit.id.in_(job_payload.audit_ids))
            .order_by(models.Audit.created_at.asc())
            .all()
        )

        primary_audit = None
        if job_payload.primary_audit_id:
            primary_audit = (
                db.query(models.Audit)
                .filter(models.Audit.id == job_payload.primary_audit_id)
                .first()
            )

        competitor_audits = []
        if job_payload.competitor_audit_ids:
            competitor_audits = (
                db.query(models.Audit)
                .filter(models.Audit.id.in_(job_payload.competitor_audit_ids))
                .all()
            )

        option_payload = dict(job_payload.options)
        report_kind = (
            str(
                (job_payload.export_manifest or {}).get("report_kind")
                or option_payload.get("report_kind")
                or ""
            )
            .strip()
            .lower()
        )

        # 1. Build executive summary only for report kinds that actually render it.
        if should_generate_ai_summary(report_kind):
            summary = await build_report_summary_text(
                template_type=job_payload.template_type,
                audits=audits,
                language=job_payload.language,
            )

            if summary and audits:
                summary_target = primary_audit or audits[-1]
                existing_report = (
                    summary_target.full_report
                    if isinstance(summary_target.full_report, dict)
                    else {}
                )
                existing_analysis = (
                    existing_report.get("analysis")
                    if isinstance(existing_report.get("analysis"), dict)
                    else {}
                )
                summary_target.full_report = {
                    **existing_report,
                    "analysis": {
                        **existing_analysis,
                        "summary": summary,
                    },
                }

        # 2. Render PDF
        pdf_bytes = render_report_pdf(
            db=db,
            selected_audits=audits,
            template_type=job_payload.template_type,
            options=option_payload,
            branding_config=job_payload.branding_config,
            export_manifest=resolved_export_manifest,
            language=job_payload.language,
            primary_audit=primary_audit,
            competitor_audits=competitor_audits,
        )

        # 3. Save PDF
        reference_audit = primary_audit or (audits[0] if audits else None)
        project_name = (
            getattr(getattr(reference_audit, "project", None), "name", None)
            or getattr(reference_audit, "target_name", None)
            or getattr(reference_audit, "url", None)
            or "Project"
        )
        audit_type = (
            getattr(reference_audit, "audit_type", None) if reference_audit is not None else None
        )
        filename = resolve_pdf_export_filename(
            project_name=project_name,
            audit_type=audit_type,
            report_type=(option_payload.get("report_type") or job_payload.template_type),
            report_kind=report_kind or None,
            timestamp=datetime.now(timezone.utc),
        )
        gcs_service = get_storage_service()
        storage_uri = gcs_service.upload_file(
            prefix=settings.STORAGE_REPORTS_PREFIX,
            filename=filename,
            data=pdf_bytes,
            content_type="application/pdf",
            cache_control="private, max-age=0, no-store",
            metadata={
                "report_job_id": str(job_id),
                "user_id": str(job_payload.user_id),
            },
        )

        # 4. Finalize job. The artifact size is recorded here, from the bytes
        # actually uploaded, so the library's Size column never has to stat
        # every stored object on a list call.
        job.status = "succeeded"
        job.file_path = storage_uri
        job.file_size_bytes = len(pdf_bytes)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Successfully completed PDF job: {job_id}")

    except Exception as e:
        logger.exception(f"Error processing PDF job {job_id}")
        try:
            db.rollback()
            job = (
                db.query(models.ComplexReportJob)
                .filter(models.ComplexReportJob.id == job_id)
                .first()
            )
            if job:
                job.attempt_count = (job.attempt_count or 0) + 1
                max_attempts = job.max_attempts or MAX_PDF_RETRY_ATTEMPTS

                if job.attempt_count < max_attempts:
                    # Transient failure, re-queue for retry
                    job.status = "queued"
                    job.error = str(e)
                    job.started_at = None
                    db.commit()
                    delay = min(
                        PDF_RETRY_BASE_DELAY_SECONDS * (2 ** (job.attempt_count - 1)),
                        PDF_RETRY_MAX_DELAY_SECONDS,
                    )
                    logger.warning(
                        f"PDF job {job_id} failed (attempt {job.attempt_count}/{max_attempts}). "
                        f"Re-queuing after {delay}s delay."
                    )
                    await asyncio.sleep(delay)
                    await redis_client.lpush(PDF_QUEUE_NAME, json.dumps(payload_dict))
                else:
                    # Permanent failure, max attempts exceeded
                    job.status = "failed"
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.error(
                        f"PDF job {job_id} permanently failed after {job.attempt_count} attempts."
                    )
        except Exception:
            logger.exception(
                f"PDF job {job_id}: failed to update retry/dead-letter state, "
                "job may need manual recovery"
            )
    finally:
        active_jobs.discard(job_id)
        db.close()


async def worker_loop():
    global shutdown_requested
    client = get_async_redis_client()
    logger.info(f"PDF Worker connected to Redis. Watching queue: {PDF_QUEUE_NAME}")

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(update_heartbeats())

    while not shutdown_requested:
        try:
            # BLPOP waits for a message
            result = await client.blpop(PDF_QUEUE_NAME, timeout=5)
            if not result:
                continue

            _, message = result
            payload_dict = json.loads(message)
            try:
                job_payload = parse_pdf_job_payload(payload_dict)
            except (TypeError, ValueError) as exc:
                logger.error("Invalid PDF job payload: %s", exc)
                _mark_malformed_pdf_job_failed(payload_dict, exc)
                continue

            # Process job
            await process_pdf_job(job_payload, payload_dict, client)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in PDF worker loop")
            await asyncio.sleep(5)

    shutdown_requested = True
    heartbeat_task.cancel()
    await client.aclose()


def handle_exit():
    global shutdown_requested
    logger.info("Shutdown signal received...")
    shutdown_requested = True


if __name__ == "__main__":
    configure_logging()
    init_tracing("pdf-worker")
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_exit)

    try:
        loop.run_until_complete(worker_loop())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
