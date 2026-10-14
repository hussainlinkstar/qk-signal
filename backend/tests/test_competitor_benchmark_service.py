import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.competitors.benchmark_service import CompetitorBenchmarkService


def test_build_benchmark_table_returns_dashboard_shape_with_rankings_and_deltas():
    service = CompetitorBenchmarkService()

    table = service.build_benchmark_table(
        target={
            "name": "Acme Dental",
            "geo_visibility": 74,
            "aeo_score": 66,
            "entity_strength": 71,
        },
        competitors=[
            {
                "name": "Bright Smile",
                "geo_visibility": 79,
                "aeo_score": 69,
                "entity_strength": 70,
            },
            {
                "name": "City Dental",
                "geo_visibility": 63,
                "aeo_score": 59,
                "entity_strength": 65,
            },
        ],
    )

    assert {column["key"] for column in table["columns"]} == {
        "rank",
        "name",
        "geo_visibility",
        "aeo_score",
        "entity_strength",
        "overall_score",
    }

    assert len(table["rows"]) == 3
    assert table["rows"][0]["name"] == "Bright Smile"
    assert table["rows"][0]["rank"] == 1

    target_row = next(row for row in table["rows"] if row["is_target"])
    assert target_row["deltas_vs_target"] == {
        "geo_visibility": 0.0,
        "aeo_score": 0.0,
        "entity_strength": 0.0,
    }
    assert table["summary"]["target"] == "Acme Dental"
    assert table["summary"]["competitor_count"] == 2
    assert table["summary"]["target_rank"] == target_row["rank"]


def test_build_benchmark_table_clamps_scores_and_skips_invalid_competitors():
    service = CompetitorBenchmarkService()

    table = service.build_benchmark_table(
        target={
            "name": "Acme Dental",
            "geo_visibility": 120,
            "aeo_score": -10,
            "entity_strength": 60,
        },
        competitors=[
            {
                "name": "  ",
                "geo_visibility": 50,
                "aeo_score": 50,
                "entity_strength": 50,
            },
            {
                "name": "acme dental",
                "geo_visibility": 80,
                "aeo_score": 80,
                "entity_strength": 80,
            },
        ],
    )

    assert len(table["rows"]) == 1
    assert table["rows"][0]["geo_visibility"] == 100.0
    assert table["rows"][0]["aeo_score"] == 0.0


def test_build_benchmark_table_validates_required_target_fields():
    service = CompetitorBenchmarkService()

    with pytest.raises(ValueError, match="target name is required"):
        service.build_benchmark_table(
            target={
                "name": " ",
                "geo_visibility": 50,
                "aeo_score": 50,
                "entity_strength": 50,
            },
            competitors=[],
        )

    with pytest.raises(ValueError, match="Missing required metrics: entity_strength"):
        service.build_benchmark_table(
            target={
                "name": "Acme",
                "geo_visibility": 50,
                "aeo_score": 50,
            },
            competitors=[],
        )


def test_build_query_answer_relevance_benchmark_maps_query_and_winner():
    service = CompetitorBenchmarkService()

    class SiteStub:
        def __init__(self, site_id: int, domain: str, display_name: str):
            self.id = site_id
            self.domain = domain
            self.display_name = display_name

    class AuditStub:
        def __init__(self, audit_id: int, site_id: int, query: str, score, created_at: str):
            self.id = audit_id
            self.site_id = site_id
            self.url = f"https://{site_id}.test/{audit_id}"
            self.created_at = datetime.fromisoformat(created_at)
            self.full_report = {
                "metadata": {"query": query},
                "aeo": {"answer_relevance": score, "answer_excerpt": f"answer-{audit_id}"},
            }

    from datetime import datetime

    competitors = [SiteStub(2, "comp-a.com", "Comp A")]
    site_audits = [AuditStub(1, 1, "best crm", 88, "2026-01-01T10:00:00+00:00")]
    competitor_audits = [AuditStub(2, 2, "best crm", 80, "2026-01-02T10:00:00+00:00")]

    payload = service.build_query_answer_relevance_benchmark(
        site_id=1,
        site_domain="example.com",
        competitors=competitors,
        queries=["best crm"],
        site_audits=site_audits,
        competitor_audits=competitor_audits,
    )

    assert payload["competitor_count"] == 1
    assert payload["queries"][0]["query"] == "best crm"
    assert payload["queries"][0]["site"]["answer_relevance"] == 88.0
    assert payload["queries"][0]["competitor"]["answer_relevance"] == 80.0
    assert payload["queries"][0]["delta"] == 8.0
    assert payload["queries"][0]["winner"] == "site"
    assert payload["queries"][0]["battle_for_snippet"]["winner"] == "site"


def test_build_query_answer_relevance_benchmark_handles_missing_queries_and_null_scores():
    service = CompetitorBenchmarkService()

    class SiteStub:
        def __init__(self, site_id: int, domain: str, display_name: str):
            self.id = site_id
            self.domain = domain
            self.display_name = display_name

    class AuditStub:
        def __init__(self, audit_id: int, site_id: int, query: str, created_at: str):
            self.id = audit_id
            self.site_id = site_id
            self.url = f"https://{site_id}.test/{audit_id}"
            self.created_at = datetime.fromisoformat(created_at)
            self.full_report = {"metadata": {"query": query}, "aeo": {"answer_excerpt": "no-score"}}

    from datetime import datetime

    empty_payload = service.build_query_answer_relevance_benchmark(
        site_id=1,
        site_domain="example.com",
        competitors=[],
        queries=[],
        site_audits=[],
        competitor_audits=[],
    )
    assert empty_payload["queries"] == []
    assert empty_payload["competitor_count"] == 0

    payload = service.build_query_answer_relevance_benchmark(
        site_id=1,
        site_domain="example.com",
        competitors=[SiteStub(2, "comp-a.com", "Comp A")],
        queries=["pricing"],
        site_audits=[AuditStub(10, 1, "pricing", "2026-01-01T10:00:00+00:00")],
        competitor_audits=[AuditStub(11, 2, "pricing", "2026-01-02T10:00:00+00:00")],
    )

    assert payload["queries"][0]["site"]["answer_relevance"] is None
    assert payload["queries"][0]["competitor"]["answer_relevance"] is None
    assert payload["queries"][0]["winner"] == "no_data"
    assert payload["queries"][0]["delta"] is None


def test_build_query_answer_relevance_benchmark_returns_all_competitors_and_explainability():
    service = CompetitorBenchmarkService()

    class SiteStub:
        def __init__(self, site_id: int, domain: str, display_name: str):
            self.id = site_id
            self.domain = domain
            self.display_name = display_name

    class AuditStub:
        def __init__(self, audit_id: int, site_id: int, query: str, aeo: dict, created_at: str):
            self.id = audit_id
            self.site_id = site_id
            self.url = f"https://{site_id}.test/{audit_id}"
            self.created_at = datetime.fromisoformat(created_at)
            self.full_report = {
                "metadata": {"query": query},
                "aeo": {"answer_excerpt": f"answer-{audit_id}", **aeo},
                "analysis": {"answer_relevance": 64},
            }

    from datetime import datetime

    competitors = [SiteStub(2, "comp-a.com", "Comp A"), SiteStub(3, "comp-b.com", "Comp B")]
    site_audits = [
        AuditStub(1, 1, "best crm", {"answer_relevance": 80}, "2026-01-01T10:00:00+00:00")
    ]
    competitor_audits = [
        AuditStub(2, 2, "best crm", {"answer_relevance_score": 82}, "2026-01-02T10:00:00+00:00"),
        AuditStub(3, 3, "best crm", {"answer_relevance": 87}, "2026-01-03T10:00:00+00:00"),
    ]

    payload = service.build_query_answer_relevance_benchmark(
        site_id=1,
        site_domain="example.com",
        competitors=competitors,
        queries=["best crm"],
        site_audits=site_audits,
        competitor_audits=competitor_audits,
    )

    row = payload["queries"][0]
    assert len(row["competitors"]) == 2
    assert row["competitor"]["domain"] == "comp-b.com"
    assert row["competitor"]["answer_relevance_source"] == "aeo.answer_relevance"
    assert row["competitors"][1]["answer_relevance_source"] == "aeo.answer_relevance_score"
    assert row["competitors"][1]["answer_relevance_fallback_used"] is True
    assert row["site"]["answer_relevance_source"] == "aeo.answer_relevance"
    assert row["winner_reason"] == "score_delta"


def test_build_query_answer_relevance_benchmark_marks_missing_competitor_data_reason():
    service = CompetitorBenchmarkService()

    class SiteStub:
        def __init__(self, site_id: int, domain: str, display_name: str):
            self.id = site_id
            self.domain = domain
            self.display_name = display_name

    class AuditStub:
        def __init__(self, audit_id: int, site_id: int, query: str, aeo: dict, created_at: str):
            self.id = audit_id
            self.site_id = site_id
            self.url = f"https://{site_id}.test/{audit_id}"
            self.created_at = datetime.fromisoformat(created_at)
            self.full_report = {"metadata": {"query": query}, "aeo": aeo}

    from datetime import datetime

    payload = service.build_query_answer_relevance_benchmark(
        site_id=1,
        site_domain="example.com",
        competitors=[SiteStub(2, "comp-a.com", "Comp A")],
        queries=["pricing"],
        site_audits=[
            AuditStub(1, 1, "pricing", {"answer_relevance": 91}, "2026-01-01T10:00:00+00:00")
        ],
        competitor_audits=[
            AuditStub(2, 2, "pricing", {"answer_excerpt": "none"}, "2026-01-02T10:00:00+00:00")
        ],
    )

    row = payload["queries"][0]
    assert row["winner"] == "site"
    assert row["winner_reason"] == "missing_competitor_data"
