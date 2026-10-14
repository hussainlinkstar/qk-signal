"""Service for the user-facing learnings loop (recommendation decisions).

Task 7.2 of the Qiko Signal learnings phase. Users mark Advisor recommendations
as ``accepted`` or ``dismissed`` (optionally with a note); decisions are stored
per project keyed by ``action_fingerprint``. Dismissed recommendations are
suppressed from the Advisor plan on future audits; the full history feeds a
user-facing Learnings view and the data moat.

``action_fingerprint`` holds one of two kinds of key, and lookups accept both,
permanently (SIGV2-1118):

* ``problem:<code>`` for a recommendation raised by a deterministic check
  (:mod:`problem_codes`). The code does not change between audits, so the
  dismissal survives the LLM rewording the fix's title.
* the legacy sha256 digest of the action text, for LLM-only advice and for
  every row stored before problem codes existed. Those older rows cannot be
  re-keyed (the oldest have no ``action_label`` to re-key from), so this path
  is permanent rather than transitional.

Mirrors :mod:`app.services.brand_facts_service`: the surrounding routers use a
synchronous SQLAlchemy ``Session``, so this service uses the SQLAlchemy 2.0
``select()`` / ``session.execute()`` API rather than the legacy ``Query`` API.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from problem_codes import problem_code_key

ALLOWED_DECISIONS: frozenset[str] = frozenset({"accepted", "dismissed"})
MAX_DECISION_NOTE_CHARS = 2000
MAX_ACTION_LABEL_CHARS = 500

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def compute_action_fingerprint(action_text: str) -> str:
    """Return the legacy sha256 fingerprint for an Advisor action.

    Identity by action text. It holds WITHIN one audit, but the text is written
    by an LLM on every run, so a rewording produces a different digest and the
    dismissal stops matching. Superseded by ``problem_code`` identity where a
    deterministic code exists (see :func:`decision_key` and SIGV2-1118), and
    retained permanently as the fallback and for every row already stored.
    ``sha256`` only (``md5`` / ``sha1`` are forbidden).
    """
    normalized = str(action_text or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def decision_key(action_text: str | None, problem_code: object = None) -> str:
    """Return the key a dismissal should be STORED under.

    Prefers the deterministic ``problem_code`` key, which survives a reworded
    title; falls back to the action-text digest when the recommendation has no
    code (LLM-only advice). An unknown code is treated as absent.
    """
    key = problem_code_key(problem_code)
    return key if key else compute_action_fingerprint(action_text or "")


def suppression_keys(action_text: str | None, problem_code: object = None) -> set[str]:
    """Return every key under which this recommendation may have been dismissed.

    Both keys are always checked, permanently and not transitionally: rows
    written before problem codes existed hold the text digest, and the oldest of
    them have a NULL ``action_label``, so they can never be re-keyed by any
    backfill. Dropping the legacy key would resurface every fix every customer
    has ever dismissed.
    """
    keys = {compute_action_fingerprint(action_text or "")}
    key = problem_code_key(problem_code)
    if key:
        keys.add(key)
    return keys


def is_suppressed(
    dismissed: Collection[str] | None,
    action_text: str | None,
    problem_code: object = None,
) -> bool:
    """Return True when a dismissal recorded for this project covers this action.

    Matches the deterministic code key OR the legacy text digest. Both are exact
    string comparisons: no fuzzy, embedding or token-overlap matching is used
    anywhere in this path, deliberately. The asymmetry that drives the design is
    that a dismissed fix reappearing is visible and merely annoying, whereas
    hiding a fix the customer never dismissed silently withholds paid-for advice,
    so identity must only ever fail toward showing the fix.
    """
    if not dismissed:
        return False
    return bool(suppression_keys(action_text, problem_code) & set(dismissed))


def normalize_decision(raw_decision: str | None) -> str:
    decision = str(raw_decision or "").strip().lower()
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"Decision must be one of: {', '.join(sorted(ALLOWED_DECISIONS))}.")
    return decision


def _sanitize_note(raw_note: str | None) -> str | None:
    if raw_note is None:
        return None
    note = str(raw_note).strip()
    if not note:
        return None
    if len(note) > MAX_DECISION_NOTE_CHARS:
        raise ValueError(f"Decision note must be at most {MAX_DECISION_NOTE_CHARS} characters.")
    return note


def sanitize_action_label(raw_label: str | None) -> str | None:
    """Return a readable, storage-safe label for an Advisor action.

    Strips control characters, collapses whitespace and trims, then caps the
    length. Stored RAW (NOT HTML-escaped) per the brand-facts lesson: escaping
    at the storage layer double-escapes in the UI. React escapes the text node
    at render time. Returns ``None`` for blank/empty input so old rows and the
    fingerprint-only path keep a NULL label.
    """
    if raw_label is None:
        return None
    text = _CONTROL_CHARS_RE.sub(" ", str(raw_label))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    if len(text) > MAX_ACTION_LABEL_CHARS:
        text = text[:MAX_ACTION_LABEL_CHARS].rstrip()
    return text


def serialize_decision(decision: models.RecommendationDecision) -> dict:
    return {
        "id": int(decision.id),
        "project_id": int(decision.project_id),
        "action_fingerprint": decision.action_fingerprint,
        "action_label": decision.action_label,
        "decision": decision.decision,
        "note": decision.note,
        "decided_by": int(decision.decided_by) if decision.decided_by is not None else None,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def record_decision(
    db: Session,
    *,
    project_id: int,
    action_fingerprint: str,
    decision: str,
    decided_by: int | None,
    note: str | None = None,
    action_label: str | None = None,
) -> dict:
    """Upsert a recommendation decision on ``(project_id, action_fingerprint)``.

    ``action_label`` is a human-readable summary of the Advisor action used by
    the Learnings view. It is RAW-sanitized (control chars stripped, whitespace
    collapsed, length-capped — never HTML-escaped). A blank/None label is stored
    as NULL; on upsert a NULL label never overwrites an existing one.
    """
    normalized_decision = normalize_decision(decision)
    safe_note = _sanitize_note(note)
    safe_label = sanitize_action_label(action_label)
    fingerprint = str(action_fingerprint or "").strip().lower()
    if not fingerprint:
        raise ValueError("action_fingerprint must not be empty.")

    existing = db.execute(
        select(models.RecommendationDecision).where(
            models.RecommendationDecision.project_id == project_id,
            models.RecommendationDecision.action_fingerprint == fingerprint,
        )
    ).scalar_one_or_none()

    if existing is None:
        row = models.RecommendationDecision(
            project_id=project_id,
            action_fingerprint=fingerprint,
            action_label=safe_label,
            decision=normalized_decision,
            note=safe_note,
            decided_by=decided_by,
        )
        db.add(row)
    else:
        existing.decision = normalized_decision
        existing.note = safe_note
        if safe_label is not None:
            existing.action_label = safe_label
        existing.decided_by = decided_by
        row = existing

    db.flush()
    db.refresh(row)
    return serialize_decision(row)


def list_decisions(db: Session, *, project_id: int) -> list[dict]:
    stmt = (
        select(models.RecommendationDecision)
        .where(models.RecommendationDecision.project_id == project_id)
        .order_by(
            models.RecommendationDecision.created_at.asc(),
            models.RecommendationDecision.id.asc(),
        )
    )
    rows = db.execute(stmt).scalars().all()
    return [serialize_decision(row) for row in rows]


def dismissed_fingerprints(db: Session | None, project_id: int | None) -> set[str]:
    """Return the set of dismissed action fingerprints for a project.

    Defensive: returns an empty set when there is no db/project, so the helper
    can never break a live audit's Advisor view.
    """
    if db is None or project_id is None:
        return set()
    stmt = select(models.RecommendationDecision.action_fingerprint).where(
        models.RecommendationDecision.project_id == project_id,
        models.RecommendationDecision.decision == "dismissed",
    )
    return {row for row in db.execute(stmt).scalars().all()}
