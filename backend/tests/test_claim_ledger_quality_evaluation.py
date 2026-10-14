"""A/B quality evaluation for claim ledger compaction.

Validates that compact transfer packets preserve critical information
from full expert payloads without degrading output quality.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.claim_ledger_service import ClaimLedgerService


# ---------------------------------------------------------------------------
# Rich expert payload fixtures
# ---------------------------------------------------------------------------


def _rich_seo_payload() -> dict:
    return {
        "summary": "The site has strong technical foundations but critical indexing issues limit visibility.",
        "seo_score": 72,
        "geo_score": 58,
        "aeo_score": 45,
        "recommendations": [
            "Implement hreflang tags for all multi-language pages.",
            "Consolidate duplicate filter URLs under canonical tags.",
            "Add structured FAQ schema to high-intent landing pages.",
            "Improve internal linking to orphaned product categories.",
            "Upgrade mobile page speed by deferring third-party scripts.",
            "Submit updated XML sitemap after URL consolidation.",
        ],
        "seo_findings": [
            {
                "description": "Crawl budget wasted on 2,400 duplicate filter URLs.",
                "severity": "critical",
                "category": "indexing",
            },
            {
                "description": "Missing hreflang on 18 multi-language pages.",
                "severity": "critical",
                "category": "internationalization",
            },
            {
                "description": "Thin content detected on 12 category pages under 200 words.",
                "severity": "warning",
                "category": "content",
            },
            {
                "description": "No canonical tags on paginated listing pages.",
                "severity": "warning",
                "category": "indexing",
            },
            {
                "description": "Image alt attributes missing on 35% of product images.",
                "severity": "warning",
                "category": "accessibility",
            },
            {
                "description": "Open Graph tags incomplete on blog posts.",
                "severity": "info",
                "category": "social",
            },
            {
                "description": "Robots.txt allows crawling of internal search result pages.",
                "severity": "info",
                "category": "crawl_control",
            },
            {
                "description": "Minor title tag length variations across service pages.",
                "severity": "info",
                "category": "on_page",
            },
        ],
        "geo_findings": [
            {
                "description": "NAP inconsistency across 4 citation sources.",
                "severity": "warning",
                "category": "citations",
            },
            {
                "description": "Google Business Profile hours outdated.",
                "severity": "info",
                "category": "local",
            },
        ],
        "aeo_findings": [
            {
                "description": "No FAQ schema detected on any page.",
                "severity": "critical",
                "category": "schema",
            },
            {
                "description": "Answer blocks too long for voice search snippets.",
                "severity": "warning",
                "category": "voice_readiness",
            },
        ],
        "aeo_signals": {
            "answerability_score": 42.0,
            "voice_readiness_score": 38.0,
            "key_recommendations": [
                "Publish concise answer blocks for high-intent queries.",
                "Add HowTo schema to tutorial pages.",
            ],
        },
        "technical_signals": {
            "mobile_friendliness": 78.0,
            "security_score": 92.0,
            "page_speed_score": 64.0,
            "issues": ["render-blocking JS", "large DOM size", "unused CSS"],
        },
        "geo_signals": {
            "citation_consistency_score": 63.0,
            "local_authority_score": 59.0,
        },
    }


def _rich_payload_with_model_ledger() -> dict:
    payload = _rich_seo_payload()
    payload["claim_ledger"] = [
        {
            "claim_id": "seo-01",
            "domain": "seo",
            "claim_text": "Crawl budget wasted on 2,400 duplicate filter URLs.",
            "confidence": 0.95,
            "evidence_refs": ["seo_findings[0]"],
            "recommended_action": "consolidate_filter_urls",
        },
        {
            "claim_id": "seo-02",
            "domain": "seo",
            "claim_text": "Missing hreflang on 18 multi-language pages.",
            "confidence": 0.93,
            "evidence_refs": ["seo_findings[1]"],
            "recommended_action": "implement_hreflang",
        },
        {
            "claim_id": "aeo-01",
            "domain": "aeo",
            "claim_text": "No FAQ schema detected on any page.",
            "confidence": 0.91,
            "evidence_refs": ["aeo_findings[0]"],
            "recommended_action": "add_faq_schema",
        },
    ]
    return payload


# ---------------------------------------------------------------------------
# Test 1: Transfer packet preserves critical claims
# ---------------------------------------------------------------------------


def test_transfer_packet_preserves_critical_claims() -> None:
    service = ClaimLedgerService(max_claims=10)
    payload = _rich_seo_payload()
    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")

    claim_texts = [c["claim_text"] for c in packet["claim_ledger"]]

    # All critical findings must survive the top-N cut when max_claims is generous
    assert any(
        "2,400 duplicate filter URLs" in t for t in claim_texts
    ), "Critical SEO finding (duplicate URLs) missing from compact ledger"
    assert any(
        "hreflang" in t.lower() for t in claim_texts
    ), "Critical SEO finding (hreflang) missing from compact ledger"
    assert any(
        "FAQ schema" in t for t in claim_texts
    ), "Critical AEO finding (FAQ schema) missing from compact ledger"

    # Top recommendation should survive
    assert any(
        "hreflang" in t.lower() for t in claim_texts
    ), "Top recommendation missing from compact ledger"


# ---------------------------------------------------------------------------
# Test 2: Information loss bounded by top-N policy
# ---------------------------------------------------------------------------


def test_information_loss_bounded_by_top_n() -> None:
    service = ClaimLedgerService(max_claims=8)
    payload = _rich_seo_payload()
    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")

    returned = packet["claim_ledger"]
    summary = packet["claim_ledger_summary"]

    assert summary["returned_claims"] == 8
    assert summary["omitted_claims"] > 0

    # Critical findings must never be omitted
    returned_texts = " ".join(c["claim_text"] for c in returned)
    assert "2,400 duplicate filter URLs" in returned_texts
    assert "hreflang" in returned_texts.lower()
    assert "FAQ schema" in returned_texts

    # Verify returned claims have higher average confidence than what
    # info-severity items would produce
    avg_confidence = sum(c["confidence"] for c in returned) / len(returned)
    assert (
        avg_confidence >= 0.55
    ), f"Average confidence {avg_confidence:.4f} too low — low-quality claims may have displaced important ones"


# ---------------------------------------------------------------------------
# Test 3: Confidence scores are deterministic
# ---------------------------------------------------------------------------


def test_confidence_scores_deterministic() -> None:
    service = ClaimLedgerService(max_claims=20)
    payload = {
        "summary": "Test summary for confidence validation.",
        "seo_score": 75,
        "geo_score": 60,
        "aeo_score": 80,
        "seo_findings": [
            {
                "description": "Critical indexing issue found.",
                "severity": "critical",
                "category": "indexing",
            },
            {
                "description": "Minor meta description warning.",
                "severity": "warning",
                "category": "on_page",
            },
            {
                "description": "Informational note about title tags.",
                "severity": "info",
                "category": "on_page",
            },
        ],
        "recommendations": ["Fix the critical indexing issue immediately."],
    }

    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")
    claims_by_id = {c["claim_id"]: c for c in packet["claim_ledger"]}

    # Expected summary confidence: clamp(avg(75, 60, 80) / 100, min=0.45) = clamp(0.7167, min=0.45) ≈ 0.7167
    expected_summary_conf = round((75 + 60 + 80) / 3 / 100, 4)

    summary_claim = claims_by_id.get("seo-summary-01")
    assert summary_claim is not None
    assert abs(summary_claim["confidence"] - expected_summary_conf) < 0.001

    # Critical finding: max(0.92, summary - 0.05)
    critical_claim = claims_by_id.get("seo-finding-01")
    assert critical_claim is not None
    assert critical_claim["confidence"] == 0.92

    # Warning finding: max(0.78, summary - 0.05) = max(0.78, 0.6667) = 0.78
    warning_claim = claims_by_id.get("seo-finding-02")
    assert warning_claim is not None
    assert warning_claim["confidence"] == 0.78

    # Recommendation inherits summary confidence
    rec_claim = claims_by_id.get("seo-rec-01")
    assert rec_claim is not None
    assert abs(rec_claim["confidence"] - expected_summary_conf) < 0.001


# ---------------------------------------------------------------------------
# Test 4: Score snapshot preserves signals
# ---------------------------------------------------------------------------


def test_score_snapshot_preserves_signals() -> None:
    service = ClaimLedgerService(max_claims=12)
    payload = _rich_seo_payload()
    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")

    snapshot = packet["score_snapshot"]

    # Top-level scores preserved
    assert snapshot["seo_score"] == 72.0
    assert snapshot["geo_score"] == 58.0
    assert snapshot["aeo_score"] == 45.0

    # Technical signals numeric values preserved
    assert snapshot["technical_signals"]["mobile_friendliness"] == 78.0
    assert snapshot["technical_signals"]["security_score"] == 92.0
    assert snapshot["technical_signals"]["page_speed_score"] == 64.0

    # String lists truncated to 4 items max
    issues = snapshot["technical_signals"]["issues"]
    assert isinstance(issues, list)
    assert len(issues) <= 4

    # Geo signals preserved
    assert snapshot["geo_signals"]["citation_consistency_score"] == 63.0
    assert snapshot["geo_signals"]["local_authority_score"] == 59.0


# ---------------------------------------------------------------------------
# Test 5: Compact vs raw claim coverage
# ---------------------------------------------------------------------------


def test_compact_vs_raw_claim_coverage() -> None:
    payload = _rich_seo_payload()

    # Collect all raw claim texts from the payload
    raw_claims: list[str] = []
    raw_critical: list[str] = []

    for rec in payload.get("recommendations") or []:
        raw_claims.append(rec)

    for field in ("seo_findings", "geo_findings", "aeo_findings"):
        for item in payload.get(field) or []:
            desc = item.get("description", "")
            raw_claims.append(desc)
            if item.get("severity") == "critical":
                raw_critical.append(desc)

    for rec in (payload.get("aeo_signals") or {}).get("key_recommendations") or []:
        raw_claims.append(rec)

    # Compact with max_claims=10
    service = ClaimLedgerService(max_claims=10)
    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")
    compact_texts = {c["claim_text"] for c in packet["claim_ledger"]}

    # Coverage: at least a quarter of raw claims survive at max_claims=10
    matched = sum(1 for raw in raw_claims if any(raw[:40] in ct for ct in compact_texts))
    coverage = matched / len(raw_claims) if raw_claims else 1.0
    assert coverage >= 0.25, f"Coverage {coverage:.2f} too low for max_claims=10"

    # Critical claims must have 100% coverage at max_claims=10
    for critical in raw_critical:
        assert any(
            critical[:40] in ct for ct in compact_texts
        ), f"Critical claim missing: {critical[:60]}..."


# ---------------------------------------------------------------------------
# Test 6: Domain inference accuracy
# ---------------------------------------------------------------------------


def test_domain_inference_accuracy() -> None:
    service = ClaimLedgerService()

    test_cases = [
        # SEO domain
        ("Missing hreflang tags for multi-language pages", "seo"),
        ("Crawl budget wasted on duplicate filter URLs", "seo"),
        ("XML sitemap not submitted after URL changes", "seo"),
        ("Robots.txt blocks important pages", "seo"),
        ("Backlink profile is weak for competitive keywords", "seo"),
        ("Canonical tags missing on paginated pages", "seo"),
        ("Poor ranking for target keywords", "seo"),
        ("Index bloat from orphaned pages", "seo"),
        # GEO domain
        ("NAP inconsistency across citation sources", "geo"),
        ("Google Business Profile information outdated", "geo"),
        ("Local authority signals are weak", "geo"),
        ("Entity references inconsistent in knowledge graph", "geo"),
        ("Brand mentions lack structured data", "geo"),
        ("Location pages missing address markup", "geo"),
        ("Map listing has incorrect coordinates", "geo"),
        ("Customer review signals are below competitors", "geo"),
        # AEO domain
        ("No FAQ markup detected on landing pages", "aeo"),
        ("Answer blocks too verbose for voice assistants", "aeo"),
        ("LLM-based search engines do not cite this site", "aeo"),
        ("Conversational query coverage is minimal", "aeo"),
        ("Generative AI omits this site from results", "aeo"),
        ("Snippet eligibility score below threshold", "aeo"),
        ("Voice readiness needs improvement for answerability", "aeo"),
        # Cross-domain (should not match any specific domain)
        ("Page load time is slow on mobile devices", "cross_domain"),
        ("Overall user experience needs improvement", "cross_domain"),
    ]

    correct = 0
    failures: list[str] = []

    for claim_text, expected_domain in test_cases:
        inferred = service._infer_domain(claim_text)
        if inferred == expected_domain:
            correct += 1
        else:
            failures.append(
                f"  '{claim_text[:50]}...' -> expected={expected_domain}, got={inferred}"
            )

    accuracy = correct / len(test_cases)
    assert accuracy >= 0.85, (
        f"Domain inference accuracy {accuracy:.0%} below 85% threshold.\nFailures:\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# Test 7: Model-provided claim ledger preferred over fallback
# ---------------------------------------------------------------------------


def test_model_ledger_quality_preserved() -> None:
    service = ClaimLedgerService(max_claims=6)
    payload = _rich_payload_with_model_ledger()
    packet = service.build_analysis_transfer_packet(payload, expert_domain="seo")

    assert packet["claim_ledger_summary"]["used_model_claim_ledger"] is True

    # Model-provided claims should be returned as-is (normalized)
    assert len(packet["claim_ledger"]) == 3
    claim_ids = {c["claim_id"] for c in packet["claim_ledger"]}
    assert claim_ids == {"seo-01", "seo-02", "aeo-01"}

    # Confidence should be preserved from model output
    for claim in packet["claim_ledger"]:
        if claim["claim_id"] == "seo-01":
            assert claim["confidence"] == 0.95
        elif claim["claim_id"] == "seo-02":
            assert claim["confidence"] == 0.93
