from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


WorkflowTriggerType = Literal[
    "platform_event", "audit_completed", "metric_threshold", "alert_triggered"
]
WorkflowActionType = Literal[
    "send_email",
    "send_slack",
    "send_teams",
    "webhook",
    "run_audit",
    "create_jira_ticket",
]
WorkflowRunStatus = Literal["running", "completed", "partial_failure", "failed"]


class WorkflowTriggerConfig(BaseModel):
    type: WorkflowTriggerType
    event_key: str | None = Field(default=None, max_length=120)
    event_keys: list[str] = Field(default_factory=list, max_length=20)
    metric: str | None = Field(default=None, max_length=120)
    condition: Literal["below", "above", "drops_by"] | None = None
    value: float | None = None
    audit_tier: str | None = Field(default=None, max_length=32)

    @field_validator("event_key", "metric", "audit_tier")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowActionConfig(BaseModel):
    type: WorkflowActionType
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    trigger_config: WorkflowTriggerConfig
    actions_config: list[WorkflowActionConfig] = Field(min_length=1, max_length=8)
    cooldown_minutes: int = Field(default=1440, ge=0, le=10080)
    is_active: bool = True

    @field_validator("name", "description")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized and value is not None:
            return None
        return normalized


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    trigger_config: WorkflowTriggerConfig | None = None
    actions_config: list[WorkflowActionConfig] | None = Field(
        default=None, min_length=1, max_length=8
    )
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)
    is_active: bool | None = None

    @field_validator("name", "description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowResponse(BaseModel):
    id: int
    workspace_id: int
    project_id: int | None
    name: str
    description: str | None
    trigger_config: dict[str, Any]
    actions_config: list[dict[str, Any]]
    cooldown_minutes: int
    is_active: bool
    last_triggered_at: str | None
    created_at: str | None
    updated_at: str | None


class WorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    triggered_at: str | None
    trigger_event: str
    trigger_context: dict[str, Any]
    status: WorkflowRunStatus | str
    action_results: list[dict[str, Any]]
    completed_at: str | None


class WorkflowTestRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestResponse(BaseModel):
    run: WorkflowRunResponse
