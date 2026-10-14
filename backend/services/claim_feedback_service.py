"""Claim feedback service, AEX-26.

Provides CRUD and analytics for per-claim feedback on audit findings.
Uses the same ``claim_key`` hash as the report-annotation service so that
feedback survives finding reordering across re-audits.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from models import ClaimFeedback, ClaimFeedbackType


# ── Claim key generation (mirrors annotation service) ───────────────


def _normalize_key_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:80]


def build_claim_key(*, title: str, category: str, description: str | None = None) -> str:
    title_key = _normalize_key_fragment(title)
    category_key = _normalize_key_fragment(category)
    description_key = _normalize_key_fragment(description or "")
    digest = hashlib.sha256(
        f"{category_key}|{title_key}|{description_key}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{category_key or 'general'}:{title_key or 'recommendation'}:{digest}"


# ── CRUD ────────────────────────────────────────────────────────────


def upsert_feedback(
    db: Session,
    *,
    audit_id: int,
    user_id: int,
    claim_key: str,
    claim_text: str,
    claim_category: str | None,
    feedback_type: str,
    feedback_text: str | None = None,
) -> ClaimFeedback:
    """Insert or update feedback for a specific claim from a specific user."""
    existing = (
        db.query(ClaimFeedback)
        .filter_by(audit_id=audit_id, claim_key=claim_key, user_id=user_id)
        .first()
    )
    ft = ClaimFeedbackType(feedback_type)
    if existing:
        existing.feedback_type = ft
        existing.feedback_text = feedback_text
        existing.claim_text = claim_text
        existing.claim_category = claim_category
        existing.updated_at = datetime.now(timezone.utc)
        db.flush()
        return existing

    fb = ClaimFeedback(
        audit_id=audit_id,
        user_id=user_id,
        claim_key=claim_key,
        claim_text=claim_text,
        claim_category=claim_category,
        feedback_type=ft,
        feedback_text=feedback_text,
    )
    db.add(fb)
    db.flush()
    return fb


def delete_feedback(db: Session, *, feedback_id: int, user_id: int) -> bool:
    """Delete feedback owned by user_id. Returns True if deleted."""
    row = db.query(ClaimFeedback).filter_by(id=feedback_id, user_id=user_id).first()
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def get_feedback_for_audit(
    db: Session,
    *,
    audit_id: int,
    user_id: int | None = None,
) -> list[ClaimFeedback]:
    """Get all feedback for an audit, optionally filtered to one user."""
    q = db.query(ClaimFeedback).filter_by(audit_id=audit_id)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    return q.order_by(ClaimFeedback.created_at.asc()).all()


def get_feedback_summary_for_audit(
    db: Session,
    *,
    audit_id: int,
) -> dict[str, dict[str, int]]:
    """Return {claim_key: {agree: N, disagree: N, fixed: N}} for an audit."""
    rows = (
        db.query(
            ClaimFeedback.claim_key,
            ClaimFeedback.feedback_type,
            func.count(ClaimFeedback.id),
        )
        .filter_by(audit_id=audit_id)
        .group_by(ClaimFeedback.claim_key, ClaimFeedback.feedback_type)
        .all()
    )
    summary: dict[str, dict[str, int]] = {}
    for claim_key, fb_type, count in rows:
        if claim_key not in summary:
            summary[claim_key] = {"agree": 0, "disagree": 0, "fixed": 0}
        summary[claim_key][fb_type.value if hasattr(fb_type, "value") else fb_type] = count
    return summary


# ── Re-audit helpers ────────────────────────────────────────────────


def get_previous_feedback_for_url(
    db: Session,
    *,
    url: str,
    current_audit_id: int,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get claim keys that were marked 'fixed' or 'disagree' in previous audits
    for the same URL, to show as context in a re-audit."""
    q = (
        db.query(ClaimFeedback)
        .join(models.Audit, ClaimFeedback.audit_id == models.Audit.id)
        .filter(
            models.Audit.url == url,
            ClaimFeedback.audit_id != current_audit_id,
            ClaimFeedback.feedback_type.in_(
                [
                    ClaimFeedbackType.FIXED,
                    ClaimFeedbackType.DISAGREE,
                ]
            ),
        )
    )
    if project_id:
        q = q.filter(models.Audit.project_id == project_id)

    q = q.order_by(ClaimFeedback.created_at.desc())
    rows = q.all()

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.claim_key not in seen:
            seen[row.claim_key] = {
                "claim_key": row.claim_key,
                "claim_text": row.claim_text,
                "claim_category": row.claim_category,
                "feedback_type": row.feedback_type.value,
                "feedback_text": row.feedback_text,
                "audit_id": row.audit_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
    return list(seen.values())


# ── Admin analytics ─────────────────────────────────────────────────


def get_feedback_analytics(
    db: Session,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """Aggregate feedback analytics for admin dashboard."""
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta

    cutoff = cutoff - timedelta(days=days)

    base = db.query(ClaimFeedback).filter(ClaimFeedback.created_at >= cutoff)

    # Total counts by type
    type_counts = (
        base.with_entities(
            ClaimFeedback.feedback_type,
            func.count(ClaimFeedback.id),
        )
        .group_by(ClaimFeedback.feedback_type)
        .all()
    )
    totals = {"agree": 0, "disagree": 0, "fixed": 0}
    for fb_type, count in type_counts:
        totals[fb_type.value if hasattr(fb_type, "value") else fb_type] = count

    total = sum(totals.values())

    # Disagree rate by category
    category_stats = (
        base.with_entities(
            ClaimFeedback.claim_category,
            ClaimFeedback.feedback_type,
            func.count(ClaimFeedback.id),
        )
        .group_by(ClaimFeedback.claim_category, ClaimFeedback.feedback_type)
        .all()
    )
    cat_agg: dict[str, dict[str, int]] = {}
    for cat, fb_type, count in category_stats:
        cat_name = cat or "Uncategorized"
        if cat_name not in cat_agg:
            cat_agg[cat_name] = {"agree": 0, "disagree": 0, "fixed": 0, "total": 0}
        ft_val = fb_type.value if hasattr(fb_type, "value") else fb_type
        cat_agg[cat_name][ft_val] = count
        cat_agg[cat_name]["total"] += count

    categories = []
    for cat_name, stats in sorted(cat_agg.items(), key=lambda x: -x[1]["total"]):
        cat_total = stats["total"]
        categories.append(
            {
                "category": cat_name,
                "total": cat_total,
                "agree": stats["agree"],
                "disagree": stats["disagree"],
                "fixed": stats["fixed"],
                "disagree_rate": round(stats["disagree"] / cat_total * 100, 1)
                if cat_total > 0
                else 0,
            }
        )

    # Most-disagreed claim patterns (>= 2 disagrees)
    flagged_claims = (
        base.with_entities(
            ClaimFeedback.claim_key,
            ClaimFeedback.claim_text,
            ClaimFeedback.claim_category,
            func.count(ClaimFeedback.id).label("disagree_count"),
        )
        .filter(ClaimFeedback.feedback_type == ClaimFeedbackType.DISAGREE)
        .group_by(ClaimFeedback.claim_key, ClaimFeedback.claim_text, ClaimFeedback.claim_category)
        .having(func.count(ClaimFeedback.id) >= 2)
        .order_by(func.count(ClaimFeedback.id).desc())
        .limit(20)
        .all()
    )
    flagged = [
        {
            "claim_key": ck,
            "claim_text": ct,
            "claim_category": cc,
            "disagree_count": dc,
        }
        for ck, ct, cc, dc in flagged_claims
    ]

    # Daily volume for time-series chart
    daily_volume = (
        base.with_entities(
            func.date_trunc("day", ClaimFeedback.created_at).label("day"),
            ClaimFeedback.feedback_type,
            func.count(ClaimFeedback.id),
        )
        .group_by("day", ClaimFeedback.feedback_type)
        .order_by("day")
        .all()
    )
    daily: dict[str, dict[str, int]] = {}
    for day, fb_type, count in daily_volume:
        day_str = day.strftime("%Y-%m-%d") if hasattr(day, "strftime") else str(day)[:10]
        if day_str not in daily:
            daily[day_str] = {"date": day_str, "agree": 0, "disagree": 0, "fixed": 0}
        ft_val = fb_type.value if hasattr(fb_type, "value") else fb_type
        daily[day_str][ft_val] = count

    return {
        "total_feedback": total,
        "totals": totals,
        "disagree_rate": round(totals["disagree"] / total * 100, 1) if total > 0 else 0,
        "categories": categories,
        "flagged_claims": flagged,
        "daily_volume": list(daily.values()),
    }
