from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

import models
from core.redis_client import get_sync_redis
from database import SessionLocal
from services.external_api_service import EXTERNAL_JOB_SOURCE, map_external_job_status

EXTERNAL_WEBHOOK_QUEUE_NAME = os.getenv("EXTERNAL_WEBHOOK_QUEUE_NAME", "external:webhook_jobs")
EXTERNAL_WEBHOOK_MAX_ATTEMPTS = int(os.getenv("EXTERNAL_WEBHOOK_MAX_ATTEMPTS", "3"))


def build_webhook_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_external_report_url(job_id: str) -> str:
    return f"/api/v1/external/audit/{job_id}/report"


def build_webhook_payload(
    *,
    audit_job: models.AuditJob,
    audit: models.Audit | None,
) -> dict[str, Any]:
    scores = None
    report = None
    if audit is not None:
        scores = {
            "geo": audit.geo_score,
            "seo": audit.seo_score,
            "aeo": audit.aeo_score,
        }
        report = audit.full_report

    return {
        "job_id": audit_job.id,
        "status": map_external_job_status(audit_job.status),
        "url": audit_job.url,
        "provider": audit_job.provider,
        "tier": audit_job.tier,
        "project_id": audit_job.project_id,
        "request_id": audit_job.request_id,
        "estimated_credit_cost": audit_job.estimated_credit_cost,
        "credit_cost": audit_job.consumed_credit_cost,
        "created_at": audit_job.created_at.isoformat() if audit_job.created_at else None,
        "completed_at": audit_job.completed_at.isoformat() if audit_job.completed_at else None,
        "error": audit_job.error,
        "scores": scores,
        "report": report,
        "report_url": _build_external_report_url(audit_job.id),
    }


async def enqueue_external_webhook(job_id: str) -> None:
    with get_sync_redis() as redis_client:
        redis_client.rpush(EXTERNAL_WEBHOOK_QUEUE_NAME, job_id)


def _load_audit_for_job(db: Session, audit_job: models.AuditJob) -> models.Audit | None:
    if not audit_job.request_id:
        return None
    return (
        db.query(models.Audit)
        .filter(
            models.Audit.user_id == audit_job.user_id,
            models.Audit.request_id == audit_job.request_id,
        )
        .order_by(models.Audit.created_at.desc())
        .first()
    )


async def deliver_external_webhook_for_job(
    db: Session,
    *,
    job_id: str,
) -> bool:
    audit_job = db.query(models.AuditJob).filter(models.AuditJob.id == job_id).first()
    if audit_job is None:
        return True
    if audit_job.source != EXTERNAL_JOB_SOURCE or not audit_job.webhook_url:
        return True
    if audit_job.webhook_delivered_at is not None:
        return True

    audit = _load_audit_for_job(db, audit_job)
    payload = build_webhook_payload(audit_job=audit_job, audit=audit)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Qiko-Signal-Event": "audit.completed"
        if map_external_job_status(audit_job.status) == "completed"
        else "audit.failed",
        "X-Qiko-Signal-Delivery": audit_job.id,
    }
    if audit_job.webhook_secret:
        headers["X-Qiko-Signal-Signature"] = build_webhook_signature(audit_job.webhook_secret, body)

    audit_job.webhook_attempts = int(audit_job.webhook_attempts or 0) + 1
    audit_job.webhook_status = "delivering"
    db.add(audit_job)
    db.commit()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(audit_job.webhook_url, content=body, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        audit_job.webhook_status = (
            "retrying" if audit_job.webhook_attempts < EXTERNAL_WEBHOOK_MAX_ATTEMPTS else "failed"
        )
        audit_job.webhook_last_error = str(exc)
        db.add(audit_job)
        db.commit()
        return False

    audit_job.webhook_status = "delivered"
    audit_job.webhook_last_error = None
    audit_job.webhook_delivered_at = datetime.now(timezone.utc)
    db.add(audit_job)
    db.commit()
    return True


def _retry_delay_seconds(attempts: int) -> int:
    return min(60, 5 * (2 ** max(0, attempts - 1)))


async def process_external_webhook_job(job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        delivered = await deliver_external_webhook_for_job(db, job_id=job_id)
        if delivered:
            return

        audit_job = db.query(models.AuditJob).filter(models.AuditJob.id == job_id).first()
        if audit_job is None:
            return
        if int(audit_job.webhook_attempts or 0) >= EXTERNAL_WEBHOOK_MAX_ATTEMPTS:
            return

        await asyncio.sleep(_retry_delay_seconds(int(audit_job.webhook_attempts or 1)))
        await enqueue_external_webhook(job_id)
    finally:
        db.close()
