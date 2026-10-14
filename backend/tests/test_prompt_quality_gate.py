from services.prompt_quality_gate import prompt_quality_gate_service


def test_prompt_quality_gate_flags_generator_and_magistrate_violations() -> None:
    result = prompt_quality_gate_service.evaluate(
        rounds=[
            {
                "role": "seo_generator",
                "semantic_role": "generator",
                "layer": 1,
                "output": {
                    "claim_ledger": [
                        {
                            "claim_id": "seo-01",
                            "domain": "geo",
                            "claim_text": "Domain authority is 80 and the FAQPage schema is present.",
                            "evidence_refs": [],
                        },
                        {
                            "claim_id": "seo-02",
                            "domain": "seo",
                            "claim_text": "Pages crawled are 99.",
                            "evidence_refs": [],
                        },
                    ]
                },
            },
            {
                "role": "consolidator",
                "semantic_role": "judge",
                "layer": 3,
                "output": {
                    "consolidated_claim_disposition": [
                        {
                            "claim_id": "seo-01",
                            "domain": "seo",
                            "disposition": "needs_manual_review",
                        },
                        {
                            "claim_id": "seo-02",
                            "domain": "seo",
                            "disposition": "needs_manual_review",
                        },
                    ],
                    "dedup_count": 0,
                },
            },
        ],
        evidence_anchor={
            "critical_metrics": {
                "domain_authority": 34,
                "pages_crawled": 18,
                "schema_types_found": ["Article"],
            }
        },
        requested_tier="deep_judgment",
        pipeline_type="delta_flow",
        judge_summary={
            "accepted_claims": 0,
            "downgraded_claims": 0,
            "rejected_claims": 0,
            "unresolved_disputes": 0,
        },
    )

    assert result["passed"] is False
    assert result["pipeline_type"] == "delta_flow"
    assert {item["code"] for item in result["violations"]} >= {
        "generator_domain_boundary_violation",
        "generator_grounding_rate_low",
        "generator_anchor_contradiction_rate_high",
        "magistrate_over_flagging",
    }


def test_prompt_quality_gate_passes_grounded_outputs() -> None:
    result = prompt_quality_gate_service.evaluate(
        rounds=[
            {
                "role": "seo_generator",
                "semantic_role": "generator",
                "layer": 1,
                "output": {
                    "claim_ledger": [
                        {
                            "claim_id": "seo-01",
                            "domain": "seo",
                            "claim_text": "Add internal links from category pages to the comparison hub.",
                            "evidence_refs": ["crawl-link-map"],
                        },
                    ]
                },
            },
            {
                "role": "consolidator",
                "semantic_role": "judge",
                "layer": 3,
                "output": {
                    "consolidated_claim_disposition": [
                        {"claim_id": "seo-01", "domain": "seo", "disposition": "accepted"},
                    ],
                    "dedup_count": 0,
                },
            },
        ],
        evidence_anchor={
            "critical_metrics": {
                "domain_authority": 34,
                "pages_crawled": 18,
                "schema_types_found": ["Article", "FAQPage"],
            }
        },
        requested_tier="smart",
        pipeline_type="smart_5step",
        judge_summary={
            "accepted_claims": 1,
            "downgraded_claims": 0,
            "rejected_claims": 0,
            "unresolved_disputes": 0,
        },
    )

    assert result["passed"] is True
    assert result["violation_count"] == 0
    assert result["agent_checks"][0]["metrics"]["grounding_rate"] == 1.0


def test_prompt_quality_gate_flags_generator_claim_collapse() -> None:
    """BUG-042: Generator with zero claims must trigger generator_claim_collapse."""
    result = prompt_quality_gate_service.evaluate(
        rounds=[
            {
                "role": "seo_generator",
                "semantic_role": "generator",
                "layer": 1,
                "output": {"claim_ledger": []},
            },
            {
                "role": "consolidator",
                "semantic_role": "judge",
                "layer": 3,
                "output": {
                    "consolidated_claim_disposition": [],
                    "dedup_count": 0,
                },
            },
        ],
        evidence_anchor=None,
        requested_tier="smart",
        pipeline_type="smart_5step",
    )

    assert result["passed"] is False
    violation_codes = {item["code"] for item in result["violations"]}
    assert "generator_claim_collapse" in violation_codes
    assert result["total_claims_evaluated"] == 0

    generator_check = next(c for c in result["agent_checks"] if c["check_type"] == "generator")
    assert generator_check["claim_count"] == 0
    assert generator_check["passed"] is False
