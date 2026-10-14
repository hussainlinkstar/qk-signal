from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.query_taxonomy import (
    CANONICAL_SEARCH_TYPES,
    PREMIUM_SEARCH_TYPES,
    QUERY_CATEGORY_CAUSAL,
    QUERY_CATEGORY_COMMERCIAL_COMPARISON,
    QUERY_CATEGORY_COMMERCIAL_PRICING,
    QUERY_CATEGORY_INSTRUCTIONAL,
    QUERY_CATEGORY_OTHER,
    QUERY_TYPE_DECISION_MAKING,
    QUERY_TYPE_INFORMATIONAL,
    to_canonical,
)


def test_canonical_search_types_are_the_five_named_ids() -> None:
    assert CANONICAL_SEARCH_TYPES == ["brand", "category", "problem", "feature", "comparison"]


def test_only_comparison_is_premium() -> None:
    assert PREMIUM_SEARCH_TYPES == {"comparison"}
    assert "comparison" in PREMIUM_SEARCH_TYPES
    for non_premium in ("brand", "category", "problem", "feature"):
        assert non_premium not in PREMIUM_SEARCH_TYPES


def test_commercial_comparison_maps_to_comparison() -> None:
    assert (
        to_canonical(QUERY_TYPE_DECISION_MAKING, QUERY_CATEGORY_COMMERCIAL_COMPARISON)
        == "comparison"
    )


def test_commercial_pricing_maps_to_feature() -> None:
    assert to_canonical(QUERY_TYPE_DECISION_MAKING, QUERY_CATEGORY_COMMERCIAL_PRICING) == "feature"


def test_instructional_and_causal_map_to_problem() -> None:
    assert to_canonical(QUERY_TYPE_INFORMATIONAL, QUERY_CATEGORY_INSTRUCTIONAL) == "problem"
    assert to_canonical(QUERY_TYPE_INFORMATIONAL, QUERY_CATEGORY_CAUSAL) == "problem"


def test_decision_making_without_specific_category_maps_to_brand() -> None:
    assert to_canonical(QUERY_TYPE_DECISION_MAKING, QUERY_CATEGORY_OTHER) == "brand"


def test_informational_without_specific_category_maps_to_category() -> None:
    assert to_canonical(QUERY_TYPE_INFORMATIONAL, QUERY_CATEGORY_OTHER) == "category"


def test_category_aliases_are_normalized_before_mapping() -> None:
    # Raw alias values (not yet canonicalized) still resolve correctly.
    assert to_canonical("decision_making", "vs") == "comparison"
    assert to_canonical("informational", "how-to") == "problem"


def test_unknown_inputs_fall_back_to_category() -> None:
    assert to_canonical(None, None) == "category"
    assert to_canonical("garbage", "garbage") == "category"
    assert to_canonical("", "") == "category"


def test_to_canonical_always_returns_a_canonical_id() -> None:
    samples = [
        (QUERY_TYPE_INFORMATIONAL, QUERY_CATEGORY_INSTRUCTIONAL),
        (QUERY_TYPE_DECISION_MAKING, QUERY_CATEGORY_COMMERCIAL_COMPARISON),
        (None, None),
        ("garbage", "garbage"),
    ]
    for query_type, query_category in samples:
        assert to_canonical(query_type, query_category) in CANONICAL_SEARCH_TYPES
