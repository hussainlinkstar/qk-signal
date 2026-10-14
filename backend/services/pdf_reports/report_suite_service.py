from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from services.ai_client import AIClient
from services.audit_data_sources import resolve_project_audit_data_sources
from services.audit_normalization_service import (
    build_normalized_audit_report,
    resolve_audit_normalization_current_plan,
)
from services.pdf_report_renderer import (
    BrandingConfig,
    render_battle_report_pdf,
    render_white_label_pdf,
)
from services.pdf_reports.assembler import (
    resolve_effective_export_manifest,
    resolve_report_type,
)
from services.audit_feature_gating_service import (
    can_use_feature,
    normalize_plan_for_audit_gating,
)
from services.pdf_reports.battle_seed import build_canonical_competitor_battle_pair
from services.project_competitive_service import (
    build_project_competitive_analysis,
    build_project_competitive_trends,
    list_project_competitors,
)
from services.project_task_service import (
    build_project_task_impact_payload,
    build_project_task_summary,
    sync_project_tasks,
)
from services.project_visibility_service import (
    PENDING_BATCH_STATUSES,
    SUPPORTED_VISIBILITY_PROVIDERS,
    VISIBILITY_PROVIDER_LABELS,
)
from services.report_i18n_service import (
    get_report_label,
    normalize_report_language,
)
from services.reports.audit_result_adapter import extract_normalized_recommendation_texts

DEFAULT_AI_PROVIDER = "google"
DEFAULT_AI_TIER = "fast"
PLACEHOLDER_SCREENSHOT_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

_REPORT_SECTION_KEY_MAP = {
    "overview": ["metadata", "summary", "analysis", "scores"],
    "geo": ["geo", "geo_analysis"],
    "seo": ["seo", "seo_analysis"],
    "aeo": ["aeo", "answerability"],
    "cwv": ["performance", "core_web_vitals"],
    "ai": ["ai_strategic_insights", "ai", "analysis"],
    "competitors": ["competitors", "competitive_analysis", "benchmark"],
}
_AI_SUMMARY_ENABLED_REPORT_KINDS = {"standard", "executive", "competitors"}
_TREND_METRICS = ("overall", "seo", "geo", "aeo")

ai_client = AIClient()


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            resolved = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
        value = resolved
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_score_breakdown(candidate: dict | None) -> dict[str, float] | None:
    if not isinstance(candidate, dict):
        return None
    if not {"seo", "geo", "aeo"}.issubset(candidate.keys()):
        return None
    score_breakdown = {
        "seo": float(candidate.get("seo") or 0.0),
        "geo": float(candidate.get("geo") or 0.0),
        "aeo": float(candidate.get("aeo") or 0.0),
    }
    score_breakdown["overall"] = float(
        candidate.get("overall")
        if candidate.get("overall") is not None
        else (score_breakdown["seo"] + score_breakdown["geo"] + score_breakdown["aeo"]) / 3
    )
    return score_breakdown


def _extract_score_breakdown_from_report(full_report: dict | None) -> dict[str, float]:
    if not isinstance(full_report, dict):
        return {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0}

    report_scores = _coerce_score_breakdown(full_report.get("scores"))
    if report_scores is not None:
        return report_scores

    analysis = full_report.get("analysis") if isinstance(full_report.get("analysis"), dict) else {}

    def _score(key: str) -> float:
        try:
            return float(analysis.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    score_breakdown = {
        "seo": _score("seo_score"),
        "geo": _score("geo_score"),
        "aeo": _score("aeo_score"),
    }
    score_breakdown["overall"] = (
        score_breakdown["seo"] + score_breakdown["geo"] + score_breakdown["aeo"]
    ) / 3
    return score_breakdown


def _resolve_report_language_for_audits(
    audits: Sequence[models.Audit],
    *,
    explicit_language: str | None = None,
) -> str:
    if explicit_language:
        return normalize_report_language(explicit_language)

    for audit in audits:
        project_language = _text(getattr(getattr(audit, "project", None), "language", None))
        if project_language:
            return normalize_report_language(project_language)

        full_report = audit.full_report if isinstance(audit.full_report, dict) else {}
        metadata = (
            full_report.get("metadata") if isinstance(full_report.get("metadata"), dict) else {}
        )
        target = full_report.get("target") if isinstance(full_report.get("target"), dict) else {}
        target_metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        for candidate in (
            metadata.get("language"),
            target_metadata.get("language"),
            getattr(audit, "target_metadata", {}).get("language")
            if isinstance(getattr(audit, "target_metadata", None), dict)
            else None,
        ):
            normalized = _text(candidate)
            if normalized:
                return normalize_report_language(normalized)

    return "en"


def _apply_complex_report_sections(
    full_report: dict[str, Any], sections: Sequence[str]
) -> dict[str, Any]:
    if not isinstance(full_report, dict):
        return {}

    filtered: dict[str, Any] = {}
    for section in sections:
        for report_key in _REPORT_SECTION_KEY_MAP.get(section, []):
            if report_key in full_report:
                filtered[report_key] = full_report[report_key]
    return filtered


def _series_delta(points: Sequence[dict[str, Any]], key: str) -> float | None:
    if len(points) < 2:
        return None
    first = _float(points[0].get(key))
    last = _float(points[-1].get(key))
    if first is None or last is None:
        return None
    return round(last - first, 2)


def _timeline_points_for_audits(audits: Sequence[models.Audit]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for audit in sorted(
        [audit for audit in audits if audit.created_at is not None],
        key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.id),
    ):
        scores = _extract_score_breakdown_from_report(
            audit.full_report if isinstance(audit.full_report, dict) else {}
        )
        created_at = _as_utc_datetime(audit.created_at)
        if created_at is None:
            continue
        points.append(
            {
                "date": created_at.isoformat(),
                "overall": scores["overall"],
                "seo": scores["seo"],
                "geo": scores["geo"],
                "aeo": scores["aeo"],
            }
        )
    return points


def should_generate_ai_summary(report_kind: str | None) -> bool:
    normalized = _text(report_kind).lower()
    return normalized in _AI_SUMMARY_ENABLED_REPORT_KINDS


async def build_report_summary_text(
    *,
    template_type: str,
    audits: list[models.Audit],
    language: str = "en",
) -> str:
    if not audits:
        return "No audits were selected for this report."

    scores = [
        _extract_score_breakdown_from_report(
            audit.full_report if isinstance(audit.full_report, dict) else {}
        )
        for audit in audits
    ]
    seo_avg = sum(item["seo"] for item in scores) / len(scores)
    geo_avg = sum(item["geo"] for item in scores) / len(scores)
    aeo_avg = sum(item["aeo"] for item in scores) / len(scores)
    resolved_language = normalize_report_language(language)

    prompt = (
        f"Write a concise 3-4 paragraph executive summary in {resolved_language} for a GEO/SEO/AEO report. "
        f"Template: {template_type}. "
        f"Audits analyzed: {len(audits)}. "
        f"Average SEO score: {seo_avg:.1f}. Average GEO score: {geo_avg:.1f}. "
        f"Average AEO score: {aeo_avg:.1f}. "
        "Keep technical SEO, GEO, AEO, SERP, and LLM terms in English. "
        f"Ensure the text is natural and grammatically correct in {resolved_language}. "
        "Focus on trend direction, competitive posture, and next-quarter priorities."
    )

    try:
        ai_response = await ai_client.generate_audit(
            provider=DEFAULT_AI_PROVIDER,
            tier=DEFAULT_AI_TIER,
            content=prompt,
            screenshot_base64=PLACEHOLDER_SCREENSHOT_BASE64,
            network_data={},
        )
    except Exception:
        return (
            f"Across {len(audits)} audits, the site averaged SEO {seo_avg:.1f}, GEO {geo_avg:.1f}, "
            f"and AEO {aeo_avg:.1f}. Prioritize structured content improvements and citation growth "
            "to strengthen AI-search visibility over the next reporting cycle."
        )

    analysis = ai_response.get("analysis") if isinstance(ai_response, dict) else None
    if isinstance(analysis, dict):
        summary = analysis.get("summary") or analysis.get("executive_summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()

    return (
        f"Across {len(audits)} audits, the site averaged SEO {seo_avg:.1f}, GEO {geo_avg:.1f}, "
        f"and AEO {aeo_avg:.1f}. The score profile is stable with room to improve answerability and "
        "competitive citation share in high-intent queries."
    )


def build_report_branding_config(
    *,
    persisted_branding: Mapping[str, Any] | None,
    export_manifest: Mapping[str, Any],
    template_type: str,
    language: str,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = {
        **_mapping(persisted_branding),
        **_mapping(overrides),
    }
    resolved_report_type = str(
        export_manifest.get("render_report_type")
        or merged.get("report_type")
        or resolve_report_type(
            explicit_report_kind=_text(export_manifest.get("report_kind")) or None,
            explicit_branding_mode=_text(export_manifest.get("branding_mode")) or None,
            explicit_report_type=_text(merged.get("report_type")) or None,
            template_type=template_type,
            agency_branding_data=merged,
        )
    )
    generated_date = _text(merged.get("generated_date") or merged.get("report_date"))
    return {
        **merged,
        "template_type": template_type,
        "language": language,
        "report_type": resolved_report_type,
        "report_kind": str(export_manifest.get("report_kind") or ""),
        "branding_mode": str(export_manifest.get("branding_mode") or ""),
        "competitor_mode": str(export_manifest.get("competitor_mode") or "") or None,
        "hide_credit_cost": bool(export_manifest.get("hide_credit_cost", True)),
        "footer_text": merged.get("footer_text"),
        "is_white_label": (
            str(export_manifest.get("branding_mode") or "").strip().lower() == "white_label"
            or resolved_report_type == "whitelabel"
        ),
        "company_name": merged.get("agency_name") or merged.get("company_name"),
        "primary_color": merged.get("primary_color"),
        "secondary_color": merged.get("secondary_color"),
        "custom_logo_url": merged.get("logo_data_url") or merged.get("custom_logo_url"),
        "title": merged.get("title"),
        "generated_date": generated_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def _build_branding_contract(
    *,
    resolved_export_manifest: Mapping[str, Any],
    template_type: str,
    options: Mapping[str, Any],
    branding_config: Mapping[str, Any] | None,
    report_language: str,
) -> BrandingConfig:
    persisted_branding = _mapping(branding_config)
    resolved_report_type = str(
        resolved_export_manifest.get("render_report_type")
        or persisted_branding.get("report_type")
        or "standard"
    )
    if resolved_report_type == "battle":
        default_title = get_report_label(
            report_language, "pdf.battle_report", default="Battle Report"
        )
    else:
        default_title = get_report_label(
            report_language,
            f"pdf.{str(template_type).lower()}_report",
            default=f"{template_type} Report",
        )
    return BrandingConfig(
        title=str(persisted_branding.get("title") or default_title),
        primary_color=_text(
            _mapping(options).get("primary_color")
            or persisted_branding.get("primary_color")
            or "#0EA5E9"
        ),
        secondary_color=_text(
            _mapping(options).get("secondary_color")
            or persisted_branding.get("secondary_color")
            or "#E2E8F0"
        ),
        company_name=_text(
            persisted_branding.get("company_name") or persisted_branding.get("agency_name")
        )
        or None,
        generated_date=_text(
            persisted_branding.get("generated_date")
            or persisted_branding.get("report_date")
            or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ),
        logo_data_url=_text(
            persisted_branding.get("custom_logo_url") or persisted_branding.get("logo_data_url")
        )
        or None,
        language=report_language,
        vendor_name="Qiko Signal",
        is_white_label=resolved_report_type == "whitelabel",
        show_powered_by=(
            resolved_report_type == "branded"
            and not bool(persisted_branding.get("hide_powered_by"))
        ),
        report_type=resolved_report_type,
        report_kind=str(resolved_export_manifest.get("report_kind") or ""),
        branding_mode=str(resolved_export_manifest.get("branding_mode") or ""),
        competitor_mode=_text(resolved_export_manifest.get("competitor_mode")) or None,
        hide_credit_cost=bool(resolved_export_manifest.get("hide_credit_cost", True)),
        footer_text=_text(
            _mapping(options).get("footer_text") or persisted_branding.get("footer_text")
        )
        or None,
        custom_footer_text=_text(
            _mapping(options).get("footer_text") or persisted_branding.get("footer_text")
        )
        or None,
        show_platform_branding=resolved_report_type != "whitelabel",
    )


def _seed_report_suite_metadata(
    payload: dict[str, Any], *, report_suite: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = _mapping(payload.get("metadata"))
    metadata["report_suite"] = deepcopy(_mapping(report_suite))
    payload["metadata"] = metadata
    return payload


def _build_executive_blueprint_payload(
    db: Session,
    *,
    audit: models.Audit,
) -> dict[str, Any]:
    project = getattr(audit, "project", None)
    target_metadata = (
        dict(audit.target_metadata)
        if isinstance(getattr(audit, "target_metadata", None), dict)
        else {}
    )
    sources_context: dict[str, Any] = {}
    source_warnings: list[str] = []
    if getattr(audit, "project_id", None):
        sources_context, source_warnings = resolve_project_audit_data_sources(
            db,
            project_id=int(audit.project_id),
        )

    active_sources = [
        {
            "label": (
                _text(item.get("source_label"))
                or _text(item.get("source_type")).replace("_", " ").title()
            ),
            "mode": _text(item.get("effective_binding_mode")).replace("_", " ").title(),
            "provider": _text(item.get("provider")).upper(),
        }
        for item in sources_context.get("sources", [])
        if isinstance(item, Mapping) and bool(item.get("has_external_data"))
    ]
    supporting_references = []
    for key, value in target_metadata.items():
        if isinstance(value, (str, int, float)) and _text(value):
            supporting_references.append(
                {
                    "label": str(key).replace("_", " ").title(),
                    "value": _text(value),
                }
            )
    if not supporting_references:
        supporting_references.append(
            {
                "label": "Audit target",
                "value": _text(audit.target_name or audit.target_url or audit.url),
            }
        )

    icp_roles = []
    if project is not None and isinstance(getattr(project, "icp_roles", None), list):
        icp_roles = [_text(item) for item in project.icp_roles if _text(item)]
    usp = _text(getattr(project, "usp", None))
    return {
        "target_name": _text(audit.target_name or audit.target_url or audit.url),
        "target_url": _text(audit.target_url or audit.url),
        "target_type": _text(
            getattr(
                getattr(audit, "audit_target_type", None),
                "value",
                getattr(audit, "audit_target_type", None),
            ),
            "website",
        ),
        "project_name": _text(getattr(project, "name", None)),
        "project_language": _text(getattr(project, "language", None)),
        "market": _text(
            getattr(project, "target_country", None) or target_metadata.get("target_country")
        ),
        "icp_roles": icp_roles,
        "usp": usp,
        "active_sources": active_sources,
        "source_warnings": source_warnings,
        "supporting_references": supporting_references[:8],
        "has_ground_truth": bool(supporting_references),
    }


def _round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _metric_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(float(current) - float(previous), 2)


def _metric_direction(delta: float | None) -> str:
    if delta is None:
        return "stable"
    if delta > 1:
        return "up"
    if delta < -1:
        return "down"
    return "stable"


def _score_snapshot_for_audit(audit: models.Audit) -> dict[str, float | None]:
    normalized = build_normalized_audit_report(
        audit,
        current_plan=resolve_audit_normalization_current_plan(audit.user),
    )
    return {
        "seo": _float(_mapping(normalized.get("scores")).get("seo")),
        "geo": _float(_mapping(normalized.get("scores")).get("geo")),
        "aeo": _float(_mapping(normalized.get("scores")).get("aeo")),
        "overall": _float(_mapping(normalized.get("scores")).get("overall")),
    }


def _build_project_interval_payload(
    db: Session,
    *,
    project_id: int,
    selected_audits: Sequence[models.Audit],
) -> dict[str, Any]:
    ordered_audits = sorted(
        [audit for audit in selected_audits if audit.created_at is not None],
        key=lambda audit: (audit.created_at or datetime.min.replace(tzinfo=timezone.utc), audit.id),
    )
    if not ordered_audits:
        return {
            "audit_count": 0,
            "trend_points": [],
            "task_status_summary": {},
            "task_movement": {"new": 0, "resolved": 0, "validated": 0},
            "validated_impact": [],
            "remaining_issues": [],
        }

    first_audit = ordered_audits[0]
    latest_audit = ordered_audits[-1]
    first_scores = _score_snapshot_for_audit(first_audit)
    latest_scores = _score_snapshot_for_audit(latest_audit)
    coverage_start = _as_utc_datetime(first_audit.created_at)
    coverage_end = _as_utc_datetime(latest_audit.created_at)

    tasks = sync_project_tasks(db, project_id=project_id)
    task_status_summary = build_project_task_summary(tasks)
    impact_payload = build_project_task_impact_payload(db, project_id=project_id)

    def _within_interval(value: datetime | None) -> bool:
        resolved = _as_utc_datetime(value)
        if resolved is None or coverage_start is None or coverage_end is None:
            return False
        return coverage_start <= resolved <= coverage_end

    new_count = 0
    resolved_count = 0
    validated_count = 0
    new_titles: list[str] = []
    resolved_titles: list[str] = []
    for task in tasks:
        source_created = _as_utc_datetime(
            getattr(getattr(task, "source_audit", None), "created_at", None)
        )
        if _within_interval(source_created):
            new_count += 1
            if len(new_titles) < 4 and _text(task.title):
                new_titles.append(_text(task.title))

        resolved_at = _as_utc_datetime(getattr(task, "resolved_at", None))
        if _within_interval(resolved_at):
            resolved_count += 1
            if len(resolved_titles) < 4 and _text(task.title):
                resolved_titles.append(_text(task.title))

        verified_at = _as_utc_datetime(getattr(task, "verified_at", None))
        if _within_interval(verified_at):
            validated_count += 1

    latest_report = build_normalized_audit_report(
        latest_audit,
        current_plan=resolve_audit_normalization_current_plan(latest_audit.user),
    )
    remaining_issues = extract_normalized_recommendation_texts(latest_report, limit=4)
    trend_points = []
    for audit in ordered_audits[-8:]:
        scores = _score_snapshot_for_audit(audit)
        created_at = _as_utc_datetime(audit.created_at)
        if created_at is None:
            continue
        trend_points.append({"date": created_at.isoformat(), **scores})

    delta = {
        "seo": _metric_delta(latest_scores["seo"], first_scores["seo"]),
        "geo": _metric_delta(latest_scores["geo"], first_scores["geo"]),
        "aeo": _metric_delta(latest_scores["aeo"], first_scores["aeo"]),
        "overall": _metric_delta(latest_scores["overall"], first_scores["overall"]),
    }
    return {
        "audit_count": len(ordered_audits),
        "coverage_start": coverage_start.isoformat() if coverage_start else None,
        "coverage_end": coverage_end.isoformat() if coverage_end else None,
        "first_scores": first_scores,
        "latest_scores": latest_scores,
        "delta": delta,
        "trend_direction": {
            "seo": _metric_direction(delta["seo"]),
            "geo": _metric_direction(delta["geo"]),
            "aeo": _metric_direction(delta["aeo"]),
            "overall": _metric_direction(delta["overall"]),
        },
        "trend_points": trend_points,
        "task_status_summary": task_status_summary,
        "task_movement": {
            "new": new_count,
            "resolved": resolved_count,
            "validated": validated_count,
            "new_titles": new_titles,
            "resolved_titles": resolved_titles,
        },
        "validated_impact": impact_payload.get("items", [])[:5],
        "validated_impact_summary": impact_payload.get("summary", {}),
        "remaining_issues": remaining_issues,
    }


def _financial_row_from_job(
    *,
    job: models.AuditJob,
    audit: models.Audit | None,
    credit_hold: models.CreditHold | None,
) -> dict[str, Any]:
    consumed_credits = int(job.consumed_credit_cost or 0)
    if consumed_credits <= 0 and credit_hold is not None:
        consumed_credits = int(credit_hold.final_amount or 0)
    estimated_credits = int(job.estimated_credit_cost or 0)
    if estimated_credits <= 0 and credit_hold is not None:
        estimated_credits = int(credit_hold.hold_amount or 0)
    audit_type_value = getattr(audit, "audit_type", None)
    audit_type = str(getattr(audit_type_value, "value", audit_type_value) or "").strip().lower()
    run_at = (
        _as_utc_datetime(getattr(job, "completed_at", None))
        or _as_utc_datetime(getattr(audit, "created_at", None))
        or _as_utc_datetime(getattr(job, "created_at", None))
    )
    return {
        "job_id": job.id,
        "request_id": _text(job.request_id) or None,
        "date": run_at.isoformat() if run_at else None,
        "audit_type": audit_type or "audit",
        "target": _text(
            getattr(audit, "target_name", None)
            or getattr(audit, "target_url", None)
            or getattr(audit, "url", None)
            or job.url
        ),
        "credits_consumed": consumed_credits,
        "estimated_credits": estimated_credits,
        "status": _text(job.status, "completed"),
    }


def _build_financial_report_payload(
    db: Session,
    *,
    project_id: int,
    hide_credit_cost: bool,
) -> dict[str, Any]:
    if hide_credit_cost:
        return {
            "redacted": True,
            "redaction_reason": "Cost disclosure was withheld for client presentation.",
        }

    jobs = (
        db.query(models.AuditJob)
        .filter(models.AuditJob.project_id == project_id)
        .order_by(
            models.AuditJob.completed_at.desc().nullslast(),
            models.AuditJob.created_at.desc(),
            models.AuditJob.id.desc(),
        )
        .all()
    )
    request_ids = [_text(job.request_id) for job in jobs if _text(job.request_id)]
    audits = (
        db.query(models.Audit)
        .filter(
            models.Audit.project_id == project_id, models.Audit.request_id.in_(request_ids or [""])
        )
        .all()
    )
    audit_by_request_id = {
        _text(audit.request_id): audit for audit in audits if _text(audit.request_id)
    }
    holds = (
        db.query(models.CreditHold)
        .filter(
            models.CreditHold.project_id == project_id,
            models.CreditHold.request_id.in_(request_ids or [""]),
        )
        .all()
    )
    hold_by_request_id = {_text(hold.request_id): hold for hold in holds if _text(hold.request_id)}

    ledger_rows = [
        _financial_row_from_job(
            job=job,
            audit=audit_by_request_id.get(_text(job.request_id)),
            credit_hold=hold_by_request_id.get(_text(job.request_id)),
        )
        for job in jobs
    ]
    ledger_rows = [row for row in ledger_rows if int(row["credits_consumed"] or 0) > 0]
    total_consumed = sum(int(row["credits_consumed"] or 0) for row in ledger_rows)

    return {
        "redacted": False,
        "ledger_rows": ledger_rows[:24],
        "total_consumed_credits": total_consumed,
        "run_count": len(ledger_rows),
    }


def _build_project_competitor_benchmark_payload(
    *,
    analysis: Mapping[str, Any],
    selected_competitor_ids: set[int] | None = None,
) -> dict[str, Any]:
    columns = [
        {"key": "rank", "label": "Rank", "type": "number"},
        {"key": "name", "label": "Brand", "type": "text"},
        {"key": "geo_visibility", "label": "GEO Visibility", "type": "number"},
        {"key": "aeo_score", "label": "AEO Score", "type": "number"},
        {"key": "entity_strength", "label": "Entity Strength", "type": "number"},
        {"key": "overall_score", "label": "Overall Score", "type": "number"},
    ]
    project_payload = _mapping(analysis.get("project"))
    project_scores = _mapping(project_payload.get("scores"))
    competitor_rows = []
    for entry in analysis.get("competitors", []):
        if not isinstance(entry, Mapping):
            continue
        competitor_id = _int(entry.get("id"))
        if selected_competitor_ids and competitor_id not in selected_competitor_ids:
            continue
        scores = _mapping(entry.get("scores"))
        deltas = _mapping(entry.get("delta"))
        competitor_rows.append(
            {
                "id": competitor_id,
                "name": _text(entry.get("name"), "Competitor"),
                "geo_visibility": _float(scores.get("geo")),
                "aeo_score": _float(scores.get("aeo")),
                "entity_strength": _float(scores.get("overall")),
                "overall_score": _float(scores.get("overall")),
                "deltas_vs_target": {
                    "geo_visibility": _float(deltas.get("geo")),
                    "aeo_score": _float(deltas.get("aeo")),
                    "entity_strength": _float(deltas.get("overall")),
                },
            }
        )
    rows = [
        {
            "is_target": True,
            "name": _text(project_payload.get("name"), "Target"),
            "geo_visibility": _float(project_scores.get("geo")),
            "aeo_score": _float(project_scores.get("aeo")),
            "entity_strength": _float(project_scores.get("overall")),
            "overall_score": _float(project_scores.get("overall")),
            "deltas_vs_target": {
                "geo_visibility": 0.0,
                "aeo_score": 0.0,
                "entity_strength": 0.0,
            },
        },
        *competitor_rows,
    ]
    rows.sort(
        key=lambda item: (
            -(item.get("overall_score") or 0.0),
            _text(item.get("name")).lower(),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return {"columns": columns, "rows": rows}


def _build_project_competitor_trend_payload(
    db: Session,
    *,
    project: models.Project,
    selected_competitor_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    trend_payloads = {
        metric: build_project_competitive_trends(
            db,
            project=project,
            period="all",
            metric=metric,
        )
        for metric in _TREND_METRICS
    }

    lines_by_key: dict[str, dict[str, Any]] = {}
    for metric, payload in trend_payloads.items():
        for line in payload.get("lines", []):
            if not isinstance(line, Mapping):
                continue
            key = _text(line.get("key"))
            if not key:
                continue
            competitor_id = None
            if key.startswith("competitor:"):
                competitor_id = _int(key.split(":", 1)[1])
                if selected_competitor_ids and competitor_id not in selected_competitor_ids:
                    continue
            line_entry = lines_by_key.setdefault(
                key,
                {
                    "label": _text(line.get("label"), "Competitor"),
                    "is_project": bool(line.get("is_project")),
                    "points": defaultdict(dict),
                },
            )
            for point in line.get("points", []):
                if not isinstance(point, Mapping):
                    continue
                point_date = _text(point.get("date"))
                if not point_date:
                    continue
                line_entry["points"][point_date][metric] = _float(point.get("value"))

    project_line = lines_by_key.get("project")
    if not project_line:
        return None

    def _normalize_points(points_by_date: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for point_date in sorted(points_by_date.keys()):
            metrics = points_by_date[point_date]
            normalized.append(
                {
                    "date": point_date,
                    "overall": _float(metrics.get("overall")),
                    "seo": _float(metrics.get("seo")),
                    "geo": _float(metrics.get("geo")),
                    "aeo": _float(metrics.get("aeo")),
                }
            )
        return normalized

    project_points = _normalize_points(project_line["points"])
    if not project_points:
        return None

    coverage_dates = [point["date"] for point in project_points if _text(point.get("date"))]
    competitors = []
    for key, line in lines_by_key.items():
        if key == "project":
            continue
        competitor_points = _normalize_points(line["points"])
        if not competitor_points:
            continue
        coverage_dates.extend(
            point["date"] for point in competitor_points if _text(point.get("date"))
        )
        competitors.append(
            {
                "name": line["label"],
                "project_points": project_points,
                "competitor_points": competitor_points,
                "project_latest": project_points[-1],
                "competitor_latest": competitor_points[-1],
                "project_delta_overall": _series_delta(project_points, "overall"),
                "competitor_delta_overall": _series_delta(competitor_points, "overall"),
            }
        )
    if not competitors:
        return None

    coverage_dates = sorted(set(coverage_dates))
    return {
        "enabled": True,
        "project_label": project.name,
        "coverage_start": coverage_dates[0] if coverage_dates else None,
        "coverage_end": coverage_dates[-1] if coverage_dates else None,
        "audit_count": len(project_points),
        "competitors": competitors,
    }


def _attach_project_competitive_metadata(
    *,
    synthetic_left_report: dict[str, Any],
    benchmark_payload: Mapping[str, Any] | None,
    trend_payload: Mapping[str, Any] | None,
    include_competitive_metadata: bool,
) -> dict[str, Any]:
    prepared = deepcopy(synthetic_left_report)
    metadata = _mapping(prepared.get("metadata"))
    competitor_summary = _mapping(metadata.get("competitor_summary"))
    # Plan sanitization clears competitor_summary for plans without
    # has_competitor_analysis; do not re-seed it afterwards.
    if include_competitive_metadata:
        if benchmark_payload:
            competitor_summary["benchmark"] = deepcopy(_mapping(benchmark_payload))
        if trend_payload:
            competitor_summary["trend_timeline"] = deepcopy(_mapping(trend_payload))
    metadata["competitor_summary"] = competitor_summary
    prepared["metadata"] = metadata
    return prepared


def _audit_engine_rows(db: Session, audit: models.Audit) -> list[dict[str, Any]]:
    """Per-engine rows measured for this audit's own job (SIGV2-1205).

    Reads only the visibility batches attached to the audit job that produced
    this audit, so an old report keeps the engine picture from that run and
    never substitutes today's live state. Status: a completed batch with a
    score is ``measured``; an unfinished batch is ``pending``; anything else
    (failed, or a completed batch without a score) is ``withheld``.
    """
    job_id: str | None = None
    request_id = _text(getattr(audit, "request_id", None))
    if request_id:
        job = (
            db.query(models.AuditJob)
            .filter(models.AuditJob.request_id == request_id)
            .order_by(models.AuditJob.created_at.desc(), models.AuditJob.id.desc())
            .first()
        )
        if job is not None:
            job_id = _text(job.id)
    if not job_id:
        return []

    batches = (
        db.query(models.VisibilityRunBatch)
        .filter(models.VisibilityRunBatch.audit_job_id == job_id)
        .order_by(models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc())
        .all()
    )
    rows: dict[str, dict[str, Any]] = {}
    for batch in batches:
        provider = _text(batch.provider).lower()
        if not provider or provider in rows:
            continue
        status = _text(batch.status).lower()
        score = _float(getattr(batch, "score", None))
        measured_at = (
            batch.completed_at.isoformat()
            if getattr(batch, "completed_at", None) is not None
            else None
        )
        # The writer never produces "completed": a batch finishes as
        # "succeeded", "degraded" (some runs answered) or "failed". Testing
        # for "completed" therefore matched nothing and every engine row in
        # every scan-scoped PDF came out "withheld", including the fully
        # successful ones. The statuses below are the ones
        # ``VisibilityIndexJobService.execute_batch`` actually writes, and
        # the pending set is the same ``PENDING_BATCH_STATUSES`` the
        # dashboard uses, so the PDF and the dashboard cannot disagree.
        if status in {"succeeded", "degraded"} and score is not None:
            row_status = "measured"
        elif status in PENDING_BATCH_STATUSES:
            row_status = "pending"
        else:
            row_status = "withheld"
        rows[provider] = {
            # Keyed "engine" rather than "provider": the recursive client-safe
            # projection strips any nested "provider" key as internal infra
            # metadata, which would erase the row identity in whitelabel PDFs.
            "engine": provider,
            "label": VISIBILITY_PROVIDER_LABELS.get(provider, provider.title()),
            "status": row_status,
            "score": score if row_status == "measured" else None,
            "measured_at": measured_at,
        }
    ordered = [rows[p] for p in SUPPORTED_VISIBILITY_PROVIDERS if p in rows]
    ordered.extend(
        row for provider, row in rows.items() if provider not in SUPPORTED_VISIBILITY_PROVIDERS
    )
    return ordered


def _prepare_primary_payload(
    db: Session,
    *,
    primary_audit: models.Audit,
    selected_audits: Sequence[models.Audit],
    report_kind: str,
    hide_credit_cost: bool,
) -> dict[str, Any]:
    payload = build_normalized_audit_report(
        primary_audit,
        current_plan=resolve_audit_normalization_current_plan(primary_audit.user),
    )
    engine_rows = _audit_engine_rows(db, primary_audit)
    if engine_rows:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata["engines"] = engine_rows
        payload["metadata"] = metadata
    report_suite: dict[str, Any] = {}
    if report_kind == "executive":
        report_suite["executive_blueprint"] = _build_executive_blueprint_payload(
            db,
            audit=primary_audit,
        )
    elif report_kind == "project":
        report_suite["project_report"] = _build_project_interval_payload(
            db,
            project_id=int(primary_audit.project_id),
            selected_audits=selected_audits,
        )
    elif report_kind == "financial":
        report_suite["financial_report"] = _build_financial_report_payload(
            db,
            project_id=int(primary_audit.project_id),
            hide_credit_cost=hide_credit_cost,
        )
    return _seed_report_suite_metadata(payload, report_suite=report_suite)


def render_report_pdf(
    *,
    db: Session,
    selected_audits: list[models.Audit],
    template_type: str,
    options: Mapping[str, Any] | None,
    branding_config: Mapping[str, Any] | None = None,
    export_manifest: Mapping[str, Any] | None = None,
    language: str | None = None,
    primary_audit: models.Audit | None = None,
    competitor_audits: Sequence[models.Audit] | None = None,
) -> bytes:
    if not selected_audits:
        raise ValueError("At least one audit is required to render a report PDF.")

    options_payload = dict(options or {})
    options_payload.setdefault("mode", "individual")
    options_payload.setdefault("sections", ["overview", "geo", "seo", "aeo"])
    report_language = _resolve_report_language_for_audits(
        selected_audits,
        explicit_language=language or _text(options_payload.get("language")) or None,
    )
    resolved_export_manifest = resolve_effective_export_manifest(
        export_manifest=export_manifest,
        options=options_payload,
        template_type=template_type,
        branding_config=branding_config,
    )
    report_kind = _text(resolved_export_manifest.get("report_kind"), "standard").lower()
    branding = _build_branding_contract(
        resolved_export_manifest=resolved_export_manifest,
        template_type=template_type,
        options=options_payload,
        branding_config=branding_config,
        report_language=report_language,
    )

    if report_kind == "competitors":
        competitor_audit_list = list(competitor_audits or [])
        if primary_audit and competitor_audit_list:
            benchmark_payload = None
            trend_payload = None
            primary_plan = resolve_audit_normalization_current_plan(primary_audit.user)
            # Same plan value sanitize_audit_payload_for_plan applied to this payload.
            allow_competitive_metadata = can_use_feature(
                normalize_plan_for_audit_gating(primary_plan), "has_competitor_analysis"
            )
            selected_left_report = build_normalized_audit_report(
                primary_audit,
                current_plan=primary_plan,
            )
            project = getattr(primary_audit, "project", None)
            if project is not None:
                tracked_competitors = list_project_competitors(db, project=project)
                selected_site_ids = {
                    int(audit.site_id)
                    for audit in competitor_audit_list
                    if audit.site_id is not None
                }
                selected_tracked_rows = [
                    row
                    for row in tracked_competitors
                    if _int(row.get("competitor_site_id")) in selected_site_ids
                ]
                selected_competitor_ids = {
                    _int(row.get("id"))
                    for row in selected_tracked_rows
                    if _int(row.get("id")) is not None
                }
                if selected_competitor_ids:
                    analysis_payload = build_project_competitive_analysis(db, project=project)
                    benchmark_payload = _build_project_competitor_benchmark_payload(
                        analysis=analysis_payload,
                        selected_competitor_ids=selected_competitor_ids,
                    )
                    if _text(resolved_export_manifest.get("competitor_mode")) == "trend":
                        trend_payload = _build_project_competitor_trend_payload(
                            db,
                            project=project,
                            selected_competitor_ids=selected_competitor_ids,
                        )
            selected_left_report = _attach_project_competitive_metadata(
                synthetic_left_report=selected_left_report,
                benchmark_payload=benchmark_payload,
                trend_payload=trend_payload,
                include_competitive_metadata=allow_competitive_metadata,
            )
            if not allow_competitive_metadata:
                benchmark_payload = None
                trend_payload = None
            comparison_pairs = [
                {
                    "left_title": primary_audit.url,
                    "left_report": _apply_complex_report_sections(
                        selected_left_report,
                        options_payload.get("sections") or [],
                    ),
                    "right_title": competitor_audit.url,
                    "right_report": _apply_complex_report_sections(
                        build_normalized_audit_report(
                            competitor_audit,
                            current_plan=resolve_audit_normalization_current_plan(
                                competitor_audit.user
                            ),
                        ),
                        options_payload.get("sections") or [],
                    ),
                    "left_full_report": selected_left_report,
                    "right_full_report": build_normalized_audit_report(
                        competitor_audit,
                        current_plan=resolve_audit_normalization_current_plan(
                            competitor_audit.user
                        ),
                    ),
                    "left_audit_record": primary_audit,
                    "right_audit_record": competitor_audit,
                }
                for competitor_audit in competitor_audit_list
            ]
            first_pair = comparison_pairs[0]
            return render_battle_report_pdf(
                left_title=str(first_pair["left_title"]),
                right_title=str(first_pair["right_title"]),
                left_report=first_pair["left_report"],
                right_report=first_pair["right_report"],
                comparison_pairs=comparison_pairs,
                branding=branding,
                selected_sections=options_payload.get("sections") or [],
                left_full_report=first_pair["left_full_report"],
                right_full_report=first_pair["right_full_report"],
                left_audit_record=first_pair["left_audit_record"],
                right_audit_record=first_pair["right_audit_record"],
                trend_payload=trend_payload,
                benchmark_payload=benchmark_payload,
            )

        if len(selected_audits) == 1:
            comparison_pair = build_canonical_competitor_battle_pair(
                selected_audits[0],
                competitor_name=_text(options_payload.get("comparison_competitor_name")) or None,
                competitor_rank=_int(options_payload.get("comparison_competitor_rank")),
            )
            return render_battle_report_pdf(
                left_title=str(comparison_pair["left_title"]),
                right_title=str(comparison_pair["right_title"]),
                left_report=comparison_pair["left_report"],
                right_report=comparison_pair["right_report"],
                comparison_pairs=[comparison_pair],
                branding=branding,
                selected_sections=options_payload.get("sections") or [],
                left_full_report=comparison_pair["left_full_report"],
                right_full_report=comparison_pair["right_full_report"],
                left_audit_record=comparison_pair["left_audit_record"],
                right_audit_record=comparison_pair["right_audit_record"],
                trend_payload=None,
                benchmark_payload=None,
            )

        left_report = build_normalized_audit_report(
            selected_audits[0],
            current_plan=resolve_audit_normalization_current_plan(selected_audits[0].user),
        )
        right_report = build_normalized_audit_report(
            selected_audits[1],
            current_plan=resolve_audit_normalization_current_plan(selected_audits[1].user),
        )
        return render_battle_report_pdf(
            left_title=selected_audits[0].url,
            right_title=selected_audits[1].url,
            left_report=_apply_complex_report_sections(
                left_report, options_payload.get("sections") or []
            ),
            right_report=_apply_complex_report_sections(
                right_report, options_payload.get("sections") or []
            ),
            branding=branding,
            selected_sections=options_payload.get("sections") or [],
            left_full_report=left_report,
            right_full_report=right_report,
            left_audit_record=selected_audits[0],
            right_audit_record=selected_audits[1],
            trend_payload=None,
            benchmark_payload=None,
        )

    reference_audit = primary_audit or selected_audits[-1]
    prepared_payload = _prepare_primary_payload(
        db,
        primary_audit=reference_audit,
        selected_audits=selected_audits,
        report_kind=report_kind,
        hide_credit_cost=bool(resolved_export_manifest.get("hide_credit_cost", True)),
    )
    return render_white_label_pdf(
        audit_id=reference_audit.id,
        audit_url=reference_audit.url,
        geo_score=float(reference_audit.geo_score or 0.0),
        highlights=[],
        full_report=prepared_payload,
        branding=branding,
        include_competitor_analysis=(
            "competitors" in (options_payload.get("sections") or [])
            or bool(options_payload.get("include_competitor_analysis"))
        ),
        audit_record=reference_audit,
        audit_history=selected_audits,
        selected_sections=options_payload.get("sections") or [],
    )


__all__ = [
    "build_report_branding_config",
    "build_report_summary_text",
    "render_report_pdf",
    "should_generate_ai_summary",
]
