from collections import defaultdict
from typing import Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from prometheus_client import REGISTRY

import models
from database import get_db
from auth.token_verifier import get_current_staff_user
from services.prompt_quality_calibration_service import prompt_quality_calibration_service
from services.prompt_quality_gate import QUALITY_GATE_SCHEMA_VERSION, prompt_quality_gate_service

router = APIRouter(prefix="/admin/observability", tags=["admin-observability"])

DUAL_TRACK_CANONICAL_DESCRIPTION = (
    "Dual-track grounding runs automatically for deep_judgment audits. "
    "Lower tiers remain single-track."
)


def _collect_prompt_quality_gate_metrics(
    *,
    db: Session,
    cutoff_date: datetime,
    window_days: int,
    end_date: datetime | None = None,
    requested_tiers: list[str] | None = None,
) -> dict[str, Any]:
    audits_query = db.query(models.Audit).filter(models.Audit.created_at >= cutoff_date)
    if end_date is not None:
        audits_query = audits_query.filter(models.Audit.created_at < end_date)
    audits = audits_query.order_by(desc(models.Audit.created_at)).all()

    audits_checked = 0
    audits_failed = 0
    violation_counts: dict[str, int] = {}
    tier_summary: dict[str, dict[str, Any]] = {}
    recent_failures: list[dict[str, Any]] = []

    for audit in audits:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        debate = report.get("debate") if isinstance(report.get("debate"), dict) else {}
        quality_gate = (
            debate.get("quality_gate") if isinstance(debate.get("quality_gate"), dict) else {}
        )
        if not quality_gate:
            continue

        requested_tier = (
            str(
                quality_gate.get("requested_tier") or debate.get("requested_tier") or "unknown"
            ).strip()
            or "unknown"
        )
        if requested_tiers and requested_tier not in requested_tiers:
            continue
        audits_checked += 1
        pipeline_type = (
            str(
                quality_gate.get("pipeline_type") or debate.get("pipeline_type") or "unknown"
            ).strip()
            or "unknown"
        )
        passed = bool(quality_gate.get("passed"))
        violations = (
            quality_gate.get("violations")
            if isinstance(quality_gate.get("violations"), list)
            else []
        )

        bucket = tier_summary.setdefault(
            requested_tier,
            {
                "audits_checked": 0,
                "audits_failed": 0,
                "violation_count": 0,
            },
        )
        bucket["audits_checked"] += 1
        bucket["violation_count"] += len(violations)

        if not passed:
            audits_failed += 1
            bucket["audits_failed"] += 1
            recent_failures.append(
                {
                    "audit_id": audit.id,
                    "created_at": audit.created_at.isoformat() if audit.created_at else None,
                    "requested_tier": requested_tier,
                    "pipeline_type": pipeline_type,
                    "violation_codes": [
                        str(item.get("code") or "unknown")
                        for item in violations
                        if isinstance(item, dict)
                    ],
                }
            )

        for violation in violations:
            if not isinstance(violation, dict):
                continue
            code = str(violation.get("code") or "unknown").strip() or "unknown"
            violation_counts[code] = violation_counts.get(code, 0) + 1

    top_violations = [
        {"code": code, "count": count}
        for code, count in sorted(violation_counts.items(), key=lambda item: (-item[1], item[0]))[
            :5
        ]
    ]

    failure_rate = round(audits_failed / audits_checked, 4) if audits_checked else 0.0
    for bucket in tier_summary.values():
        checked = int(bucket["audits_checked"] or 0)
        failed = int(bucket["audits_failed"] or 0)
        bucket["failure_rate"] = round(failed / checked, 4) if checked else 0.0

    return {
        "schema_version": QUALITY_GATE_SCHEMA_VERSION,
        "window_days": window_days,
        "audits_checked": audits_checked,
        "audits_failed": audits_failed,
        "failure_rate": failure_rate,
        "thresholds": dict(prompt_quality_gate_service.THRESHOLDS),
        "top_violations": top_violations,
        "tier_summary": dict(sorted(tier_summary.items())),
        "recent_failures": recent_failures[:10],
    }


def _collect_dual_track_grounding_metrics() -> dict[str, Any]:
    claim_dispositions: dict[str, dict[str, int]] = defaultdict(dict)
    reason_codes: dict[str, dict[str, int]] = defaultdict(dict)
    fallback_reasons: dict[str, int] = {}

    claims_observed = 0
    reason_codes_observed = 0
    fallbacks_observed = 0

    try:
        for metric in REGISTRY.collect():
            if metric.name == "audit_dual_track_claims_total":
                for sample in metric.samples:
                    if sample.name != "audit_dual_track_claims_total_total":
                        continue
                    track = str(sample.labels.get("track", "unknown") or "unknown")
                    disposition = str(sample.labels.get("disposition", "unknown") or "unknown")
                    value = int(sample.value)
                    if value <= 0:
                        continue
                    claim_dispositions[track][disposition] = (
                        claim_dispositions[track].get(disposition, 0) + value
                    )
                    claims_observed += value
            elif metric.name == "audit_dual_track_reason_codes_total":
                for sample in metric.samples:
                    if sample.name != "audit_dual_track_reason_codes_total_total":
                        continue
                    track = str(sample.labels.get("track", "unknown") or "unknown")
                    reason_code = str(sample.labels.get("reason_code", "unknown") or "unknown")
                    value = int(sample.value)
                    if value <= 0:
                        continue
                    reason_codes[track][reason_code] = (
                        reason_codes[track].get(reason_code, 0) + value
                    )
                    reason_codes_observed += value
            elif metric.name == "audit_dual_track_fallback_total":
                for sample in metric.samples:
                    if sample.name != "audit_dual_track_fallback_total_total":
                        continue
                    fallback_reason = str(
                        sample.labels.get("fallback_reason", "unknown") or "unknown"
                    )
                    value = int(sample.value)
                    if value <= 0:
                        continue
                    fallback_reasons[fallback_reason] = (
                        fallback_reasons.get(fallback_reason, 0) + value
                    )
                    fallbacks_observed += value
    except Exception:
        pass

    top_reason_codes: list[dict[str, object]] = []
    for track, track_reason_codes in reason_codes.items():
        for reason_code, count in track_reason_codes.items():
            top_reason_codes.append(
                {
                    "track": track,
                    "reason_code": reason_code,
                    "count": count,
                }
            )
    top_reason_codes.sort(
        key=lambda item: (-int(item["count"]), str(item["track"]), str(item["reason_code"]))
    )

    return {
        "claims_observed": claims_observed,
        "reason_codes_observed": reason_codes_observed,
        "fallbacks_observed": fallbacks_observed,
        "claim_dispositions": {
            track: dict(sorted(dispositions.items()))
            for track, dispositions in sorted(claim_dispositions.items())
        },
        "reason_codes": {
            track: dict(sorted(track_reason_codes.items()))
            for track, track_reason_codes in sorted(reason_codes.items())
        },
        "fallback_reasons": dict(sorted(fallback_reasons.items())),
        "top_reason_codes": top_reason_codes[:5],
    }


@router.get("/metrics")
def get_historical_metrics(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Fetch time-series data of metrics snapshots for the observability chart."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots = (
        db.query(models.MetricsSnapshot)
        .filter(models.MetricsSnapshot.snapshot_at >= cutoff_date)
        .order_by(asc(models.MetricsSnapshot.snapshot_at))
        .all()
    )

    return [
        {
            "id": s.id,
            "snapshot_at": s.snapshot_at.isoformat(),
            "requests_total": s.requests_total,
            "requests_2xx": s.requests_2xx,
            "requests_4xx": s.requests_4xx,
            "requests_5xx": s.requests_5xx,
            "latency_p50_ms": s.latency_p50_ms,
            "latency_p95_ms": s.latency_p95_ms,
            "latency_p99_ms": s.latency_p99_ms,
            "latency_avg_ms": s.latency_avg_ms,
            "audit_jobs_completed": s.audit_jobs_completed,
            "audit_jobs_failed": s.audit_jobs_failed,
            "audit_avg_duration_seconds": s.audit_avg_duration_seconds,
            "slow_endpoints": s.slow_endpoints,
        }
        for s in snapshots
    ]


@router.get("/slow-endpoints")
def get_slow_endpoints(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Fetch the latest snapshot to list the current slow endpoints."""
    latest_snapshot = (
        db.query(models.MetricsSnapshot).order_by(desc(models.MetricsSnapshot.snapshot_at)).first()
    )

    if not latest_snapshot or not latest_snapshot.slow_endpoints:
        return {}

    return latest_snapshot.slow_endpoints


@router.get("/uptime")
def get_uptime_stats(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Calculate uptime percentage based on 5xx errors from snapshots."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots = (
        db.query(models.MetricsSnapshot)
        .filter(models.MetricsSnapshot.snapshot_at >= cutoff_date)
        .order_by(asc(models.MetricsSnapshot.snapshot_at))
        .all()
    )

    if not snapshots:
        return {"uptime_percentage": 100.0, "total_downtime_minutes": 0}

    # A snapshot is taken every X minutes (e.g., 5 or 15 mins by cron).
    # We estimate based on consecutive snapshot deltas if error rate > 5%.

    # Actually, simpler: count snapshots where 5xx > 5% of total requests
    total_snapshots = len(snapshots)
    down_snapshots = 0

    # We need to look at the DELTA between snapshots to know the errors in that interval,
    # because metrics are cumulative counters.

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        req_delta = curr.requests_total - prev.requests_total
        err_delta = curr.requests_5xx - prev.requests_5xx

        if req_delta > 0:
            error_rate = err_delta / req_delta
            if error_rate >= 0.05:
                down_snapshots += 1

    # If using crons that run every 5 mins, each down snapshot = ~5 mins downtime.
    # We can just return the raw ratio
    if total_snapshots <= 1:
        return {"uptime_percentage": 100.0, "total_downtime_minutes": 0}

    uptime_ratio = 1.0 - (down_snapshots / (total_snapshots - 1))

    # Assumes cron runs every 15 minutes as defualt SWE cron job?
    # Usually SWE cron is set to run every 15m or 1h. For demo, we just multiply by an arbitrary 15.
    return {
        "uptime_percentage": round(uptime_ratio * 100, 4),
        "total_downtime_minutes": down_snapshots * 15,
    }


@router.get("/dual-track-grounding")
def get_dual_track_grounding_snapshot(
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Expose canonical dual-track runtime semantics."""
    del admin_user
    del db
    return {
        "mode": "canonical_deep_judgment",
        "description": DUAL_TRACK_CANONICAL_DESCRIPTION,
        "effective_scope": "deep_judgment_only",
        "source": "canonical",
        "metrics": _collect_dual_track_grounding_metrics(),
    }


@router.get("/prompt-quality-gate")
def get_prompt_quality_gate_snapshot(
    days: int = Query(7, ge=1, le=30),
    tier: str | None = Query(None, pattern="^(fast|smart|deep_judgment)$"),
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Expose recent Orchestra V3 prompt quality-gate outcomes for admin calibration work."""
    del admin_user
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=days)
    previous_cutoff_date = cutoff_date - timedelta(days=days)
    requested_tiers = [tier] if isinstance(tier, str) and tier.strip() else None

    current_window = _collect_prompt_quality_gate_metrics(
        db=db,
        cutoff_date=cutoff_date,
        end_date=now,
        window_days=days,
        requested_tiers=requested_tiers,
    )
    previous_window = _collect_prompt_quality_gate_metrics(
        db=db,
        cutoff_date=previous_cutoff_date,
        end_date=cutoff_date,
        window_days=days,
        requested_tiers=requested_tiers,
    )

    current_window["comparison"] = {
        "previous_window": {
            "window_days": days,
            "audits_checked": previous_window["audits_checked"],
            "audits_failed": previous_window["audits_failed"],
            "failure_rate": previous_window["failure_rate"],
        },
        "deltas": {
            "audits_checked": current_window["audits_checked"] - previous_window["audits_checked"],
            "audits_failed": current_window["audits_failed"] - previous_window["audits_failed"],
            "failure_rate": round(
                float(current_window["failure_rate"]) - float(previous_window["failure_rate"]),
                4,
            ),
        },
    }
    return current_window


@router.get("/prompt-quality-calibration")
def get_prompt_quality_calibration_snapshot(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    tier: str | None = Query(None, pattern="^(fast|smart|deep_judgment)$"),
    audit_id: list[int] | None = Query(None),
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_staff_user),
) -> Any:
    """Expose prompt-calibration readiness, trace coverage, and suggested prompt files."""
    del admin_user
    requested_tiers = [tier] if isinstance(tier, str) and tier.strip() else None
    return prompt_quality_calibration_service.build_report(
        db=db,
        days=None if audit_id else days,
        audit_ids=audit_id,
        requested_tiers=requested_tiers,
        limit=limit,
    )
