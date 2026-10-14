from __future__ import annotations

import logging
from typing import Any

import models
from app.config.plans import resolve_entitled_subscription_plan
from app.services.advisor_view import attach_advisor_view
from app.services.aio_view import attach_aio_view
from app.services.search_types_view import attach_search_types
from services.audit_feature_gating_service import sanitize_audit_payload_for_plan
from services.query_taxonomy import (
    classify_query_category,
    normalize_intent_value,
    normalize_query_category,
    resolve_query_type,
)
from services.reports.audit_result_adapter import to_canonical_audit_result
from score_utils import DeterministicScoringEngine

"""Shared normalization helpers for persisted audit records.

Source-of-truth precedence for normalized audit API payloads:
1. Target identity comes from relational audit columns first, then persisted report fields.
2. Effective public scores come from relational audit summary columns when present, otherwise
   from the persisted report. This keeps list/detail payloads aligned for mixed legacy rows.
3. metadata.plan represents the plan persisted with the audit when available; current plan is
   exposed separately via metadata.current_plan when a caller provides it.
4. Intent and query category prefer relational audit columns, then persisted report metadata,
   then deterministic fallback classification from the stored audit context.
"""

logger = logging.getLogger(__name__)


def normalize_audit_target_type(value: Any) -> str:
    enum_value = getattr(value, "value", value)
    normalized = str(enum_value or "website").strip().lower()
    return normalized if normalized in {"website", "brand"} else "website"


def resolve_audit_target_type(audit: models.Audit) -> str:
    return normalize_audit_target_type(getattr(audit, "audit_target_type", None))


def resolve_audit_target_url(audit: models.Audit) -> str | None:
    candidate = getattr(audit, "target_url", None) or getattr(audit, "url", None)
    if isinstance(candidate, str):
        normalized = candidate.strip()
        return normalized or None
    return None


def resolve_audit_target_name(audit: models.Audit) -> str | None:
    candidate = getattr(audit, "target_name", None)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    fallback_url = resolve_audit_target_url(audit)
    if fallback_url:
        return fallback_url

    if resolve_audit_target_type(audit) == "brand":
        return "Brand audit"
    return None


def resolve_audit_target_metadata(audit: models.Audit) -> dict[str, Any]:
    value = getattr(audit, "target_metadata", None)
    return dict(value) if isinstance(value, dict) else {}


def resolve_legacy_audit_url(audit: models.Audit) -> str:
    return resolve_audit_target_url(audit) or ""


def resolve_audit_intent(audit: models.Audit) -> str | None:
    normalized_column_intent = normalize_intent_value(getattr(audit, "intent", None))
    if normalized_column_intent:
        return normalized_column_intent

    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    return normalize_intent_value(metadata.get("intent"))


def resolve_audit_query_category(audit: models.Audit) -> str:
    normalized_column_query_category = normalize_query_category(
        getattr(audit, "query_category", None)
    )
    if normalized_column_query_category:
        return normalized_column_query_category

    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    aeo_section = report.get("aeo") if isinstance(report.get("aeo"), dict) else {}
    raw_query = (
        metadata.get("query")
        or metadata.get("prompt")
        or report.get("query")
        or getattr(audit, "url", None)
    )
    return classify_query_category(
        raw_query=raw_query,
        query_category=(
            metadata.get("query_category")
            or metadata.get("queryCategory")
            or aeo_section.get("query_category")
            or aeo_section.get("queryCategory")
        ),
    )


def _normalize_plan_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _coerce_score(value: Any) -> float | None:
    candidate = value
    if isinstance(value, dict):
        candidate = value.get("score")
    try:
        parsed = float(candidate)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, parsed))


def _extract_report_scores(report: dict[str, Any] | None) -> dict[str, float | None]:
    if not isinstance(report, dict):
        return {"seo": None, "geo": None, "aeo": None, "overall": None}

    score_block = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    if score_block:
        return {
            "seo": _coerce_score(score_block.get("seo")),
            "geo": _coerce_score(score_block.get("geo")),
            "aeo": _coerce_score(score_block.get("aeo")),
            "overall": _coerce_score(score_block.get("overall")),
        }

    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    return {
        "seo": _coerce_score(analysis.get("seo_score")),
        "geo": _coerce_score(analysis.get("geo_score")),
        "aeo": _coerce_score(analysis.get("aeo_score")),
        "overall": None,
    }


def resolve_effective_audit_scores(
    audit: models.Audit,
    *,
    canonical_report: dict[str, Any] | None = None,
) -> dict[str, float | None]:
    report_scores = _extract_report_scores(
        canonical_report
        if isinstance(canonical_report, dict)
        else (audit.full_report if isinstance(audit.full_report, dict) else {})
    )

    effective_scores = {
        "seo": _coerce_score(getattr(audit, "seo_score", None)),
        "geo": _coerce_score(getattr(audit, "geo_score", None)),
        "aeo": _coerce_score(getattr(audit, "aeo_score", None)),
    }
    for dimension in ("seo", "geo", "aeo"):
        if effective_scores[dimension] is None:
            effective_scores[dimension] = report_scores.get(dimension)

    recompute_overall = any(
        _coerce_score(getattr(audit, f"{dimension}_score", None)) is not None
        for dimension in ("seo", "geo", "aeo")
    )
    if recompute_overall:
        overall_inputs = {
            dimension: score
            for dimension, score in effective_scores.items()
            if isinstance(score, (int, float))
        }
        effective_scores["overall"] = (
            DeterministicScoringEngine.calculate_overall_score(overall_inputs)
            if overall_inputs
            else report_scores.get("overall")
        )
    else:
        effective_scores["overall"] = report_scores.get("overall")

    return effective_scores


def resolve_audit_effective_scores(
    audit: models.Audit,
    *,
    canonical_report: dict[str, Any] | None = None,
) -> dict[str, float | None]:
    return resolve_effective_audit_scores(audit, canonical_report=canonical_report)


def _resolve_persisted_audit_plan(audit: models.Audit) -> str | None:
    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    return _normalize_plan_value(metadata.get("plan"))


def resolve_audit_effective_plan(
    audit: models.Audit,
    *,
    current_plan: str | None = None,
) -> str:
    return (
        _resolve_persisted_audit_plan(audit)
        or _normalize_plan_value(current_plan)
        or "plan_starter"
    )


def resolve_audit_normalization_current_plan(user: models.User | None) -> str:
    if user is not None:
        plan_type = _normalize_plan_value(resolve_entitled_subscription_plan(user))
        if plan_type and plan_type != "plan_agency_trial":
            return plan_type
        trial_plan = _normalize_plan_value(getattr(user, "trial_plan", None))
        if trial_plan:
            return trial_plan
    return "plan_starter"


def build_normalized_audit_report(
    audit: models.Audit,
    *,
    current_plan: str | None = None,
    dismissed: set[str] | None = None,
    search_type_measurements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = to_canonical_audit_result(
        audit.full_report if isinstance(audit.full_report, dict) else {},
        audit_url=resolve_audit_target_url(audit),
        audit_target_type=resolve_audit_target_type(audit),
        target_name=resolve_audit_target_name(audit),
        target_url=resolve_audit_target_url(audit),
        target_metadata=resolve_audit_target_metadata(audit),
        created_at=audit.created_at,
        plan=resolve_audit_effective_plan(audit, current_plan=current_plan),
    )

    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    resolved_intent = resolve_audit_intent(audit)
    resolved_query_category = resolve_audit_query_category(audit)
    resolved_current_plan = _normalize_plan_value(current_plan)

    metadata["plan"] = resolve_audit_effective_plan(audit, current_plan=current_plan)
    metadata["intent"] = resolved_intent
    metadata["query_category"] = resolved_query_category
    metadata["query_type"] = resolve_query_type(
        query_type=metadata.get("query_type") or metadata.get("queryType"),
        intent=resolved_intent,
    )
    if resolved_current_plan:
        metadata["current_plan"] = resolved_current_plan
    report["metadata"] = metadata

    # Only `scores` is refreshed here, from the audit columns, which take
    # precedence over whatever the adapter stored in the report. The section
    # mirrors are deliberately left as they were written, because
    # `seo.performance`, `seo.indexing`, `geo.citation_share` and friends can hold
    # real sub-signals that these dimension scores would destroy.
    #
    # The consequence is that a served report can be internally inconsistent, and
    # it is: for one production audit `scores.seo` is 72 while `seo.onpage`,
    # `seo.performance`, `seo.indexing` and `scores.seo_breakdown.score` all hold
    # 7, because the adapter wrote 7 everywhere and only `scores.seo` was
    # refreshed afterwards.
    #
    # So read `scores.<dimension>` first. `admin._resolve_audit_score` documents
    # the same order and calls the section fields `legacy_sections`. Two frontend
    # pages derived their headline score from those mirrors instead and showed 7
    # and 0 where the workspace card showed 72 and 64 for the same audit.
    scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    effective_scores = resolve_effective_audit_scores(audit, canonical_report=report)
    for key, value in effective_scores.items():
        scores[key] = value
    report["scores"] = scores

    sanitized = sanitize_audit_payload_for_plan(
        report,
        resolved_current_plan or metadata.get("current_plan") or metadata.get("plan"),
        lock_origin="read",
    )

    # Response-time additive metadata views, attached after plan sanitization so the
    # additive metadata.* views survive; never persisted, canonical contract untouched.
    # Each attach is isolated: a failure in one view is logged and the audit response
    # continues with the remaining views applied (one view can't 500 the whole audit).
    #   - aio: AIO roll-up (AEO+GEO).
    #   - advisor: deterministic Advisor plan (ROI-ranked, grounding-enforced). Learnings
    #     loop (Task 7.2): caller-supplied dismissed fingerprints suppress those actions;
    #     None == no suppression (backward-compatible).
    #   - search_types: the 5 canonical search types (Brand/Category/Problem/Feature/
    #     Comparison) for the AIO drilldown. Measured only: the caller supplies this
    #     project's per-type visibility and answer ratio from its own
    #     ProjectVisibilityQuery runs (search_type_measurements); None == all five
    #     unmeasured. There is no estimated fallback (SIGV2-1105).
    for _label, _attach in (
        ("aio", lambda r: attach_aio_view(r)),
        ("advisor", lambda r: attach_advisor_view(r, dismissed=dismissed)),
        ("search_types", lambda r: attach_search_types(r, measurements=search_type_measurements)),
    ):
        try:
            sanitized = _attach(sanitized)
        except Exception:
            logger.exception("metadata attach failed: %s", _label)
    return sanitized
