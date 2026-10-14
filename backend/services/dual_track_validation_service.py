from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Mapping, Sequence

import models
from services.reports.audit_result_adapter import (
    extract_normalized_recommendation_texts,
    to_canonical_audit_result,
)

REQUIRED_VALIDATION_ROLES = (
    "deep_judgment_exemplar",
    "website_control",
    "brand_metadata_control",
    "fallback_control",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _normalized_url_text(value: Any) -> str | None:
    normalized = _text(value)
    if not normalized:
        return None
    return normalized.rstrip("/")


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _normalize_bucket_key(bucket: Mapping[str, Any]) -> str:
    track = _text(bucket.get("track")) or "unknown"
    category = _text(bucket.get("category")) or "unknown"
    return f"{track}:{category}"


def _normalize_blocked_buckets(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, Mapping):
            continue
        track = _text(item.get("track"))
        category = _text(item.get("category"))
        count = item.get("count")
        if not track or not category or not isinstance(count, int) or count <= 0:
            continue
        normalized.append(
            {
                "track": track,
                "category": category,
                "count": count,
                "key": f"{track}:{category}",
            }
        )
    return normalized


def build_report_validation_summary(
    raw_report: Mapping[str, Any] | None,
    *,
    audit_id: int | None = None,
    request_id: str | None = None,
    audit_url: str | None = None,
    audit_target_type: str = "website",
    target_name: str | None = None,
    target_url: str | None = None,
    target_metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    canonical = to_canonical_audit_result(
        dict(raw_report) if isinstance(raw_report, Mapping) else {},
        audit_url=audit_url,
        audit_target_type=audit_target_type,
        target_name=target_name,
        target_url=target_url,
        target_metadata=target_metadata,
        created_at=created_at,
    )
    metadata = _as_dict(canonical.get("metadata"))
    integrity_certificate = _as_dict(canonical.get("integrity_certificate"))
    integrity_summary = _as_dict(integrity_certificate.get("summary"))
    dual_track_shadow = _as_dict(metadata.get("dual_track_shadow"))
    dual_track_shadow_summary = _as_dict(dual_track_shadow.get("summary"))
    track_b_judge = _as_dict(dual_track_shadow.get("track_b_judge"))
    target = _as_dict(canonical.get("target"))

    recommendation_texts = extract_normalized_recommendation_texts(canonical)
    blocked_buckets = _normalize_blocked_buckets(integrity_certificate.get("blocked_claim_buckets"))

    return {
        "audit_id": audit_id,
        "request_id": _text(request_id),
        "created_at": _isoformat(created_at),
        "schema_version": _text(canonical.get("schema_version")),
        "target": {
            "type": _text(target.get("type")) or audit_target_type,
            "name": _text(target.get("name")),
            "url": _normalized_url_text(target.get("url")),
        },
        "requested_tier": _text(metadata.get("requested_tier")),
        "report_version": _text(metadata.get("version")),
        "has_integrity_certificate": bool(integrity_certificate),
        "grounding_profile": (
            _text(integrity_certificate.get("grounding_profile"))
            or _text(metadata.get("grounding_profile"))
        ),
        "dual_track_grounding_enabled": bool(
            integrity_certificate.get("dual_track_grounding_enabled") is True
            or metadata.get("dual_track_grounding_enabled") is True
        ),
        "degraded": integrity_certificate.get("degraded") is True,
        "degraded_reason": _text(integrity_certificate.get("degraded_reason")),
        "fallback_reason": _text(metadata.get("fallback_reason")),
        "track_counts": {
            "track_a_total": int(integrity_summary.get("track_a_total") or 0),
            "track_a_supported": int(integrity_summary.get("track_a_supported") or 0),
            "track_a_flagged": int(integrity_summary.get("track_a_flagged") or 0),
            "track_a_omitted": int(integrity_summary.get("track_a_omitted") or 0),
            "track_b_total": int(integrity_summary.get("track_b_total") or 0),
            "track_b_supported": int(integrity_summary.get("track_b_supported") or 0),
            "track_b_flagged": int(integrity_summary.get("track_b_flagged") or 0),
            "track_b_needs_manual_review": int(
                integrity_summary.get("track_b_needs_manual_review") or 0
            ),
            "track_b_omitted": int(integrity_summary.get("track_b_omitted") or 0),
        },
        "recommendation_count": len(recommendation_texts),
        "recommendation_texts": recommendation_texts,
        "blocked_buckets": blocked_buckets,
        "dual_track_shadow": {
            "present": bool(dual_track_shadow),
            "status": _text(dual_track_shadow.get("status")),
            "summary": {
                "track_a_claims": int(dual_track_shadow_summary.get("track_a_claims") or 0),
                "track_b_claims": int(dual_track_shadow_summary.get("track_b_claims") or 0),
                "supported_claims": int(dual_track_shadow_summary.get("supported_claims") or 0),
                "flagged_claims": int(dual_track_shadow_summary.get("flagged_claims") or 0),
                "needs_manual_review_claims": int(
                    dual_track_shadow_summary.get("needs_manual_review_claims") or 0
                ),
                "omitted_claims": int(dual_track_shadow_summary.get("omitted_claims") or 0),
            },
            "track_b_judge": {
                "mode": _text(track_b_judge.get("mode")),
                "requested_tier": _text(track_b_judge.get("requested_tier")),
                "enabled": track_b_judge.get("enabled") is True,
                "available": track_b_judge.get("available") is True,
                "judge_unavailable_claims": int(track_b_judge.get("judge_unavailable_claims") or 0),
            },
        },
    }


def build_validation_summary_from_audit(audit: models.Audit) -> dict[str, Any]:
    return build_report_validation_summary(
        audit.full_report if isinstance(audit.full_report, Mapping) else {},
        audit_id=getattr(audit, "id", None),
        request_id=getattr(audit, "request_id", None),
        audit_url=getattr(audit, "target_url", None) or getattr(audit, "url", None),
        audit_target_type=getattr(getattr(audit, "audit_target_type", None), "value", None)
        or getattr(getattr(audit, "audit_target_type", None), "name", None)
        or "website",
        target_name=getattr(audit, "target_name", None),
        target_url=getattr(audit, "target_url", None),
        target_metadata=dict(getattr(audit, "target_metadata", None) or {}),
        created_at=getattr(audit, "created_at", None),
    )


def compare_validation_summaries(
    *,
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
    review_type: str = "standard",
) -> dict[str, Any]:
    baseline = dict(baseline_summary)
    candidate = dict(candidate_summary)

    baseline_target = _as_dict(baseline.get("target"))
    candidate_target = _as_dict(candidate.get("target"))
    target_match = (_text(baseline_target.get("type")) or "website") == (
        _text(candidate_target.get("type")) or "website"
    ) and (
        _text(baseline_target.get("name")) or _normalized_url_text(baseline_target.get("url"))
    ) == (_text(candidate_target.get("name")) or _normalized_url_text(candidate_target.get("url")))

    baseline_recommendations = set(_as_list(baseline.get("recommendation_texts")))
    candidate_recommendations = set(_as_list(candidate.get("recommendation_texts")))

    baseline_buckets = Counter(
        {
            _normalize_bucket_key(bucket): int(bucket.get("count") or 0)
            for bucket in _as_list(baseline.get("blocked_buckets"))
            if isinstance(bucket, Mapping)
        }
    )
    candidate_buckets = Counter(
        {
            _normalize_bucket_key(bucket): int(bucket.get("count") or 0)
            for bucket in _as_list(candidate.get("blocked_buckets"))
            if isinstance(bucket, Mapping)
        }
    )

    automatic_blockers: list[str] = []
    if not target_match:
        automatic_blockers.append("baseline and candidate target identity do not match")
    if not bool(candidate.get("has_integrity_certificate")):
        automatic_blockers.append("candidate report is missing integrity_certificate")
    if candidate.get("degraded") is True and not _text(candidate.get("degraded_reason")):
        automatic_blockers.append("candidate report is degraded but degraded_reason is missing")

    candidate_grounding_profile = _text(candidate.get("grounding_profile"))
    candidate_fallback_reason = _text(candidate.get("fallback_reason"))
    if review_type == "standard":
        if candidate_grounding_profile == "single_track_fallback":
            automatic_blockers.append(
                "candidate standard review fell back to single_track_fallback"
            )
    elif review_type == "fallback_control":
        if not candidate_fallback_reason:
            automatic_blockers.append("fallback control candidate is missing fallback_reason")
    else:
        automatic_blockers.append(f"unsupported review_type: {review_type}")

    bucket_delta = []
    all_bucket_keys = sorted(set(baseline_buckets) | set(candidate_buckets))
    for key in all_bucket_keys:
        baseline_count = baseline_buckets.get(key, 0)
        candidate_count = candidate_buckets.get(key, 0)
        if baseline_count == candidate_count:
            continue
        track, category = key.split(":", 1)
        bucket_delta.append(
            {
                "key": key,
                "track": track,
                "category": category,
                "baseline_count": baseline_count,
                "candidate_count": candidate_count,
                "delta": candidate_count - baseline_count,
            }
        )

    return {
        "review_type": review_type,
        "baseline": baseline,
        "candidate": candidate,
        "target_match": target_match,
        "recommendation_delta": {
            "baseline_count": len(baseline_recommendations),
            "candidate_count": len(candidate_recommendations),
            "added": sorted(candidate_recommendations - baseline_recommendations),
            "removed": sorted(baseline_recommendations - candidate_recommendations),
            "unchanged_count": len(baseline_recommendations & candidate_recommendations),
        },
        "blocked_bucket_delta": bucket_delta,
        "automatic_blockers": automatic_blockers,
        "manual_review_questions": [
            "Did recommendation specificity improve without inventing facts?",
            "Did any previously correct factual claim become incorrectly blocked?",
            "Did any unsupported factual premise become incorrectly accepted through strategic wording?",
            "Did any report, PDF, export, or UI consumer regress on the new contract shape?",
            "If the run degraded, did it fail safe and remain auditable?",
        ],
        "signoff_record": {
            "baseline_audit_id": baseline.get("audit_id"),
            "candidate_audit_id": candidate.get("audit_id"),
            "review_type": review_type,
            "rollout_mode_used": candidate.get("grounding_profile"),
            "improvements_observed": [],
            "regressions_found_and_resolved": [],
            "final_decision": None,
        },
    }


def summarize_validation_suite(
    validation_cases: Sequence[Mapping[str, Any]],
    *,
    suite_label: str | None = None,
    required_roles: Sequence[str] = REQUIRED_VALIDATION_ROLES,
) -> dict[str, Any]:
    normalized_cases: list[dict[str, Any]] = []
    observed_roles: list[str] = []
    automatic_blockers: list[str] = []
    candidate_rollout_modes: set[str] = set()

    normalized_required_roles = [
        role for role in (_text(value) for value in required_roles) if role is not None
    ]

    for index, raw_case in enumerate(validation_cases, start=1):
        case = _as_dict(raw_case)
        label = _text(case.get("label")) or _text(case.get("case_id")) or f"case-{index}"
        validation_role = _text(case.get("validation_role")) or "unclassified"
        comparison = dict(_as_dict(case.get("comparison")))
        review_type = (
            _text(case.get("review_type")) or _text(comparison.get("review_type")) or "standard"
        )
        baseline = _as_dict(comparison.get("baseline"))
        candidate = _as_dict(comparison.get("candidate"))
        target = _as_dict(candidate.get("target")) or _as_dict(baseline.get("target"))

        case_blockers = [
            str(item)
            for item in _as_list(comparison.get("automatic_blockers"))
            if isinstance(item, str)
        ]

        if validation_role == "deep_judgment_exemplar":
            requested_tier = _text(candidate.get("requested_tier")) or _text(
                baseline.get("requested_tier")
            )
            if requested_tier != "deep_judgment":
                case_blockers.append(
                    "deep_judgment_exemplar case is not using requested_tier=deep_judgment"
                )
        if validation_role == "website_control" and _text(target.get("type")) != "website":
            case_blockers.append("website_control case target type is not website")
        if validation_role == "fallback_control" and review_type != "fallback_control":
            case_blockers.append("fallback_control case must use review_type=fallback_control")

        comparison["automatic_blockers"] = case_blockers
        observed_roles.append(validation_role)

        candidate_rollout_mode = _text(candidate.get("grounding_profile"))
        if candidate_rollout_mode:
            candidate_rollout_modes.add(candidate_rollout_mode)

        normalized_cases.append(
            {
                "case_id": _text(case.get("case_id")) or f"case-{index}",
                "label": label,
                "validation_role": validation_role,
                "review_type": review_type,
                "comparison": comparison,
                "has_blockers": bool(case_blockers),
            }
        )
        automatic_blockers.extend(f"{label}: {item}" for item in case_blockers)

    missing_required_roles = [
        role for role in normalized_required_roles if role not in set(observed_roles)
    ]
    if missing_required_roles:
        automatic_blockers.append(
            "validation suite is missing required roles: " + ", ".join(missing_required_roles)
        )

    case_count = len(normalized_cases)
    cases_with_blockers = sum(1 for item in normalized_cases if item["has_blockers"])
    baseline_audit_ids = [
        comparison.get("baseline", {}).get("audit_id")
        for comparison in (item.get("comparison") for item in normalized_cases)
        if isinstance(comparison, Mapping)
        and _as_dict(comparison.get("baseline")).get("audit_id") is not None
    ]
    candidate_audit_ids = [
        comparison.get("candidate", {}).get("audit_id")
        for comparison in (item.get("comparison") for item in normalized_cases)
        if isinstance(comparison, Mapping)
        and _as_dict(comparison.get("candidate")).get("audit_id") is not None
    ]

    return {
        "suite_label": suite_label or "EPIC-03 validation suite",
        "required_roles": normalized_required_roles,
        "missing_required_roles": missing_required_roles,
        "required_coverage_complete": not missing_required_roles,
        "candidate_rollout_modes": sorted(candidate_rollout_modes),
        "case_counts": {
            "total": case_count,
            "with_blockers": cases_with_blockers,
            "without_blockers": case_count - cases_with_blockers,
        },
        "cases": normalized_cases,
        "automatic_blockers": automatic_blockers,
        "signoff_record": {
            "baseline_audit_ids": baseline_audit_ids,
            "candidate_audit_ids": candidate_audit_ids,
            "rollout_modes_used": sorted(candidate_rollout_modes),
            "improvements_observed": [],
            "regressions_found_and_resolved": [],
            "final_decision": None,
        },
    }


def render_validation_markdown(comparison: Mapping[str, Any]) -> str:
    baseline = _as_dict(comparison.get("baseline"))
    candidate = _as_dict(comparison.get("candidate"))
    recommendation_delta = _as_dict(comparison.get("recommendation_delta"))
    automatic_blockers = [
        str(item)
        for item in _as_list(comparison.get("automatic_blockers"))
        if isinstance(item, str)
    ]

    lines = [
        "# EPIC-03 Dual-Track Validation Comparison",
        "",
        "## Run Summary",
        f"- Review type: {_text(comparison.get('review_type')) or 'standard'}",
        f"- Target match: {'yes' if comparison.get('target_match') else 'no'}",
        f"- Baseline audit id: {baseline.get('audit_id') or 'n/a'}",
        f"- Candidate audit id: {candidate.get('audit_id') or 'n/a'}",
        "",
        "## Baseline",
        f"- Grounding profile: {_text(baseline.get('grounding_profile')) or 'n/a'}",
        f"- Degraded: {'yes' if baseline.get('degraded') else 'no'}",
        f"- Recommendation count: {int(baseline.get('recommendation_count') or 0)}",
        "",
        "## Candidate",
        f"- Grounding profile: {_text(candidate.get('grounding_profile')) or 'n/a'}",
        f"- Degraded: {'yes' if candidate.get('degraded') else 'no'}",
        f"- Degraded reason: {_text(candidate.get('degraded_reason')) or _text(candidate.get('fallback_reason')) or 'n/a'}",
        f"- Recommendation count: {int(candidate.get('recommendation_count') or 0)}",
        "",
        "## Recommendation Delta",
        f"- Added: {len(_as_list(recommendation_delta.get('added')))}",
        f"- Removed: {len(_as_list(recommendation_delta.get('removed')))}",
        f"- Unchanged: {int(recommendation_delta.get('unchanged_count') or 0)}",
        "",
        "## Automatic Blockers",
    ]
    if automatic_blockers:
        lines.extend(f"- {item}" for item in automatic_blockers)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Manual Review Questions",
        ]
    )
    lines.extend(
        f"- {item}"
        for item in _as_list(comparison.get("manual_review_questions"))
        if isinstance(item, str)
    )
    return "\n".join(lines)


def render_validation_suite_markdown(suite: Mapping[str, Any]) -> str:
    case_counts = _as_dict(suite.get("case_counts"))
    automatic_blockers = [
        str(item) for item in _as_list(suite.get("automatic_blockers")) if isinstance(item, str)
    ]
    missing_required_roles = [
        str(item) for item in _as_list(suite.get("missing_required_roles")) if isinstance(item, str)
    ]
    rollout_modes = [
        str(item)
        for item in _as_list(suite.get("candidate_rollout_modes"))
        if isinstance(item, str)
    ]

    lines = [
        "# EPIC-03 Dual-Track Validation Suite",
        "",
        "## Suite Summary",
        f"- Label: {_text(suite.get('suite_label')) or 'EPIC-03 validation suite'}",
        f"- Case count: {int(case_counts.get('total') or 0)}",
        f"- Cases with blockers: {int(case_counts.get('with_blockers') or 0)}",
        f"- Required coverage complete: {'yes' if suite.get('required_coverage_complete') else 'no'}",
        f"- Candidate rollout modes observed: {', '.join(rollout_modes) if rollout_modes else 'n/a'}",
        "",
        "## Missing Required Roles",
    ]
    if missing_required_roles:
        lines.extend(f"- {item}" for item in missing_required_roles)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Automatic Blockers",
        ]
    )
    if automatic_blockers:
        lines.extend(f"- {item}" for item in automatic_blockers)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Cases",
        ]
    )
    for case in _as_list(suite.get("cases")):
        if not isinstance(case, Mapping):
            continue
        comparison = _as_dict(case.get("comparison"))
        baseline = _as_dict(comparison.get("baseline"))
        candidate = _as_dict(comparison.get("candidate"))
        case_blockers = [
            str(item)
            for item in _as_list(comparison.get("automatic_blockers"))
            if isinstance(item, str)
        ]
        lines.extend(
            [
                "",
                f"### {_text(case.get('label')) or _text(case.get('case_id')) or 'Case'}",
                f"- Validation role: {_text(case.get('validation_role')) or 'unclassified'}",
                f"- Review type: {_text(case.get('review_type')) or 'standard'}",
                f"- Baseline audit id: {baseline.get('audit_id') or 'n/a'}",
                f"- Candidate audit id: {candidate.get('audit_id') or 'n/a'}",
                f"- Target match: {'yes' if comparison.get('target_match') else 'no'}",
                f"- Candidate grounding profile: {_text(candidate.get('grounding_profile')) or 'n/a'}",
            ]
        )
        if case_blockers:
            lines.append("- Automatic blockers:")
            lines.extend(f"  - {item}" for item in case_blockers)
        else:
            lines.append("- Automatic blockers: none")

    return "\n".join(lines)


def extract_signoff_record(result: Mapping[str, Any]) -> dict[str, Any]:
    signoff_record = _as_dict(result.get("signoff_record"))
    automatic_blockers = [
        str(item) for item in _as_list(result.get("automatic_blockers")) if isinstance(item, str)
    ]
    artifact_type = "suite" if isinstance(result.get("cases"), list) else "comparison"

    extracted = dict(signoff_record)
    extracted["artifact_type"] = artifact_type
    extracted["automatic_blockers"] = automatic_blockers
    extracted["ready_for_signoff"] = not automatic_blockers

    if artifact_type == "suite":
        extracted["required_coverage_complete"] = result.get("required_coverage_complete") is True
        extracted["case_counts"] = _as_dict(result.get("case_counts"))

    return extracted


def _is_dual_track_candidate(summary: Mapping[str, Any]) -> bool:
    grounding_profile = _text(summary.get("grounding_profile")) or ""
    if _is_fallback_candidate(summary):
        return False
    return bool(summary.get("dual_track_grounding_enabled")) or grounding_profile.startswith(
        "dual_track"
    )


def _is_fallback_candidate(summary: Mapping[str, Any]) -> bool:
    grounding_profile = _text(summary.get("grounding_profile")) or ""
    return (
        bool(_text(summary.get("fallback_reason"))) or grounding_profile == "single_track_fallback"
    )


def _is_single_track_baseline(summary: Mapping[str, Any]) -> bool:
    if _is_dual_track_candidate(summary) or _is_fallback_candidate(summary):
        return False
    grounding_profile = _text(summary.get("grounding_profile"))
    return grounding_profile in {None, "", "single_track_v1"}


def _candidate_context_for_audit(audit: models.Audit) -> dict[str, Any]:
    summary = build_validation_summary_from_audit(audit)
    project = getattr(audit, "project", None)
    target_metadata = dict(getattr(audit, "target_metadata", None) or {})
    target_country = _text(target_metadata.get("target_country")) or _text(
        getattr(project, "target_country", None)
    )
    language = _text(target_metadata.get("language")) or _text(getattr(project, "language", None))
    target = _as_dict(summary.get("target"))

    return {
        "audit": audit,
        "summary": summary,
        "audit_id": getattr(audit, "id", None),
        "target_key": (
            f"{_text(target.get('type')) or 'website'}:"
            f"{_text(target.get('name')) or _normalized_url_text(target.get('url')) or 'unknown'}"
        ),
        "target_type": _text(target.get("type")) or "website",
        "requested_tier": _text(summary.get("requested_tier")),
        "target_country": target_country,
        "language": language,
        "has_contextual_brand_metadata": bool(target_metadata)
        or bool(target_country)
        or bool(language),
        "is_baseline": _is_single_track_baseline(summary),
        "is_dual_track_candidate": _is_dual_track_candidate(summary),
        "is_fallback_candidate": _is_fallback_candidate(summary),
        "created_at": getattr(audit, "created_at", None),
    }


def _pick_pair(
    records: Sequence[Mapping[str, Any]],
    *,
    candidate_filter,
    baseline_filter,
    used_audit_ids: set[int],
) -> dict[str, Any] | None:
    def _created_sort_value(record: Mapping[str, Any]) -> float:
        created_at = record.get("created_at")
        if isinstance(created_at, datetime):
            return created_at.timestamp()
        return float("-inf")

    sorted_candidates = sorted(
        (
            record
            for record in records
            if isinstance(record.get("audit_id"), int)
            and record["audit_id"] not in used_audit_ids
            and candidate_filter(record)
        ),
        key=lambda item: (
            _created_sort_value(item),
            int(item.get("audit_id") or 0),
        ),
        reverse=True,
    )

    for candidate in sorted_candidates:
        matching_baselines = sorted(
            (
                record
                for record in records
                if isinstance(record.get("audit_id"), int)
                and record["audit_id"] not in used_audit_ids
                and record["audit_id"] != candidate["audit_id"]
                and record.get("target_key") == candidate.get("target_key")
                and baseline_filter(record, candidate)
            ),
            key=lambda item: (
                _created_sort_value(item),
                int(item.get("audit_id") or 0),
            ),
            reverse=True,
        )
        if matching_baselines:
            baseline = matching_baselines[0]
            return {
                "baseline": baseline,
                "candidate": candidate,
            }
    return None


def discover_validation_suite_candidates(audits: Sequence[models.Audit]) -> dict[str, Any]:
    records = [_candidate_context_for_audit(audit) for audit in audits]
    used_audit_ids: set[int] = set()

    role_results: dict[str, dict[str, Any]] = {}

    def _register(role: str, pair: dict[str, Any] | None, *, review_type: str = "standard") -> None:
        if pair is None:
            role_results[role] = {
                "status": "missing",
                "reason": "No matching baseline/candidate audit pair was found in persisted audits.",
            }
            return
        baseline = _as_dict(pair.get("baseline"))
        candidate = _as_dict(pair.get("candidate"))
        used_audit_ids.update(
            audit_id
            for audit_id in (baseline.get("audit_id"), candidate.get("audit_id"))
            if isinstance(audit_id, int)
        )
        role_results[role] = {
            "status": "ready",
            "case": {
                "case_id": role,
                "label": role.replace("_", " ").title(),
                "validation_role": role,
                "review_type": review_type,
                "baseline_audit_id": baseline.get("audit_id"),
                "candidate_audit_id": candidate.get("audit_id"),
            },
            "baseline_summary": baseline.get("summary"),
            "candidate_summary": candidate.get("summary"),
        }

    _register(
        "deep_judgment_exemplar",
        _pick_pair(
            records,
            used_audit_ids=used_audit_ids,
            candidate_filter=lambda record: (
                record.get("target_type") == "brand"
                and record.get("requested_tier") == "deep_judgment"
                and record.get("is_dual_track_candidate") is True
            ),
            baseline_filter=lambda record, candidate: (
                record.get("requested_tier") == "deep_judgment"
                and record.get("is_baseline") is True
                and record.get("target_type") == candidate.get("target_type")
            ),
        ),
    )
    _register(
        "website_control",
        _pick_pair(
            records,
            used_audit_ids=used_audit_ids,
            candidate_filter=lambda record: (
                record.get("target_type") == "website"
                and record.get("is_dual_track_candidate") is True
            ),
            baseline_filter=lambda record, candidate: (
                record.get("is_baseline") is True
                and record.get("target_type") == candidate.get("target_type")
            ),
        ),
    )
    _register(
        "brand_metadata_control",
        _pick_pair(
            records,
            used_audit_ids=used_audit_ids,
            candidate_filter=lambda record: (
                record.get("target_type") == "brand"
                and record.get("has_contextual_brand_metadata") is True
                and record.get("is_dual_track_candidate") is True
            ),
            baseline_filter=lambda record, candidate: (
                record.get("is_baseline") is True
                and record.get("target_type") == candidate.get("target_type")
            ),
        ),
    )
    _register(
        "fallback_control",
        _pick_pair(
            records,
            used_audit_ids=used_audit_ids,
            candidate_filter=lambda record: record.get("is_fallback_candidate") is True,
            baseline_filter=lambda record, candidate: (
                record.get("is_baseline") is True
                and record.get("target_type") == candidate.get("target_type")
            ),
        ),
        review_type="fallback_control",
    )

    ready_cases = [
        _as_dict(result.get("case"))
        for result in role_results.values()
        if _text(result.get("status")) == "ready"
    ]
    missing_roles = [
        role for role, result in role_results.items() if _text(result.get("status")) != "ready"
    ]

    return {
        "audits_scanned": len(records),
        "ready_case_count": len(ready_cases),
        "missing_roles": missing_roles,
        "roles": role_results,
        "draft_manifest": {
            "suite_label": "EPIC-03 discovered validation suite",
            "required_roles": list(REQUIRED_VALIDATION_ROLES),
            "cases": ready_cases,
        },
    }


def render_discovered_validation_candidates_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# EPIC-03 Validation Candidate Discovery",
        "",
        "## Summary",
        f"- Audits scanned: {int(result.get('audits_scanned') or 0)}",
        f"- Ready cases: {int(result.get('ready_case_count') or 0)}",
        "",
        "## Roles",
    ]

    for role in REQUIRED_VALIDATION_ROLES:
        role_result = _as_dict(_as_dict(result.get("roles")).get(role))
        status = _text(role_result.get("status")) or "missing"
        lines.append(f"- {role}: {status}")
        if status == "ready":
            case = _as_dict(role_result.get("case"))
            lines.append(
                f"  baseline={case.get('baseline_audit_id') or 'n/a'} candidate={case.get('candidate_audit_id') or 'n/a'}"
            )
        else:
            lines.append(f"  reason={_text(role_result.get('reason')) or 'not available'}")

    missing_roles = [
        str(item) for item in _as_list(result.get("missing_roles")) if isinstance(item, str)
    ]
    lines.extend(
        [
            "",
            "## Missing Roles",
        ]
    )
    if missing_roles:
        lines.extend(f"- {item}" for item in missing_roles)
    else:
        lines.append("- None")

    return "\n".join(lines)
