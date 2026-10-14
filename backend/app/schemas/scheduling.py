from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_target_type(value: Any) -> str:
    normalized = str(value or "website").strip().lower()
    return normalized if normalized in {"website", "brand"} else "website"


def _normalize_model_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        candidate = str(item).strip().lower()
        if candidate:
            normalized.append(candidate)
    return normalized


def _normalize_entity_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        candidate = str(item).strip()
        if candidate:
            normalized.append(candidate)
    return normalized


class ScheduledAuditConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = "google"
    tier: str = "fast"
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_metadata: dict[str, Any] | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    entities: list[str] = Field(default_factory=list)
    selected_models: list[str] = Field(default_factory=list)
    brand_truth_payload: dict[str, Any] | None = None

    @field_validator(
        "provider", "tier", "category", "market", "language", "target_name", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        return _normalize_optional_string(value)

    @field_validator("audit_target_type", mode="before")
    @classmethod
    def normalize_target_type(cls, value: Any) -> str:
        return _normalize_target_type(value)

    @field_validator("selected_models", mode="before")
    @classmethod
    def normalize_selected_models(cls, value: Any) -> list[str]:
        return _normalize_model_list(value)

    @field_validator("entities", mode="before")
    @classmethod
    def normalize_entities(cls, value: Any) -> list[str]:
        return _normalize_entity_list(value)

    @model_validator(mode="after")
    def normalize_target_contract(self) -> "ScheduledAuditConfig":
        if self.audit_target_type == "website":
            self.target_name = None
            self.target_metadata = {}
        return self


class ScheduledAuditConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str | None = None
    tier: str | None = None
    audit_target_type: Literal["website", "brand"] | None = None
    target_name: str | None = None
    target_metadata: dict[str, Any] | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    entities: list[str] | None = None
    selected_models: list[str] | None = None
    brand_truth_payload: dict[str, Any] | None = None

    @field_validator(
        "provider", "tier", "category", "market", "language", "target_name", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        return _normalize_optional_string(value)

    @field_validator("audit_target_type", mode="before")
    @classmethod
    def normalize_target_type(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _normalize_target_type(value)

    @field_validator("selected_models", mode="before")
    @classmethod
    def normalize_selected_models(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        return _normalize_model_list(value)

    @field_validator("entities", mode="before")
    @classmethod
    def normalize_entities(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        return _normalize_entity_list(value)


def merge_scheduled_audit_config(
    existing: ScheduledAuditConfig | dict[str, Any] | None,
    patch: ScheduledAuditConfigUpdate | ScheduledAuditConfig | dict[str, Any] | None,
) -> ScheduledAuditConfig:
    base_payload = (
        existing.model_dump()
        if isinstance(existing, ScheduledAuditConfig)
        else dict(existing or {})
    )
    patch_payload = (
        patch.model_dump(exclude_unset=True)
        if isinstance(patch, ScheduledAuditConfigUpdate)
        else patch.model_dump()
        if isinstance(patch, ScheduledAuditConfig)
        else dict(patch or {})
    )
    return ScheduledAuditConfig.model_validate({**base_payload, **patch_payload})


def resolve_scheduled_audit_target_contract(
    *,
    url: str | None,
    project_id: int | None,
    site_id: int | None,
    audit_params: ScheduledAuditConfig | dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_url = _normalize_optional_string(url)
    normalized_config = (
        audit_params
        if isinstance(audit_params, ScheduledAuditConfig)
        else ScheduledAuditConfig.model_validate(audit_params or {})
    )

    if project_id is None and site_id is None:
        raise ValueError("Either project_id or site_id must be provided.")

    if normalized_config.audit_target_type == "brand":
        if not normalized_config.target_name:
            raise ValueError("Brand scheduled audits require audit_params.target_name.")
    elif not normalized_url:
        raise ValueError("Website scheduled audits require a url.")

    return {
        "url": normalized_url,
        "project_id": project_id,
        "site_id": site_id,
        "audit_params": normalized_config,
        "audit_target_type": normalized_config.audit_target_type,
        "target_name": normalized_config.target_name,
        "target_metadata": normalized_config.target_metadata or {},
    }


class ScheduledAuditBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    project_id: int | None = None
    site_id: int | None = None
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP", "DEEP_JUDGMENT"] = "STANDARD"
    frequency: Literal["weekly", "monthly"] = "weekly"
    audit_params: ScheduledAuditConfig = Field(default_factory=ScheduledAuditConfig)
    is_active: bool = True

    @field_validator("url", mode="before")
    @classmethod
    def normalize_url(cls, value: Any) -> str | None:
        return _normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_target(self) -> "ScheduledAuditBase":
        resolved = resolve_scheduled_audit_target_contract(
            url=self.url,
            project_id=self.project_id,
            site_id=self.site_id,
            audit_params=self.audit_params,
        )
        self.url = resolved["url"]
        self.audit_params = resolved["audit_params"]
        return self


class ScheduledAuditCreate(ScheduledAuditBase):
    pass


class ScheduledAuditUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    project_id: int | None = None
    site_id: int | None = None
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP", "DEEP_JUDGMENT"] | None = None
    is_active: bool | None = None
    frequency: Literal["weekly", "monthly"] | None = None
    audit_params: ScheduledAuditConfigUpdate | None = None

    @field_validator("url", mode="before")
    @classmethod
    def normalize_optional_url(cls, value: Any) -> str | None:
        return _normalize_optional_string(value)


class ScheduledAuditResponse(ScheduledAuditBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    paused_reason: str | None = None
    last_run_status: str | None = None
    last_job_id: str | None = None
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
