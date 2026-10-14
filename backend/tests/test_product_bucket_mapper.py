import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.product_bucket_mapper import (
    BUCKET_ORDER,
    ProductBucket,
    aggregate_bucket_scores,
    bucket_for,
)


def test_bucket_for_maps_each_intent_signal() -> None:
    # Brand ← navigational intent
    assert bucket_for("navigational", None) is ProductBucket.BRAND
    assert bucket_for("navigational", "other") is ProductBucket.BRAND
    # Comparison ← explicit comparison queries
    assert bucket_for("informational", "commercial_comparison") is ProductBucket.COMPARISON
    # Feature ← commercial pricing (v1 proxy)
    assert bucket_for("transactional", "commercial_pricing") is ProductBucket.FEATURE
    # Problem ← how-to / why
    assert bucket_for("informational", "instructional") is ProductBucket.PROBLEM
    assert bucket_for("informational", "causal") is ProductBucket.PROBLEM
    # Category ← general informational / unclassified fallback
    assert bucket_for("informational", "other") is ProductBucket.CATEGORY
    assert bucket_for(None, None) is ProductBucket.CATEGORY


def test_bucket_for_is_case_and_whitespace_insensitive() -> None:
    assert bucket_for("  Navigational ", None) is ProductBucket.BRAND
    assert bucket_for("informational", " Commercial_Comparison ") is ProductBucket.COMPARISON


def test_comparison_precedence_for_non_navigational() -> None:
    # A non-navigational comparison query is Comparison, not Category.
    assert bucket_for("transactional", "commercial_comparison") is ProductBucket.COMPARISON
    # Navigational always wins (brand search) even if category looks commercial.
    assert bucket_for("navigational", "commercial_comparison") is ProductBucket.BRAND


def test_aggregate_returns_all_five_buckets_in_order() -> None:
    result = aggregate_bucket_scores([])
    assert list(result.keys()) == list(BUCKET_ORDER)
    # No data → every bucket is None.
    assert all(value is None for value in result.values())


def test_aggregate_averages_per_bucket_and_skips_none() -> None:
    result = aggregate_bucket_scores(
        [
            (ProductBucket.BRAND, 80.0),
            (ProductBucket.BRAND, 90.0),
            (ProductBucket.CATEGORY, 50.0),
            (ProductBucket.PROBLEM, None),  # skipped
        ]
    )
    assert result[ProductBucket.BRAND] == 85.0
    assert result[ProductBucket.CATEGORY] == 50.0
    assert result[ProductBucket.PROBLEM] is None
    assert result[ProductBucket.FEATURE] is None
    assert result[ProductBucket.COMPARISON] is None
