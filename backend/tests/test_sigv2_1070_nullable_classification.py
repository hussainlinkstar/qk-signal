"""SIGV2-1070 — nullable recommendation classification fields.

category, estimated_effort and cross_score_leverage must stay absent when
nothing measured them, end to end: _to_canonical_suggestions ->
audit_result_adapter -> advisor_view -> advisor_service. expected_score_impact
already carries explicit nulls; these fields now follow the same pattern.

The ROI ranking still substitutes unrated effort with "medium" (dropping the
item would hide the recommendation), but discloses it per item via
``ranking_assumptions``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.models.audit import RecommendationItem
from app.services.advisor_view import _effort_label, attach_advisor_view
from app.services.suggestions.suggestion_engine import (
    _normalize_suggestion,
    generate_unified_suggestions,
)
from audit_runner import _to_canonical_suggestions
from services.advisor_service import build_advisor_plan
from services.reports.audit_result_adapter import _normalize_recommendation_item


class _NoEnrichmentClient:
    """generate_suggestion_detail that returns nothing classifiable."""

    async def generate_suggestion_detail(self, **kwargs):
        return {
            "short_title": kwargs["suggestion"],
            "comprehensive_action": kwargs["suggestion"],
        }


class _FullEnrichmentClient:
    async def generate_suggestion_detail(self, **kwargs):
        return {
            "short_title": "Fix schema",
            "comprehensive_action": "Add FAQPage schema to the pricing page",
            "category": "technical",
            "rationale": "Missing structured data.",
            "estimated_effort": "low",
            "owner": "engineering",
            "confidence": "high",
            "affected_scores": ["aeo", "geo"],
            "expected_score_impact": {"aeo": 15},
            "usage": {"total_tokens": 0},
        }


def _run(coro):
    return asyncio.run(coro)


def _canonical(client, suggestion):
    return _run(
        _to_canonical_suggestions(
            unified_suggestions=[suggestion],
            ai_client=client,
            provider="google",
            tier="standard",
            market="US",
            language="en",
        )
    )[0]


# ── Layer 1: _to_canonical_suggestions ───────────────────────────────────


def test_canonical_suggestions_absent_enrichment_stays_null() -> None:
    rows = _canonical(_NoEnrichmentClient(), {"action": "Improve crawlability", "effort": None})
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] is None
    assert row["estimated_effort"] is None
    assert row["cross_score_leverage"] == []
    # expected_score_impact already carried explicit nulls — unchanged.
    assert row["expected_score_impact"] == {
        "seo": None,
        "geo": None,
        "aeo": None,
        "overall": None,
    }


def test_canonical_suggestions_real_values_unchanged() -> None:
    rows = _canonical(_FullEnrichmentClient(), {"action": "whatever"})
    row = rows[0]
    assert row["category"] == "Technical"
    assert row["estimated_effort"] == "low"
    assert row["cross_score_leverage"] == ["aeo", "geo"]


def test_canonical_suggestions_invalid_enrichment_category_is_null_not_technical() -> None:
    class _WeirdCategory:
        async def generate_suggestion_detail(self, **kwargs):
            return {"short_title": "x", "category": "ux-polish"}

    rows = _canonical(_WeirdCategory(), {"action": "Improve crawlability"})
    # Unmapped non-empty categories are NOT silently bucketed as Technical;
    # they are also not in the approved vocabulary, so they stay null.
    assert rows[0]["category"] is None


# ── Layer 2: suggestion_engine ────────────────────────────────────────────


def test_suggestion_engine_absent_effort_stays_null() -> None:
    suggestion = _normalize_suggestion({"action": "Improve crawlability"})
    assert suggestion is not None
    assert suggestion["effort"] is None


def test_suggestion_engine_sort_is_deterministic_with_null_effort() -> None:
    module_outputs = {
        "analysis": {
            "suggestions": [
                {"action": "Low impact unrated", "impact": "low"},
                {"action": "High impact unrated", "impact": "high"},
                {"action": "Rated low effort", "impact": "medium", "effort": "low"},
            ]
        }
    }
    first = generate_unified_suggestions(module_outputs)
    second = generate_unified_suggestions(module_outputs)
    assert [s["action"] for s in first] == [s["action"] for s in second]
    assert len(first) == 3  # unrated items are not dropped from the ordering
    assert first[0]["action"] == "High impact unrated"


# ── Layer 3: audit_result_adapter ─────────────────────────────────────────


def test_adapter_item_absent_classification_stays_null() -> None:
    item = _normalize_recommendation_item(
        {"action": "Improve crawlability", "title": "Improve crawlability"},
        index=1,
    )
    assert item is not None
    assert item["category"] is None
    assert item["estimated_effort"] is None
    assert item["cross_score_leverage"] == []


def test_adapter_item_unmapped_category_not_keyword_guessed() -> None:
    # "FAQ schema" text previously triggered _guess_recommendation_dimensions
    # -> ["aeo", "geo"]; now empty leverage stays empty.
    item = _normalize_recommendation_item(
        {
            "action": "Add FAQ schema markup",
            "title": "Add FAQ schema markup",
            "category": "content",
        },
        index=1,
    )
    assert item["cross_score_leverage"] == []
    assert item["category"] == "content"


def test_adapter_item_real_values_unchanged() -> None:
    item = _normalize_recommendation_item(
        {
            "action": "Build citations",
            "category": "backlinks",
            "estimated_effort": "high",
            "cross_score_leverage": ["geo"],
        },
        index=1,
    )
    assert item["category"] == "authority"  # backlinks maps to the canonical vocabulary
    assert item["estimated_effort"] == "high"
    assert item["cross_score_leverage"] == ["geo"]


def test_canonical_contract_accepts_null_fields() -> None:
    item = _normalize_recommendation_item({"action": "Improve crawlability"}, index=1)
    validated = RecommendationItem.model_validate(item)
    assert validated.category is None
    assert validated.estimated_effort is None
    assert validated.cross_score_leverage == []


# ── Layer 4: advisor_view + advisor_service ──────────────────────────────


def test_effort_label_absent_is_none() -> None:
    assert _effort_label({"action": "x"}) is None
    assert _effort_label({"estimated_effort": "not-a-level"}) is None
    assert _effort_label({"estimated_effort": "high"}) == "high"


def _report(items):
    return {"recommendations": {"items": items}}


def test_advisor_plan_null_effort_discloses_ranking_assumption() -> None:
    report = attach_advisor_view(
        _report(
            [
                {
                    "action": "Unrated effort action",
                    "grounded_by_findings": ["seo.a"],
                    "expected_score_impact": {"seo": 12},
                },
                {
                    "action": "Rated effort action",
                    "estimated_effort": "high",
                    "grounded_by_findings": ["seo.b"],
                    "expected_score_impact": {"seo": 1},
                },
            ]
        )
    )
    actions = report["metadata"]["advisor"]["actions"]
    assert len(actions) == 2
    by_action = {a["action"]: a for a in actions}
    unrated = by_action["Unrated effort action"]
    rated = by_action["Rated effort action"]
    assert unrated["effort"] is None
    assert unrated["ranking_assumptions"] == {"effort": "medium"}
    assert rated["effort"] == "high"
    assert rated["ranking_assumptions"] == {}
    # Unrated still participates in the deterministic order, not dropped.
    assert {a["rank"] for a in actions} == {1, 2}


def test_build_advisor_plan_repeatable_order_with_null_effort() -> None:
    suggestions = [
        {
            "action": "B unrated",
            "grounded_by_findings": ["f2"],
        },
        {
            "action": "A unrated",
            "grounded_by_findings": ["f1"],
        },
        {
            "action": "C rated",
            "effort": "low",
            "impact": "high",
            "grounded_by_findings": ["f3"],
        },
    ]
    first = build_advisor_plan(suggestions, require_grounding=True)["actions"]
    second = build_advisor_plan(suggestions, require_grounding=True)["actions"]
    assert [a["action"] for a in first] == [a["action"] for a in second]
    # C (high impact / low effort) outranks unrated mediums; unrateds tie-break
    # deterministically on action text.
    assert first[0]["action"] == "C rated"


def test_nothing_refabricates_defaults() -> None:
    """End-to-end: raw suggestion with no classification keeps null fields
    through every layer; no Technical / medium / ["seo"] appears anywhere."""
    rows = _canonical(_NoEnrichmentClient(), {"action": "Improve crawlability", "effort": None})
    row = rows[0]
    item = _normalize_recommendation_item(row, index=1)
    assert item["category"] is None
    assert item["estimated_effort"] is None
    assert item["cross_score_leverage"] == []

    report = attach_advisor_view(
        _report(
            [
                {
                    **item,
                    "grounded_by_findings": ["seo.a"],
                }
            ]
        )
    )
    action = report["metadata"]["advisor"]["actions"][0]
    assert action["effort"] is None
    assert action["ranking_assumptions"] == {"effort": "medium"}


def test_unified_suggestions_effort_none_from_dict_entries() -> None:
    # audit_runner now emits "effort": None for unclassified entries; the
    # engine must preserve that instead of re-defaulting.
    suggestion = _normalize_suggestion({"action": "Do the thing", "effort": None})
    assert suggestion["effort"] is None
