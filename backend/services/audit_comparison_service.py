"""
Audit Comparison Service, AEX-19

Provides score delta calculations between consecutive audits of the same
target (URL or brand) and score history for sparkline visualisation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

import models
from services.audit_normalization_service import resolve_effective_audit_scores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metric_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def _metric_direction(delta: float | None) -> str:
    if delta is None:
        return "stable"
    if delta > 1:
        return "up"
    if delta < -1:
        return "down"
    return "stable"


def _extract_v3_breakdown(report: dict, domain: str) -> dict[str, float]:
    """Extract V3 sub-component scores from a report's scores breakdown."""
    scores = report.get("scores") if isinstance(report, dict) else {}
    if not isinstance(scores, dict):
        return {}
    breakdown = scores.get(f"{domain}_breakdown")
    if not isinstance(breakdown, dict):
        return {}
    components = breakdown.get("components")
    if not isinstance(components, dict):
        return {}
    return {k: v for k, v in components.items() if isinstance(v, (int, float))}


def _build_score_entry(
    scores: dict[str, float | None],
    *,
    direction: bool = False,
    previous: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """Build a score entry dict with optional delta/direction fields."""
    entry: dict[str, Any] = {}
    for key in ("overall", "seo", "geo", "aeo"):
        current_val = scores.get(key)
        entry[key] = {"current": current_val}
        if previous is not None:
            prev_val = previous.get(key)
            delta = _metric_delta(current_val, prev_val)
            entry[key]["previous"] = prev_val
            entry[key]["delta"] = delta
            if direction:
                entry[key]["direction"] = _metric_direction(delta)
    return entry


# ---------------------------------------------------------------------------
# Core queries
# ---------------------------------------------------------------------------


def _target_filter(audit: models.Audit):
    """Match by URL for website audits, by target_name for brand audits."""
    target_type = getattr(audit, "audit_target_type", None)
    if target_type is not None and hasattr(target_type, "value"):
        target_type = target_type.value

    if target_type == "brand" and audit.target_name:
        return models.Audit.target_name == audit.target_name
    return models.Audit.url == audit.url


def _depth_filter(audit: models.Audit):
    """Scan depth must match exactly.

    A Fast scan and a Deep scan of the same site run different pipelines and
    produce scores on different evidence, so a delta between them measures the
    pipeline, not the site (SIGV2-1109).
    """
    depth = getattr(audit, "audit_type", None)
    if depth is None:
        return models.Audit.audit_type.is_(None)
    return models.Audit.audit_type == depth


def _project_filter(audit: models.Audit):
    """Project must match exactly, including "no project" on both sides."""
    project_id = getattr(audit, "project_id", None)
    if project_id is None:
        return models.Audit.project_id.is_(None)
    return models.Audit.project_id == project_id


def _comparable_audit_filters(audit: models.Audit, user_id: int) -> list:
    """Filters every audit must satisfy to be comparable with *audit*."""
    return [
        models.Audit.user_id == user_id,
        models.Audit.geo_score.isnot(None),
        _target_filter(audit),
        _depth_filter(audit),
        _project_filter(audit),
    ]


def _find_previous_audit(
    db: Session,
    audit: models.Audit,
    user_id: int,
) -> models.Audit | None:
    """Find the most recent comparable completed audit before *audit*.

    Comparable means: same user, same target, same scan depth and same project.
    None of those constraints is relaxed on a miss. When nothing matches, the
    honest answer is "no baseline", not a delta against an audit that was
    produced by a different pipeline or belongs to another project.
    """
    filters = [
        models.Audit.id != audit.id,
        models.Audit.created_at < audit.created_at,
        *_comparable_audit_filters(audit, user_id),
    ]

    return (
        db.query(models.Audit)
        .filter(and_(*filters))
        .order_by(models.Audit.created_at.desc())
        .first()
    )


def _load_audit_history(
    db: Session,
    audit: models.Audit,
    user_id: int,
    *,
    limit: int = 20,
) -> list[models.Audit]:
    """Load the last *limit* comparable audits for the same target, ordered oldest to newest.

    Comparability is the same rule the baseline uses: same target, same scan
    depth, same project. A trend line that mixes depths plots pipeline
    differences as if they were movement of the site.
    """
    filters = _comparable_audit_filters(audit, user_id)

    audits = (
        db.query(models.Audit)
        .filter(and_(*filters))
        .order_by(models.Audit.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(audits))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_audit_comparison(
    db: Session,
    audit_id: int,
    user_id: int,
) -> dict[str, Any] | None:
    """
    Return score comparison data for *audit_id* vs the previous audit of the
    same target.  Returns ``None`` when the audit does not exist or does not
    belong to *user_id*.
    """
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == audit_id, models.Audit.user_id == user_id)
        .first()
    )
    if not audit:
        return None

    current_scores = resolve_effective_audit_scores(audit)
    previous = _find_previous_audit(db, audit, user_id)

    if previous is None:
        return {
            "audit_id": audit.id,
            "has_previous": False,
            "scores": _build_score_entry(current_scores),
            "sub_components": {},
            "history": _build_history_points(db, audit, user_id),
        }

    previous_scores = resolve_effective_audit_scores(previous)

    # Sub-component deltas (V3 breakdowns)
    sub_components: dict[str, Any] = {}
    current_report = audit.full_report if isinstance(audit.full_report, dict) else {}
    previous_report = previous.full_report if isinstance(previous.full_report, dict) else {}

    for domain in ("seo", "geo", "aeo"):
        curr_comps = _extract_v3_breakdown(current_report, domain)
        prev_comps = _extract_v3_breakdown(previous_report, domain)
        if curr_comps or prev_comps:
            all_keys = sorted(set(curr_comps) | set(prev_comps))
            domain_deltas = {}
            for key in all_keys:
                c = curr_comps.get(key)
                p = prev_comps.get(key)
                delta = _metric_delta(c, p)
                domain_deltas[key] = {
                    "current": c,
                    "previous": p,
                    "delta": delta,
                    "direction": _metric_direction(delta),
                }
            sub_components[domain] = domain_deltas

    scores_entry = {}
    for key in ("overall", "seo", "geo", "aeo"):
        c = current_scores.get(key)
        p = previous_scores.get(key)
        delta = _metric_delta(c, p)
        scores_entry[key] = {
            "current": c,
            "previous": p,
            "delta": delta,
            "direction": _metric_direction(delta),
        }

    return {
        "audit_id": audit.id,
        "has_previous": True,
        "previous_audit_id": previous.id,
        "previous_audit_date": previous.created_at.isoformat() if previous.created_at else None,
        "scores": scores_entry,
        "sub_components": sub_components,
        "history": _build_history_points(db, audit, user_id),
    }


def _build_history_points(
    db: Session,
    audit: models.Audit,
    user_id: int,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Build sparkline-ready score history points."""
    audits = _load_audit_history(db, audit, user_id, limit=limit)
    points: list[dict[str, Any]] = []
    for a in audits:
        scores = resolve_effective_audit_scores(a)
        points.append(
            {
                "audit_id": a.id,
                "date": a.created_at.isoformat() if a.created_at else "",
                "overall": scores.get("overall"),
                "seo": scores.get("seo"),
                "geo": scores.get("geo"),
                "aeo": scores.get("aeo"),
            }
        )
    return points
