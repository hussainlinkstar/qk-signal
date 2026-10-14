"""Tests for audit_feature_gating_service — score recalculation on E-E-A-T lock."""

from services.audit_feature_gating_service import (
    _lock_eeat_trust,
    _lock_entities,
    sanitize_audit_payload_for_plan,
)


def _make_scores_payload(
    *,
    core_web_vitals: float = 80.0,
    technical_seo: float = 70.0,
    onpage_content: float = 60.0,
    eeat_trust: float = 90.0,
    security_accessibility: float = 50.0,
    geo_score: float = 65.0,
    aeo_score: float = 72.0,
) -> dict:
    """Build a minimal payload dict with scores matching production shape."""
    # Original weighted SEO: 0.25*80 + 0.20*70 + 0.20*60 + 0.20*90 + 0.15*50
    # = 20 + 14 + 12 + 18 + 7.5 = 71.5
    seo_score = round(
        core_web_vitals * 0.25
        + technical_seo * 0.20
        + onpage_content * 0.20
        + eeat_trust * 0.20
        + security_accessibility * 0.15,
        1,
    )
    overall = round(seo_score * 0.4 + aeo_score * 0.3 + geo_score * 0.3, 1)
    return {
        "seo": {"eeat_trust": {"score": eeat_trust, "checks": []}},
        "scores": {
            "seo_score": seo_score,
            "geo_score": geo_score,
            "aeo_score": aeo_score,
            "overall_score": overall,
            "seo_breakdown": {
                "score": seo_score,
                "components": {
                    "core_web_vitals": core_web_vitals,
                    "technical_seo": technical_seo,
                    "onpage_content": onpage_content,
                    "eeat_trust": eeat_trust,
                    "security_accessibility": security_accessibility,
                },
                "penalties": [],
                "bonuses": [],
            },
            "geo_breakdown": {"score": geo_score, "components": {}, "penalties": [], "bonuses": []},
            "aeo_breakdown": {"score": aeo_score, "components": {}, "penalties": [], "bonuses": []},
        },
        "metadata": {},
    }


class TestLockEeatTrust:
    """Unit tests for _lock_eeat_trust score recalculation."""

    def test_eeat_component_removed(self):
        payload = _make_scores_payload()
        _lock_eeat_trust(payload)
        components = payload["scores"]["seo_breakdown"]["components"]
        assert "eeat_trust" not in components

    def test_seo_data_nulled(self):
        payload = _make_scores_payload()
        _lock_eeat_trust(payload)
        assert payload["seo"]["eeat_trust"] is None

    def test_seo_score_recalculated_without_eeat(self):
        payload = _make_scores_payload()
        original_seo = payload["scores"]["seo_score"]

        _lock_eeat_trust(payload)

        # Expected: normalise remaining 4 weights (sum=0.80) to 1.0
        # 0.25/0.80*80 + 0.20/0.80*70 + 0.20/0.80*60 + 0.15/0.80*50
        # = 0.3125*80 + 0.25*70 + 0.25*60 + 0.1875*50
        # = 25 + 17.5 + 15 + 9.375 = 66.875 → 66.9
        expected_seo = 66.9
        assert payload["scores"]["seo_score"] == expected_seo
        assert payload["scores"]["seo_breakdown"]["score"] == expected_seo
        assert payload["scores"]["seo_score"] != original_seo

    def test_overall_score_recalculated(self):
        payload = _make_scores_payload()
        original_overall = payload["scores"]["overall_score"]

        _lock_eeat_trust(payload)

        recalculated_seo = payload["scores"]["seo_score"]
        geo = payload["scores"]["geo_score"]
        aeo = payload["scores"]["aeo_score"]
        expected_overall = round(recalculated_seo * 0.4 + aeo * 0.3 + geo * 0.3, 1)
        assert payload["scores"]["overall_score"] == expected_overall
        assert payload["scores"]["overall_score"] != original_overall

    def test_no_scores_key_is_safe(self):
        payload = {"seo": {"eeat_trust": {"score": 80}}}
        _lock_eeat_trust(payload)
        assert payload["seo"]["eeat_trust"] is None

    def test_no_components_key_is_safe(self):
        payload = {"scores": {"seo_breakdown": {}}}
        _lock_eeat_trust(payload)
        # Should not raise

    def test_uniform_scores_produce_same_total(self):
        """When all 5 categories equal, removing eeat should not change SEO score."""
        payload = _make_scores_payload(
            core_web_vitals=75.0,
            technical_seo=75.0,
            onpage_content=75.0,
            eeat_trust=75.0,
            security_accessibility=75.0,
        )
        _lock_eeat_trust(payload)
        assert payload["scores"]["seo_score"] == 75.0


class TestLockEntities:
    """The 'entities' section must be lockable the same way 'competitors' is,
    otherwise a starter-plan audit with entity_enhancement disabled shows
    'No entities detected' (implying the AI looked and found none) instead of
    an upgrade prompt (the AI never ran entity analysis at all)."""

    def test_entities_cleared(self):
        payload = {"entities": [{"name": "Acme Corp", "type": "Organization"}]}
        _lock_entities(payload)
        assert payload["entities"] == []

    def test_no_entities_key_is_safe(self):
        payload = {}
        _lock_entities(payload)
        assert payload["entities"] == []


class TestSanitizePayloadEntitiesIntegration:
    def test_plan_starter_locks_entities_with_upgrade_metadata(self):
        payload = {"entities": [{"name": "Acme Corp", "type": "Organization"}], "metadata": {}}

        result = sanitize_audit_payload_for_plan(payload, "plan_starter")

        assert result["entities"] == []
        locked = result["metadata"]["locked_sections"]
        assert "entities" in locked
        assert locked["entities"]["is_locked"] is True
        assert locked["entities"]["required_plan_label"] == "Specialist"

    def test_plan_specialist_keeps_entities_unlocked(self):
        payload = {"entities": [{"name": "Acme Corp", "type": "Organization"}], "metadata": {}}

        result = sanitize_audit_payload_for_plan(payload, "plan_specialist")

        assert result["entities"] == [{"name": "Acme Corp", "type": "Organization"}]
        assert "entities" not in result["metadata"].get("locked_sections", {})


class TestSanitizePayloadEeatIntegration:
    """Integration: sanitize_audit_payload_for_plan triggers eeat recalculation for low plans."""

    def test_plan_standard_gets_recalculated_scores(self):
        payload = _make_scores_payload(eeat_trust=90.0)
        original_seo = payload["scores"]["seo_score"]

        result = sanitize_audit_payload_for_plan(payload, "plan_standard")

        # plan_standard lacks has_eeat_trust_audit
        assert result["scores"]["seo_score"] != original_seo
        assert "eeat_trust" not in result["scores"]["seo_breakdown"]["components"]
        locked = result["metadata"]["locked_sections"]
        assert "eeat_trust" in locked
        assert locked["eeat_trust"]["is_locked"] is True

    def test_plan_executive_keeps_original_scores(self):
        payload = _make_scores_payload(eeat_trust=90.0)
        original_seo = payload["scores"]["seo_score"]

        result = sanitize_audit_payload_for_plan(payload, "plan_executive")

        assert result["scores"]["seo_score"] == original_seo
        assert "eeat_trust" in result["scores"]["seo_breakdown"]["components"]
