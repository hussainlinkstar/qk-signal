from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.audit import AuditResult


class AuditResultSchema(BaseModel):
    """FastAPI response schema using the canonical audit result model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result: AuditResult


class AuditResultJSONSchema(BaseModel):
    """JSONB-friendly payload schema for persistence and report generation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    payload: AuditResult


__all__ = ["AuditResultJSONSchema", "AuditResultSchema", "AuditResult"]
