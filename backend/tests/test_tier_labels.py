"""Tests for core.tier_labels canonical tier mapping."""

import pytest

import core.tier_labels as tier_labels
from core.tier_labels import (
    TIER_DISPLAY_LABELS,
    TIER_SHORT_LABELS,
    VALID_TIERS,
    normalize_tier,
    get_tier_display,
    get_tier_short,
)


class TestNormalizeTier:
    """normalize_tier() resolves aliases to canonical IDs."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("fast", "fast"),
            ("FAST", "fast"),
            ("standard", "fast"),
            ("Standard", "fast"),
            ("lite", "lite"),
            ("smart", "smart"),
            ("deep", "smart"),
            ("thorough", "smart"),
            ("deep_judgment", "deep_judgment"),
            ("DEEP_JUDGMENT", "deep_judgment"),
            ("high_confidence", "deep_judgment"),
            ("quick", "fast"),
            ("", "fast"),
            (None, "fast"),
            ("  ", "fast"),
            ("nonexistent", "fast"),
        ],
    )
    def test_aliases(self, raw, expected):
        assert normalize_tier(raw) == expected


class TestGetTierDisplay:
    """get_tier_display() returns full user-facing label."""

    def test_all_tiers_have_display_labels(self):
        for tier in VALID_TIERS:
            label = get_tier_display(tier)
            assert isinstance(label, str)
            assert len(label) > 0

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("fast", "Fast Audit"),
            ("smart", "Smart Audit"),
            ("deep_judgment", "Deep Analysis"),
            ("lite", "Quick Scan"),
            ("standard", "Fast Audit"),
            ("deep", "Smart Audit"),
            (None, "Fast Audit"),
        ],
    )
    def test_display_labels(self, raw, expected):
        assert get_tier_display(raw) == expected


class TestGetTierShort:
    """get_tier_short() returns short badge label."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("fast", "Fast"),
            ("smart", "Smart"),
            ("deep_judgment", "Deep"),
            ("lite", "Quick"),
        ],
    )
    def test_short_labels(self, raw, expected):
        assert get_tier_short(raw) == expected


class TestNoHardcodedRuntimeConstant:
    """This module states no duration, and must never state one again.

    SIGV2-1177. It held ``TIER_RUNTIME_ESTIMATES`` and
    ``get_tier_runtime_estimate`` through two generations of figures: first a
    set that traced to nothing measured, then the approved design's, which is a
    real source but still not a measurement. The duration now comes from
    ``services.tier_duration_stats_service``, derived from completed
    ``audit_jobs`` runs.

    These assertions are the guard rail: re-adding a constant here, under any
    name, fails the suite rather than quietly reintroducing an unsourced number
    into the label module every surface imports.
    """

    def test_the_runtime_constant_is_gone(self):
        assert not hasattr(tier_labels, "TIER_RUNTIME_ESTIMATES")
        assert not hasattr(tier_labels, "get_tier_runtime_estimate")

    def test_no_duration_shaped_value_is_exported(self):
        for name in dir(tier_labels):
            if name.startswith("_"):
                continue
            value = getattr(tier_labels, name)
            rendered = str(value)
            assert "min" not in rendered.lower() or not any(
                character.isdigit() for character in rendered
            ), f"core.tier_labels.{name} looks like a hardcoded duration: {rendered!r}"


class TestMappingCompleteness:
    """All canonical tier IDs are covered in every mapping."""

    def test_display_labels_cover_valid_tiers(self):
        for tier in VALID_TIERS:
            assert tier in TIER_DISPLAY_LABELS

    def test_short_labels_cover_valid_tiers(self):
        for tier in VALID_TIERS:
            assert tier in TIER_SHORT_LABELS
