"""Audit data retention and archival service (AEX-24).

Tiered lifecycle:
  Hot   (0-30 days) , full_report in PostgreSQL, screenshots live.
  Warm  (30-90 days), screenshots redacted (sanitized_at set).
  Cold  (90-365 days), full_report archived to object storage; DB retains
                        scores, metadata, and report_archive_uri.
  Purge (365+ days) , archived object deleted; DB retains scores and
                        summary metadata only.

Pinned audits (is_pinned=True) are exempt from all archival tiers.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from services.s3_storage_service import get_storage_service

logger = logging.getLogger(__name__)

# ── Configurable thresholds (days) ────────────────────────────────────────────

WARM_THRESHOLD_DAYS = 30
COLD_THRESHOLD_DAYS = 90
PURGE_THRESHOLD_DAYS = 365

# GCS prefix for archived audit reports
ARCHIVE_PREFIX = "audit-archives"

# Batch size for each sweep pass to limit memory and lock contention
SWEEP_BATCH_SIZE = 200


# ── Screenshot redaction (warm tier) ─────────────────────────────────────────


def redact_screenshots(
    db: Session, *, now: datetime | None = None, batch_size: int = SWEEP_BATCH_SIZE
) -> int:
    """Redact screenshot data from audits older than WARM_THRESHOLD_DAYS.

    Sets ``sanitized_at`` to prevent repeat processing.
    Returns the count of audits processed.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WARM_THRESHOLD_DAYS)

    audits = (
        db.query(models.Audit)
        .filter(
            models.Audit.created_at < cutoff,
            models.Audit.sanitized_at.is_(None),
            models.Audit.is_pinned.is_(False),
            models.Audit.full_report.isnot(None),
        )
        .order_by(models.Audit.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    redacted = 0
    for audit in audits:
        try:
            report = audit.full_report
            if not isinstance(report, dict):
                audit.sanitized_at = now
                redacted += 1
                continue

            changed = _strip_screenshot_fields(report)
            if changed:
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(audit, "full_report")
            audit.sanitized_at = now
            redacted += 1
        except Exception:
            logger.exception("Failed to redact screenshots for audit_id=%s", audit.id)
    return redacted


def _strip_screenshot_fields(report: dict) -> bool:
    """Remove screenshot_url / screenshot_data / screenshots from report.

    Walks the dict tree and strips known screenshot keys.  Returns True if
    anything was removed.
    """
    removed = False
    screenshot_keys = {"screenshot_url", "screenshot_data", "screenshots", "screenshot"}

    keys_to_remove = [k for k in report if k in screenshot_keys]
    for k in keys_to_remove:
        del report[k]
        removed = True

    for value in report.values():
        if isinstance(value, dict):
            if _strip_screenshot_fields(value):
                removed = True
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    if _strip_screenshot_fields(item):
                        removed = True
    return removed


# ── Report archival (cold tier) ──────────────────────────────────────────────


def archive_reports(
    db: Session, *, now: datetime | None = None, batch_size: int = SWEEP_BATCH_SIZE
) -> int:
    """Archive full_report JSON to object storage for audits older than
    COLD_THRESHOLD_DAYS.

    Compresses the report with gzip and uploads via S3StorageService.
    Sets ``report_archive_uri``, ``report_archived_at``, and NULLs
    ``full_report`` to reclaim DB storage.

    Returns the count of audits archived.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=COLD_THRESHOLD_DAYS)

    audits = (
        db.query(models.Audit)
        .filter(
            models.Audit.created_at < cutoff,
            models.Audit.full_report.isnot(None),
            models.Audit.report_archive_uri.is_(None),
            models.Audit.is_pinned.is_(False),
        )
        .order_by(models.Audit.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    gcs = get_storage_service()
    archived = 0
    for audit in audits:
        try:
            report = audit.full_report
            if report is None:
                continue

            json_bytes = json.dumps(report, default=str).encode("utf-8")
            compressed = gzip.compress(json_bytes, compresslevel=6)

            filename = f"audit_{audit.id}.json.gz"
            storage_uri = gcs.upload_file(
                prefix=ARCHIVE_PREFIX,
                filename=filename,
                data=compressed,
                content_type="application/gzip",
                metadata={
                    "audit_id": str(audit.id),
                    "user_id": str(audit.user_id),
                    "original_size": str(len(json_bytes)),
                    "created_at": audit.created_at.isoformat() if audit.created_at else "",
                },
            )

            audit.report_archive_uri = storage_uri
            audit.report_archived_at = now
            audit.full_report = None
            archived += 1
        except Exception:
            logger.exception("Failed to archive report for audit_id=%s", audit.id)
    return archived


# ── Report purge (purge tier) ────────────────────────────────────────────────


def purge_archived_reports(
    db: Session, *, now: datetime | None = None, batch_size: int = SWEEP_BATCH_SIZE
) -> int:
    """Delete archived report objects from storage for audits older than
    PURGE_THRESHOLD_DAYS.

    Clears ``report_archive_uri`` so the audit row only retains scores
    and summary metadata.

    Returns the count of audits purged.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=PURGE_THRESHOLD_DAYS)

    audits = (
        db.query(models.Audit)
        .filter(
            models.Audit.created_at < cutoff,
            models.Audit.report_archive_uri.isnot(None),
            models.Audit.is_pinned.is_(False),
        )
        .order_by(models.Audit.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    gcs = get_storage_service()
    purged = 0
    for audit in audits:
        try:
            uri = audit.report_archive_uri
            if uri:
                gcs.delete_file(storage_uri=uri)
            audit.report_archive_uri = None
            purged += 1
        except Exception:
            logger.exception("Failed to purge archived report for audit_id=%s", audit.id)
    return purged


# ── On-demand retrieval ──────────────────────────────────────────────────────


def restore_archived_report(db: Session, audit: models.Audit) -> dict[str, Any] | None:
    """Fetch an archived full_report from object storage, decompress it, and
    return the JSON dict.

    Does NOT write back to the DB, the report stays archived, but we serve
    the content temporarily.  The caller can decide to cache it.
    """
    uri = audit.report_archive_uri
    if not uri:
        return None

    gcs = get_storage_service()
    data = gcs.download_file(storage_uri=uri)
    if data is None:
        logger.warning("Archive file not found for audit_id=%s uri=%s", audit.id, uri)
        return None

    try:
        decompressed = gzip.decompress(data)
        return json.loads(decompressed)
    except Exception:
        logger.exception("Failed to decompress/parse archived report for audit_id=%s", audit.id)
        return None


# ── Pin / unpin ──────────────────────────────────────────────────────────────


def pin_audit(db: Session, audit_id: int, user_id: int) -> bool:
    """Pin an audit to exempt it from archival.  Returns True on success."""
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == audit_id, models.Audit.user_id == user_id)
        .first()
    )
    if not audit:
        return False
    audit.is_pinned = True
    return True


def unpin_audit(db: Session, audit_id: int, user_id: int) -> bool:
    """Unpin an audit, allowing normal archival.  Returns True on success."""
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == audit_id, models.Audit.user_id == user_id)
        .first()
    )
    if not audit:
        return False
    audit.is_pinned = False
    return True


# ── Full retention sweep (called from cron_sweeper) ──────────────────────────


def run_retention_sweep(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Execute all retention tiers in order: redact → archive → purge.

    Returns a summary dict with counts per tier.
    """
    now = now or datetime.now(timezone.utc)

    redacted = redact_screenshots(db, now=now)
    archived = archive_reports(db, now=now)
    purged = purge_archived_reports(db, now=now)

    return {
        "screenshots_redacted": redacted,
        "reports_archived": archived,
        "reports_purged": purged,
    }
