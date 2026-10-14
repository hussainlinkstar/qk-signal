from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from services.dual_track_validation_service import (
    build_report_validation_summary,
    build_validation_summary_from_audit,
    compare_validation_summaries,
    discover_validation_suite_candidates,
    extract_signoff_record,
    render_discovered_validation_candidates_markdown,
    render_validation_markdown,
    render_validation_suite_markdown,
    summarize_validation_suite,
)


def _baseline_report() -> dict:
    return {
        "schema_version": "2026-03-09",
        "url": "https://example.com",
        "analysis": {
            "seo_score": 80,
            "geo_score": 78,
            "aeo_score": 75,
            "recommendations": ["Add FAQ schema to the homepage."],
        },
        "metadata": {
            "requested_tier": "deep_judgment",
        },
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": False,
            "grounding_profile": "single_track_v1",
            "summary": {
                "total_claims": 1,
                "track_a_total": 1,
                "track_a_supported": 1,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 0,
                "track_b_supported": 0,
                "track_b_flagged": 0,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [],
            "degraded": False,
            "degraded_reason": None,
        },
    }


def _candidate_report() -> dict:
    return {
        "schema_version": "2026-03-09",
        "url": "https://example.com",
        "analysis": {
            "seo_score": 80,
            "geo_score": 78,
            "aeo_score": 75,
            "recommendations": [
                "Add FAQ schema to the homepage.",
                "Add a Romania primary-market modifier to the homepage H1.",
            ],
        },
        "metadata": {
            "requested_tier": "deep_judgment",
            "grounding_profile": "dual_track_shadow_v1",
            "dual_track_grounding_enabled": True,
            "dual_track_shadow": {
                "status": "shadow",
                "summary": {
                    "track_a_claims": 1,
                    "track_b_claims": 2,
                    "supported_claims": 2,
                    "flagged_claims": 0,
                    "omitted_claims": 1,
                },
                "track_b_judge": {
                    "requested_tier": "deep_judgment",
                    "enabled": True,
                    "available": True,
                    "mode": "llm_shadow",
                    "judge_unavailable_claims": 0,
                },
            },
        },
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": True,
            "grounding_profile": "dual_track_v1",
            "summary": {
                "total_claims": 3,
                "track_a_total": 1,
                "track_a_supported": 1,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 2,
                "track_b_supported": 1,
                "track_b_flagged": 1,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [
                {"track": "track_b", "category": "generic_recommendation", "count": 1}
            ],
            "degraded": False,
            "degraded_reason": None,
        },
    }


def test_build_report_validation_summary_extracts_dual_track_snapshot() -> None:
    summary = build_report_validation_summary(
        _candidate_report(),
        audit_id=123,
        request_id="req-123",
        audit_url="https://example.com",
        created_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
    )

    assert summary["audit_id"] == 123
    assert summary["request_id"] == "req-123"
    assert summary["target"]["url"] == "https://example.com"
    assert summary["has_integrity_certificate"] is True
    assert summary["grounding_profile"] == "dual_track_v1"
    assert summary["dual_track_grounding_enabled"] is True
    assert summary["track_counts"]["track_b_total"] == 2
    assert summary["recommendation_count"] == 2
    assert summary["dual_track_shadow"]["present"] is True
    assert summary["dual_track_shadow"]["track_b_judge"]["mode"] == "llm_shadow"


def test_build_validation_summary_from_audit_uses_relational_target_fields() -> None:
    audit = models.Audit(
        id=77,
        user_id=1,
        project_id=None,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://legacy.example.com",
        target_url="https://example.com",
        target_name="Example",
        target_metadata={"market": "ro"},
        audit_target_type=models.AuditTargetType.BRAND,
        geo_score=78,
        seo_score=80,
        aeo_score=75,
        full_report=_candidate_report(),
        request_id="req-77",
        created_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
    )

    summary = build_validation_summary_from_audit(audit)

    assert summary["audit_id"] == 77
    assert summary["target"]["type"] == "brand"
    assert summary["target"]["name"] == "Example"
    assert summary["target"]["url"] == "https://example.com"


def test_compare_validation_summaries_reports_recommendation_and_bucket_delta() -> None:
    comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=1),
        candidate_summary=build_report_validation_summary(_candidate_report(), audit_id=2),
        review_type="standard",
    )

    assert comparison["target_match"] is True
    assert comparison["automatic_blockers"] == []
    assert comparison["recommendation_delta"]["added"] == [
        "Add a Romania primary-market modifier to the homepage H1."
    ]
    assert comparison["recommendation_delta"]["removed"] == []
    assert comparison["blocked_bucket_delta"] == [
        {
            "key": "track_b:generic_recommendation",
            "track": "track_b",
            "category": "generic_recommendation",
            "baseline_count": 0,
            "candidate_count": 1,
            "delta": 1,
        }
    ]


def test_compare_validation_summaries_flags_standard_fallback_as_blocker() -> None:
    candidate = _candidate_report()
    candidate["integrity_certificate"]["grounding_profile"] = "single_track_fallback"
    candidate["metadata"]["fallback_reason"] = "unified_truth_context_unavailable"

    comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=1),
        candidate_summary=build_report_validation_summary(candidate, audit_id=2),
        review_type="standard",
    )

    assert (
        "candidate standard review fell back to single_track_fallback"
        in comparison["automatic_blockers"]
    )


def test_render_validation_markdown_includes_blocker_section() -> None:
    comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=11),
        candidate_summary=build_report_validation_summary(_candidate_report(), audit_id=12),
        review_type="standard",
    )

    rendered = render_validation_markdown(comparison)

    assert "# EPIC-03 Dual-Track Validation Comparison" in rendered
    assert "- Baseline audit id: 11" in rendered
    assert "- Candidate audit id: 12" in rendered
    assert "## Automatic Blockers" in rendered
    assert "- None" in rendered


def test_summarize_validation_suite_enforces_required_roles_and_case_specific_rules() -> None:
    standard_comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=11),
        candidate_summary=build_report_validation_summary(_candidate_report(), audit_id=12),
        review_type="standard",
    )
    fallback_candidate = _candidate_report()
    fallback_candidate["integrity_certificate"]["grounding_profile"] = "single_track_fallback"
    fallback_candidate["metadata"]["fallback_reason"] = "track_b_judge_unavailable"
    fallback_comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=21),
        candidate_summary=build_report_validation_summary(fallback_candidate, audit_id=22),
        review_type="fallback_control",
    )

    suite = summarize_validation_suite(
        [
            {
                "case_id": "exemplar",
                "label": "Deep judgment exemplar",
                "validation_role": "deep_judgment_exemplar",
                "review_type": "standard",
                "comparison": standard_comparison,
            },
            {
                "case_id": "fallback",
                "label": "Fallback control",
                "validation_role": "fallback_control",
                "review_type": "fallback_control",
                "comparison": fallback_comparison,
            },
        ]
    )

    assert suite["required_coverage_complete"] is False
    assert suite["missing_required_roles"] == [
        "website_control",
        "brand_metadata_control",
    ]
    assert (
        "validation suite is missing required roles: website_control, brand_metadata_control"
        in suite["automatic_blockers"]
    )
    assert suite["case_counts"]["with_blockers"] == 0


def test_render_validation_suite_markdown_lists_cases_and_suite_status() -> None:
    comparison = compare_validation_summaries(
        baseline_summary=build_report_validation_summary(_baseline_report(), audit_id=31),
        candidate_summary=build_report_validation_summary(_candidate_report(), audit_id=32),
        review_type="standard",
    )
    suite = summarize_validation_suite(
        [
            {
                "case_id": "website",
                "label": "Website control",
                "validation_role": "website_control",
                "review_type": "standard",
                "comparison": comparison,
            }
        ],
        suite_label="Validation Gate Batch",
        required_roles=("website_control",),
    )

    rendered = render_validation_suite_markdown(suite)

    assert "# EPIC-03 Dual-Track Validation Suite" in rendered
    assert "- Label: Validation Gate Batch" in rendered
    assert "- Required coverage complete: yes" in rendered
    assert "### Website control" in rendered
    assert "- Automatic blockers: none" in rendered


def test_extract_signoff_record_marks_suite_readiness_and_carries_blockers() -> None:
    suite = summarize_validation_suite(
        [],
        suite_label="Empty gate",
    )

    signoff_record = extract_signoff_record(suite)

    assert signoff_record["artifact_type"] == "suite"
    assert signoff_record["ready_for_signoff"] is False
    assert signoff_record["required_coverage_complete"] is False
    assert "validation suite is missing required roles:" in signoff_record["automatic_blockers"][0]


def test_discover_validation_suite_candidates_reports_missing_roles_for_sparse_history() -> None:
    project = models.Project(
        id=2,
        workspace_id=1,
        name="Lavan Events",
        domain_url="https://lavan.ro",
        target_country="RO",
        language="ro",
    )
    baseline_audit = models.Audit(
        id=101,
        user_id=1,
        project_id=2,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://lavan.ro",
        target_url="https://lavan.ro",
        target_name="Lavan Events",
        target_metadata={},
        audit_target_type=models.AuditTargetType.BRAND,
        geo_score=5.1,
        seo_score=28.5,
        aeo_score=15.3,
        full_report=_baseline_report() | {"metadata": {"requested_tier": "deep_judgment"}},
    )
    baseline_audit.project = project

    result = discover_validation_suite_candidates([baseline_audit])

    assert result["ready_case_count"] == 0
    assert "deep_judgment_exemplar" in result["missing_roles"]
    assert result["draft_manifest"]["cases"] == []


def test_discover_validation_suite_candidates_builds_manifest_for_ready_pairs() -> None:
    brand_project = models.Project(
        id=2,
        workspace_id=1,
        name="Lavan Events",
        domain_url="https://lavan.ro",
        target_country="RO",
        language="ro",
    )
    website_project = models.Project(
        id=3,
        workspace_id=1,
        name="Example Site",
        domain_url="https://example.com",
        target_country="US",
        language="en",
    )
    fallback_project = models.Project(
        id=4,
        workspace_id=1,
        name="Fallback Site",
        domain_url="https://fallback.example",
        target_country="US",
        language="en",
    )

    brand_baseline = models.Audit(
        id=201,
        user_id=1,
        project_id=2,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://lavan.ro",
        target_url="https://lavan.ro",
        target_name="Lavan Events",
        target_metadata={},
        audit_target_type=models.AuditTargetType.BRAND,
        geo_score=5.1,
        seo_score=28.5,
        aeo_score=15.3,
        full_report=_baseline_report() | {"metadata": {"requested_tier": "deep_judgment"}},
        created_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
    )
    brand_baseline.project = brand_project
    brand_candidate = models.Audit(
        id=202,
        user_id=1,
        project_id=2,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://lavan.ro",
        target_url="https://lavan.ro",
        target_name="Lavan Events",
        target_metadata={},
        audit_target_type=models.AuditTargetType.BRAND,
        geo_score=5.1,
        seo_score=28.5,
        aeo_score=15.3,
        full_report=_candidate_report(),
        created_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
    )
    brand_candidate.project = brand_project

    website_baseline = models.Audit(
        id=203,
        user_id=1,
        project_id=3,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        target_url="https://example.com",
        target_name="Example Site",
        target_metadata={},
        audit_target_type=models.AuditTargetType.WEBSITE,
        geo_score=65,
        seo_score=70,
        aeo_score=60,
        full_report=_baseline_report() | {"metadata": {"requested_tier": "smart"}},
        created_at=datetime(2026, 3, 9, tzinfo=timezone.utc),
    )
    website_baseline.project = website_project
    website_candidate = models.Audit(
        id=204,
        user_id=1,
        project_id=3,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://example.com",
        target_url="https://example.com",
        target_name="Example Site",
        target_metadata={},
        audit_target_type=models.AuditTargetType.WEBSITE,
        geo_score=65,
        seo_score=70,
        aeo_score=60,
        full_report=_candidate_report()
        | {
            "metadata": {
                "requested_tier": "smart",
                "grounding_profile": "dual_track_shadow_v1",
                "dual_track_grounding_enabled": True,
            }
        },
        created_at=datetime(2026, 3, 11, 1, tzinfo=timezone.utc),
    )
    website_candidate.project = website_project

    fallback_baseline = models.Audit(
        id=205,
        user_id=1,
        project_id=4,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://fallback.example",
        target_url="https://fallback.example",
        target_name="Fallback Site",
        target_metadata={},
        audit_target_type=models.AuditTargetType.WEBSITE,
        geo_score=40,
        seo_score=50,
        aeo_score=45,
        full_report=_baseline_report() | {"metadata": {"requested_tier": "deep_judgment"}},
        created_at=datetime(2026, 3, 8, tzinfo=timezone.utc),
    )
    fallback_baseline.project = fallback_project
    fallback_candidate_report = _candidate_report()
    fallback_candidate_report["integrity_certificate"]["grounding_profile"] = (
        "single_track_fallback"
    )
    fallback_candidate_report["metadata"]["fallback_reason"] = "unified_truth_context_unavailable"
    fallback_candidate = models.Audit(
        id=206,
        user_id=1,
        project_id=4,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://fallback.example",
        target_url="https://fallback.example",
        target_name="Fallback Site",
        target_metadata={},
        audit_target_type=models.AuditTargetType.WEBSITE,
        geo_score=40,
        seo_score=50,
        aeo_score=45,
        full_report=fallback_candidate_report,
        created_at=datetime(2026, 3, 11, 2, tzinfo=timezone.utc),
    )
    fallback_candidate.project = fallback_project

    result = discover_validation_suite_candidates(
        [
            brand_baseline,
            brand_candidate,
            website_baseline,
            website_candidate,
            fallback_baseline,
            fallback_candidate,
        ]
    )

    assert result["ready_case_count"] == 3
    assert result["missing_roles"] == ["brand_metadata_control"]
    assert [case["validation_role"] for case in result["draft_manifest"]["cases"]] == [
        "deep_judgment_exemplar",
        "website_control",
        "fallback_control",
    ]

    rendered = render_discovered_validation_candidates_markdown(result)
    assert "# EPIC-03 Validation Candidate Discovery" in rendered
    assert "- deep_judgment_exemplar: ready" in rendered
