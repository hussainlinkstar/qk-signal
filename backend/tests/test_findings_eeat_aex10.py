# pyre-unsafe
"""Tests for AEX-10: Recalibrated findings penalty and E-E-A-T scoring."""

import pytest
from score_utils import DeterministicScoringEngine as DSE


def _make_findings(critical: int = 0, warning: int = 0) -> list:
    findings = []
    for _ in range(critical):
        findings.append({"severity": "critical", "description": "Test critical finding"})
    for _ in range(warning):
        findings.append({"severity": "warning", "description": "Test warning finding"})
    return findings


class TestFindingsPenaltyTiered:
    """Tests for the tiered diminishing-returns findings penalty."""

    def test_one_critical(self):
        """1 critical → ~7.5 penalty."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=1))
        assert penalty == pytest.approx(7.5, abs=0.1)

    def test_three_critical(self):
        """3 critical → 3 * 7.5 = 22.5."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=3))
        assert penalty == pytest.approx(22.5, abs=0.1)

    def test_five_critical(self):
        """5 critical → 3*7.5 + 2*5.0 = 22.5 + ~10 = ~32.5."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=5))
        assert 30 < penalty < 35, f"Expected ~32.5, got {penalty}"

    def test_ten_critical_diminishing(self):
        """10 critical → 22.5 + 15.0 + ~8.0 = ~45.5 → capped at 45."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=10))
        assert 38 < penalty <= 45, f"Expected 40-45 range, got {penalty}"

    def test_one_warning(self):
        """1 warning → 2.5 penalty."""
        penalty = DSE._calculate_findings_penalty(_make_findings(warning=1))
        assert penalty == pytest.approx(2.5, abs=0.1)

    def test_mixed_findings(self):
        """2 critical + 3 warnings → 2*7.5 + 3*2.5 = 15 + 7.5 = 22.5."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=2, warning=3))
        assert penalty == pytest.approx(22.5, abs=0.1)

    def test_no_findings(self):
        """No findings → 0 penalty."""
        penalty = DSE._calculate_findings_penalty([])
        assert penalty == 0.0

    def test_diminishing_returns_above_three(self):
        """Findings 4-6 add less per finding than 1-3."""
        penalty_3 = DSE._calculate_findings_penalty(_make_findings(critical=3))
        penalty_4 = DSE._calculate_findings_penalty(_make_findings(critical=4))
        increment_4th = penalty_4 - penalty_3
        # 4th finding should add ~5.0 (15*0.333), less than 7.5
        assert (
            increment_4th < 7.5
        ), f"4th finding added {increment_4th}, should be < 7.5 (diminishing)"
        assert increment_4th > 3.0, f"4th finding added {increment_4th}, should be ~5.0"

    def test_cap_is_45(self):
        """Cap should be 45, not the old 10."""
        assert DSE.FINDINGS_PENALTY_CAP == 45.0

    def test_five_critical_penalty_exceeds_old_cap(self):
        """5 critical findings should deduct more than the old 10-point cap."""
        penalty = DSE._calculate_findings_penalty(_make_findings(critical=5))
        assert penalty > 10.0, "5 critical findings should exceed old 10-point cap"


class TestEEATStructuredChecks:
    """Tests for the improved E-E-A-T author detection."""

    def test_unauthorized_no_author_credit(self):
        """'unauthorized access' should NOT trigger author detection."""
        content = "This page had unauthorized access attempts. Please secure your account."
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "author" in b.get("reason", "").lower()]
        assert len(author_bonuses) == 0, f"'unauthorized' matched author: {author_bonuses}"

    def test_meta_author_tag_detects(self):
        """<meta name='author' content='John Doe'> DOES trigger author detection."""
        content = '<html><head><meta name="author" content="John Doe"></head><body>Content here</body></html>'
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [
            b
            for b in bonuses
            if "author" in b.get("reason", "").lower()
            and "attribution" in b.get("reason", "").lower()
        ]
        assert len(author_bonuses) == 1

    def test_jsonld_person_detects(self):
        """JSON-LD Person author DOES trigger author detection."""
        content = '{"@type": "Person", "name": "Jane Smith"} Some content about the topic.'
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 1

    def test_rel_author_link_detects(self):
        """rel='author' link DOES trigger author detection."""
        content = '<a href="/team/john" rel="author">John Doe</a> wrote this article.'
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 1

    def test_visible_byline_detects(self):
        """'Written by John Doe' in content body DOES trigger author detection."""
        content = "This article was written by John Doe in 2024. It covers important topics."
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 1

    def test_author_bio_class_detects(self):
        """<div class='author-bio'> DOES trigger author detection."""
        content = '<div class="author-bio"><p>John Doe is a senior engineer.</p></div>'
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 1

    def test_author_in_css_class_no_credit(self):
        """CSS class 'author-list' without structured pattern should NOT trigger."""
        content = '<ul class="author-list"><li>Item 1</li><li>Item 2</li></ul>'
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        # author-list is not in the allowed patterns (author-bio, author-info, byline)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 0

    def test_author_word_in_body_text_no_credit(self):
        """The word 'author' appearing in body text should NOT trigger."""
        content = "The author of this book is unknown. We contacted the author for comment."
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 0

    def test_no_trust_signals_low_score(self):
        """Content with no genuine trust signals should score low."""
        content = "This is a simple page with no links, no dates, no structured data at all."
        penalties, bonuses = [], []
        score = DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        assert score < 15, f"Score {score} should be < 15 with no trust signals"

    def test_all_trust_signals_high_score(self):
        """Content with all trust signals should score high."""
        content = (
            '<html><head><meta name="author" content="John Doe"></head>'
            "<body>"
            '<a href="/about">About Us</a> <a href="/contact">Contact</a> '
            "Privacy policy is available. "
            '<a href="https://wikipedia.org/wiki/Topic">Source 1</a> '
            '<a href="https://bbc.com/article">Source 2</a> '
            '<a href="https://reuters.com/article">Source 3</a> '
            "[1] citation marker "
            "Published: 2024 "
            '{"@type": "Person", "name": "John Doe"}'
            "</body></html>"
        )
        penalties, bonuses = [], []
        score = DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        assert score >= 80, f"Score {score} should be >= 80 with all trust signals"

    def test_posted_by_name_detects(self):
        """'Posted by Jane Smith' should trigger author detection."""
        content = "This article was posted by Jane Smith on our corporate blog."
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        author_bonuses = [b for b in bonuses if "Author attribution" in b.get("reason", "")]
        assert len(author_bonuses) == 1

    def test_schema_org_person_url_detects(self):
        """schema.org/Person in content should give +5 structured bonus."""
        content = (
            '<script type="application/ld+json">{"@context": "http://schema.org/Person"}</script>'
        )
        penalties, bonuses = [], []
        DSE._calculate_eeat_trust_score(content, {}, penalties, bonuses)
        schema_bonuses = [b for b in bonuses if "Structured author" in b.get("reason", "")]
        assert len(schema_bonuses) == 1
