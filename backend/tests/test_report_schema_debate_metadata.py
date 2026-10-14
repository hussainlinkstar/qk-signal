from report_schema import AuditReport


def test_report_schema_preserves_fast_pipeline_debate_metadata() -> None:
    report = AuditReport(
        analysis={"schema_version": "1.0"},
        performance={},
        network={},
        metadata={},
        debate={
            "enabled": True,
            "mode": "debate",
            "provider": "multi-provider",
            "model": "multi-agent",
            "requested_tier": "fast",
            "pipeline_type": "fast_3step",
            "agent_count": 3,
            "parallel_layers": 0,
            "evidence_anchor": {
                "scores": {"seo": 72, "geo": 68, "aeo": 70},
                "critical_metrics": {"pages_crawled": 12},
            },
            "consolidated_claim_disposition": [
                {
                    "claim_id": "seo-01",
                    "domain": "seo",
                    "disposition": "accepted",
                }
            ],
            "dedup_count": 1,
            "per_agent_costs": [
                {
                    "role": "fast_proposer",
                    "semantic_role": "generator",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "execution_tier": "fast",
                    "latency_ms": 12.5,
                    "cost_usd": 0.01,
                    "tokens": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            ],
            "quality_gate": {
                "schema_version": "orchestra-v3-qg-1",
                "passed": True,
                "violation_count": 0,
            },
            "transcript": [
                {
                    "role": "fast_proposer",
                    "semantic_role": "generator",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "output_summary": "First pass summary",
                    "execution_tier": "fast",
                    "routing_mode": "server_policy",
                    "requested_tier": "fast",
                    "layer": 1,
                }
            ],
        },
    ).model_dump()

    assert report["debate"]["mode"] == "debate"
    assert report["debate"]["requested_tier"] == "fast"
    assert report["debate"]["pipeline_type"] == "fast_3step"
    assert report["debate"]["agent_count"] == 3
    assert report["debate"]["evidence_anchor"]["scores"]["seo"] == 72
    assert report["debate"]["consolidated_claim_disposition"][0]["domain"] == "seo"
    assert report["debate"]["dedup_count"] == 1
    assert report["debate"]["per_agent_costs"][0]["execution_tier"] == "fast"
    assert report["debate"]["transcript"][0]["semantic_role"] == "generator"
    assert report["debate"]["quality_gate"]["schema_version"] == "orchestra-v3-qg-1"
