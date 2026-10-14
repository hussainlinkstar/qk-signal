"""Positive identification of a project's own audits (SIGV2-1117).

A competitor benchmark is written with ``Audit.project_id`` set to the customer's
own project, so project history, trend, change and rank cannot be derived from
``project_id`` alone. The previous approach subtracted a list of competitor audit
ids collected from ``project_competitor_snapshots``. That fails in the dangerous
direction: an audit with no snapshot row (a ``lite-refresh`` benchmark never gets
one) or an audit whose snapshot was deleted together with its competitor passes
straight through and is read back as the project's own score.

This module provides the opposite shape. ``Audit.project_scope`` records on the
audit row whether it measures the project's own target, and every project-history
read requires that proof. A row that cannot be proven to belong to the project is
simply not counted as the project's.

SIGV2-1121: the scope is declared, never guessed. A write path states what it is
measuring through :func:`declare_audit_project_scope` (or by stamping
``AUDIT_PROJECT_SCOPE_COMPETITOR`` directly), and :func:`resolve_audit_project_scope`
returns ``None`` for an audit that neither declares a scope nor carries a legacy
competitor marker. ``None`` leaves the row unclassified, and an unclassified row
is excluded from the project's own scores rather than counted as the project's.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

import models
from models import AUDIT_PROJECT_SCOPE_COMPETITOR, AUDIT_PROJECT_SCOPE_OWN

__all__ = [
    "AUDIT_PROJECT_SCOPE_COMPETITOR",
    "AUDIT_PROJECT_SCOPE_OWN",
    "competitor_audit_clause",
    "declare_audit_project_scope",
    "is_own_project_audit",
    "is_reserved_internal_request_id",
    "own_project_audit_clause",
    "project_own_audits_clause",
    "resolve_audit_project_scope",
    "sanitize_client_request_id",
]

logger = logging.getLogger(__name__)

COMPETITOR_REQUEST_ID_PREFIXES = ("competitive-benchmark:", "lite-refresh:")
COMPETITOR_CATEGORY_MARKER = "competitor lite audit"

# SIGV2-1126: these prefixes are internal markers written by the competitor
# benchmark writers, and they are read back as a classification marker, as the
# worker's lite-job flag and as the cron sweeper's snapshot coordinates. A
# client-supplied correlation id must therefore never be allowed to carry one.
RESERVED_INTERNAL_REQUEST_ID_PREFIXES = COMPETITOR_REQUEST_ID_PREFIXES


def own_project_audit_clause() -> ColumnElement[bool]:
    """Require positive proof that an audit measures its project's own target."""
    return models.Audit.project_scope == AUDIT_PROJECT_SCOPE_OWN


def competitor_audit_clause() -> ColumnElement[bool]:
    """Require positive proof that an audit measures a competitor's target."""
    return models.Audit.project_scope == AUDIT_PROJECT_SCOPE_COMPETITOR


def project_own_audits_clause(project_id: int | ColumnElement) -> ColumnElement[bool]:
    """Match only the audits that a project owns."""
    return and_(models.Audit.project_id == project_id, own_project_audit_clause())


def is_own_project_audit(audit: models.Audit | None) -> bool:
    """In-Python counterpart of :func:`own_project_audit_clause`."""
    if audit is None:
        return False
    return str(getattr(audit, "project_scope", None) or "") == AUDIT_PROJECT_SCOPE_OWN


def _competitor_marker_scope(
    *,
    request_id: str | None = None,
    category: str | None = None,
    project_competitor_id: int | None = None,
    source_audit_id: int | None = None,
) -> str | None:
    """Detect a competitor benchmark from the markers its writers leave behind.

    These markers are what a job enqueued before ``project_scope`` existed still
    carries, so they must keep working across a deploy that drains Redis.
    """
    if project_competitor_id is not None and source_audit_id is not None:
        return AUDIT_PROJECT_SCOPE_COMPETITOR

    normalized_request_id = str(request_id or "").strip()
    if any(normalized_request_id.startswith(prefix) for prefix in COMPETITOR_REQUEST_ID_PREFIXES):
        return AUDIT_PROJECT_SCOPE_COMPETITOR

    if COMPETITOR_CATEGORY_MARKER in str(category or "").strip().lower():
        return AUDIT_PROJECT_SCOPE_COMPETITOR

    return None


def declare_audit_project_scope(*, category: str | None = None) -> str:
    """Declare the scope of an audit a write path is requesting for a project.

    Call this from every path that creates an audit against a project target.
    The caller holds the whole request, so it can state what it is measuring
    instead of leaving the classification to be inferred later from a partially
    populated row. ``POST /api/v1/audit`` and the external API let the caller ask
    for a competitor lite audit through ``category``, which the competitor lite
    entitlement gate authorizes, so the declaration honours that; anything else
    is the project's own target. An internal competitor writer stamps
    ``AUDIT_PROJECT_SCOPE_COMPETITOR`` directly instead of calling this.

    SIGV2-1126: the declaration deliberately does not look at ``request_id``.
    That value is a correlation id the client controls on every external write
    path (an ``X-Request-ID`` header, or the ``request_id`` body field of
    ``POST /api/v1/audit/jobs``), so deriving the classification from it let a
    caller choose how its own audit was classified by forging a
    ``lite-refresh:`` prefix. Classification now comes only from inputs the
    server has authorized.

    The returned value is never ``None``: a write path that calls this has said
    what it measures. A write path that calls nothing gets no classification at
    all, which is the point of SIGV2-1121.
    """
    return _competitor_marker_scope(category=category) or AUDIT_PROJECT_SCOPE_OWN


def is_reserved_internal_request_id(value: str | None) -> bool:
    """Report whether a request id impersonates an internal competitor marker."""
    normalized = str(value or "").strip()
    return any(normalized.startswith(prefix) for prefix in RESERVED_INTERNAL_REQUEST_ID_PREFIXES)


def sanitize_client_request_id(value: str | None, *, fallback: str) -> str:
    """Return a correlation id a client is allowed to have chosen.

    SIGV2-1126: a client-supplied request id is echoed into logs and stored on
    the job, which is harmless, but the competitor prefixes are also parsed as
    internal routing data. Anything carrying one is dropped in favour of the
    server's own id rather than refused, so a forged header cannot be used to
    probe which prefixes are reserved.
    """
    candidate = str(value or "").strip()
    if not candidate:
        return fallback
    if is_reserved_internal_request_id(candidate):
        logger.warning(
            "Discarding a client-supplied request id that impersonates an internal "
            "competitor marker; using the server-generated id instead."
        )
        return fallback
    return candidate


def resolve_audit_project_scope(
    *,
    request_id: str | None = None,
    category: str | None = None,
    project_competitor_id: int | None = None,
    source_audit_id: int | None = None,
    declared_scope: str | None = None,
) -> str | None:
    """Classify an audit about to be written, or refuse to classify it.

    ``declared_scope`` is authoritative: the enqueueing code knows exactly what
    it asked for and stamps it on the job. The marker checks only cover jobs
    enqueued before that field existed, which can still be sitting in Redis
    across a deploy.

    SIGV2-1121: an audit that is neither declared nor marked resolves to
    ``None``, not to the project's own scope. ``Audit.project_scope`` carries no
    server_default and no model default precisely so an unclassified row cannot
    pass as the project's own, and this function must not contradict that. Every
    project-history read requires ``project_scope == 'project'`` positively, so a
    ``None`` row is left out of the project's scores: it fails closed. Guessing
    ``project`` here, as this function used to, would reintroduce the SIGV2-1117
    defect for any future write path that forgets to declare, and it would do so
    silently, as a plausible wrong number on the history, trend, 30-day change,
    rank, digests and PDFs rather than as an error. A missing audit is visible
    and recoverable; a competitor's score shown as the customer's own is neither.
    Raising instead would be louder, but the worker reaches this code while
    running a paying customer's audit, so a legacy undeclared job would fail that
    audit outright. Fail closed, and log it.
    """
    normalized_declared = str(declared_scope or "").strip().lower()
    if normalized_declared in {AUDIT_PROJECT_SCOPE_OWN, AUDIT_PROJECT_SCOPE_COMPETITOR}:
        return normalized_declared

    marker_scope = _competitor_marker_scope(
        request_id=request_id,
        category=category,
        project_competitor_id=project_competitor_id,
        source_audit_id=source_audit_id,
    )
    if marker_scope is not None:
        return marker_scope

    logger.warning(
        "Audit project scope is undeclared and unmarked; leaving the audit "
        "unclassified so it is excluded from the project's own scores. "
        "Declare it with declare_audit_project_scope at the write path. "
        "request_id=%s category=%s",
        request_id,
        category,
    )
    return None
