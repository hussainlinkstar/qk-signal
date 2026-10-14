from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models
from core.config import settings
from app.config.plans import can_use_feature, resolve_plan_alias
from services.cms_adapters import get_cms_adapter
from services.cms_adapters.base_adapter import (
    CMSChangePreview,
    CMSPushResult,
    validate_supported_field,
)
from services.cms_ai_service import _normalize_markdown_body

SUPPORTED_CMS_TYPES = {"wordpress", "shopify"}
CMS_CONFIRMATION_TOKEN_TTL_SECONDS = 300


@dataclass(frozen=True)
class CMSPreviewResult:
    preview: CMSChangePreview
    confirmation_token: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_cms_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SUPPORTED_CMS_TYPES:
        supported = ", ".join(sorted(SUPPORTED_CMS_TYPES))
        raise ValueError(f"Unsupported CMS type '{value}'. Supported: {supported}.")
    return normalized


def normalize_site_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or parsed.scheme not in {"http", "https"}:
        raise ValueError("Site URL must include http:// or https://.")
    if not parsed.netloc:
        raise ValueError("Site URL must include a valid host.")
    return normalized


def serialize_credentials(credentials: dict[str, Any]) -> str:
    if not isinstance(credentials, dict) or not credentials:
        raise ValueError("Credentials payload is required.")
    normalized: dict[str, str] = {}
    for key, value in credentials.items():
        key_str = str(key or "").strip()
        if not key_str:
            continue
        value_str = str(value or "").strip()
        if not value_str:
            continue
        normalized[key_str] = value_str
    if not normalized:
        raise ValueError("Credentials payload must include at least one non-empty value.")
    return json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def deserialize_credentials(raw_credentials: str | None) -> dict[str, str]:
    if not raw_credentials:
        return {}
    try:
        payload = json.loads(raw_credentials)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value is not None}


def redact_credentials(raw_credentials: str | None) -> dict[str, str]:
    credentials = deserialize_credentials(raw_credentials)
    redacted: dict[str, str] = {}
    for key, value in credentials.items():
        if not value:
            redacted[key] = ""
            continue
        tail = value[-4:] if len(value) >= 4 else value
        redacted[key] = f"***{tail}"
    return redacted


def resolve_user_plan(user: models.User) -> str:
    if user.subscription is None:
        return resolve_plan_alias(user.trial_plan) or "plan_starter"
    if str(user.subscription.status or "").strip().lower() != "active":
        return resolve_plan_alias(user.trial_plan) or "plan_starter"
    return resolve_plan_alias(user.subscription.plan_type) or "plan_starter"


def require_cms_push_plan(user: models.User) -> str:
    plan = resolve_user_plan(user)
    if can_use_feature(plan, "cms_push"):
        return plan
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail="CMS push-to-live requires an active Executive plan.",
    )


def _resolve_task_fix_value(task: models.ProjectTask, explicit_value: str | None) -> str:
    candidate = str(explicit_value or "").strip()
    if candidate:
        return candidate

    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    for key in (
        "ai_code_snippet",
        "code_snippet",
        "cms_fix_snippet",
        "recommended_code",
        "proposed_value",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if task.description and task.description.strip():
        return task.description.strip()

    raise ValueError(
        "No proposed fix snippet found on the task. Provide new_value explicitly from the UI preview form."
    )


def _token_secret() -> str:
    secret = (
        os.getenv("CMS_CONFIRMATION_TOKEN_SECRET") or settings.JWT_SECRET_KEY or settings.JWT_SECRET
    )
    if not secret:
        raise ValueError(
            "No CMS confirmation token secret configured. "
            "Set CMS_CONFIRMATION_TOKEN_SECRET or JWT_SECRET_KEY."
        )
    return secret


def _normalize_token_value(field: str, value: str) -> str:
    if field == "head_scripts":
        return _normalize_markdown_body(value)
    return value


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _encode_token_payload(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_token_payload(encoded_payload: str) -> dict[str, Any]:
    padding = "=" * (-len(encoded_payload) % 4)
    decoded = base64.urlsafe_b64decode(f"{encoded_payload}{padding}")
    payload = json.loads(decoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid confirmation payload.")
    return payload


def build_confirmation_token(
    *,
    task_id: int,
    connection_id: int,
    page_url: str,
    field: str,
    value: str,
    ttl_seconds: int = CMS_CONFIRMATION_TOKEN_TTL_SECONDS,
) -> str:
    now = _utcnow()
    payload = {
        "task_id": int(task_id),
        "connection_id": int(connection_id),
        "page_url": page_url,
        "field": field,
        "value_hash": _value_hash(value),
        "issued_at": int(now.timestamp()),
        "expires_at": int((now + timedelta(seconds=max(30, int(ttl_seconds)))).timestamp()),
        "nonce": secrets.token_hex(8),
    }
    encoded = _encode_token_payload(payload)
    signature = hmac.new(
        _token_secret().encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def validate_confirmation_token(
    *,
    token: str,
    task_id: int,
    connection_id: int,
    page_url: str,
    field: str,
    value: str,
) -> None:
    token_value = str(token or "").strip()
    if "." not in token_value:
        raise ValueError("Invalid confirmation token.")
    encoded_payload, provided_signature = token_value.split(".", 1)
    expected_signature = hmac.new(
        _token_secret().encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise ValueError("Confirmation token signature mismatch.")

    payload = _decode_token_payload(encoded_payload)
    now_ts = int(_utcnow().timestamp())
    expires_at = int(payload.get("expires_at") or 0)
    if expires_at <= now_ts:
        raise ValueError("Confirmation token expired. Preview again before pushing.")

    expected = {
        "task_id": int(task_id),
        "connection_id": int(connection_id),
        "page_url": page_url,
        "field": field,
        "value_hash": _value_hash(value),
    }
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            raise ValueError("Confirmation token no longer matches the preview payload.")


def _coerce_task_status(value: models.ProjectTaskStatus | str) -> models.ProjectTaskStatus:
    if isinstance(value, models.ProjectTaskStatus):
        return value
    return models.ProjectTaskStatus(str(value))


def _restore_task_state(task: models.ProjectTask, snapshot: dict[str, Any]) -> None:
    task.status = snapshot["status"]
    task.resolved_at = snapshot["resolved_at"]
    task.verified_at = snapshot["verified_at"]
    task.verification_audit_id = snapshot["verification_audit_id"]
    task.resolution_source = snapshot["resolution_source"]


def _task_state_snapshot(task: models.ProjectTask) -> dict[str, Any]:
    return {
        "status": _coerce_task_status(task.status),
        "resolved_at": task.resolved_at,
        "verified_at": task.verified_at,
        "verification_audit_id": task.verification_audit_id,
        "resolution_source": task.resolution_source,
    }


def create_or_update_connection(
    db: Session,
    *,
    project: models.Project,
    cms_type: str,
    site_url: str,
    credentials: dict[str, Any],
) -> models.CMSConnection:
    normalized_type = _normalize_cms_type(cms_type)
    normalized_site_url = normalize_site_url(site_url)
    serialized_credentials = serialize_credentials(credentials)

    connection = (
        db.query(models.CMSConnection)
        .filter(
            models.CMSConnection.project_id == project.id,
            models.CMSConnection.cms_type == normalized_type,
        )
        .first()
    )
    if connection is None:
        connection = models.CMSConnection(
            project_id=project.id,
            workspace_id=project.workspace_id,
            cms_type=normalized_type,
            site_url=normalized_site_url,
            credentials_json=serialized_credentials,
            status="pending",
            schema_version="1",
        )
        db.add(connection)
    else:
        connection.site_url = normalized_site_url
        connection.credentials_json = serialized_credentials
        connection.status = "pending"

    db.commit()
    db.refresh(connection)
    return connection


def list_project_connections(db: Session, *, project_id: int) -> list[models.CMSConnection]:
    return (
        db.query(models.CMSConnection)
        .filter(models.CMSConnection.project_id == project_id)
        .order_by(models.CMSConnection.created_at.asc(), models.CMSConnection.id.asc())
        .all()
    )


def get_project_connection_or_404(
    db: Session,
    *,
    project_id: int,
    connection_id: int,
) -> models.CMSConnection:
    row = (
        db.query(models.CMSConnection)
        .filter(
            models.CMSConnection.project_id == project_id,
            models.CMSConnection.id == connection_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="CMS connection not found for project.")
    return row


async def verify_connection(
    db: Session,
    *,
    connection: models.CMSConnection,
) -> models.CMSConnection:
    try:
        adapter = get_cms_adapter(connection)
        is_healthy = await adapter.test_connection()
    except Exception:
        is_healthy = False

    connection.status = "verified" if is_healthy else "error"
    connection.last_verified_at = _utcnow()
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def delete_connection(db: Session, *, connection: models.CMSConnection) -> None:
    db.delete(connection)
    db.commit()


def list_project_deployment_logs(
    db: Session,
    *,
    project_id: int,
    task_id: int | None = None,
    connection_id: int | None = None,
    limit: int = 50,
) -> list[models.CMSDeploymentLog]:
    query = (
        db.query(models.CMSDeploymentLog)
        .join(models.ProjectTask, models.ProjectTask.id == models.CMSDeploymentLog.project_task_id)
        .filter(models.ProjectTask.project_id == project_id)
    )
    if task_id is not None:
        query = query.filter(models.CMSDeploymentLog.project_task_id == task_id)
    if connection_id is not None:
        query = query.filter(models.CMSDeploymentLog.cms_connection_id == connection_id)
    return (
        query.order_by(models.CMSDeploymentLog.created_at.desc(), models.CMSDeploymentLog.id.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )


def _resolve_value_for_field(
    field: str, task: models.ProjectTask, explicit_value: str | None
) -> str:
    normalized = validate_supported_field(field)
    proposed = _resolve_task_fix_value(task, explicit_value)
    return _normalize_token_value(normalized, proposed)


async def preview_task_change(
    db: Session,
    *,
    task: models.ProjectTask,
    connection: models.CMSConnection,
    page_url: str,
    field: str,
    explicit_value: str | None,
) -> CMSPreviewResult:
    normalized_field = validate_supported_field(field)
    proposed_value = _resolve_value_for_field(normalized_field, task, explicit_value)
    adapter = get_cms_adapter(connection)
    preview = await adapter.preview_change(
        page_url=page_url,
        field=normalized_field,
        new_value=proposed_value,
    )
    token = build_confirmation_token(
        task_id=task.id,
        connection_id=connection.id,
        page_url=page_url,
        field=normalized_field,
        value=preview.proposed_value,
    )
    _ = db
    return CMSPreviewResult(preview=preview, confirmation_token=token)


async def push_task_change(
    db: Session,
    *,
    task: models.ProjectTask,
    connection: models.CMSConnection,
    initiated_by_user_id: int,
    page_url: str,
    field: str,
    explicit_value: str | None,
    confirmation_token: str,
) -> tuple[models.CMSDeploymentLog, CMSPushResult]:
    normalized_field = validate_supported_field(field)
    proposed_value = _resolve_value_for_field(normalized_field, task, explicit_value)

    adapter = get_cms_adapter(connection)
    preview = await adapter.preview_change(
        page_url=page_url,
        field=normalized_field,
        new_value=proposed_value,
    )
    validate_confirmation_token(
        token=confirmation_token,
        task_id=task.id,
        connection_id=connection.id,
        page_url=page_url,
        field=normalized_field,
        value=preview.proposed_value,
    )

    snapshot = _task_state_snapshot(task)
    task.status = models.ProjectTaskStatus.IN_PROGRESS
    db.add(task)
    db.flush()

    push_result = await adapter.push_change(
        page_url=page_url,
        field=normalized_field,
        new_value=preview.proposed_value,
        approved_by=initiated_by_user_id,
    )

    now = _utcnow()
    if push_result.success:
        task.status = models.ProjectTaskStatus.DONE
        task.resolved_at = now
        task.verified_at = None
        task.verification_audit_id = None
        task.resolution_source = models.ProjectTaskResolutionSource.MANUAL
        log_status = "pushed"
        pushed_at = now
        rolled_back_at = None
        error_message = None
    else:
        _restore_task_state(task, snapshot)
        log_status = "failed"
        pushed_at = None
        rolled_back_at = None
        error_message = push_result.error_message or "CMS push failed."

    log = models.CMSDeploymentLog(
        project_task_id=task.id,
        cms_connection_id=connection.id,
        initiated_by=initiated_by_user_id,
        page_url=page_url,
        field_changed=normalized_field,
        value_before=preview.current_value,
        value_after=preview.proposed_value,
        cms_revision_id=push_result.revision_id,
        status=log_status,
        pushed_at=pushed_at,
        rolled_back_at=rolled_back_at,
        error_message=error_message,
        schema_version="1",
    )
    db.add(task)
    db.add(log)
    db.commit()
    db.refresh(task)
    db.refresh(log)
    return log, push_result


def get_task_deployment_log_or_404(
    db: Session,
    *,
    task_id: int,
    connection_id: int,
    deployment_log_id: int | None,
) -> models.CMSDeploymentLog:
    query = db.query(models.CMSDeploymentLog).filter(
        models.CMSDeploymentLog.project_task_id == task_id,
        models.CMSDeploymentLog.cms_connection_id == connection_id,
        models.CMSDeploymentLog.status == "pushed",
    )
    if deployment_log_id is not None:
        row = query.filter(models.CMSDeploymentLog.id == deployment_log_id).first()
    else:
        row = query.order_by(
            models.CMSDeploymentLog.created_at.desc(), models.CMSDeploymentLog.id.desc()
        ).first()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No successful CMS deployment log found for rollback."
        )
    return row


async def rollback_task_change(
    db: Session,
    *,
    task: models.ProjectTask,
    connection: models.CMSConnection,
    initiated_by_user_id: int,
    source_log: models.CMSDeploymentLog,
) -> tuple[models.CMSDeploymentLog, CMSPushResult]:
    rollback_value = source_log.value_before or ""
    normalized_field = validate_supported_field(source_log.field_changed)
    adapter = get_cms_adapter(connection)

    snapshot = _task_state_snapshot(task)
    task.status = models.ProjectTaskStatus.IN_PROGRESS
    db.add(task)
    db.flush()

    push_result = await adapter.push_change(
        page_url=source_log.page_url,
        field=normalized_field,
        new_value=rollback_value,
        approved_by=initiated_by_user_id,
    )

    now = _utcnow()
    if push_result.success:
        task.status = models.ProjectTaskStatus.TODO
        task.resolved_at = None
        task.verified_at = None
        task.verification_audit_id = None
        task.resolution_source = None
        log_status = "rolled_back"
        pushed_at = None
        rolled_back_at = now
        error_message = None
    else:
        _restore_task_state(task, snapshot)
        log_status = "failed"
        pushed_at = None
        rolled_back_at = None
        error_message = push_result.error_message or "CMS rollback failed."

    log = models.CMSDeploymentLog(
        project_task_id=task.id,
        cms_connection_id=connection.id,
        initiated_by=initiated_by_user_id,
        page_url=source_log.page_url,
        field_changed=normalized_field,
        value_before=source_log.value_after,
        value_after=rollback_value,
        cms_revision_id=push_result.revision_id,
        status=log_status,
        pushed_at=pushed_at,
        rolled_back_at=rolled_back_at,
        error_message=error_message,
        schema_version="1",
    )

    db.add(task)
    db.add(log)
    db.commit()
    db.refresh(task)
    db.refresh(log)
    return log, push_result
