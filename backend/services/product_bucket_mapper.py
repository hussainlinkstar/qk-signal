"""Qiko Signal product-bucket mapping (EPIC 11 / S11.3).

Maps the engine's intent-tagged audit signals onto the five **Qiko Signal product
buckets** (the user-facing "when does AI mention us?" breakdown):

    Brand → Category → Problem → Feature → Comparison   (canonical order)

This module is **pure and deterministic** (no DB / no network / no LLM), so the
mapping is unit-testable in isolation and the classification is reproducible.

Source signals (already produced by the audit pipeline and stored on ``Audit``):
  - ``intent``          ∈ {informational, transactional, navigational}
  - ``query_category``  ∈ {instructional, causal, commercial_pricing,
                            commercial_comparison, other}

Mapping rationale (v1 heuristic — see qiko_enablement/BUCKETS.md for definitions):
  - **Brand**      ← navigational intent (the user is searching the brand by name)
  - **Comparison** ← commercial_comparison query category ("X vs Y", alternatives)
  - **Feature**    ← commercial_pricing query category (commercial, offering-level,
                     non-comparison). NOTE: the engine has no dedicated "feature"
                     query category yet, so pricing/commercial is used as the v1
                     proxy; refine when a feature-intent signal is added.
  - **Problem**    ← instructional / causal query categories (how-to / why — the
                     user describes a need rather than naming a brand or category)
  - **Category**   ← everything else (general informational / unclassified)

The per-bucket *score* breakdown is a project-level aggregation across multiple
intent-tagged queries (one query usually maps to one bucket); ``aggregate_bucket_scores``
provides that reduction. Wiring it to a multi-query project summary is a follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class ProductBucket(str, Enum):
    BRAND = "brand"
    CATEGORY = "category"
    PROBLEM = "problem"
    FEATURE = "feature"
    COMPARISON = "comparison"


# Canonical, user-facing order (Brand → Category → Problem → Feature → Comparison).
BUCKET_ORDER: tuple[ProductBucket, ...] = (
    ProductBucket.BRAND,
    ProductBucket.CATEGORY,
    ProductBucket.PROBLEM,
    ProductBucket.FEATURE,
    ProductBucket.COMPARISON,
)

BUCKET_LABELS: dict[ProductBucket, str] = {
    ProductBucket.BRAND: "Brand",
    ProductBucket.CATEGORY: "Category",
    ProductBucket.PROBLEM: "Problem",
    ProductBucket.FEATURE: "Feature",
    ProductBucket.COMPARISON: "Comparison",
}


def bucket_for(intent: str | None, query_category: str | None) -> ProductBucket:
    """Classify a single audit's intent/query-category into one product bucket.

    Deterministic; unknown/empty values fall back to ``Category``.
    """
    normalized_intent = (intent or "").strip().lower()
    normalized_category = (query_category or "").strip().lower()

    if normalized_intent == "navigational":
        return ProductBucket.BRAND
    if normalized_category == "commercial_comparison":
        return ProductBucket.COMPARISON
    if normalized_category == "commercial_pricing":
        return ProductBucket.FEATURE
    if normalized_category in ("instructional", "causal"):
        return ProductBucket.PROBLEM

    return ProductBucket.CATEGORY


def aggregate_bucket_scores(
    items: Iterable[tuple[ProductBucket, float | None]],
) -> dict[ProductBucket, float | None]:
    """Reduce per-query ``(bucket, score)`` pairs into one score per bucket.

    Returns all five buckets in canonical order; a bucket with no scored data
    maps to ``None`` (caller decides how to present "no data" vs locked/zero).
    The score is the mean of the bucket's contributing scores, rounded to 1dp.
    """
    sums: dict[ProductBucket, float] = {bucket: 0.0 for bucket in BUCKET_ORDER}
    counts: dict[ProductBucket, int] = {bucket: 0 for bucket in BUCKET_ORDER}

    for bucket, score in items:
        if score is None:
            continue
        sums[bucket] += float(score)
        counts[bucket] += 1

    return {
        bucket: (round(sums[bucket] / counts[bucket], 1) if counts[bucket] else None)
        for bucket in BUCKET_ORDER
    }
