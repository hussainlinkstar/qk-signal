"""CRUD service for per-project brand facts (guardrails input).

Task 6.2 of the Qiko Signal Guardrails phase. Brand facts are structured
statements (facts / claims, optionally flagged as forbidden) that feed the
audit's evidence/grounding context so the engine respects brand truth.

The wider backend uses a synchronous SQLAlchemy ``Session`` (there is no async
engine configured; ``database.get_db`` yields a sync ``Session``). To stay
consistent with the surrounding routers/services while honouring the
"SQLAlchemy 2.0 style" rule, this service uses the 2.0 ``select()`` /
``session.execute()`` API rather than the legacy ``Query`` API.
"""

from __future__ import annotations

import re

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import models

ALLOWED_BRAND_FACT_KINDS: frozenset[str] = frozenset({"fact", "claim"})
MAX_BRAND_FACT_STATEMENT_CHARS = 2000
MAX_BRAND_FACTS_PER_PROJECT = 100

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_brand_fact_kind(raw_kind: str | None) -> str:
    kind = str(raw_kind or "").strip().lower()
    if kind not in ALLOWED_BRAND_FACT_KINDS:
        raise ValueError(
            f"Brand fact kind must be one of: {', '.join(sorted(ALLOWED_BRAND_FACT_KINDS))}."
        )
    return kind


def sanitize_brand_fact_statement(raw_statement: str | None) -> str:
    """Sanitize a brand-fact statement for storage WITHOUT HTML-escaping.

    Strips control characters, collapses runs of whitespace, trims, rejects
    blank input and enforces the max length. The statement is stored RAW (the
    real text) — HTML/markup is neutralised at each output boundary instead:
    React escapes UI text nodes automatically and the audit evidence anchor
    needs the genuine text, not an HTML-escaped copy. Escaping at the storage
    layer was the wrong layer (it double-escaped in the UI and corrupted the
    evidence anchor fed to the LLM).
    """
    text = _CONTROL_CHARS_RE.sub(" ", str(raw_statement or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        raise ValueError("Brand fact statement must not be empty.")
    if len(text) > MAX_BRAND_FACT_STATEMENT_CHARS:
        raise ValueError(
            f"Brand fact statement must be at most {MAX_BRAND_FACT_STATEMENT_CHARS} characters."
        )
    return text


def serialize_brand_fact(fact: models.ProjectBrandFact) -> dict:
    return {
        "id": int(fact.id),
        "project_id": int(fact.project_id),
        "kind": fact.kind,
        "statement": fact.statement,
        "is_forbidden": bool(fact.is_forbidden),
        "created_at": fact.created_at.isoformat() if fact.created_at else None,
    }


def get_brand_facts_evidence(db: Session | None, project_id: int | None) -> list[dict]:
    """Return per-project brand facts as structured evidence for the audit.

    Task 6.3. These items are ADDITIVE, closed-world evidence consumed by the
    audit's evidence-anchor builder (``UnifiedTruthContextService.build_context``)
    — NOT free text injected into expert prompts. Forbidden facts are flagged via
    ``is_forbidden`` so the grounding context can respect brand truth.

    Returns ``[]`` when there is no db/project or no facts (never raises for the
    caller path; the helper is defensive so it can never break a live audit).
    """
    if db is None or project_id is None:
        return []
    stmt = (
        select(models.ProjectBrandFact)
        .where(models.ProjectBrandFact.project_id == project_id)
        .order_by(
            models.ProjectBrandFact.created_at.asc(),
            models.ProjectBrandFact.id.asc(),
        )
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "kind": row.kind,
            "statement": row.statement,
            "is_forbidden": bool(row.is_forbidden),
            "source": "brand_fact",
        }
        for row in rows
    ]


def list_brand_facts(db: Session, *, project_id: int) -> list[dict]:
    stmt = (
        select(models.ProjectBrandFact)
        .where(models.ProjectBrandFact.project_id == project_id)
        .order_by(
            models.ProjectBrandFact.created_at.asc(),
            models.ProjectBrandFact.id.asc(),
        )
    )
    rows = db.execute(stmt).scalars().all()
    return [serialize_brand_fact(row) for row in rows]


def create_brand_fact(
    db: Session,
    *,
    project_id: int,
    kind: str,
    statement: str,
    is_forbidden: bool = False,
) -> dict:
    normalized_kind = normalize_brand_fact_kind(kind)
    safe_statement = sanitize_brand_fact_statement(statement)

    existing_count = (
        db.execute(
            select(models.ProjectBrandFact.id).where(
                models.ProjectBrandFact.project_id == project_id
            )
        )
        .scalars()
        .all()
    )
    if len(existing_count) >= MAX_BRAND_FACTS_PER_PROJECT:
        raise ValueError(f"A project supports up to {MAX_BRAND_FACTS_PER_PROJECT} brand facts.")

    fact = models.ProjectBrandFact(
        project_id=project_id,
        kind=normalized_kind,
        statement=safe_statement,
        is_forbidden=bool(is_forbidden),
    )
    db.add(fact)
    db.flush()
    db.refresh(fact)
    return serialize_brand_fact(fact)


def delete_brand_fact(db: Session, *, project_id: int, fact_id: int) -> None:
    fact = db.execute(
        select(models.ProjectBrandFact).where(
            models.ProjectBrandFact.project_id == project_id,
            models.ProjectBrandFact.id == fact_id,
        )
    ).scalar_one_or_none()
    if fact is None:
        raise ValueError("Brand fact not found for this project.")
    db.execute(
        sql_delete(models.ProjectBrandFact).where(
            models.ProjectBrandFact.project_id == project_id,
            models.ProjectBrandFact.id == fact_id,
        )
    )
    db.flush()
