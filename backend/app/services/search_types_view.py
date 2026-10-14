"""Deterministic per-search-type view derivation (response-time only).

The 5 customer-facing search types (Brand, Category, Problem, Feature, Comparison)
are an additive roll-up shown under the AIO drilldown. ``Comparison`` is the
premium (Specialist+) type. The aggregation logic lives in
:func:`services.query_taxonomy.aggregate_search_types`; this module only attaches
the resulting list at ``metadata.search_types``.

Like :mod:`app.services.aio_view`, this is a pure, additive augmentation: it never
persists, never mutates the canonical ``CanonicalAuditAnalysisContract``, performs
no I/O and makes no LLM call. It never raises on malformed reports, and the call
is idempotent.
"""

from __future__ import annotations

from typing import Optional

from services.query_taxonomy import aggregate_search_types


def attach_search_types(
    report: Optional[dict],
    measurements: Optional[dict] = None,
) -> Optional[dict]:
    """Attach the 5 canonical search-type entries at ``metadata.search_types``.

    Sources a per-type view via :func:`aggregate_search_types` (all five ids always
    present; ``comparison.premium`` is ``True``). ``measurements`` carries the
    measured per-canonical-type visibility and answer ratio the caller computed
    from this project's ``ProjectVisibilityQuery`` runs
    (:func:`services.project_visibility_service.compute_search_type_measurements`).
    A type with no measurement reports ``score: None``,
    ``answer_ratio: None`` and ``"source": "unmeasured"``; ``None`` (the default)
    makes all five unmeasured. There is no estimated fallback (SIGV2-1105).
    ``metadata`` is free-form, so adding the ``search_types`` key is non-breaking.
    Idempotent and never persisted.
    """
    if not isinstance(report, dict):
        return report

    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    metadata["search_types"] = aggregate_search_types(measurements=measurements)
    report["metadata"] = metadata
    return report
