"""Persisted advisor-chat history — Phase 8 follow-up (F3).

Stores and replays the audit-grounded Advisor chat transcript so follow-up
questions carry prior-turn context, WITHOUT weakening the closed-world /
grounding / abstention guarantees of ``advisor_chat_service``.

Security posture:

* History is scoped per (``audit_id``, ``user_id``) — a user can only ever read
  or extend their own conversation about an audit they own. The router enforces
  ownership + plan gating before any call here.
* Stored ``content`` is RAW-sanitized (control chars stripped, collapsed
  whitespace, length-capped) and persisted as plain text — never HTML-escaped,
  because React escapes at render. This keeps the model input clean and bounds
  storage without changing meaning.
* History is PRIOR-TURN CONTEXT ONLY: the caller passes it to
  ``advisor_chat_service.answer`` as a list of role-tagged turns, which the
  service replays as delimited *data* (never merged into the system prompt), so
  a historical user turn can never inject instructions.

Sync SQLAlchemy 2.0 style (``select`` + ``Session.execute``); never called from
the request path for anything but small, bounded reads/writes.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import models

# Roles we accept/persist. Anything else is coerced to "user" defensively.
_VALID_ROLES = {"user", "assistant"}

# Storage caps (defence-in-depth; the API layer also bounds request size).
_CONTENT_MAX_CHARS = 4000

# Default read window: chronological, capped so the prompt stays within budget.
_DEFAULT_LIMIT = 20

# Match C0/C1 control characters except tab/newline/carriage-return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _sanitize_content(value: Any, *, limit: int = _CONTENT_MAX_CHARS) -> str:
    """Strip control chars + collapse whitespace, then length-cap. RAW (no escape)."""
    text = _CONTROL_CHARS.sub("", str(value or ""))
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _normalize_role(role: Any) -> str:
    candidate = str(role or "").strip().lower()
    return candidate if candidate in _VALID_ROLES else "user"


def _to_dict(message: models.AdvisorChatMessage) -> dict[str, Any]:
    citations = message.citations if isinstance(message.citations, list) else []
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": [str(c) for c in citations],
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def list_messages(
    db: Session,
    audit_id: int,
    user_id: int | None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Return this (audit, user)'s persisted turns, oldest-first, capped at ``limit``.

    We fetch the most-recent ``limit`` rows (newest first) then reverse so the
    caller gets chronological order — this keeps the context window bounded to
    the latest turns while preserving order for the UI and the model.
    """
    capped = max(1, min(int(limit or _DEFAULT_LIMIT), 100))
    stmt = (
        select(models.AdvisorChatMessage)
        .where(
            models.AdvisorChatMessage.audit_id == audit_id,
            models.AdvisorChatMessage.user_id == user_id,
        )
        .order_by(models.AdvisorChatMessage.created_at.desc(), models.AdvisorChatMessage.id.desc())
        .limit(capped)
    )
    rows = list(db.execute(stmt).scalars().all())
    rows.reverse()
    return [_to_dict(row) for row in rows]


def append_message(
    db: Session,
    audit_id: int,
    user_id: int | None,
    role: str,
    content: str,
    citations: list[str] | None = None,
) -> models.AdvisorChatMessage | None:
    """Persist one turn for (audit, user). Returns the row, or ``None`` if empty.

    Empty content (after sanitizing) is not persisted so history never carries
    blank turns. Citations are stored only for assistant turns.
    """
    clean = _sanitize_content(content)
    if not clean:
        return None

    normalized_role = _normalize_role(role)
    stored_citations: list[str] | None = None
    if normalized_role == "assistant" and citations:
        stored_citations = [str(c).strip() for c in citations if str(c).strip()]

    message = models.AdvisorChatMessage(
        audit_id=audit_id,
        user_id=user_id,
        role=normalized_role,
        content=clean,
        citations=stored_citations,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
