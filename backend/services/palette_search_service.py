"""Bounded authorized search for the command palette (SIGV2-1020).

Two dynamic groups only: Projects and Reports. Static Pages, Settings and
Actions stay in the frontend and need no backend.

Rules of record (AC3):

- Normalization: leading/trailing whitespace stripped; matching and ranking
  compare on ``str.casefold()`` so Unicode (including Arabic) folds
  consistently. Interior whitespace is preserved (names may contain spaces).
- Minimum length: 1 character after stripping. A blank query returns empty
  groups, not an error.
- Maximum length: 200 characters after stripping. Longer input is rejected
  with 422 by the endpoint's ``max_length`` validation, before any query runs.
- Caps: ``per_group`` results per group (default 5, min 1, max 20); the global
  cap is ``per_group * 2`` because there are exactly two groups. Caps apply to
  matching rows, never to an arbitrary position in the table.
- Query shape: the whole table is considered. SQL prefilters
  ``lower(column) LIKE :pattern`` (pattern = casefolded query with ``%``,
  ``_`` and ``\\`` escaped, wrapped in ``%..%``), scoped by ``workspace_id``
  and the ``project_id`` subquery as before. A generous
  ``PALETTE_SEARCH_PREFILTER_LIMIT`` bound on the prefiltered set is a safety
  valve against pathological broad queries, not a functional limit. Python
  then applies ``str.casefold()`` matching for the final decision, the
  exact/prefix/substring ranking and the deterministic tie-break, which is
  Unicode-correct and engine-independent.
  Known edge: ``casefold()`` expansions (e.g. German sharp s -> ``ss``) can
  match in Python while the lowered-column prefilter does not recall the row;
  ordinary accented case variants (``CAFÉ`` vs ``Café``) work on both
  Postgres and SQLite because ``lower()`` folds ASCII and accented case on
  UTF-8 collations.
- Ranking: exact match on the normalized label, then prefix, then substring.
  Ties break on ``(label.casefold(), id asc)`` so identical queries always
  return identical ordering.
- Authorization is inside the query, not a post-filter (AC2): both groups are
  filtered by the caller's resolved current workspace, so a foreign or
  revoked object is indistinguishable from a genuine miss - same shape, same
  counts.
- Read-only (AC5): no ingestion, generation or mutation of any kind.

Matching fields:

- Projects: ``name`` and ``domain_url``. Inclusion rule: every status,
  including archived projects (the existing workspace project list returns
  them too); archived projects are flagged in the secondary text. There is no
  soft-delete, so "deleted" projects simply have no row.
- Reports: audits linked to a project of the current workspace, matching
  ``target_name``, ``target_url`` or ``url``. Audits with no project linkage
  are out of scope (the workspace access model cannot authorize them).
  Inclusion rule: archived reports (``report_archived_at`` set) are included
  and flagged; sanitized reports keep a valid destination and are included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

import models

PALETTE_SEARCH_MIN_QUERY_LENGTH = 1
PALETTE_SEARCH_MAX_QUERY_LENGTH = 200
PALETTE_SEARCH_DEFAULT_PER_GROUP = 5
PALETTE_SEARCH_MAX_PER_GROUP = 20
# Safety-valve bound on SQL-prefiltered rows per group before Python ranking.
# Every matching row is a candidate; this only guards pathological queries
# that match thousands of rows - not a functional limit on results.
PALETTE_SEARCH_PREFILTER_LIMIT = 1000


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so the query is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_pattern(value: str) -> str:
    """Casefolded substring pattern for ``lower(col) LIKE pattern``."""
    return f"%{_escape_like(value.casefold())}%"


def normalize_palette_query(raw: Any) -> str:
    """Strip outer whitespace; return the normalized query string."""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


@dataclass(frozen=True)
class PaletteSearchItem:
    type: str
    id: int
    label: str
    secondary: str
    destination: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "label": self.label,
            "secondary": self.secondary,
            "destination": self.destination,
        }


def _match_class(query_folded: str, candidates: Iterable[str | None]) -> int | None:
    """0 = exact, 1 = prefix, 2 = substring, None = no match.

    All comparisons are casefolded; every candidate field counts.
    """
    best: int | None = None
    for raw in candidates:
        if not raw:
            continue
        folded = raw.strip().casefold()
        if not folded:
            continue
        if folded == query_folded:
            return 0
        if folded.startswith(query_folded):
            best = min(best, 1) if best is not None else 1
        elif query_folded in folded:
            best = min(best, 2) if best is not None else 2
    return best


def _rank_key(match_class: int, label: str, row_id: int) -> tuple[int, str, int]:
    return (match_class, label.casefold(), row_id)


def search_projects(
    db: Session,
    *,
    workspace_id: int,
    query: str,
    per_group: int,
) -> list[PaletteSearchItem]:
    """Projects of the current workspace matching the normalized query.

    Authorization is inside the query (workspace_id filter) - a foreign
    project cannot appear even on exact match (AC2).
    """
    pattern = _contains_pattern(query)
    rows = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace_id)
        .filter(
            func.lower(models.Project.name).like(pattern, escape="\\")
            | func.lower(models.Project.domain_url).like(pattern, escape="\\")
        )
        .order_by(models.Project.name.asc(), models.Project.id.asc())
        .limit(PALETTE_SEARCH_PREFILTER_LIMIT)
        .all()
    )
    query_folded = query.casefold()
    ranked: list[tuple[tuple[int, str, int], PaletteSearchItem]] = []
    for project in rows:
        label = str(project.name or "").strip() or f"Project {project.id}"
        match_class = _match_class(query_folded, [project.name, project.domain_url])
        if match_class is None:
            continue
        secondary_parts = [str(project.domain_url).strip()] if project.domain_url else []
        if str(getattr(project.status, "value", project.status) or "") == "archived":
            secondary_parts.append("Archived")
        ranked.append(
            (
                _rank_key(match_class, label, int(project.id)),
                PaletteSearchItem(
                    type="project",
                    id=int(project.id),
                    label=label,
                    secondary=" · ".join(secondary_parts),
                    destination=f"/dashboard/projects/{int(project.id)}",
                ),
            )
        )
    ranked.sort(key=lambda pair: pair[0])
    return [item for _key, item in ranked[:per_group]]


def search_reports(
    db: Session,
    *,
    workspace_id: int,
    query: str,
    per_group: int,
) -> list[PaletteSearchItem]:
    """Audit reports linked to projects of the current workspace (AC2)."""
    project_ids = db.query(models.Project.id).filter(models.Project.workspace_id == workspace_id)
    pattern = _contains_pattern(query)
    rows = (
        db.query(models.Audit, models.Project.name)
        .join(models.Project, models.Audit.project_id == models.Project.id)
        .filter(models.Audit.project_id.in_(project_ids))
        .filter(
            func.lower(models.Audit.target_name).like(pattern, escape="\\")
            | func.lower(models.Audit.target_url).like(pattern, escape="\\")
            | func.lower(models.Audit.url).like(pattern, escape="\\")
        )
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .limit(PALETTE_SEARCH_PREFILTER_LIMIT)
        .all()
    )
    query_folded = query.casefold()
    ranked: list[tuple[tuple[int, str, int], PaletteSearchItem]] = []
    for audit, project_name in rows:
        label = (
            str(audit.target_name or "").strip()
            or str(audit.target_url or "").strip()
            or str(audit.url or "").strip()
            or f"Audit {audit.id}"
        )
        match_class = _match_class(query_folded, [audit.target_name, audit.target_url, audit.url])
        if match_class is None:
            continue
        created = getattr(audit, "created_at", None)
        secondary_parts = []
        if project_name:
            secondary_parts.append(str(project_name).strip())
        if created is not None:
            secondary_parts.append(created.date().isoformat())
        if getattr(audit, "report_archived_at", None) is not None:
            secondary_parts.append("Archived report")
        ranked.append(
            (
                _rank_key(match_class, label, int(audit.id)),
                PaletteSearchItem(
                    type="report",
                    id=int(audit.id),
                    label=label,
                    secondary=" · ".join(part for part in secondary_parts if part),
                    destination=f"/dashboard/audit/{int(audit.id)}",
                ),
            )
        )
    ranked.sort(key=lambda pair: pair[0])
    return [item for _key, item in ranked[:per_group]]


def run_palette_search(
    db: Session,
    *,
    workspace_id: int,
    raw_query: Any,
    per_group: int = PALETTE_SEARCH_DEFAULT_PER_GROUP,
) -> dict[str, Any]:
    query = normalize_palette_query(raw_query)
    per_group = max(1, min(int(per_group), PALETTE_SEARCH_MAX_PER_GROUP))
    if len(query) < PALETTE_SEARCH_MIN_QUERY_LENGTH:
        return {
            "query": query,
            "groups": {"projects": [], "reports": []},
        }
    return {
        "query": query,
        "groups": {
            "projects": [
                item.to_dict()
                for item in search_projects(
                    db, workspace_id=workspace_id, query=query, per_group=per_group
                )
            ],
            "reports": [
                item.to_dict()
                for item in search_reports(
                    db, workspace_id=workspace_id, query=query, per_group=per_group
                )
            ],
        },
    }
