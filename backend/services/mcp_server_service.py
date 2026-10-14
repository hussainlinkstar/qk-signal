"""The Qiko Signal MCP server: plan gate, tool registry and dispatch (SIGV2-1210).

Scope of this release, stated here because the omissions are decisions:

* **One tool spends money, and only one.** ``signal_run_audit`` starts a real
  audit and consumes one of the customer's scans. It is the only tool with a
  write scope, it says so in its own description, and it runs the single
  shared launch path in ``services.external_audit_launch_service`` so its
  entitlement check, idempotency, in-flight dedup, scan allowance and project
  cap are the same ones the REST API applies rather than a second copy.
  ``tests/test_api_key_scopes.py`` pins that every write tool sits outside the
  default read-only grant, so a spending tool can never be handed out by
  omitting a scope list.
* **The plan gate is server-side.** ``require_mcp_plan`` runs for every
  method, including ``initialize`` and ``tools/list``. Filtering a catalogue
  while the endpoint still answers ``tools/call`` is not gating, so the refusal
  happens where the work is dispatched and not where the list is built.
* **One scope vocabulary.** Tool scopes come from the closed allow-list in
  ``services.external_api_service`` and are enforced through the same
  ``require_principal_scope`` the REST routes use. A scope this code does not
  know raises at import time rather than guarding nothing at runtime.
* **Tenancy is resolved, never asserted.** A caller-supplied project id goes
  through ``resolve_project_access``, which refuses an inaccessible project
  instead of substituting an accessible one. An audit or a job that belongs to
  someone else reads as absent, so the endpoint cannot be used to confirm that
  another tenant's record exists.
* **Minimum disclosure.** Every tool result crosses into an agent's context,
  so each serializer returns the fields that answer the tool's question and
  stops. ``signal_list_recommendations`` is the one to watch: a task title
  already carries audit recommendation text, and the description body and the
  assignee identity are deliberately not returned.

The transport this module serves is implemented in ``routers.mcp_router``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Final, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
)
from services.external_api_service import (
    EXTERNAL_JOB_SOURCE,
    ExternalAPIPrincipal,
    assert_known_api_key_scope,
    external_error,
    map_external_job_status,
    require_principal_scope,
    serialize_audit_scores,
)
from services.external_audit_launch_service import (
    ExternalAuditCreateRequest,
    RedisContextFactory,
    launch_external_audit,
)
from services.project_audit_scope import own_project_audit_clause
from services.scan_allowance_service import scan_allowance_snapshot
from services.workspace_rbac import accessible_workspace_ids, resolve_project_access

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

MCP_SERVER_NAME: Final[str] = "qiko-signal"
MCP_SERVER_TITLE: Final[str] = "Qiko Signal"
MCP_ENDPOINT_PATH: Final[str] = "/api/v1/mcp"

# Protocol revisions this server will negotiate, newest first. The newest is
# what an older or version-less client is answered with, which is what the
# specification asks a server to do when it cannot honour the requested one.
SUPPORTED_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
)
LATEST_PROTOCOL_VERSION: Final[str] = SUPPORTED_PROTOCOL_VERSIONS[0]
PROTOCOL_VERSION_HEADER: Final[str] = "MCP-Protocol-Version"

# The entitlement that opens this server. A separate key from ``api_access``
# on purpose: ``api_access`` is granted to the agency trial, and the agreed
# grant for MCP is Specialist and Executive only.
MCP_PLAN_CAPABILITY: Final[str] = "mcp_access"

# JSON-RPC 2.0 reserved codes, plus two in the implementation-defined server
# range. Authorization and absence are answered as protocol errors rather than
# as tool content, so a model cannot read a refusal as an answer.
JSONRPC_PARSE_ERROR: Final[int] = -32700
JSONRPC_INVALID_REQUEST: Final[int] = -32600
JSONRPC_METHOD_NOT_FOUND: Final[int] = -32601
JSONRPC_INVALID_PARAMS: Final[int] = -32602
JSONRPC_INTERNAL_ERROR: Final[int] = -32603
MCP_ERROR_FORBIDDEN: Final[int] = -32003
MCP_ERROR_NOT_FOUND: Final[int] = -32004


class McpProtocolError(Exception):
    """A JSON-RPC level failure, carried back to the caller as an error object."""

    def __init__(self, code: int, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# ---------------------------------------------------------------------------
# Plan gate
# ---------------------------------------------------------------------------


def mcp_eligible_plan_ids() -> tuple[str, ...]:
    """Canonical plans whose entitlement really includes the MCP server."""
    return tuple(
        plan for plan in CANONICAL_PLAN_TYPES if can_use_feature(plan, MCP_PLAN_CAPABILITY)
    )


def mcp_minimum_plan_id() -> str | None:
    """The cheapest plan the entitlement ladder says includes the MCP server."""
    return MINIMUM_PLAN_BY_FEATURE.get(MCP_PLAN_CAPABILITY)


def mcp_eligible_plan_labels() -> tuple[str, ...]:
    """Display names of the eligible plans, read from the plan catalogue."""
    return tuple(
        str(PLAN_PRESENTATION.get(plan, {}).get("name") or plan) for plan in mcp_eligible_plan_ids()
    )


def mcp_availability_sentence() -> str:
    """The one sentence every refusal and every availability notice uses.

    Derived from the capability matrix, so a plan gaining or losing the
    entitlement cannot leave this wording claiming the old answer.
    """
    labels = mcp_eligible_plan_labels()
    if not labels:
        return "The Qiko Signal MCP server is not available on any plan."
    if len(labels) == 1:
        named = labels[0]
    else:
        named = f"{', '.join(labels[:-1])} and {labels[-1]}"
    plural = "plan" if len(labels) == 1 else "plans"
    return f"The Qiko Signal MCP server is available on the {named} {plural}."


def require_mcp_plan(principal: ExternalAPIPrincipal) -> None:
    """Refuse a key whose plan does not include the MCP server.

    Called for every MCP method, so an ineligible plan cannot reach
    ``tools/call`` by guessing a tool name it was never shown.
    """
    if not can_use_feature(principal.plan, MCP_PLAN_CAPABILITY):
        raise external_error(
            code="PLAN_NOT_ELIGIBLE",
            message=mcp_availability_sentence(),
            status_code=403,
        )


# ---------------------------------------------------------------------------
# Tool context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool handler may use, and nothing it may not.

    The Redis factory is carried here rather than imported by this module, so
    the transport decides which client the audit launch talks to, the same way
    the REST router does. ``correlation_id`` is the inbound request id, used
    only to build a job's request id, and it is sanitized downstream.
    """

    db: Session
    principal: ExternalAPIPrincipal
    redis_ctx: RedisContextFactory
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Tool argument models
# ---------------------------------------------------------------------------


class ListProjectsArgs(BaseModel):
    """No identifier: the workspaces are resolved from the authenticated key."""

    model_config = {"extra": "forbid"}

    limit: int = Field(default=20, ge=1, le=100, description="Maximum projects to return.")


class GetAuditArgs(BaseModel):
    model_config = {"extra": "forbid"}

    project_id: int = Field(gt=0, description="Project to read, from signal_list_projects.")
    audit_id: int | None = Field(
        default=None,
        gt=0,
        description="A specific audit of that project. Omitted returns the most recent one.",
    )


class ListRecommendationsArgs(BaseModel):
    model_config = {"extra": "forbid"}

    project_id: int = Field(gt=0, description="Project to read, from signal_list_projects.")
    status: Literal["TODO", "IN_PROGRESS", "DONE"] | None = Field(
        default=None, description="Return only recommendations in this state."
    )
    limit: int = Field(default=20, ge=1, le=100, description="Maximum recommendations to return.")


class GetScanStatusArgs(BaseModel):
    model_config = {"extra": "forbid"}

    job_id: str = Field(
        min_length=1,
        max_length=191,
        description="Job id returned when the scan was submitted through the API.",
    )


class ScanAllowanceArgs(BaseModel):
    """No arguments: the allowance belongs to the authenticated key's owner."""

    model_config = {"extra": "forbid"}


class ProjectOnlyArgs(BaseModel):
    """The argument shape for every tool that reads one whole project."""

    model_config = {"extra": "forbid"}

    project_id: int = Field(gt=0, description="Project to read, from signal_list_projects.")


class ListAuditsArgs(BaseModel):
    model_config = {"extra": "forbid"}

    project_id: int = Field(gt=0, description="Project to read, from signal_list_projects.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum audits to return.")


class GetAuditBreakdownArgs(BaseModel):
    model_config = {"extra": "forbid"}

    project_id: int = Field(gt=0, description="Project to read, from signal_list_projects.")
    audit_id: int | None = Field(
        default=None,
        gt=0,
        description="A specific audit of that project. Omitted uses the most recent one.",
    )


class ListSchedulesArgs(BaseModel):
    model_config = {"extra": "forbid"}

    project_id: int | None = Field(
        default=None,
        gt=0,
        description="Only schedules for this project. Omitted returns every reachable one.",
    )
    limit: int = Field(default=20, ge=1, le=100, description="Maximum schedules to return.")


class RunAuditArgs(BaseModel):
    """Deliberately the narrowest shape that can start an audit.

    There is no ``url``. The target is the project's own registered domain,
    read from the project row after the id is resolved inside the key's tenant
    boundary, so this tool cannot be pointed at an arbitrary host. An agent
    that wants to audit something else has to create the project first, which
    is a decision a human makes in the app.
    """

    model_config = {"extra": "forbid"}

    project_id: int = Field(
        gt=0,
        description="Project to audit, from signal_list_projects. Its registered domain is "
        "the target; this tool cannot audit any other address.",
    )
    tier: Literal["fast", "smart", "deep_judgment"] = Field(
        default="fast",
        description="Depth of the audit. 'fast' is the cheapest and the default.",
    )


# ---------------------------------------------------------------------------
# Serializers: the minimum that answers each tool's question
# ---------------------------------------------------------------------------


def _enum_value(value: Any, fallback: str | None = None) -> str | None:
    if value is None:
        return fallback
    return str(value.value) if hasattr(value, "value") else str(value)


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if value else None


def _project_summary(project: models.Project) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "name": project.name,
        "domain_url": project.domain_url,
        "target_country": project.target_country,
        "language": project.language or "en",
        "created_at": _isoformat(project.created_at),
    }


def _audit_summary(audit: models.Audit) -> dict[str, Any]:
    return {
        "audit_id": int(audit.id),
        "project_id": audit.project_id,
        "url": audit.url or None,
        "target_name": audit.target_name,
        "audit_target_type": _enum_value(audit.audit_target_type),
        "tier": _enum_value(audit.audit_type),
        "scores": serialize_audit_scores(audit),
        "completed_at": _isoformat(audit.created_at),
    }


def _recommendation_summary(task: models.ProjectTask) -> dict[str, Any]:
    """Title, category, priority and state. Not the body, not the assignee.

    A task title already carries audit recommendation text, which is customer
    data crossing into an agent's context. The description body adds the full
    recommendation and ``assigned_to_user_id`` adds a third party's identity;
    neither answers "what should this project fix next", so neither is sent.
    """
    return {
        "recommendation_id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "category": task.category or "General",
        "priority": _enum_value(task.priority, "MEDIUM"),
        "status": _enum_value(task.status, "TODO"),
        "created_at": _isoformat(task.created_at),
    }


def _scan_status_summary(db: Session, job: models.AuditJob) -> dict[str, Any]:
    audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.user_id == job.user_id,
            models.Audit.request_id == job.request_id,
        )
        .order_by(models.Audit.created_at.desc())
        .first()
        if job.request_id
        else None
    )
    return {
        "job_id": job.id,
        "status": map_external_job_status(job.status),
        "project_id": job.project_id,
        "tier": job.tier,
        "scores": serialize_audit_scores(audit),
        "error": job.error,
        "created_at": _isoformat(job.created_at),
        "completed_at": _isoformat(job.completed_at),
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _resolve_project(ctx: ToolContext, project_id: int) -> models.Project:
    """Resolve a caller-supplied project id inside the key's tenant boundary.

    The id is resolved, never merely shape-checked, and an inaccessible one is
    refused rather than replaced with a project the caller can see
    (the SIGV2-1220 pattern).
    """
    try:
        access = resolve_project_access(
            ctx.db,
            user=ctx.principal.user,
            project_id=project_id,
            allow_client_readonly=False,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise McpProtocolError(MCP_ERROR_NOT_FOUND, "Project not found.") from exc
        raise McpProtocolError(
            MCP_ERROR_FORBIDDEN, "You do not have access to this project."
        ) from exc
    return access.project


def _handle_list_projects(ctx: ToolContext, args: ListProjectsArgs) -> dict[str, Any]:
    workspace_ids = accessible_workspace_ids(ctx.db, ctx.principal.user)
    if not workspace_ids:
        return {"projects": [], "count": 0}
    rows = (
        ctx.db.query(models.Project)
        .filter(models.Project.workspace_id.in_(workspace_ids))
        .order_by(models.Project.created_at.desc(), models.Project.id.desc())
        .limit(args.limit)
        .all()
    )
    return {"projects": [_project_summary(project) for project in rows], "count": len(rows)}


def _handle_get_audit(ctx: ToolContext, args: GetAuditArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    # ``own_project_audit_clause`` keeps competitor benchmark audits out: they
    # measure somebody else's site and are not this project's score.
    query = ctx.db.query(models.Audit).filter(
        models.Audit.project_id == project.id,
        own_project_audit_clause(),
    )
    if args.audit_id is not None:
        query = query.filter(models.Audit.id == args.audit_id)
    audit = query.order_by(models.Audit.created_at.desc(), models.Audit.id.desc()).first()
    if audit is None:
        raise McpProtocolError(
            MCP_ERROR_NOT_FOUND,
            "No audit is available for this project yet."
            if args.audit_id is None
            else "Audit not found for this project.",
        )
    return _audit_summary(audit)


def _handle_list_recommendations(ctx: ToolContext, args: ListRecommendationsArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    query = ctx.db.query(models.ProjectTask).filter(models.ProjectTask.project_id == project.id)
    if args.status is not None:
        query = query.filter(models.ProjectTask.status == args.status)
    rows = (
        query.order_by(
            models.ProjectTask.sort_order.asc(),
            models.ProjectTask.created_at.desc(),
        )
        .limit(args.limit)
        .all()
    )
    return {
        "project_id": project.id,
        "recommendations": [_recommendation_summary(task) for task in rows],
        "count": len(rows),
    }


def _handle_get_scan_status(ctx: ToolContext, args: GetScanStatusArgs) -> dict[str, Any]:
    job = (
        ctx.db.query(models.AuditJob)
        .filter(
            models.AuditJob.id == args.job_id,
            models.AuditJob.user_id == ctx.principal.user.id,
            models.AuditJob.source == EXTERNAL_JOB_SOURCE,
        )
        .first()
    )
    if job is None:
        # Absent rather than forbidden: a job belonging to another tenant must
        # not be distinguishable from one that was never submitted.
        raise McpProtocolError(MCP_ERROR_NOT_FOUND, "Scan job not found.")
    return _scan_status_summary(ctx.db, job)


def _latest_own_audit(ctx: ToolContext, project_id: int, audit_id: int | None):
    """The project's own most recent audit, or one named audit of it.

    ``own_project_audit_clause`` keeps competitor benchmark audits out: they
    measure somebody else's site and are not this project's score.
    """
    query = ctx.db.query(models.Audit).filter(
        models.Audit.project_id == project_id,
        own_project_audit_clause(),
    )
    if audit_id is not None:
        query = query.filter(models.Audit.id == audit_id)
    return query.order_by(models.Audit.created_at.desc(), models.Audit.id.desc()).first()


def _handle_get_project(ctx: ToolContext, args: ProjectOnlyArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    latest = _latest_own_audit(ctx, project.id, None)
    payload = _project_summary(project)
    # The id travels with the scores so an agent can ask about this audit next
    # without guessing or re-listing.
    payload["latest_audit"] = (
        None
        if latest is None
        else {
            "audit_id": int(latest.id),
            "scores": serialize_audit_scores(latest),
            "completed_at": _isoformat(latest.created_at),
        }
    )
    return payload


def _handle_list_audits(ctx: ToolContext, args: ListAuditsArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    rows = (
        ctx.db.query(models.Audit)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .limit(args.limit)
        .all()
    )
    return {
        "project_id": project.id,
        "audits": [
            {
                "audit_id": int(audit.id),
                "tier": _enum_value(audit.audit_type),
                "scores": serialize_audit_scores(audit),
                "completed_at": _isoformat(audit.created_at),
            }
            for audit in rows
        ],
        "count": len(rows),
    }


def _engine_breakdown(audit: models.Audit) -> dict[str, Any]:
    """Per-pillar detail out of the stored report, and nothing else from it.

    The full report is a large nested document containing raw evidence and
    model reasoning. Only the per-pillar scores and each pillar's headline
    findings are lifted out: the rest would cross into an agent's context
    without answering "how does this site score, and on what".
    """
    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    pillars: dict[str, Any] = {}
    for pillar in ("seo", "aeo", "geo"):
        section = report.get(pillar)
        if not isinstance(section, dict):
            continue
        score = section.get("score")
        findings = section.get("findings") or section.get("issues")
        headlines: list[str] = []
        if isinstance(findings, list):
            for item in findings[:5]:
                if isinstance(item, str):
                    headlines.append(item)
                elif isinstance(item, dict):
                    title = item.get("title") or item.get("issue") or item.get("name")
                    if isinstance(title, str):
                        headlines.append(title)
        pillars[pillar] = {
            "score": score if isinstance(score, (int, float)) else None,
            "findings": headlines,
        }
    return pillars


def _handle_get_audit_breakdown(ctx: ToolContext, args: GetAuditBreakdownArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    audit = _latest_own_audit(ctx, project.id, args.audit_id)
    if audit is None:
        raise McpProtocolError(
            MCP_ERROR_NOT_FOUND,
            "No audit is available for this project yet."
            if args.audit_id is None
            else "Audit not found for this project.",
        )
    return {
        "audit_id": int(audit.id),
        "project_id": project.id,
        "scores": serialize_audit_scores(audit),
        "engines": _engine_breakdown(audit),
        "completed_at": _isoformat(audit.created_at),
    }


def _require_tool_plan_feature(ctx: ToolContext, feature: str, label: str) -> None:
    """Refuse a tool whose underlying feature the plan does not include.

    The MCP entitlement opens the server; it does not grant every feature
    behind it. Competitor analysis is a separate entitlement on the REST
    surface and stays separate here, enforced at the point the work happens.
    """
    if not can_use_feature(ctx.principal.plan, feature):
        raise McpProtocolError(
            MCP_ERROR_FORBIDDEN,
            f"Your plan does not include {label}. Please upgrade.",
        )


def _handle_list_competitors(ctx: ToolContext, args: ProjectOnlyArgs) -> dict[str, Any]:
    _require_tool_plan_feature(ctx, "has_competitor_analysis", "competitor analysis")
    project = _resolve_project(ctx, args.project_id)
    competitors = (
        ctx.db.query(models.ProjectCompetitor)
        .filter(models.ProjectCompetitor.project_id == project.id)
        .all()
    )
    items: list[dict[str, Any]] = []
    for competitor in competitors:
        latest = (
            ctx.db.query(models.ProjectCompetitorSnapshot)
            .filter(
                models.ProjectCompetitorSnapshot.competitor_id == competitor.id,
                models.ProjectCompetitorSnapshot.status == "completed",
            )
            .order_by(models.ProjectCompetitorSnapshot.captured_at.desc())
            .first()
        )
        items.append(
            {
                "competitor_id": competitor.id,
                "display_name": competitor.display_name,
                "domain": competitor.normalized_domain,
                "scores": None
                if latest is None
                else {
                    "geo": latest.geo_score,
                    "seo": latest.seo_score,
                    "aeo": latest.aeo_score,
                },
                "measured_at": _isoformat(latest.captured_at) if latest else None,
            }
        )
    return {"project_id": project.id, "competitors": items, "count": len(items)}


def _handle_list_schedules(ctx: ToolContext, args: ListSchedulesArgs) -> dict[str, Any]:
    """Scheduled audits, scoped to the key's reachable projects either way.

    When no project is named the listing is bounded by the resolved workspace
    set rather than by the user id alone, so it cannot reach a schedule on a
    project the key may not read.
    """
    query = ctx.db.query(models.ScheduledAudit)
    if args.project_id is not None:
        project = _resolve_project(ctx, args.project_id)
        query = query.filter(models.ScheduledAudit.project_id == project.id)
    else:
        workspace_ids = accessible_workspace_ids(ctx.db, ctx.principal.user)
        if not workspace_ids:
            return {"schedules": [], "count": 0}
        reachable = ctx.db.query(models.Project.id).filter(
            models.Project.workspace_id.in_(workspace_ids)
        )
        query = query.filter(models.ScheduledAudit.project_id.in_(reachable))
    rows = query.order_by(models.ScheduledAudit.next_run_at.asc()).limit(args.limit).all()
    return {
        "schedules": [
            {
                "schedule_id": row.id,
                "project_id": row.project_id,
                "frequency": _enum_value(row.frequency, "weekly"),
                "tier": _enum_value(row.audit_type, "STANDARD"),
                "is_active": bool(row.is_active),
                "next_run_at": _isoformat(row.next_run_at),
                "last_run_at": _isoformat(row.last_run_at),
                "last_run_status": _enum_value(row.last_run_status),
            }
            for row in rows
        ],
        "count": len(rows),
    }


def _handle_list_alerts(ctx: ToolContext, args: ProjectOnlyArgs) -> dict[str, Any]:
    project = _resolve_project(ctx, args.project_id)
    rows = (
        ctx.db.query(models.AlertRule)
        .filter(models.AlertRule.project_id == project.id)
        .order_by(models.AlertRule.created_at.desc())
        .all()
    )
    return {
        "project_id": project.id,
        "alerts": [
            {
                "alert_id": row.id,
                "metric": _enum_value(getattr(row, "metric", None)),
                "comparator": _enum_value(getattr(row, "comparator", None)),
                "threshold": getattr(row, "threshold", None),
                "is_active": bool(getattr(row, "is_active", False)),
                "last_triggered_at": _isoformat(getattr(row, "last_triggered_at", None)),
            }
            for row in rows
        ],
        "count": len(rows),
    }


def _handle_get_scan_allowance(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
    """What is left of the plan's scan allowance, before anything is spent.

    Exists so an agent can check the cost of ``signal_run_audit`` without
    discovering it by being refused, which is the behaviour that turns one
    refusal into a retry loop.
    """
    snapshot = scan_allowance_snapshot(ctx.db, ctx.principal.user)
    return {
        "scans_limit": snapshot.limit,
        "scans_used": snapshot.scans_used,
        "scans_remaining": snapshot.scans_remaining,
        "window_days": 30,
        "resets_at": snapshot.reset_at,
        "unlimited": snapshot.limit is None,
    }


# ---------------------------------------------------------------------------
# The one tool that spends
# ---------------------------------------------------------------------------


def _audit_idempotency_key(principal: ExternalAPIPrincipal, project_id: int, tier: str) -> str:
    """A deterministic idempotency key for an agent-initiated audit.

    The single most expensive failure mode in this feature is a client that
    treats a slow or ambiguous response as a failure and calls again, paying
    for a second audit of the same target. MCP callers do not supply an
    idempotency key, so one is derived here instead of leaving the retry
    unprotected.

    The key covers the key's owner, the project, the tier and a ten-minute
    bucket. Within a bucket a repeated call replays the original job and
    spends nothing; a deliberate re-audit later lands in a new bucket and
    proceeds, because refusing that would be a different defect. The
    in-flight dedup in the launch path covers the whole duration of a running
    audit regardless of bucket, so the window only has to catch the retry
    that arrives after a job has already finished.
    """
    bucket = int(datetime.now(timezone.utc).timestamp() // 600)
    material = f"mcp:{principal.user.id}:{project_id}:{tier}:{bucket}"
    return "mcp-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


async def _handle_run_audit(ctx: ToolContext, args: RunAuditArgs) -> dict[str, Any]:
    """Start one audit of a project's own domain, or refuse it legibly."""
    project = _resolve_project(ctx, args.project_id)
    target_url = (project.domain_url or "").strip()
    if not target_url:
        raise McpProtocolError(
            MCP_ERROR_NOT_FOUND,
            "This project has no registered domain, so there is nothing to audit.",
        )

    payload = ExternalAuditCreateRequest(
        url=target_url,
        audit_target_type="website",
        tier=args.tier,
        project_id=project.id,
        language=project.language or None,
        market=project.target_country or None,
        idempotency_key=_audit_idempotency_key(ctx.principal, project.id, args.tier),
    )

    try:
        result = await launch_external_audit(
            payload=payload,
            principal=ctx.principal,
            correlation_id=ctx.correlation_id,
            db=ctx.db,
            redis_ctx=ctx.redis_ctx,
        )
    except HTTPException as exc:
        raise _audit_launch_refusal(ctx, exc) from exc

    # The job id is returned so the agent polls signal_get_scan_status rather
    # than calling this tool again to find out what happened.
    return {
        "job_id": result["job_id"],
        "project_id": project.id,
        "status": result.get("status", "queued"),
        "tier": args.tier,
        "target_url": target_url,
        "already_running": bool(result.get("idempotent_replay")),
        "estimated_completion_seconds": result.get("estimated_completion_seconds"),
        "poll_with": "signal_get_scan_status",
        "scan_allowance": _handle_get_scan_allowance(ctx, args),
    }


def _audit_launch_refusal(ctx: ToolContext, exc: HTTPException) -> McpProtocolError:
    """Turn a launch refusal into something a client stops on.

    An opaque error is what turns one refusal into a hundred attempts, so the
    allowance case says plainly that it is exhausted and when it resets. The
    reset time is read from the same snapshot the limiter counted, not
    recomputed, so the two cannot disagree.
    """
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("code") or "")
    message = _http_detail_message(exc)

    if exc.status_code == 402 and code == "SCAN_LIMIT_EXCEEDED":
        snapshot = scan_allowance_snapshot(ctx.db, ctx.principal.user)
        resets = (
            f" The allowance resets at {snapshot.reset_at}."
            if snapshot.reset_at
            else " The allowance resets as scans age out of the 30-day window."
        )
        return McpProtocolError(
            MCP_ERROR_FORBIDDEN,
            f"This workspace has used all {snapshot.limit} scans in its plan's rolling "
            f"30-day allowance, so no audit was started and nothing was charged.{resets} "
            "Do not retry until then: upgrading the plan or waiting for the reset is the "
            "only way to start another scan.",
            data={
                "reason": "scan_allowance_exhausted",
                "retryable": False,
                "scans_limit": snapshot.limit,
                "scans_used": snapshot.scans_used,
                "resets_at": snapshot.reset_at,
            },
        )

    if exc.status_code == 409 and code == "AUDIT_ALREADY_IN_PROGRESS":
        return McpProtocolError(
            MCP_ERROR_FORBIDDEN,
            "An audit of this project is already running, so a second one was not started "
            "and nothing was charged. Poll signal_get_scan_status instead of calling this "
            "tool again.",
            data={"reason": "audit_already_running", "retryable": False},
        )

    if exc.status_code == 402:
        return McpProtocolError(
            MCP_ERROR_FORBIDDEN,
            f"{message} No audit was started and nothing was charged.",
            data={"reason": "not_entitled", "retryable": False},
        )

    return McpProtocolError(MCP_ERROR_FORBIDDEN, message, data={"retryable": False})


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class McpTool:
    """One tool, with the scope it enforces and the model that validates it."""

    name: str
    title: str
    description: str
    scope: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict[str, Any] | Awaitable[dict[str, Any]]]
    # Whether calling this tool consumes one of the customer's scans. Declared
    # rather than inferred so the cost is visible in the registry, and checked
    # against the scope below: a tool cannot claim to be free and hold a write
    # scope, nor charge while holding only a read scope.
    consumes_scan: bool = False

    def __post_init__(self) -> None:
        # Import-time, so a tool guarded by an unknown scope cannot ship.
        assert_known_api_key_scope(self.scope)
        if self.consumes_scan and self.is_read_only:
            raise ValueError(
                f"{self.name} consumes a scan but holds the read scope {self.scope}. A tool "
                "that spends must hold a write scope, which is outside the default grant."
            )
        if self.consumes_scan and "scan allowance" not in self.description:
            raise ValueError(
                f"{self.name} consumes a scan without saying so in its description. A tool "
                "whose cost is discoverable only by running it is a trap for the agent and "
                "the customer."
            )

    @property
    def is_read_only(self) -> bool:
        return self.scope.endswith(":read")

    def input_schema(self) -> dict[str, Any]:
        """The published JSON Schema, generated from the validating model.

        Generated rather than written out, so the schema a client validates
        against and the model the server validates with cannot disagree.
        """
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema(),
            # Annotations are derived from the scope and the declared cost, not
            # written per tool, so none of them can describe a tool as safer
            # than it is. A client that asks the user to approve non-read-only
            # calls gets asked for exactly the tool that spends money.
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.is_read_only,
                # Nothing here deletes or overwrites anything; the write tool
                # creates a job.
                "destructiveHint": False,
                "idempotentHint": self.is_read_only,
                # The audit tool reaches out to the customer's own site.
                "openWorldHint": not self.is_read_only,
            },
        }


TOOL_REGISTRY: Final[tuple[McpTool, ...]] = (
    McpTool(
        name="signal_list_projects",
        title="List projects",
        description=(
            "List the Qiko Signal projects this API key can read, newest first. "
            "Returns each project's id, name, domain, country and language. Use it "
            "to find the project_id the other tools take."
        ),
        scope="projects:read",
        args_model=ListProjectsArgs,
        handler=_handle_list_projects,
    ),
    McpTool(
        name="signal_get_audit",
        title="Get an audit",
        description=(
            "Read one audit of a project: its SEO, GEO and AEO scores plus a single "
            "overall visibility score. Omit audit_id for the most recent audit. "
            "Competitor benchmark audits are excluded; these are the project's own "
            "measurements."
        ),
        scope="audit:read",
        args_model=GetAuditArgs,
        handler=_handle_get_audit,
    ),
    McpTool(
        name="signal_list_recommendations",
        title="List recommendations",
        description=(
            "List the recommendations raised for a project, in the order Signal ranks "
            "them, with each one's category, priority and whether it is still open. "
            "Returns the headline of each recommendation, not its full text."
        ),
        scope="projects:read",
        args_model=ListRecommendationsArgs,
        handler=_handle_list_recommendations,
    ),
    McpTool(
        name="signal_get_scan_status",
        title="Get scan status",
        description=(
            "Report the progress of a scan by its job id: whether it is queued, running, "
            "completed or failed, and its scores once it has finished. Use this to follow "
            "an audit started with signal_run_audit instead of starting another one."
        ),
        scope="audit:read",
        args_model=GetScanStatusArgs,
        handler=_handle_get_scan_status,
    ),
    McpTool(
        name="signal_get_project",
        title="Get a project",
        description=(
            "Read one project's details and the scores of its most recent audit, including "
            "that audit's id so it can be examined further. Use it to check a project's "
            "current standing in a single call."
        ),
        scope="projects:read",
        args_model=ProjectOnlyArgs,
        handler=_handle_get_project,
    ),
    McpTool(
        name="signal_list_audits",
        title="List audits",
        description=(
            "List a project's own audits, newest first, each with its id, tier, scores and "
            "completion time. Use it to see how a project's visibility has moved over time. "
            "Competitor benchmark audits are excluded."
        ),
        scope="audit:read",
        args_model=ListAuditsArgs,
        handler=_handle_list_audits,
    ),
    McpTool(
        name="signal_get_audit_breakdown",
        title="Get an audit's engine breakdown",
        description=(
            "Read one audit's per-engine detail: the SEO, AEO and GEO scores with the "
            "headline findings behind each. Omit audit_id for the most recent audit. Use it "
            "to explain why a score is what it is, rather than only what it is."
        ),
        scope="audit:read",
        args_model=GetAuditBreakdownArgs,
        handler=_handle_get_audit_breakdown,
    ),
    McpTool(
        name="signal_list_competitors",
        title="List competitors",
        description=(
            "List the competitors tracked for a project with each one's most recent SEO, "
            "AEO and GEO scores, so they can be compared against the project's own. "
            "Requires a plan that includes competitor analysis."
        ),
        scope="competitors:read",
        args_model=ProjectOnlyArgs,
        handler=_handle_list_competitors,
    ),
    McpTool(
        name="signal_list_schedules",
        title="List scheduled audits",
        description=(
            "List the recurring audit schedules this key can reach: how often each runs, "
            "whether it is active, and when it next runs. Omit project_id for every "
            "reachable project."
        ),
        scope="schedules:read",
        args_model=ListSchedulesArgs,
        handler=_handle_list_schedules,
    ),
    McpTool(
        name="signal_list_alerts",
        title="List alert rules",
        description=(
            "List a project's alert rules: which metric each one watches, its threshold, "
            "whether it is active and when it last fired."
        ),
        scope="alerts:read",
        args_model=ProjectOnlyArgs,
        handler=_handle_list_alerts,
    ),
    McpTool(
        name="signal_get_scan_allowance",
        title="Get the scan allowance",
        description=(
            "Report how many scans the plan allows, how many have been used in the current "
            "rolling 30-day window, how many remain and when the window resets. Call it "
            "before signal_run_audit to see whether a scan is available."
        ),
        scope="audit:read",
        args_model=ScanAllowanceArgs,
        handler=_handle_get_scan_allowance,
    ),
    # The only tool that spends. Its scope is outside the default grant, its
    # cost is in its own description, and its annotations say it is not a read.
    McpTool(
        name="signal_run_audit",
        title="Run an audit",
        description=(
            "Start a new audit of a project's registered domain. This consumes one scan "
            "from the customer's plan scan allowance and therefore costs them money, so "
            "only call it when the user has asked for a fresh audit; use signal_get_audit "
            "or signal_list_audits to read an existing one. The audit runs in the "
            "background: this returns a job id to follow with signal_get_scan_status. "
            "Calling it again for the same project within a few minutes returns the "
            "original job instead of starting a second paid audit, and it is refused "
            "outright when the allowance is exhausted or an audit is already running."
        ),
        scope="audit:write",
        args_model=RunAuditArgs,
        handler=_handle_run_audit,
        consumes_scan=True,
    ),
)

TOOLS_BY_NAME: Final[dict[str, McpTool]] = {tool.name: tool for tool in TOOL_REGISTRY}


def tool_scopes() -> tuple[str, ...]:
    """Every scope the tool registry enforces, in registry order."""
    return tuple(dict.fromkeys(tool.scope for tool in TOOL_REGISTRY))


def tool_descriptors() -> list[dict[str, Any]]:
    return [tool.descriptor() for tool in TOOL_REGISTRY]


def server_capabilities() -> dict[str, Any]:
    """What this server offers. Tools only: no prompts, resources or sampling."""
    return {"tools": {"listChanged": False}}


def negotiate_protocol_version(requested: str | None) -> str:
    """Answer with the requested revision when supported, else with the newest."""
    candidate = (requested or "").strip()
    if candidate in SUPPORTED_PROTOCOL_VERSIONS:
        return candidate
    return LATEST_PROTOCOL_VERSION


def instructions() -> str:
    """Server instructions, stated so an agent does not infer a wider remit.

    A client passes this to the model as standing guidance, so the one tool
    that costs money is named here rather than left to be discovered from a
    tool list. The names of the spending tools are derived from the registry,
    so this text cannot keep describing a read-only server after a second
    write tool is added.
    """
    spending = [tool.name for tool in TOOL_REGISTRY if tool.consumes_scan]
    cost_sentence = (
        f"{' and '.join(spending)} starts a new audit and consumes one scan from the "
        "customer's plan allowance, so it costs them money: only call it when the user "
        "has asked for a fresh audit, and read existing results with signal_get_audit "
        "or signal_list_audits instead. Every other tool only reads and is free."
        if spending
        else "Every tool here only reads and none of them can spend the customer's money."
    )
    return (
        "Qiko Signal exposes SEO, AEO and GEO visibility data for the projects this API "
        "key can reach, and can start a new audit of one of them. Call "
        "signal_list_projects first to get a project_id. "
        f"{cost_sentence} "
        "After starting an audit, follow it with signal_get_scan_status rather than "
        "starting another. This server can only see the workspaces the key belongs to, "
        "and it can only audit a project's own registered domain."
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _http_detail_message(exc: HTTPException) -> str:
    """The human-readable sentence out of an ``external_error`` envelope.

    The REST surface answers failures as ``{"code", "message", "status"}``, and
    the MCP surface has to carry the same refusal inside a JSON-RPC error
    object. Reading the shared envelope means a refusal is worded once, in the
    service that decided it, rather than once per transport.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return str(detail) if detail else "The request was refused."


def _validation_message(error: ValidationError) -> str:
    """One readable sentence from a pydantic failure, with no internals."""
    parts: list[str] = []
    for item in error.errors()[:5]:
        location = ".".join(str(piece) for piece in item.get("loc", ())) or "arguments"
        parts.append(f"{location}: {item.get('msg', 'is invalid')}")
    return "Invalid tool arguments. " + "; ".join(parts)


async def call_tool(
    *,
    ctx: ToolContext,
    name: str,
    arguments: Any,
) -> dict[str, Any]:
    """Authorize, validate and run one tool call, returning an MCP tool result.

    The order is deliberate: the tool must exist, the key must hold the tool's
    scope, and only then are the arguments validated. Authorizing first means
    a caller who may not use a tool learns nothing about its arguments, and
    neither check can be reached by a query.
    """
    tool = TOOLS_BY_NAME.get(str(name or ""))
    if tool is None:
        raise McpProtocolError(JSONRPC_METHOD_NOT_FOUND, f"Unknown tool: {name}.")

    try:
        require_principal_scope(ctx.principal, tool.scope)
    except HTTPException as exc:
        raise McpProtocolError(MCP_ERROR_FORBIDDEN, _http_detail_message(exc)) from exc

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise McpProtocolError(JSONRPC_INVALID_PARAMS, "Tool arguments must be an object.")

    try:
        args = tool.args_model.model_validate(arguments)
    except ValidationError as exc:
        raise McpProtocolError(JSONRPC_INVALID_PARAMS, _validation_message(exc)) from exc

    # Handlers may be sync or async; the one that launches an audit is async
    # because the launch path writes to Redis.
    payload = tool.handler(ctx, args)
    if inspect.isawaitable(payload):
        payload = await payload

    logger.info(
        "mcp.tool_called tool=%s api_key_id=%s plan=%s consumes_scan=%s",
        tool.name,
        ctx.principal.api_key.id,
        ctx.principal.plan,
        tool.consumes_scan,
    )
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str, sort_keys=True)}],
        "structuredContent": payload,
        "isError": False,
    }
