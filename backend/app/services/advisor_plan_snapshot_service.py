"""Persist one Advisor-plan snapshot per completed audit (R12 progress foundation).

The deterministic Advisor plan is computed at response-time
(:func:`app.services.advisor_view.attach_advisor_view` → ``metadata.advisor``)
and never mutates the canonical contract. To later show plan progress / trend
over time (Executive tier), we record exactly one point-in-time copy of that
plan per audit in ``advisor_plan_snapshots``.

This module is **additive + defensive**: it reuses the existing plan shape
verbatim (it does not recompute the plan differently), never auto-executes
anything, and :func:`record_snapshot` must never raise into the audit-completion
caller — a snapshot failure can never break an audit.

The surrounding worker/routers use a synchronous SQLAlchemy ``Session``, so this
service uses the SQLAlchemy 2.0 ``select()`` / ``session.execute()`` API rather
than the legacy ``Query`` API (mirrors :mod:`app.services.learnings_service`).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from app.services.learnings_service import decision_key
from problem_codes import normalize_problem_code

logger = logging.getLogger(__name__)

_IMPACT_KEYS = ("high", "medium", "low")


def summarize_plan(advisor_plan: dict[str, Any] | None) -> dict[str, int]:
    """Return action counts for an Advisor plan: total + by impact label.

    Pure and defensive: a missing / malformed plan, a missing ``actions`` list,
    or actions without a recognised ``impact`` all degrade to zeros. Unknown
    impact labels are counted in ``total_actions`` only.
    """
    summary = {
        "total_actions": 0,
        "high_impact": 0,
        "medium_impact": 0,
        "low_impact": 0,
    }
    if not isinstance(advisor_plan, dict):
        return summary

    actions = advisor_plan.get("actions")
    if not isinstance(actions, list):
        return summary

    for action in actions:
        if not isinstance(action, dict):
            continue
        summary["total_actions"] += 1
        impact = str(action.get("impact") or "").strip().lower()
        if impact in _IMPACT_KEYS:
            summary[f"{impact}_impact"] += 1
    return summary


def _plan_has_actions(advisor_plan: dict[str, Any] | None) -> bool:
    if not isinstance(advisor_plan, dict):
        return False
    actions = advisor_plan.get("actions")
    return isinstance(actions, list) and any(isinstance(a, dict) for a in actions)


def record_snapshot(
    db: Session,
    audit_id: int | None,
    project_id: int | None,
    advisor_plan: dict[str, Any] | None,
) -> models.AdvisorPlanSnapshot | None:
    """Upsert one Advisor-plan snapshot for ``audit_id`` (one snapshot per audit).

    No-ops (returns ``None``) when ``audit_id``/``project_id`` is missing or the
    plan carries no actions. On re-run for the same audit the existing row is
    updated in place (no duplicate). Fully defensive: any error is logged and
    swallowed so a snapshot failure can never break audit completion.
    """
    try:
        if audit_id is None or project_id is None:
            return None
        if not _plan_has_actions(advisor_plan):
            return None

        summary = summarize_plan(advisor_plan)

        existing = db.execute(
            select(models.AdvisorPlanSnapshot).where(
                models.AdvisorPlanSnapshot.audit_id == audit_id
            )
        ).scalar_one_or_none()

        if existing is None:
            row = models.AdvisorPlanSnapshot(
                audit_id=audit_id,
                project_id=project_id,
                advisor_plan=advisor_plan,
                plan_summary=summary,
            )
            db.add(row)
        else:
            existing.project_id = project_id
            existing.advisor_plan = advisor_plan
            existing.plan_summary = summary
            row = existing

        db.flush()
        db.refresh(row)
        return row
    except Exception:
        logger.warning(
            "advisor plan snapshot persistence failed for audit %s", audit_id, exc_info=True
        )
        return None


def list_snapshots(
    db: Session,
    project_id: int,
    limit: int = 24,
) -> list[models.AdvisorPlanSnapshot]:
    """Return a project's Advisor-plan snapshots in chronological (oldest-first) order."""
    stmt = (
        select(models.AdvisorPlanSnapshot)
        .where(models.AdvisorPlanSnapshot.project_id == project_id)
        .order_by(
            models.AdvisorPlanSnapshot.created_at.asc(),
            models.AdvisorPlanSnapshot.id.asc(),
        )
        .limit(max(0, int(limit)))
    )
    return list(db.execute(stmt).scalars().all())


# --- Pure progress / delta helpers (R12 Executive progress surface) -------
#
# These functions are PURE and deterministic: no DB, no LLM, no network, no
# mutation. They reuse :func:`decision_key` for stable action identity across
# snapshots: the deterministic ``problem_code`` when the action carries one,
# otherwise the digest of the SAME ``action`` text field that the response-time
# plan stores (see ``services.advisor_service.build_advisor_plan``). That is
# exactly the key the Learnings loop dismisses on (see
# ``app.services.advisor_view``), so prev/curr fingerprints are directly
# comparable and progress cannot contradict suppression.

_SUMMARY_KEYS = ("total_actions", "high_impact", "medium_impact", "low_impact")


def _iter_actions(advisor_plan: dict[str, Any] | None):
    """Yield well-formed action dicts from a plan, defensively."""
    if not isinstance(advisor_plan, dict):
        return
    actions = advisor_plan.get("actions")
    if not isinstance(actions, list):
        return
    for action in actions:
        if isinstance(action, dict):
            yield action


def _action_view(action: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single action into the delta's stable shape (with fingerprint)."""
    text = str(action.get("action") or "").strip()
    code = normalize_problem_code(action.get("problem_code"))
    return {
        # Same key as suppression (``decision_key``): an action raised by a
        # deterministic check is identified by that check, so a reworded title
        # reads as "carried", not as one action resolved plus a new one added.
        # Two surfaces answering the same question with different keys would be
        # a defect in itself (SIGV2-1118).
        "fingerprint": decision_key(text, code),
        "problem_code": code,
        "action": text,
        "title": (str(action.get("title")).strip() if action.get("title") else None),
        "impact": str(action.get("impact") or "").strip().lower() or None,
        "effort": str(action.get("effort") or "").strip().lower() or None,
        "rank": action.get("rank") if isinstance(action.get("rank"), int) else None,
    }


def _fingerprint_index(advisor_plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map fingerprint -> normalised action view for a plan (first occurrence wins)."""
    index: dict[str, dict[str, Any]] = {}
    for action in _iter_actions(advisor_plan):
        view = _action_view(action)
        if not view["action"]:
            continue
        index.setdefault(view["fingerprint"], view)
    return index


def compute_plan_delta(
    prev_plan: dict[str, Any] | None,
    curr_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Diff two Advisor plans by stable action fingerprint.

    Pure + defensive. Returns ``actions_added`` (in ``curr`` not ``prev``),
    ``actions_resolved`` (in ``prev`` not ``curr``), ``actions_carried`` (in
    both), an ``impact_delta`` (curr summary minus prev summary, per count key),
    and the two summaries. When ``prev_plan`` is ``None``/empty every current
    action is treated as added.
    """
    prev_index = _fingerprint_index(prev_plan)
    curr_index = _fingerprint_index(curr_plan)

    added = [view for fp, view in curr_index.items() if fp not in prev_index]
    resolved = [view for fp, view in prev_index.items() if fp not in curr_index]
    carried = [view for fp, view in curr_index.items() if fp in prev_index]

    summary_prev = summarize_plan(prev_plan)
    summary_curr = summarize_plan(curr_plan)
    impact_delta = {key: summary_curr[key] - summary_prev[key] for key in _SUMMARY_KEYS}

    return {
        "actions_added": added,
        "actions_resolved": resolved,
        "actions_carried": carried,
        "impact_delta": impact_delta,
        "summary_prev": summary_prev,
        "summary_curr": summary_curr,
    }


def _snapshot_attr(snapshot: Any, name: str) -> Any:
    """Read an attribute from an ORM row or a plain dict, defensively."""
    if isinstance(snapshot, dict):
        return snapshot.get(name)
    return getattr(snapshot, name, None)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def build_plan_progress(snapshots: list[Any] | None) -> dict[str, Any]:
    """Summarise plan progress across chronological (oldest-first) snapshots.

    Pure + defensive. Returns ``latest_summary``, ``first_summary``, a ``trend``
    (``{created_at, total_actions, high_impact}`` per snapshot, in order), and
    ``latest_delta`` (the delta between the last two snapshots). With fewer than
    two snapshots ``latest_delta`` is ``None``; with zero snapshots every field
    degrades to an empty-but-valid shape.
    """
    rows = list(snapshots or [])

    trend: list[dict[str, Any]] = []
    for snapshot in rows:
        summary = _snapshot_attr(snapshot, "plan_summary")
        if not isinstance(summary, dict):
            summary = summarize_plan(_snapshot_attr(snapshot, "advisor_plan"))
        trend.append(
            {
                "created_at": _isoformat(_snapshot_attr(snapshot, "created_at")),
                "total_actions": int(summary.get("total_actions", 0) or 0),
                "high_impact": int(summary.get("high_impact", 0) or 0),
            }
        )

    def _summary_of(snapshot: Any) -> dict[str, int]:
        summary = _snapshot_attr(snapshot, "plan_summary")
        if isinstance(summary, dict):
            return {key: int(summary.get(key, 0) or 0) for key in _SUMMARY_KEYS}
        return summarize_plan(_snapshot_attr(snapshot, "advisor_plan"))

    latest_summary = _summary_of(rows[-1]) if rows else None
    first_summary = _summary_of(rows[0]) if rows else None

    latest_delta = None
    if len(rows) >= 2:
        latest_delta = compute_plan_delta(
            _snapshot_attr(rows[-2], "advisor_plan"),
            _snapshot_attr(rows[-1], "advisor_plan"),
        )

    return {
        "latest_summary": latest_summary,
        "first_summary": first_summary,
        "trend": trend,
        "latest_delta": latest_delta,
    }
