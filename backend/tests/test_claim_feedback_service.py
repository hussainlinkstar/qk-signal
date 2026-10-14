"""Tests for the claim feedback service (AEX-26).

Covers build_claim_key, CRUD operations, summary aggregation,
re-audit helpers, and admin analytics — all with mocked DB sessions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the backend package root is importable and GCP bootstrap is disabled.
sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")
os.environ.setdefault("SSM_ENABLED", "false")

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models import ClaimFeedbackType
from services.claim_feedback_service import (
    _normalize_key_fragment,
    build_claim_key,
    delete_feedback,
    get_feedback_analytics,
    get_feedback_for_audit,
    get_feedback_summary_for_audit,
    get_previous_feedback_for_url,
    upsert_feedback,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_db() -> MagicMock:
    """Return a MagicMock that behaves like a SQLAlchemy Session."""
    db = MagicMock()
    # By default, query().filter_by().first() returns None (no existing row)
    db.query.return_value.filter_by.return_value.first.return_value = None
    return db


def _make_feedback(
    *,
    id: int = 1,
    audit_id: int = 100,
    user_id: int = 10,
    claim_key: str = "seo:missing-faq-schema:abc123def456",
    claim_text: str = "Missing FAQ schema on homepage",
    claim_category: str = "SEO",
    feedback_type: ClaimFeedbackType = ClaimFeedbackType.AGREE,
    feedback_text: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    """Build a mock ClaimFeedback row."""
    fb = MagicMock()
    fb.id = id
    fb.audit_id = audit_id
    fb.user_id = user_id
    fb.claim_key = claim_key
    fb.claim_text = claim_text
    fb.claim_category = claim_category
    fb.feedback_type = feedback_type
    fb.feedback_text = feedback_text
    fb.created_at = created_at or datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    fb.updated_at = updated_at or datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return fb


# ── 1. build_claim_key: determinism and format ──────────────────────


class TestBuildClaimKey:
    """Test suite for build_claim_key (pure logic, no mocks needed)."""

    def test_deterministic_output(self) -> None:
        """Same inputs always produce the same claim key."""
        key1 = build_claim_key(title="Missing FAQ schema", category="SEO")
        key2 = build_claim_key(title="Missing FAQ schema", category="SEO")
        assert key1 == key2

    def test_deterministic_with_description(self) -> None:
        key1 = build_claim_key(
            title="Missing FAQ schema",
            category="SEO",
            description="Homepage lacks FAQ structured data",
        )
        key2 = build_claim_key(
            title="Missing FAQ schema",
            category="SEO",
            description="Homepage lacks FAQ structured data",
        )
        assert key1 == key2

    def test_format_has_three_segments(self) -> None:
        """Key format: category:title:hash_digest."""
        key = build_claim_key(title="Add breadcrumbs", category="Technical SEO")
        parts = key.split(":")
        assert len(parts) == 3, f"Expected 3 colon-separated segments, got {parts}"

    def test_hash_portion_is_12_hex_chars(self) -> None:
        key = build_claim_key(title="Some Title", category="AEO")
        digest_part = key.split(":")[-1]
        assert len(digest_part) == 12
        assert all(c in "0123456789abcdef" for c in digest_part)

    def test_different_inputs_produce_different_keys(self) -> None:
        key_a = build_claim_key(title="Missing FAQ schema", category="SEO")
        key_b = build_claim_key(title="Missing breadcrumbs", category="SEO")
        assert key_a != key_b

    def test_different_categories_produce_different_keys(self) -> None:
        key_a = build_claim_key(title="Same Title", category="SEO")
        key_b = build_claim_key(title="Same Title", category="AEO")
        assert key_a != key_b

    def test_description_changes_key(self) -> None:
        key_a = build_claim_key(title="T", category="C", description="desc1")
        key_b = build_claim_key(title="T", category="C", description="desc2")
        assert key_a != key_b

    def test_none_description_same_as_omitted(self) -> None:
        key_a = build_claim_key(title="T", category="C", description=None)
        key_b = build_claim_key(title="T", category="C")
        assert key_a == key_b

    def test_normalizes_case_and_whitespace(self) -> None:
        key_a = build_claim_key(title="  Missing FAQ Schema  ", category="  SEO  ")
        key_b = build_claim_key(title="missing faq schema", category="seo")
        assert key_a == key_b

    def test_normalizes_special_characters(self) -> None:
        key_a = build_claim_key(title="FAQ (schema) — missing!", category="SEO & AEO")
        key_b = build_claim_key(title="FAQ  schema   missing", category="SEO   AEO")
        assert key_a == key_b

    def test_empty_title_uses_recommendation_fallback(self) -> None:
        key = build_claim_key(title="", category="SEO")
        parts = key.split(":")
        assert parts[1] == "recommendation"

    def test_empty_category_uses_general_fallback(self) -> None:
        key = build_claim_key(title="Some Title", category="")
        parts = key.split(":")
        assert parts[0] == "general"

    def test_sha256_digest_is_correct(self) -> None:
        """Verify the digest matches manual SHA-256 computation.

        Claim keys are hashed with SHA-256 (SHA-1 is forbidden per the
        security coding standards).
        """
        title_norm = _normalize_key_fragment("Missing FAQ schema")
        cat_norm = _normalize_key_fragment("SEO")
        desc_norm = _normalize_key_fragment("")
        expected_digest = hashlib.sha256(
            f"{cat_norm}|{title_norm}|{desc_norm}".encode("utf-8")
        ).hexdigest()[:12]
        key = build_claim_key(title="Missing FAQ schema", category="SEO")
        actual_digest = key.split(":")[-1]
        assert actual_digest == expected_digest

    def test_long_fragments_truncated_to_80_chars(self) -> None:
        long_title = "a" * 200
        key = build_claim_key(title=long_title, category="SEO")
        title_part = key.split(":")[1]
        assert len(title_part) <= 80


# ── 2. upsert_feedback: agree ──────────────────────────────────────


class TestUpsertFeedbackAgree:
    """Test case #1: submitting agree feedback → stored correctly."""

    def test_agree_feedback_creates_new_row(self) -> None:
        db = _mock_db()

        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="agree",
        )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.feedback_type == ClaimFeedbackType.AGREE
        assert added_obj.audit_id == 100
        assert added_obj.user_id == 10
        assert added_obj.claim_key == "seo:missing-faq:abc123"
        assert added_obj.claim_text == "Missing FAQ schema"
        assert added_obj.claim_category == "SEO"


# ── 3. upsert_feedback: disagree ───────────────────────────────────


class TestUpsertFeedbackDisagree:
    """Test case #2: submitting disagree feedback → stored correctly."""

    def test_disagree_feedback_creates_new_row(self) -> None:
        db = _mock_db()

        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="disagree",
            feedback_text="This finding is not applicable to our site",
        )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.feedback_type == ClaimFeedbackType.DISAGREE
        assert added_obj.feedback_text == "This finding is not applicable to our site"


# ── 4. upsert_feedback: feedback text is optional ───────────────────


class TestFeedbackTextOptional:
    """Test case #7: feedback_text is optional."""

    def test_feedback_text_none_by_default(self) -> None:
        db = _mock_db()

        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="agree",
        )

        added_obj = db.add.call_args[0][0]
        assert added_obj.feedback_text is None

    def test_feedback_text_can_be_provided(self) -> None:
        db = _mock_db()

        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="disagree",
            feedback_text="Already fixed this last week",
        )

        added_obj = db.add.call_args[0][0]
        assert added_obj.feedback_text == "Already fixed this last week"


# ── 5. upsert_feedback: update existing ────────────────────────────


class TestUpsertUpdatesExisting:
    """Test case #9: upsert updates existing instead of creating duplicate."""

    def test_existing_feedback_is_updated(self) -> None:
        db = _mock_db()
        existing_fb = _make_feedback(
            feedback_type=ClaimFeedbackType.AGREE,
            feedback_text=None,
        )
        db.query.return_value.filter_by.return_value.first.return_value = existing_fb

        result = upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq-schema:abc123def456",
            claim_text="Updated text",
            claim_category="SEO",
            feedback_type="disagree",
            feedback_text="Actually, I disagree now",
        )

        # Should NOT add a new row
        db.add.assert_not_called()
        db.flush.assert_called_once()

        # Should update existing row's fields
        assert existing_fb.feedback_type == ClaimFeedbackType.DISAGREE
        assert existing_fb.feedback_text == "Actually, I disagree now"
        assert existing_fb.claim_text == "Updated text"
        assert existing_fb.claim_category == "SEO"
        assert existing_fb.updated_at is not None

        # Return value is the existing row
        assert result is existing_fb

    def test_upsert_from_disagree_to_fixed(self) -> None:
        db = _mock_db()
        existing_fb = _make_feedback(feedback_type=ClaimFeedbackType.DISAGREE)
        db.query.return_value.filter_by.return_value.first.return_value = existing_fb

        result = upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq-schema:abc123def456",
            claim_text="Missing FAQ schema on homepage",
            claim_category="SEO",
            feedback_type="fixed",
        )

        assert existing_fb.feedback_type == ClaimFeedbackType.FIXED
        assert result is existing_fb
        db.add.assert_not_called()


# ── 6. Multiple users can provide feedback on same finding ──────────


class TestMultipleUsersOnSameFinding:
    """Test case #6: multiple users can provide feedback on the same finding."""

    def test_different_users_create_separate_rows(self) -> None:
        db = _mock_db()
        claim_key = "seo:missing-faq:abc123"

        # User 10 submits agree
        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key=claim_key,
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="agree",
        )

        # User 20 submits disagree — filter_by returns None (different user_id)
        upsert_feedback(
            db,
            audit_id=100,
            user_id=20,
            claim_key=claim_key,
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="disagree",
        )

        # Both should have called db.add (two new rows)
        assert db.add.call_count == 2
        assert db.flush.call_count == 2

        # Verify user IDs differ
        first_added = db.add.call_args_list[0][0][0]
        second_added = db.add.call_args_list[1][0][0]
        assert first_added.user_id == 10
        assert second_added.user_id == 20
        assert first_added.claim_key == second_added.claim_key


# ── 7. delete_feedback ──────────────────────────────────────────────


class TestDeleteFeedback:
    """Test case #10: delete_feedback only deletes own feedback."""

    def test_delete_own_feedback_returns_true(self) -> None:
        db = _mock_db()
        existing_fb = _make_feedback(id=42, user_id=10)
        db.query.return_value.filter_by.return_value.first.return_value = existing_fb

        result = delete_feedback(db, feedback_id=42, user_id=10)

        assert result is True
        db.delete.assert_called_once_with(existing_fb)
        db.flush.assert_called_once()

    def test_delete_other_users_feedback_returns_false(self) -> None:
        db = _mock_db()
        # filter_by(id=42, user_id=99) returns None because user 99 doesn't own it
        db.query.return_value.filter_by.return_value.first.return_value = None

        result = delete_feedback(db, feedback_id=42, user_id=99)

        assert result is False
        db.delete.assert_not_called()
        db.flush.assert_not_called()

    def test_delete_nonexistent_feedback_returns_false(self) -> None:
        db = _mock_db()
        db.query.return_value.filter_by.return_value.first.return_value = None

        result = delete_feedback(db, feedback_id=9999, user_id=10)

        assert result is False
        db.delete.assert_not_called()


# ── 8. get_feedback_for_audit ───────────────────────────────────────


class TestGetFeedbackForAudit:
    """Test case #11: get_feedback_for_audit with and without user_id filter."""

    def test_returns_all_feedback_for_audit(self) -> None:
        db = _mock_db()
        fb1 = _make_feedback(id=1, user_id=10, feedback_type=ClaimFeedbackType.AGREE)
        fb2 = _make_feedback(id=2, user_id=20, feedback_type=ClaimFeedbackType.DISAGREE)

        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_by_mock = MagicMock()
        query_mock.filter_by.return_value = filter_by_mock
        order_mock = MagicMock()
        filter_by_mock.order_by.return_value = order_mock
        order_mock.all.return_value = [fb1, fb2]

        result = get_feedback_for_audit(db, audit_id=100)

        assert len(result) == 2
        assert result[0] is fb1
        assert result[1] is fb2
        query_mock.filter_by.assert_called_once_with(audit_id=100)

    def test_returns_filtered_feedback_for_user(self) -> None:
        db = _mock_db()
        fb1 = _make_feedback(id=1, user_id=10, feedback_type=ClaimFeedbackType.AGREE)

        query_mock = MagicMock()
        db.query.return_value = query_mock
        # First filter_by (audit_id)
        first_filter = MagicMock()
        query_mock.filter_by.return_value = first_filter
        # Second filter_by (user_id)
        second_filter = MagicMock()
        first_filter.filter_by.return_value = second_filter
        order_mock = MagicMock()
        second_filter.order_by.return_value = order_mock
        order_mock.all.return_value = [fb1]

        result = get_feedback_for_audit(db, audit_id=100, user_id=10)

        assert len(result) == 1
        assert result[0] is fb1

    def test_returns_empty_list_when_no_feedback(self) -> None:
        db = _mock_db()

        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_by_mock = MagicMock()
        query_mock.filter_by.return_value = filter_by_mock
        order_mock = MagicMock()
        filter_by_mock.order_by.return_value = order_mock
        order_mock.all.return_value = []

        result = get_feedback_for_audit(db, audit_id=999)

        assert result == []


# ── 9. get_feedback_summary_for_audit ───────────────────────────────


class TestGetFeedbackSummaryForAudit:
    """Test case #12: get_feedback_summary_for_audit returns correct counts."""

    def test_summary_with_mixed_feedback_types(self) -> None:
        db = _mock_db()
        # Simulated DB rows: (claim_key, feedback_type, count)
        rows = [
            ("seo:missing-faq:abc123", ClaimFeedbackType.AGREE, 5),
            ("seo:missing-faq:abc123", ClaimFeedbackType.DISAGREE, 3),
            ("seo:missing-faq:abc123", ClaimFeedbackType.FIXED, 2),
            ("aeo:missing-schema:def456", ClaimFeedbackType.AGREE, 8),
            ("aeo:missing-schema:def456", ClaimFeedbackType.DISAGREE, 1),
        ]

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.filter_by.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.all.return_value = rows

        result = get_feedback_summary_for_audit(db, audit_id=100)

        assert result["seo:missing-faq:abc123"] == {"agree": 5, "disagree": 3, "fixed": 2}
        assert result["aeo:missing-schema:def456"] == {"agree": 8, "disagree": 1, "fixed": 0}

    def test_summary_empty_audit(self) -> None:
        db = _mock_db()

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.filter_by.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.all.return_value = []

        result = get_feedback_summary_for_audit(db, audit_id=999)

        assert result == {}

    def test_summary_single_claim_single_type(self) -> None:
        db = _mock_db()
        rows = [
            ("seo:test:hash12", ClaimFeedbackType.AGREE, 7),
        ]

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.filter_by.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.all.return_value = rows

        result = get_feedback_summary_for_audit(db, audit_id=100)

        assert result == {"seo:test:hash12": {"agree": 7, "disagree": 0, "fixed": 0}}


# ── 10. Feedback aggregation: 50% disagree rate ────────────────────


class TestFeedbackAggregationDisagreeRate:
    """Test case #3: 5 disagrees out of 10 → 50% disagree rate."""

    def test_fifty_percent_disagree_rate(self) -> None:
        db = _mock_db()
        claim_key = "seo:questionable-finding:abc123"
        rows = [
            (claim_key, ClaimFeedbackType.AGREE, 5),
            (claim_key, ClaimFeedbackType.DISAGREE, 5),
        ]

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.filter_by.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.all.return_value = rows

        summary = get_feedback_summary_for_audit(db, audit_id=100)

        total = (
            summary[claim_key]["agree"]
            + summary[claim_key]["disagree"]
            + summary[claim_key]["fixed"]
        )
        disagree_rate = summary[claim_key]["disagree"] / total * 100
        assert disagree_rate == 50.0
        assert total == 10


# ── 11. Re-audit: previous "fixed" feedback ────────────────────────


class TestGetPreviousFeedbackForUrl:
    """Test case #4: re-audit with previous 'fixed' feedback → marker shown."""

    def test_returns_fixed_feedback_from_prior_audits(self) -> None:
        db = _mock_db()

        fb_fixed = _make_feedback(
            id=1,
            audit_id=50,  # previous audit
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema on homepage",
            claim_category="SEO",
            feedback_type=ClaimFeedbackType.FIXED,
            feedback_text="We added FAQ schema",
            created_at=datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
        )

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = [fb_fixed]

        result = get_previous_feedback_for_url(
            db,
            url="https://example.com",
            current_audit_id=100,
        )

        assert len(result) == 1
        assert result[0]["claim_key"] == "seo:missing-faq:abc123"
        assert result[0]["feedback_type"] == "fixed"
        assert result[0]["feedback_text"] == "We added FAQ schema"
        assert result[0]["audit_id"] == 50

    def test_returns_disagree_feedback_from_prior_audits(self) -> None:
        db = _mock_db()

        fb_disagree = _make_feedback(
            id=2,
            audit_id=50,
            claim_key="aeo:wrong-claim:def456",
            feedback_type=ClaimFeedbackType.DISAGREE,
            feedback_text="This was never an issue",
            created_at=datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
        )

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = [fb_disagree]

        result = get_previous_feedback_for_url(
            db,
            url="https://example.com",
            current_audit_id=100,
        )

        assert len(result) == 1
        assert result[0]["feedback_type"] == "disagree"

    def test_deduplicates_by_claim_key_keeping_latest(self) -> None:
        db = _mock_db()

        # Two feedback rows for the same claim_key — query is ordered desc, so first wins
        fb_newer = _make_feedback(
            id=3,
            audit_id=75,
            claim_key="seo:dup-claim:hash12",
            feedback_type=ClaimFeedbackType.FIXED,
            feedback_text="Fixed in second audit",
            created_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        fb_older = _make_feedback(
            id=2,
            audit_id=50,
            claim_key="seo:dup-claim:hash12",
            feedback_type=ClaimFeedbackType.DISAGREE,
            feedback_text="Disagree in first audit",
            created_at=datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
        )

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = [fb_newer, fb_older]

        result = get_previous_feedback_for_url(
            db,
            url="https://example.com",
            current_audit_id=100,
        )

        # Only one entry per claim_key — the newer one (first in order)
        assert len(result) == 1
        assert result[0]["feedback_type"] == "fixed"
        assert result[0]["audit_id"] == 75

    def test_empty_when_no_prior_audits(self) -> None:
        db = _mock_db()

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = []

        result = get_previous_feedback_for_url(
            db,
            url="https://example.com",
            current_audit_id=100,
        )

        assert result == []

    def test_project_id_filter_applied(self) -> None:
        db = _mock_db()

        query_mock = MagicMock()
        db.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = []

        get_previous_feedback_for_url(
            db,
            url="https://example.com",
            current_audit_id=100,
            project_id=5,
        )

        # When project_id is given, an extra .filter() call is made
        assert query_mock.filter.call_count == 2


# ── 12. Admin analytics ────────────────────────────────────────────


class TestGetFeedbackAnalytics:
    """Test case #5: admin analytics endpoint → correct aggregation."""

    def _setup_analytics_db(
        self,
        *,
        type_counts: list[tuple],
        category_stats: list[tuple],
        flagged_claims: list[tuple],
        daily_volume: list[tuple],
    ) -> MagicMock:
        """Wire up a mock db for get_feedback_analytics.

        The function chains:
          db.query(ClaimFeedback).filter(...)  → base
          base.with_entities(...).group_by(...).all() → type_counts
          base.with_entities(...).group_by(...).all() → category_stats
          base.with_entities(...).filter(...).group_by(...).having(...).order_by(...).limit(...).all() → flagged_claims
          base.with_entities(...).group_by(...).order_by(...).all() → daily_volume
        """
        db = MagicMock()

        # The base query returned by db.query(ClaimFeedback).filter(...)
        base = MagicMock()
        db.query.return_value.filter.return_value = base

        # Each with_entities call produces a fresh chain.
        # We use side_effect to return different chains per call.
        type_chain = MagicMock()
        type_chain.group_by.return_value.all.return_value = type_counts

        cat_chain = MagicMock()
        cat_chain.group_by.return_value.all.return_value = category_stats

        flagged_chain = MagicMock()
        flagged_filter = MagicMock()
        flagged_chain.filter.return_value = flagged_filter
        flagged_filter.group_by.return_value.having.return_value.order_by.return_value.limit.return_value.all.return_value = flagged_claims

        daily_chain = MagicMock()
        daily_chain.group_by.return_value.order_by.return_value.all.return_value = daily_volume

        base.with_entities.side_effect = [type_chain, cat_chain, flagged_chain, daily_chain]

        return db

    def test_totals_and_disagree_rate(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[
                (ClaimFeedbackType.AGREE, 60),
                (ClaimFeedbackType.DISAGREE, 30),
                (ClaimFeedbackType.FIXED, 10),
            ],
            category_stats=[],
            flagged_claims=[],
            daily_volume=[],
        )

        result = get_feedback_analytics(db, days=30)

        assert result["totals"] == {"agree": 60, "disagree": 30, "fixed": 10}
        assert result["total_feedback"] == 100
        assert result["disagree_rate"] == 30.0

    def test_category_breakdown(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[
                (ClaimFeedbackType.AGREE, 10),
                (ClaimFeedbackType.DISAGREE, 5),
            ],
            category_stats=[
                ("SEO", ClaimFeedbackType.AGREE, 7),
                ("SEO", ClaimFeedbackType.DISAGREE, 3),
                ("AEO", ClaimFeedbackType.AGREE, 3),
                ("AEO", ClaimFeedbackType.DISAGREE, 2),
            ],
            flagged_claims=[],
            daily_volume=[],
        )

        result = get_feedback_analytics(db, days=30)

        categories = {c["category"]: c for c in result["categories"]}
        assert "SEO" in categories
        assert "AEO" in categories
        assert categories["SEO"]["agree"] == 7
        assert categories["SEO"]["disagree"] == 3
        assert categories["SEO"]["total"] == 10
        assert categories["SEO"]["disagree_rate"] == 30.0
        assert categories["AEO"]["disagree_rate"] == 40.0

    def test_flagged_claims_returned(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[
                (ClaimFeedbackType.DISAGREE, 10),
            ],
            category_stats=[],
            flagged_claims=[
                ("seo:bad-claim:hash12", "Bad claim text", "SEO", 5),
                ("aeo:another-bad:hash34", "Another bad claim", "AEO", 3),
            ],
            daily_volume=[],
        )

        result = get_feedback_analytics(db, days=30)

        assert len(result["flagged_claims"]) == 2
        assert result["flagged_claims"][0]["claim_key"] == "seo:bad-claim:hash12"
        assert result["flagged_claims"][0]["disagree_count"] == 5
        assert result["flagged_claims"][1]["claim_key"] == "aeo:another-bad:hash34"

    def test_daily_volume_formatted(self) -> None:
        day1 = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2025, 1, 16, 0, 0, 0, tzinfo=timezone.utc)

        db = self._setup_analytics_db(
            type_counts=[
                (ClaimFeedbackType.AGREE, 5),
                (ClaimFeedbackType.DISAGREE, 3),
            ],
            category_stats=[],
            flagged_claims=[],
            daily_volume=[
                (day1, ClaimFeedbackType.AGREE, 3),
                (day1, ClaimFeedbackType.DISAGREE, 1),
                (day2, ClaimFeedbackType.AGREE, 2),
                (day2, ClaimFeedbackType.DISAGREE, 2),
            ],
        )

        result = get_feedback_analytics(db, days=30)

        daily = result["daily_volume"]
        assert len(daily) == 2
        day_map = {d["date"]: d for d in daily}
        assert day_map["2025-01-15"]["agree"] == 3
        assert day_map["2025-01-15"]["disagree"] == 1
        assert day_map["2025-01-16"]["agree"] == 2
        assert day_map["2025-01-16"]["disagree"] == 2

    def test_zero_feedback_returns_zero_disagree_rate(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[],
            category_stats=[],
            flagged_claims=[],
            daily_volume=[],
        )

        result = get_feedback_analytics(db, days=30)

        assert result["total_feedback"] == 0
        assert result["disagree_rate"] == 0
        assert result["totals"] == {"agree": 0, "disagree": 0, "fixed": 0}
        assert result["categories"] == []
        assert result["flagged_claims"] == []
        assert result["daily_volume"] == []

    def test_uncategorized_feedback(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[
                (ClaimFeedbackType.AGREE, 4),
            ],
            category_stats=[
                (None, ClaimFeedbackType.AGREE, 4),
            ],
            flagged_claims=[],
            daily_volume=[],
        )

        result = get_feedback_analytics(db, days=30)

        categories = {c["category"]: c for c in result["categories"]}
        assert "Uncategorized" in categories
        assert categories["Uncategorized"]["agree"] == 4

    def test_custom_days_parameter(self) -> None:
        db = self._setup_analytics_db(
            type_counts=[],
            category_stats=[],
            flagged_claims=[],
            daily_volume=[],
        )

        # Should not raise; the days parameter affects the cutoff filter
        result = get_feedback_analytics(db, days=7)

        assert result["total_feedback"] == 0


# ── 13. upsert_feedback: invalid feedback_type raises ValueError ───


class TestUpsertFeedbackValidation:
    """Edge case: invalid feedback_type string raises ValueError."""

    def test_invalid_feedback_type_raises(self) -> None:
        db = _mock_db()

        with pytest.raises(ValueError):
            upsert_feedback(
                db,
                audit_id=100,
                user_id=10,
                claim_key="seo:test:hash12",
                claim_text="Test claim",
                claim_category="SEO",
                feedback_type="invalid_type",
            )

        db.add.assert_not_called()
        db.flush.assert_not_called()


# ── 14. upsert_feedback: fixed type ────────────────────────────────


class TestUpsertFeedbackFixed:
    """Test submitting fixed feedback → stored correctly."""

    def test_fixed_feedback_creates_new_row(self) -> None:
        db = _mock_db()

        upsert_feedback(
            db,
            audit_id=100,
            user_id=10,
            claim_key="seo:missing-faq:abc123",
            claim_text="Missing FAQ schema",
            claim_category="SEO",
            feedback_type="fixed",
            feedback_text="Deployed the fix yesterday",
        )

        db.add.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.feedback_type == ClaimFeedbackType.FIXED
        assert added_obj.feedback_text == "Deployed the fix yesterday"


# ── 15. _normalize_key_fragment edge cases ──────────────────────────


class TestNormalizeKeyFragment:
    """Unit tests for the internal normalization helper."""

    def test_lowercases(self) -> None:
        assert _normalize_key_fragment("HELLO") == "hello"

    def test_strips_whitespace(self) -> None:
        assert _normalize_key_fragment("  hello  ") == "hello"

    def test_replaces_special_chars_with_hyphens(self) -> None:
        result = _normalize_key_fragment("hello, world! (test)")
        assert result == "hello-world-test"

    def test_collapses_consecutive_hyphens(self) -> None:
        result = _normalize_key_fragment("a --- b")
        assert result == "a-b"

    def test_none_returns_empty_string(self) -> None:
        assert _normalize_key_fragment(None) == ""

    def test_empty_string(self) -> None:
        assert _normalize_key_fragment("") == ""

    def test_truncates_at_80_chars(self) -> None:
        result = _normalize_key_fragment("a" * 200)
        assert len(result) <= 80
