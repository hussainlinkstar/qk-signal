from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

JobStatus = Literal["queued", "running", "succeeded", "failed"]

JOB_STATUS_QUEUED: JobStatus = "queued"
JOB_STATUS_RUNNING: JobStatus = "running"
JOB_STATUS_SUCCEEDED: JobStatus = "succeeded"
JOB_STATUS_FAILED: JobStatus = "failed"

JOB_STATUS_LIFECYCLE = {
    JOB_STATUS_QUEUED: "created_at",
    JOB_STATUS_RUNNING: "started_at",
    JOB_STATUS_SUCCEEDED: "completed_at",
    JOB_STATUS_FAILED: "completed_at",
}


@dataclass(frozen=True)
class AuditJobPayload:
    job_id: str
    request_id: str
    user_id: int
    url: str
    provider: str
    tier: str
    requested_tier: str | None = None
    mode_label: str | None = None
    audit_target_type: str = "website"
    target_name: str | None = None
    target_url: str | None = None
    target_metadata: dict[str, Any] | None = None
    tier_class: str | None = None
    routing_feature_key: str | None = None
    routing_mode: str | None = None
    routing_preferred_provider: str | None = None
    routing_reason: str | None = None
    project_id: int | None = None
    scheduled_audit_id: int | None = None
    charge_credits: bool = True
    estimated_credit_cost: int = 1
    cost_forecast: dict[str, Any] | None = None
    brand_truth_payload: dict[str, Any] | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    entities: list[str] | None = None
    selected_models: list[str] | None = None
    source_audit_id: int | None = None
    project_competitor_id: int | None = None
    sitemap_crawl_job_id: str | None = None
    site_structure_summary: str | None = None
    # SIGV2-1117: whose target this job measures relative to ``project_id``
    # ("project" or "competitor"). Declared by the enqueueing code so the audit
    # row is classified from intent rather than inferred after the fact.
    project_scope: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_job_payload(payload: dict) -> AuditJobPayload:
    resolved_url = str(payload.get("url") or payload.get("target_url") or "").strip()
    resolved_target_type = (
        str(payload.get("audit_target_type") or "website").strip().lower() or "website"
    )
    if resolved_target_type not in {"website", "brand"}:
        resolved_target_type = "website"
    missing = [
        key for key in ("job_id", "request_id", "user_id", "provider", "tier") if key not in payload
    ]
    if resolved_target_type == "brand":
        resolved_target_name = str(payload.get("target_name") or "").strip()
        if not resolved_target_name:
            missing.append("target_name")
    elif not resolved_url:
        missing.append("url")
    if missing:
        raise ValueError(f"Payload missing required fields: {', '.join(missing)}")
    return AuditJobPayload(
        job_id=str(payload["job_id"]),
        request_id=str(payload["request_id"]),
        user_id=int(payload["user_id"]),
        url=resolved_url,
        audit_target_type=resolved_target_type,
        target_name=(
            str(payload["target_name"]).strip()
            if isinstance(payload.get("target_name"), str)
            and payload.get("target_name", "").strip()
            else None
        ),
        target_url=(
            str(payload["target_url"]).strip()
            if isinstance(payload.get("target_url"), str) and payload.get("target_url", "").strip()
            else None
        ),
        target_metadata=(
            payload.get("target_metadata")
            if isinstance(payload.get("target_metadata"), dict)
            else None
        ),
        provider=str(payload["provider"]),
        tier=str(payload["tier"]),
        requested_tier=(
            str(payload["requested_tier"]).strip().lower()
            if isinstance(payload.get("requested_tier"), str)
            and payload.get("requested_tier", "").strip()
            else None
        ),
        mode_label=(
            str(payload["mode_label"]).strip()
            if isinstance(payload.get("mode_label"), str) and payload.get("mode_label", "").strip()
            else None
        ),
        tier_class=(
            str(payload["tier_class"]).strip().lower()
            if isinstance(payload.get("tier_class"), str) and payload.get("tier_class", "").strip()
            else None
        ),
        routing_feature_key=(
            str(payload["routing_feature_key"]).strip()
            if isinstance(payload.get("routing_feature_key"), str)
            and payload.get("routing_feature_key", "").strip()
            else None
        ),
        routing_mode=(
            str(payload["routing_mode"]).strip()
            if isinstance(payload.get("routing_mode"), str)
            and payload.get("routing_mode", "").strip()
            else None
        ),
        routing_preferred_provider=(
            str(payload["routing_preferred_provider"]).strip().lower()
            if isinstance(payload.get("routing_preferred_provider"), str)
            and payload.get("routing_preferred_provider", "").strip()
            else None
        ),
        routing_reason=(
            str(payload["routing_reason"]).strip()
            if isinstance(payload.get("routing_reason"), str)
            and payload.get("routing_reason", "").strip()
            else None
        ),
        project_id=int(payload["project_id"]) if payload.get("project_id") is not None else None,
        scheduled_audit_id=(
            int(payload["scheduled_audit_id"])
            if payload.get("scheduled_audit_id") is not None
            else None
        ),
        charge_credits=bool(payload.get("charge_credits", True)),
        estimated_credit_cost=max(1, int(payload.get("estimated_credit_cost") or 1)),
        cost_forecast=payload.get("cost_forecast")
        if isinstance(payload.get("cost_forecast"), dict)
        else None,
        brand_truth_payload=(
            payload.get("brand_truth_payload")
            if isinstance(payload.get("brand_truth_payload"), dict)
            else None
        ),
        category=(
            str(payload["category"]).strip()
            if isinstance(payload.get("category"), str) and payload.get("category", "").strip()
            else None
        ),
        market=(
            str(payload["market"]).strip()
            if isinstance(payload.get("market"), str) and payload.get("market", "").strip()
            else None
        ),
        language=(
            str(payload["language"]).strip()
            if isinstance(payload.get("language"), str) and payload.get("language", "").strip()
            else None
        ),
        entities=[
            str(entity).strip() for entity in payload.get("entities", []) if str(entity).strip()
        ]
        if isinstance(payload.get("entities"), list)
        else None,
        selected_models=[
            str(m).strip().lower() for m in payload.get("selected_models", []) if str(m).strip()
        ]
        or None
        if isinstance(payload.get("selected_models"), list)
        else None,
        source_audit_id=int(payload["source_audit_id"])
        if payload.get("source_audit_id") is not None
        else None,
        project_competitor_id=(
            int(payload["project_competitor_id"])
            if payload.get("project_competitor_id") is not None
            else None
        ),
        sitemap_crawl_job_id=(
            str(payload["sitemap_crawl_job_id"]).strip()
            if isinstance(payload.get("sitemap_crawl_job_id"), str)
            and payload.get("sitemap_crawl_job_id", "").strip()
            else None
        ),
        site_structure_summary=(
            str(payload["site_structure_summary"])
            if isinstance(payload.get("site_structure_summary"), str)
            and payload.get("site_structure_summary", "").strip()
            else None
        ),
        project_scope=(
            str(payload["project_scope"]).strip().lower()
            if isinstance(payload.get("project_scope"), str)
            and payload.get("project_scope", "").strip()
            else None
        ),
    )


@dataclass(frozen=True)
class PDFJobPayload:
    job_id: str
    user_id: int
    template_type: Literal["Technical", "Executive", "Comparative"]
    audit_ids: list[int]
    options: dict[str, Any]
    branding_config: dict[str, Any]
    export_manifest: dict[str, Any] | None = None
    language: str = "en"
    primary_audit_id: int | None = None
    competitor_audit_ids: list[int] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_pdf_job_payload(payload: dict) -> PDFJobPayload:
    missing = [
        key for key in ("job_id", "user_id", "template_type", "audit_ids") if key not in payload
    ]
    if missing:
        raise ValueError(f"PDF Payload missing required fields: {', '.join(missing)}")
    return PDFJobPayload(
        job_id=str(payload["job_id"]),
        user_id=int(payload["user_id"]),
        template_type=payload["template_type"],
        audit_ids=list(payload["audit_ids"]),
        options=dict(payload.get("options", {})),
        branding_config=dict(payload.get("branding_config", {})),
        export_manifest=dict(payload.get("export_manifest", {}))
        if isinstance(payload.get("export_manifest"), dict)
        else None,
        language=str(payload.get("language") or "en").strip().lower() or "en",
        primary_audit_id=int(payload["primary_audit_id"])
        if payload.get("primary_audit_id")
        else None,
        competitor_audit_ids=list(payload["competitor_audit_ids"])
        if payload.get("competitor_audit_ids")
        else None,
    )
