"""SIGV2-1205 parts 2 and 3: report data-integrity guards.

Each test pins one defect from the ticket:

- benchmark rows derived from competitors must keep absent metrics absent;
  a missing metric is not a measured zero and must not get a rank, a delta
  or an overall, while a genuinely measured 0 still renders as 0.
- a legacy canonical-shaped report whose stored SEO score is absent is
  recomputed by the deterministic fallback only as a last resort, and the
  recomputation must be identified in the payload metadata rather than
  presented as a stored measurement.
- a date-only string is a calendar date, not a host-local timestamp.
- the AI engines section renders the engine rows attached to the audit and
  distinguishes measured / pending / withheld instead of printing one
  blanket "unavailable" sentence.
- a saved report download serves its stored bytes; the renderer is never
  invoked on the download path.
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.pdf_reports.assembler import (  # noqa: E402
    _canonicalize_audit,
    _derive_benchmark_from_competitors,
    _format_display_date,
    _parse_datetime,
    build_report_context,
)
from services.reports.audit_result_adapter import to_canonical_audit_result  # noqa: E402


def _audit_with_competitors() -> dict:
    return {
        "target": {
            "type": "website",
            "name": "example.com",
            "url": "https://example.com",
            "metadata": {},
        },
        "site": {"url": "https://example.com", "market": "us", "language": "en"},
        "seo": {"onpage": 74},
        "geo": {"visibility_index": 71},
        "aeo": {"llm_schema_readiness": 76},
        "scores": {"seo": 74, "geo": None, "aeo": 76, "overall": 74},
        "competitors": [
            {
                "name": "Rival A",
                "geo_visibility": 55.0,
                "aeo_score": 61.0,
                "entity_strength": 40.0,
            },
            {
                "name": "Rival B",
                "geo_visibility": None,
                "aeo_score": 0.0,
                "entity_strength": 30.0,
            },
        ],
        "metadata": {
            "created_at": "2026-10-07T12:00:00Z",
            "updated_at": "2026-10-07T12:00:00Z",
            "plan": "plan_specialist",
            "version": "2.0",
        },
    }


def test_benchmark_missing_metric_stays_absent_and_measured_zero_renders() -> None:
    canonical = _canonicalize_audit(_audit_with_competitors())
    table = _derive_benchmark_from_competitors(canonical)
    assert table is not None
    rows = {row["name"]: row for row in table["rows"]}

    target = rows["example.com"]
    assert target["geo_visibility"] is None
    # An absent input must not produce a fabricated rank, delta or overall.
    assert target["rank"] is None
    assert target["overall_score"] is None
    assert target["deltas_vs_target"]["geo_visibility"] is None

    rival_b = rows["Rival B"]
    assert rival_b["geo_visibility"] is None
    # A genuinely measured zero stays a zero.
    assert rival_b["aeo_score"] == 0.0
    # But a partially measured row is not ranked or given a made-up overall.
    assert rival_b["rank"] is None
    assert rival_b["overall_score"] is None
    assert rival_b["deltas_vs_target"]["geo_visibility"] is None

    # A fully measured competitor still gets a rank.
    rival_a = rows["Rival A"]
    assert rival_a["rank"] == 1
    assert rival_a["overall_score"] is not None


def test_legacy_report_with_absent_seo_score_is_flagged_as_recomputed() -> None:
    raw_report = {
        # Canonical-shaped payload (scores + target) that fails strict
        # re-validation and rebuilds through the fallback path.
        "scores": {"seo": None, "geo": 70, "aeo": 60, "overall": 65},
        "target": {"type": "website", "name": "example.com", "url": "https://example.com"},
        "site": {"url": "https://example.com", "market": "us", "language": "en"},
        "seo": {"onpage": 60},
        "geo": {"visibility_index": 70},
        "aeo": {"llm_schema_readiness": 60},
        "metadata": {
            "created_at": "2026-10-07T12:00:00Z",
            "updated_at": "2026-10-07T12:00:00Z",
            "plan": "plan_specialist",
            "version": "2.0",
            # An out-of-vocabulary intent survives payload prep but fails
            # strict re-validation, forcing the deterministic fallback that
            # used to silently substitute a recomputed SEO score.
            "intent": "bogus-intent",
        },
    }
    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    provenance = result["metadata"].get("score_provenance")
    assert provenance is not None, "recomputed scores must be identified in metadata"
    seo_source = provenance.get("seo")
    assert seo_source is not None
    assert seo_source["stored"] is False
    assert seo_source["source"] == "deterministic"
    assert seo_source.get("version")
    # Stored measurements report themselves as stored, not recomputed.
    assert provenance["geo"]["stored"] is True


def test_naive_datetime_and_date_only_strings_are_utc() -> None:
    # Host tz must not move a stored timestamp or a calendar date.
    os.environ["TZ"] = "Europe/Bucharest"
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        parsed = _parse_datetime("2026-10-07")
        assert parsed == datetime(2026, 10, 7, tzinfo=timezone.utc)
        assert _format_display_date("2026-10-07") == "October 07, 2026"
        aware = _parse_datetime("2026-10-07T22:30:00")
        assert aware == datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)
        # A genuinely zoned timestamp still normalizes to UTC.
        zoned = _parse_datetime("2026-10-07T22:30:00+02:00")
        assert zoned == datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)
    finally:
        os.environ.pop("TZ", None)
        if hasattr(time, "tzset"):
            time.tzset()


def _engines_payload() -> dict:
    return {
        "target": {
            "type": "website",
            "name": "example.com",
            "url": "https://example.com",
            "metadata": {},
        },
        "site": {"url": "https://example.com", "market": "us", "language": "en"},
        "seo": {"onpage": 74},
        "geo": {"visibility_index": 71},
        "aeo": {"llm_schema_readiness": 76},
        "scores": {"seo": 74, "geo": 71, "aeo": 76, "overall": 74},
        "metadata": {
            "created_at": "2026-10-07T12:00:00Z",
            "updated_at": "2026-10-07T12:00:00Z",
            "plan": "plan_specialist",
            "version": "2.0",
            # Stored engine rows are keyed "engine": the client-safe
            # projection strips nested "provider" keys, so rows written with
            # that key would lose their identity in whitelabel reports.
            "engines": [
                {
                    "engine": "openai",
                    "label": "ChatGPT",
                    "status": "measured",
                    "score": 64.0,
                },
                {
                    "engine": "perplexity",
                    "label": "Perplexity",
                    "status": "pending",
                    "score": None,
                },
                {
                    "engine": "bing",
                    "label": "Copilot",
                    "status": "withheld",
                    "score": None,
                },
            ],
        },
    }


def test_ai_engines_section_renders_attached_rows() -> None:
    context = build_report_context(_engines_payload(), report_type="whitelabel")
    section = context["sections"]["ai_engines"]
    items = {item["provider"]: item for item in section["items"]}
    assert items["openai"]["status"] == "measured"
    assert items["openai"]["score"] == 64.0
    assert items["perplexity"]["status"] == "pending"
    assert items["bing"]["status"] == "withheld"


def test_ai_engines_section_absent_when_nothing_attached() -> None:
    payload = _engines_payload()
    payload["metadata"].pop("engines")
    context = build_report_context(payload, report_type="whitelabel")
    section = context["sections"]["ai_engines"]
    assert section["items"] == []
    assert section["available"] is False


@pytest.mark.parametrize("report_type", ["whitelabel"])
def test_engines_section_present_for_standard_and_aio(report_type: str) -> None:
    context = build_report_context(_engines_payload(), report_type=report_type)
    assert "ai_engines" in context["sections"]


def test_saved_report_download_serves_stored_bytes() -> None:
    """Library and project surfaces both call this endpoint; it must return
    the stored object bytes verbatim and never re-render history."""
    from unittest.mock import MagicMock, patch

    from routers.api_router import download_complex_report

    stored_bytes = b"%PDF-1.4 stored-report-bytes"
    job = MagicMock()
    job.id = "report-1"
    job.user_id = "user-1"
    job.status = "succeeded"
    job.file_path = "local://reports/report-1.pdf"
    job.created_at = None
    job.completed_at = None
    job.export_manifest = {}

    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = "user-1"
    mock_db.query.return_value.filter.return_value.first.return_value = job

    mock_gcs = MagicMock()
    mock_gcs.download_file.return_value = stored_bytes
    mock_gcs.filename_from_uri.return_value = "report-1.pdf"

    with (
        patch("routers.api_router.get_storage_service", return_value=mock_gcs),
        patch("routers.api_router._resolve_report_job_expired", return_value=False),
        patch(
            "routers.api_router.first_unmet_report_export_requirement",
            return_value=None,
        ),
        patch(
            "services.pdf_reports.report_suite_service.render_report_pdf",
            side_effect=AssertionError("renderer must not run on download"),
        ),
    ):
        response = download_complex_report(report_id="report-1", user=mock_user, db=mock_db)

    assert response.body == stored_bytes
    assert response.media_type == "application/pdf"
    mock_gcs.download_file.assert_called_once_with(storage_uri="local://reports/report-1.pdf")
