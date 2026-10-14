import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.claim_ledger_service import ClaimLedgerService


def test_build_analysis_transfer_packet_extracts_compact_claim_ledger() -> None:
    service = ClaimLedgerService(max_claims=4)

    packet = service.build_analysis_transfer_packet(
        {
            "summary": "The site is technically stable but underexposed in answer engines.",
            "recommendations": [
                "Add FAQ schema to the core service pages.",
                "Strengthen local citation consistency for the main office.",
            ],
            "seo_findings": [
                {
                    "description": "Critical crawl budget is wasted on duplicate filter URLs.",
                    "severity": "critical",
                    "category": "indexing",
                }
            ],
            "geo_findings": [
                {
                    "description": "Local entity references are inconsistent across citations.",
                    "severity": "warning",
                    "category": "citations",
                }
            ],
            "aeo_signals": {
                "answerability_score": 71.0,
                "voice_readiness_score": 68.0,
                "key_recommendations": ["Publish concise answer blocks for high-intent questions."],
            },
            "technical_signals": {
                "mobile_friendliness": 78.0,
                "security_score": 92.0,
            },
            "geo_signals": {
                "citation_consistency_score": 63.0,
                "local_authority_score": 59.0,
            },
        }
    )

    assert packet["summary"] == "The site is technically stable but underexposed in answer engines."
    assert packet["claim_ledger_summary"]["returned_claims"] == 4
    assert packet["claim_ledger_summary"]["omitted_claims"] == 2
    assert (
        packet["claim_ledger"][0]["recommended_action"]
        == "Add FAQ schema to the core service pages."
    )
    assert packet["claim_ledger"][0]["domain"] == "aeo"
    assert packet["score_snapshot"]["technical_signals"]["mobile_friendliness"] == 78.0


def test_build_analysis_transfer_packet_prefers_model_claim_ledger_when_present() -> None:
    service = ClaimLedgerService(max_claims=4)

    packet = service.build_analysis_transfer_packet(
        {
            "summary": "SEO expert summary",
            "claim_ledger": [
                {
                    "claim_id": "seo-03",
                    "domain": "seo",
                    "claim_text": "Missing hreflang tags for multi-language content",
                    "confidence": 0.85,
                    "evidence_refs": ["scan.hreflang_check", "competitor.hreflang_present"],
                    "recommended_action": "implement_hreflang",
                }
            ],
            "seo_findings": [
                {
                    "description": "This fallback finding should not be used when claim_ledger is present.",
                    "severity": "critical",
                    "category": "indexing",
                }
            ],
        },
        expert_domain="seo",
    )

    assert packet["claim_ledger_summary"]["used_model_claim_ledger"] is True
    assert packet["claim_ledger"] == [
        {
            "claim_id": "seo-03",
            "domain": "seo",
            "claim_text": "Missing hreflang tags for multi-language content",
            "confidence": 0.85,
            "evidence_refs": ["scan.hreflang_check", "competitor.hreflang_present"],
            "recommended_action": "implement_hreflang",
        }
    ]


def test_build_challenge_transfer_packet_normalizes_critic_output() -> None:
    service = ClaimLedgerService(max_claims=3)

    packet = service.build_challenge_transfer_packet(
        {
            "unsupported_claims": [
                {
                    "target_claim": "Authority graph is complete",
                    "issue_type": "unsupported_claim",
                    "severity": "critical",
                    "counter_argument": "The crawl does not show coverage for authoritative citations.",
                    "suggested_disposition": "downgrade",
                }
            ],
            "weak_recommendations": [
                {
                    "target_claim": "Add more content",
                    "issue_type": "weak_recommendation",
                    "severity": "moderate",
                    "counter_argument": "This is generic advice without a site-specific problem anchor.",
                    "suggested_disposition": "remove",
                }
            ],
            "missed_items": ["FAQ schema evidence is absent"],
            "unresolved_questions": ["Is there a verified source for the benchmark claim?"],
            "confidence_delta": -0.2,
        }
    )

    assert packet["challenge_summary"]["returned_challenges"] == 2
    assert packet["challenge_summary"]["confidence_delta"] == -0.2
    assert packet["challenge_ledger"][0]["issue_type"] == "unsupported_claim"
    assert packet["challenge_ledger"][1]["suggested_disposition"] == "remove"
    assert packet["missed_items"] == ["FAQ schema evidence is absent"]


# ---------------------------------------------------------------------------
# Environment variable override tests
# ---------------------------------------------------------------------------


def _payload_with_findings_and_recommendations() -> dict:
    return {
        "summary": "Test summary.",
        "seo_score": 70,
        "recommendations": [
            "Improve internal linking structure.",
        ],
        "seo_findings": [
            {
                "description": "Critical crawl issue detected.",
                "severity": "critical",
                "category": "indexing",
            },
            {
                "description": "Minor meta tag warning.",
                "severity": "warning",
                "category": "on_page",
            },
        ],
    }


def test_env_priority_override_changes_ranking(monkeypatch) -> None:
    """When finding priority exceeds recommendation priority, findings should rank first."""
    # Default: recommendations=320 > findings=280, so recommendations come first
    service_default = ClaimLedgerService(max_claims=20)
    packet_default = service_default.build_analysis_transfer_packet(
        _payload_with_findings_and_recommendations(),
        expert_domain="seo",
    )
    default_ids = [c["claim_id"] for c in packet_default["claim_ledger"]]
    # Recommendation (priority 319) should come before finding (priority 279)
    rec_pos = next(i for i, cid in enumerate(default_ids) if "rec" in cid)
    finding_pos = next(i for i, cid in enumerate(default_ids) if "finding" in cid)
    assert rec_pos < finding_pos, "Default: recommendations should rank above findings"

    # Override: make findings outrank recommendations
    monkeypatch.setenv("CLAIM_LEDGER_PRIORITY_FINDING", "400")
    monkeypatch.setenv("CLAIM_LEDGER_PRIORITY_RECOMMENDATION", "200")

    service_override = ClaimLedgerService(max_claims=20)
    packet_override = service_override.build_analysis_transfer_packet(
        _payload_with_findings_and_recommendations(),
        expert_domain="seo",
    )
    override_ids = [c["claim_id"] for c in packet_override["claim_ledger"]]
    rec_pos_o = next(i for i, cid in enumerate(override_ids) if "rec" in cid)
    finding_pos_o = next(i for i, cid in enumerate(override_ids) if "finding" in cid)
    assert finding_pos_o < rec_pos_o, "Override: findings should now rank above recommendations"


def test_env_severity_confidence_override(monkeypatch) -> None:
    """Custom severity confidence should propagate to finding claims."""
    monkeypatch.setenv("CLAIM_LEDGER_SEVERITY_CRITICAL", "0.99")

    service = ClaimLedgerService(max_claims=20)
    packet = service.build_analysis_transfer_packet(
        {
            "seo_findings": [
                {"description": "Critical issue.", "severity": "critical", "category": "indexing"},
            ],
        },
        expert_domain="seo",
    )

    critical_claim = next(c for c in packet["claim_ledger"] if "finding" in c["claim_id"])
    assert critical_claim["confidence"] == 0.99


def test_env_max_claims_respected(monkeypatch) -> None:
    """DEBATE_CLAIM_LEDGER_MAX_ITEMS env var should control max_claims on default service."""
    monkeypatch.setenv("DEBATE_CLAIM_LEDGER_MAX_ITEMS", "5")

    service = ClaimLedgerService()
    assert service.max_claims == 5


def test_env_max_text_chars_override(monkeypatch) -> None:
    """CLAIM_LEDGER_MAX_TEXT_CHARS env var should control text truncation."""
    monkeypatch.setenv("CLAIM_LEDGER_MAX_TEXT_CHARS", "100")

    service = ClaimLedgerService()
    assert service.max_text_chars == 100


def test_env_max_refs_override(monkeypatch) -> None:
    """CLAIM_LEDGER_MAX_REFS env var should control evidence_refs limit."""
    monkeypatch.setenv("CLAIM_LEDGER_MAX_REFS", "5")

    service = ClaimLedgerService()
    assert service.max_refs == 5
