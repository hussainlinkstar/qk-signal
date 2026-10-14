from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, TypeVar

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
from services.audit_helpers import resolve_subscription_plan as _resolve_subscription_plan
from app.config.plans import can_use_feature
from job_models import JOB_STATUS_QUEUED, AuditJobPayload
from services.ai_routing_policy import (
    get_audit_tier_label,
    normalize_audit_tier,
    normalize_audit_tier_class,
    resolve_audit_route,
)
from services.cost_forecast_service import (
    build_audit_forecast_input,
    forecast_audit_cost,
    serialize_cost_forecast,
)
from services.email_service import EmailService
from services.jira_service import jira_service
from services.notification_router import NotificationRouter
from services.project_audit_scope import declare_audit_project_scope
from core.redis_client import get_sync_redis


logger = logging.getLogger(__name__)
T = TypeVar("T")

from services.queue_routing import resolve_queue_for_tier

RUNNING_AUDIT_STATUSES = {"queued", "running"}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# _resolve_subscription_plan imported from services.audit_helpers.


def _require_audit_mode_access(
    user: models.User | None,
    db: Session,
    *,
    requested_tier: str,
) -> None:
    if normalize_audit_tier(requested_tier) != "deep_judgment":
        return
    if not can_use_feature(_resolve_subscription_plan(user), "has_high_confidence_mode"):
        raise ValueError(
            "High Confidence / Prescriptive Confidence mode requires " "Specialist or above."
        )


def _ensure_http_url(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("A target URL is required to run an audit.")
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    return f"https://{normalized}"


def _safe_format(value: str, context: Mapping[str, Any]) -> str:
    template = str(value or "").strip()
    if not template:
        return ""
    try:
        return template.format(**dict(context))
    except Exception:
        # Keep user-authored templates resilient to missing keys.
        return template


def _run_async_in_sync(callable_factory: Callable[[], Awaitable[T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(callable_factory())

    result_holder: dict[str, T] = {}
    error_holder: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result_holder["value"] = asyncio.run(callable_factory())
        except BaseException as exc:  # noqa: BLE001
            error_holder["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder["value"]


def serialize_workflow(workflow: models.Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "workspace_id": workflow.workspace_id,
        "project_id": workflow.project_id,
        "name": workflow.name,
        "description": workflow.description,
        "trigger_config": dict(workflow.trigger_config or {}),
        "actions_config": list(workflow.actions_config or []),
        "cooldown_minutes": int(workflow.cooldown_minutes or 0),
        "is_active": bool(workflow.is_active),
        "last_triggered_at": _as_utc(workflow.last_triggered_at).isoformat()
        if workflow.last_triggered_at
        else None,
        "created_at": _as_utc(workflow.created_at).isoformat() if workflow.created_at else None,
        "updated_at": _as_utc(workflow.updated_at).isoformat() if workflow.updated_at else None,
    }


def serialize_workflow_run(run: models.WorkflowRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "triggered_at": _as_utc(run.triggered_at).isoformat() if run.triggered_at else None,
        "trigger_event": run.trigger_event,
        "trigger_context": dict(run.trigger_context or {}),
        "status": run.status,
        "action_results": list(run.action_results or []),
        "completed_at": _as_utc(run.completed_at).isoformat() if run.completed_at else None,
    }


class WorkflowEngine:
    def __init__(self, db: Session):
        self.db = db
        self.notification_router = NotificationRouter(db)

    def evaluate_event(
        self,
        *,
        workspace_id: int,
        project_id: int | None,
        event_key: str,
        context: Mapping[str, Any],
    ) -> list[models.WorkflowRun]:
        workflows = (
            self.db.query(models.Workflow)
            .filter(
                models.Workflow.workspace_id == workspace_id,
                models.Workflow.is_active.is_(True),
                or_(models.Workflow.project_id == project_id, models.Workflow.project_id.is_(None)),
            )
            .order_by(models.Workflow.created_at.asc(), models.Workflow.id.asc())
            .all()
        )

        runs: list[models.WorkflowRun] = []
        for workflow in workflows:
            try:
                if not self._matches_trigger(
                    dict(workflow.trigger_config or {}), event_key, context
                ):
                    continue
                if not self._cooldown_ok(workflow):
                    continue
                runs.append(
                    self.execute_workflow(
                        workflow=workflow,
                        event_key=event_key,
                        context=context,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Workflow evaluation failed for workflow %s event %s",
                    workflow.id,
                    event_key,
                    exc_info=exc,
                )
        return runs

    def execute_workflow(
        self,
        *,
        workflow: models.Workflow,
        event_key: str,
        context: Mapping[str, Any],
    ) -> models.WorkflowRun:
        triggered_at = _now()
        run = models.WorkflowRun(
            workflow_id=workflow.id,
            trigger_event=event_key,
            trigger_context=dict(context),
            status="running",
            action_results=[],
            triggered_at=triggered_at,
        )
        self.db.add(run)
        self.db.flush()

        results: list[dict[str, Any]] = []
        for action in list(workflow.actions_config or []):
            action_type = str(action.get("type") or "").strip().lower()
            action_config = action.get("config") if isinstance(action.get("config"), dict) else {}
            try:
                action_result = self._run_action(
                    workflow=workflow,
                    action_type=action_type,
                    action_config=action_config,
                    event_key=event_key,
                    context=context,
                )
                results.append({"type": action_type, "status": "ok", **action_result})
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Workflow action failed workflow=%s action=%s",
                    workflow.id,
                    action_type,
                    exc_info=exc,
                )
                results.append(
                    {
                        "type": action_type,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        run.action_results = results
        run.status = self._resolve_status(results)
        run.completed_at = _now()
        workflow.last_triggered_at = triggered_at
        self.db.commit()
        self.db.refresh(run)
        return run

    def _matches_trigger(
        self,
        trigger_config: Mapping[str, Any],
        event_key: str,
        context: Mapping[str, Any],
    ) -> bool:
        trigger_type = str(trigger_config.get("type") or "").strip().lower()
        if trigger_type == "platform_event":
            trigger_event = str(trigger_config.get("event_key") or "").strip()
            trigger_events = [
                str(item).strip()
                for item in list(trigger_config.get("event_keys") or [])
                if str(item).strip()
            ]
            candidate_events = set(trigger_events)
            if trigger_event:
                candidate_events.add(trigger_event)
            return event_key in candidate_events

        if trigger_type == "audit_completed":
            if event_key not in {"audit.completed", "audit.consensus_ready"}:
                return False
            audit_tier = str(trigger_config.get("audit_tier") or "").strip().lower()
            if not audit_tier or audit_tier == "any":
                return True
            return str(context.get("audit_tier") or "").strip().lower() == audit_tier

        if trigger_type in {"metric_threshold", "alert_triggered"}:
            if trigger_type == "alert_triggered" and not event_key.startswith("alert."):
                return False
            metric_name = str(context.get("metric_name") or "").strip().lower()
            required_metric = str(trigger_config.get("metric") or "").strip().lower()
            if required_metric and metric_name != required_metric:
                return False
            condition = str(trigger_config.get("condition") or "").strip().lower()
            threshold = trigger_config.get("value")
            metric_value = self._coerce_float(context.get("metric_value"))
            baseline_metric_value = self._coerce_float(context.get("baseline_metric_value"))
            if metric_value is None or threshold is None:
                return False
            threshold_value = float(threshold)
            if condition == "below":
                return metric_value < threshold_value
            if condition == "above":
                return metric_value > threshold_value
            if condition == "drops_by" and baseline_metric_value is not None:
                return baseline_metric_value - metric_value >= threshold_value
            return False

        return False

    def _cooldown_ok(self, workflow: models.Workflow) -> bool:
        last_triggered_at = _as_utc(workflow.last_triggered_at)
        if last_triggered_at is None:
            return True
        cooldown_minutes = max(0, int(workflow.cooldown_minutes or 0))
        return _now() >= last_triggered_at + timedelta(minutes=cooldown_minutes)

    def _run_action(
        self,
        *,
        workflow: models.Workflow,
        action_type: str,
        action_config: Mapping[str, Any],
        event_key: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        if action_type == "send_email":
            to_email = str(action_config.get("to") or "").strip()
            template_key = str(action_config.get("template_key") or event_key).strip()
            if not to_email:
                raise ValueError("send_email action requires config.to")
            EmailService(self.db).queue_template_email(
                to_email=to_email,
                template_key=template_key,
                context=context,
                user_id=workflow.created_by_user_id,
                workspace_id=workflow.workspace_id,
                correlation_id=f"workflow:{workflow.id}:{event_key}:{to_email.lower()}",
            )
            return {"recipient": to_email, "template_key": template_key}

        if action_type == "send_slack":
            connection = (
                self.db.query(models.SlackConnection)
                .filter(models.SlackConnection.workspace_id == workflow.workspace_id)
                .first()
            )
            if connection is None:
                raise ValueError("Slack is not connected for this workspace.")
            channel_id = str(action_config.get("channel_id") or "").strip() or None
            self.notification_router.send_slack_message(
                connection=connection,
                event_key=event_key,
                context=context,
                channel_id=channel_id,
            )
            return {"channel_id": channel_id or connection.default_channel_id}

        if action_type == "send_teams":
            connection = (
                self.db.query(models.TeamsConnection)
                .filter(models.TeamsConnection.workspace_id == workflow.workspace_id)
                .first()
            )
            if connection is None:
                raise ValueError("Teams is not connected for this workspace.")
            webhook_url = str(action_config.get("webhook_url") or "").strip() or None
            self.notification_router.send_teams_message(
                connection=connection,
                event_key=event_key,
                context=context,
                webhook_url=webhook_url,
            )
            return {"channel_name": connection.channel_name}

        if action_type == "webhook":
            url = str(action_config.get("url") or "").strip()
            if not url:
                raise ValueError("webhook action requires config.url")
            _SAFE_WEBHOOK_METHODS = {"GET", "POST", "PUT", "PATCH"}
            method = str(action_config.get("method") or "POST").strip().upper() or "POST"
            if method not in _SAFE_WEBHOOK_METHODS:
                raise ValueError(f"Unsupported webhook method: {method}")
            from services.url_validation import safe_sync_fetch

            response = safe_sync_fetch(
                url,
                method=method,
                json={"event_key": event_key, "context": dict(context), "workflow_id": workflow.id},
                timeout=10.0,
            )
            response.raise_for_status()
            return {"url": url, "method": method}

        if action_type == "run_audit":
            return self._run_audit_action(
                workflow=workflow,
                action_config=action_config,
                context=context,
            )

        if action_type == "create_jira_ticket":
            return self._create_jira_ticket_action(
                workflow=workflow,
                action_config=action_config,
                event_key=event_key,
                context=context,
            )

        raise ValueError(f"Unsupported workflow action '{action_type}'.")

    def _resolve_workflow_project(self, workflow: models.Workflow) -> models.Project:
        if workflow.project_id is None:
            raise ValueError("Workflow run_audit action requires a project-scoped workflow.")
        project = (
            self.db.query(models.Project).filter(models.Project.id == workflow.project_id).first()
        )
        if project is None:
            raise ValueError("Project not found for workflow audit action.")
        return project

    def _resolve_workflow_actor(self, workflow: models.Workflow) -> models.User:
        if workflow.created_by_user_id is not None:
            user = (
                self.db.query(models.User)
                .filter(models.User.id == workflow.created_by_user_id)
                .first()
            )
            if user is not None:
                return user

        workspace = (
            self.db.query(models.Workspace)
            .filter(models.Workspace.id == workflow.workspace_id)
            .first()
        )
        if workspace is None:
            raise ValueError("Workspace not found for workflow action.")
        owner = self.db.query(models.User).filter(models.User.id == workspace.owner_id).first()
        if owner is None:
            raise ValueError("Workspace owner not found for workflow action.")
        return owner

    def _ensure_no_running_audit(
        self,
        *,
        user_id: int,
        project_id: int | None,
        target_url: str,
    ) -> None:
        duplicate = (
            self.db.query(models.AuditJob)
            .filter(
                models.AuditJob.user_id == user_id,
                models.AuditJob.url == target_url,
                models.AuditJob.status.in_(RUNNING_AUDIT_STATUSES),
                models.AuditJob.project_id == project_id,
            )
            .first()
        )
        if duplicate is not None:
            raise ValueError("An audit is already running for this target.")

    def _enqueue_audit_payload(self, *, job_key: str, payload: AuditJobPayload) -> None:
        with get_sync_redis() as redis_client:
            redis_client.hset(
                job_key,
                mapping={
                    "status": JOB_STATUS_QUEUED,
                    "created_at": _now().isoformat(),
                    "request_id": payload.request_id,
                    "user_id": str(payload.user_id),
                    "provider": payload.provider,
                    "tier": payload.requested_tier or payload.tier_class or payload.tier,
                    "requested_tier": payload.requested_tier or "",
                    "execution_tier": payload.tier,
                    "mode_label": payload.mode_label or "",
                    "routing_mode": payload.routing_mode or "",
                    "routing_preferred_provider": payload.routing_preferred_provider or "",
                    "routing_reason": payload.routing_reason or "",
                    "project_id": str(payload.project_id) if payload.project_id is not None else "",
                    "estimated_credit_cost": str(max(1, int(payload.estimated_credit_cost or 1))),
                },
            )
            redis_client.rpush(resolve_queue_for_tier(payload.tier), json.dumps(payload.to_dict()))
            from services.job_ttl_dlq_service import TTL_QUEUED

            redis_client.expire(job_key, TTL_QUEUED)

    def _run_audit_action(
        self,
        *,
        workflow: models.Workflow,
        action_config: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        project = self._resolve_workflow_project(workflow)
        actor = self._resolve_workflow_actor(workflow)

        action_target_type = (
            str(action_config.get("audit_target_type") or "website").strip().lower()
        )
        if action_target_type not in {"website", "brand"}:
            action_target_type = "website"

        raw_url = str(
            action_config.get("url") or context.get("target_url") or project.domain_url or ""
        ).strip()
        action_target_name = str(action_config.get("target_name") or "").strip() or None
        action_target_metadata = (
            action_config.get("target_metadata")
            if isinstance(action_config.get("target_metadata"), dict)
            else {}
        )

        if action_target_type == "brand":
            target_url = _ensure_http_url(raw_url) if raw_url else ""
            if not action_target_name:
                raise ValueError("Brand audit actions require a target_name.")
        else:
            target_url = _ensure_http_url(raw_url)

        display_name = action_target_name or target_url or "Brand audit"

        tier = str(action_config.get("tier") or "fast").strip().lower() or "fast"
        category = (
            str(action_config.get("category") or context.get("category") or "").strip() or None
        )
        market = str(action_config.get("market") or context.get("market") or "").strip() or None
        language = str(action_config.get("language") or project.language or "").strip() or None
        entities = (
            action_config.get("entities")
            if isinstance(action_config.get("entities"), list)
            else None
        )
        route = resolve_audit_route(
            tier=tier, provider=action_config.get("provider"), selected_models=None
        )
        _require_audit_mode_access(actor, self.db, requested_tier=route.requested_tier)
        forecast = forecast_audit_cost(
            audit_data=build_audit_forecast_input(
                target_url=target_url or None,
                target_name=display_name,
                target_metadata=action_target_metadata,
                category=category,
                market=market,
                language=language,
                entities=[str(entity).strip() for entity in entities or [] if str(entity).strip()]
                or None,
            ),
            dataforseo_results=None,
            tier_class=normalize_audit_tier_class(route.requested_tier),
            requested_tier=route.requested_tier,
            policy_version=None,
            feature_key="audit.main",
            entities_count=len(entities or []),
            category=category,
            market=market,
            provider=route.provider,
            db=self.db,
        )
        estimated_credit_cost = max(1, int(forecast.estimated_credits or 1))
        forecast_payload = serialize_cost_forecast(forecast)

        duplicate_url = target_url or display_name
        self._ensure_no_running_audit(
            user_id=actor.id,
            project_id=project.id,
            target_url=duplicate_url,
        )
        # SIGV2-1024: credits are internal soft limits and never block an audit.
        job_id = str(uuid.uuid4())
        request_id = f"workflow:{workflow.id}:run_audit:{job_id}"

        # Workflow/scheduled audits consume one scan like manual launches.
        from services.scan_allowance_service import consume_scan_allowance

        consume_scan_allowance(self.db, actor)

        # Project scan cap (SIGV2-1102): runs block at the configured cap.
        from services.project_budget_service import (
            consume_project_scan,
            project_scan_cap_exceeded_detail,
        )

        budget_result = consume_project_scan(self.db, project_id=project.id)
        if budget_result.status == "budget_exceeded":
            raise ValueError(
                project_scan_cap_exceeded_detail(
                    project_name=project.name,
                    monthly_limit_scans=int(budget_result.monthly_limit_scans or 0),
                    period_end=budget_result.period_end,
                )
            )
        if budget_result.threshold_events:
            from services.audit_helpers import queue_project_budget_notifications

            queue_project_budget_notifications(
                self.db,
                project=project,
                consumed_scans=budget_result.consumed_scans,
                monthly_limit_scans=budget_result.monthly_limit_scans,
                percent_consumed=budget_result.percent_consumed,
                threshold_events=budget_result.threshold_events,
            )

        db_job = models.AuditJob(
            id=job_id,
            user_id=actor.id,
            project_id=project.id,
            status=JOB_STATUS_QUEUED,
            audit_target_type=models.AuditTargetType(action_target_type),
            target_name=display_name,
            target_url=target_url or None,
            target_metadata=action_target_metadata,
            url=target_url,
            provider=route.provider,
            tier=route.execution_tier,
            estimated_credit_cost=estimated_credit_cost,
            request_id=request_id,
            # SIGV2-1129: a workflow the customer configured runs their own
            # target, so it is one of their scans, as it was before.
            scan_origin=models.SCAN_ORIGIN_CUSTOMER,
        )
        self.db.add(db_job)
        self.db.commit()

        payload = AuditJobPayload(
            job_id=job_id,
            request_id=request_id,
            user_id=actor.id,
            url=target_url,
            audit_target_type=action_target_type,
            target_name=display_name,
            target_url=target_url or None,
            target_metadata=action_target_metadata,
            provider=route.provider,
            tier=route.execution_tier,
            requested_tier=route.requested_tier,
            mode_label=route.product_label,
            tier_class=route.tier_class,
            routing_feature_key=route.feature_key,
            routing_mode=route.routing_mode,
            routing_preferred_provider=route.preferred_provider,
            routing_reason=route.route_reason,
            project_id=project.id,
            estimated_credit_cost=estimated_credit_cost,
            cost_forecast=forecast_payload,
            category=category,
            market=market,
            language=language,
            entities=[str(entity).strip() for entity in entities or [] if str(entity).strip()]
            or None,
            # SIGV2-1121: a workflow-triggered audit measures the project's own
            # target unless the action itself asks for a competitor lite audit.
            project_scope=declare_audit_project_scope(category=category),
        )
        job_key = f"audit:job:{job_id}"
        try:
            self._enqueue_audit_payload(job_key=job_key, payload=payload)
        except Exception as exc:  # noqa: BLE001
            db_job.status = "failed"
            db_job.error = f"Failed to enqueue workflow-triggered audit: {exc}"
            db_job.completed_at = _now()
            self.db.add(db_job)
            self.db.commit()
            raise ValueError("Unable to queue workflow-triggered audit.") from exc

        return {
            "job_id": job_id,
            "request_id": request_id,
            "url": target_url or None,
            "audit_target_type": action_target_type,
            "target_name": display_name,
            "provider": route.provider,
            "tier": route.requested_tier,
            "execution_tier": route.execution_tier,
            "mode_label": route.product_label or get_audit_tier_label(route.requested_tier),
            "estimated_credit_cost": estimated_credit_cost,
        }

    def _create_jira_ticket_action(
        self,
        *,
        workflow: models.Workflow,
        action_config: Mapping[str, Any],
        event_key: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        project = self._resolve_workflow_project(workflow)
        connection = (
            self.db.query(models.JiraConnection)
            .filter(models.JiraConnection.workspace_id == workflow.workspace_id)
            .first()
        )
        if connection is None or not connection.access_token:
            raise ValueError("Jira is not connected for this workspace.")
        if not connection.cloud_id:
            raise ValueError("Jira connection is missing cloud_id.")

        if connection.refresh_token and connection.expires_at:
            expires_at = _as_utc(connection.expires_at)
            if expires_at and _now() >= expires_at - timedelta(minutes=5):
                token_payload = _run_async_in_sync(
                    lambda: jira_service.refresh_access_token(connection.refresh_token)
                )
                connection.access_token = str(
                    token_payload.get("access_token") or connection.access_token
                )
                refreshed_token = token_payload.get("refresh_token")
                if isinstance(refreshed_token, str) and refreshed_token.strip():
                    connection.refresh_token = refreshed_token
                expires_in = token_payload.get("expires_in")
                try:
                    expires_seconds = int(expires_in)
                except (TypeError, ValueError):
                    expires_seconds = 3600
                connection.expires_at = _now() + timedelta(seconds=max(60, expires_seconds))
                self.db.add(connection)
                self.db.commit()

        jira_project_key = str(
            action_config.get("project_key") or connection.default_jira_project_key or ""
        ).strip()
        if not jira_project_key:
            raise ValueError(
                "Jira project key is required (config.project_key or workspace default)."
            )

        summary_template = str(action_config.get("summary") or f"[{project.name}] {event_key}")
        description_template = str(
            action_config.get("description")
            or "Workflow `{event_key}` triggered for project `{project_name}`.\n\nMessage: {message}"
        )
        issue_type = str(action_config.get("issue_type") or "Task").strip() or "Task"
        summary = _safe_format(summary_template, context)[:255]
        description = _safe_format(
            description_template,
            {
                **dict(context),
                "event_key": event_key,
                "project_name": project.name,
            },
        )

        browse_base_url = jira_service.normalize_browse_base_url(connection.site_url)
        export = _run_async_in_sync(
            lambda: jira_service.create_issue(
                cloud_id=connection.cloud_id,
                access_token=connection.access_token,
                project_key=jira_project_key,
                summary=summary,
                description_md=description,
                issue_type=issue_type,
                site_url=browse_base_url,
            )
        )
        self.db.add(
            models.ProjectJiraExport(
                project_id=project.id,
                created_by_user_id=workflow.created_by_user_id,
                jira_project_key=jira_project_key,
                issue_id=export.issue_id,
                issue_key=export.issue_key,
                issue_url=export.issue_url,
                title=summary,
                issue_type=issue_type,
                status_name="Exported",
            )
        )
        self.db.commit()
        return {
            "issue_id": export.issue_id,
            "issue_key": export.issue_key,
            "issue_url": export.issue_url,
            "project_key": jira_project_key,
        }

    def _resolve_status(self, results: list[dict[str, Any]]) -> str:
        if not results:
            return "failed"
        if all(item.get("status") == "ok" for item in results):
            return "completed"
        if any(item.get("status") == "ok" for item in results):
            return "partial_failure"
        return "failed"

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def evaluate_workflows_for_event(
    db: Session,
    *,
    workspace_id: int | None,
    project_id: int | None,
    event_key: str,
    context: Mapping[str, Any],
) -> list[models.WorkflowRun]:
    if workspace_id is None:
        return []
    return WorkflowEngine(db).evaluate_event(
        workspace_id=workspace_id,
        project_id=project_id,
        event_key=event_key,
        context=context,
    )
