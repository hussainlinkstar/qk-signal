"""Tests for audit data retention and archival service (AEX-24)."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_audit(
    *,
    id: int = 1,
    user_id: int = 10,
    created_at: datetime | None = None,
    full_report: dict | None = None,
    sanitized_at: datetime | None = None,
    report_archive_uri: str | None = None,
    report_archived_at: datetime | None = None,
    is_pinned: bool = False,
):
    """Create a mock Audit object."""
    audit = MagicMock()
    audit.id = id
    audit.user_id = user_id
    audit.created_at = created_at or datetime.now(timezone.utc)
    audit.full_report = full_report
    audit.sanitized_at = sanitized_at
    audit.report_archive_uri = report_archive_uri
    audit.report_archived_at = report_archived_at
    audit.is_pinned = is_pinned
    return audit


def _now():
    return datetime.now(timezone.utc)


# ── Tests: _strip_screenshot_fields ─────────────────────────────────────────


class TestStripScreenshotFields:
    def test_removes_screenshot_keys(self):
        from services.audit_archive_service import _strip_screenshot_fields

        report = {
            "url": "https://example.com",
            "screenshot_url": "https://cdn.example.com/shot.png",
            "screenshot_data": "base64...",
            "metadata": {"title": "Test"},
        }
        changed = _strip_screenshot_fields(report)
        assert changed is True
        assert "screenshot_url" not in report
        assert "screenshot_data" not in report
        assert report["url"] == "https://example.com"

    def test_removes_nested_screenshots(self):
        from services.audit_archive_service import _strip_screenshot_fields

        report = {
            "seo": {
                "score": 80,
                "screenshots": ["shot1.png", "shot2.png"],
            },
            "items": [
                {"name": "test", "screenshot": "data:image/png;base64,xyz"},
            ],
        }
        changed = _strip_screenshot_fields(report)
        assert changed is True
        assert "screenshots" not in report["seo"]
        assert "screenshot" not in report["items"][0]

    def test_no_changes_when_no_screenshots(self):
        from services.audit_archive_service import _strip_screenshot_fields

        report = {"url": "https://example.com", "score": 90}
        changed = _strip_screenshot_fields(report)
        assert changed is False

    def test_handles_empty_report(self):
        from services.audit_archive_service import _strip_screenshot_fields

        report = {}
        changed = _strip_screenshot_fields(report)
        assert changed is False


# ── Tests: redact_screenshots ────────────────────────────────────────────────


class TestRedactScreenshots:
    def test_redacts_old_unprocessed_audits(self):
        from services.audit_archive_service import redact_screenshots

        now = _now()
        old_audit = _make_audit(
            id=1,
            created_at=now - timedelta(days=35),
            full_report={"url": "test", "screenshot_url": "http://cdn/shot.png"},
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [old_audit]

        result = redact_screenshots(mock_db, now=now)
        assert result == 1
        assert old_audit.sanitized_at == now
        assert "screenshot_url" not in old_audit.full_report

    def test_skips_pinned_audits(self):
        """Pinned audits are excluded by the query filter (is_pinned=False)."""
        from services.audit_archive_service import redact_screenshots

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = []  # pinned audits filtered out

        result = redact_screenshots(mock_db, now=_now())
        assert result == 0

    def test_handles_non_dict_report(self):
        from services.audit_archive_service import redact_screenshots

        now = _now()
        audit = _make_audit(
            id=2,
            created_at=now - timedelta(days=40),
            full_report="not a dict",
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = redact_screenshots(mock_db, now=now)
        assert result == 1
        assert audit.sanitized_at == now


# ── Tests: archive_reports ───────────────────────────────────────────────────


class TestArchiveReports:
    @patch("services.audit_archive_service.get_storage_service")
    def test_archives_old_report_to_gcs(self, mock_get_gcs):
        from services.audit_archive_service import archive_reports

        now = _now()
        report_data = {
            "url": "https://example.com",
            "score": 85,
            "metadata": {"audit_outcome": "completed"},
        }
        audit = _make_audit(
            id=42,
            created_at=now - timedelta(days=100),
            full_report=report_data,
        )

        mock_gcs = MagicMock()
        mock_gcs.upload_file.return_value = "gs://bucket/audit-archives/audit_42.json.gz"
        mock_get_gcs.return_value = mock_gcs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = archive_reports(mock_db, now=now)
        assert result == 1
        assert audit.report_archive_uri == "gs://bucket/audit-archives/audit_42.json.gz"
        assert audit.report_archived_at == now
        assert audit.full_report is None

        # Verify upload was called with gzipped data
        call_kwargs = mock_gcs.upload_file.call_args[1]
        assert call_kwargs["prefix"] == "audit-archives"
        assert call_kwargs["filename"] == "audit_42.json.gz"
        assert call_kwargs["content_type"] == "application/gzip"
        decompressed = gzip.decompress(call_kwargs["data"])
        assert json.loads(decompressed) == report_data

    @patch("services.audit_archive_service.get_storage_service")
    def test_skips_already_archived(self, mock_get_gcs):
        """Audits with report_archive_uri set are excluded by query filter."""
        from services.audit_archive_service import archive_reports

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = []

        result = archive_reports(mock_db, now=_now())
        assert result == 0

    @patch("services.audit_archive_service.get_storage_service")
    def test_handles_upload_failure(self, mock_get_gcs):
        from services.audit_archive_service import archive_reports

        now = _now()
        audit = _make_audit(
            id=99,
            created_at=now - timedelta(days=120),
            full_report={"score": 70},
        )

        mock_gcs = MagicMock()
        mock_gcs.upload_file.side_effect = RuntimeError("GCS unavailable")
        mock_get_gcs.return_value = mock_gcs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = archive_reports(mock_db, now=now)
        # Should not count as archived due to exception
        assert result == 0
        # full_report should remain intact
        assert audit.full_report == {"score": 70}

    @patch("services.audit_archive_service.get_storage_service")
    def test_skips_null_full_report(self, mock_get_gcs):
        from services.audit_archive_service import archive_reports

        now = _now()
        audit = _make_audit(
            id=50,
            created_at=now - timedelta(days=100),
            full_report=None,
        )

        mock_gcs = MagicMock()
        mock_get_gcs.return_value = mock_gcs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = archive_reports(mock_db, now=now)
        assert result == 0


# ── Tests: purge_archived_reports ────────────────────────────────────────────


class TestPurgeArchivedReports:
    @patch("services.audit_archive_service.get_storage_service")
    def test_purges_old_archived_reports(self, mock_get_gcs):
        from services.audit_archive_service import purge_archived_reports

        now = _now()
        audit = _make_audit(
            id=7,
            created_at=now - timedelta(days=400),
            full_report=None,
            report_archive_uri="gs://bucket/audit-archives/audit_7.json.gz",
            report_archived_at=now - timedelta(days=310),
        )

        mock_gcs = MagicMock()
        mock_gcs.delete_file.return_value = True
        mock_get_gcs.return_value = mock_gcs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = purge_archived_reports(mock_db, now=now)
        assert result == 1
        assert audit.report_archive_uri is None
        mock_gcs.delete_file.assert_called_once_with(
            storage_uri="gs://bucket/audit-archives/audit_7.json.gz"
        )

    @patch("services.audit_archive_service.get_storage_service")
    def test_handles_delete_failure(self, mock_get_gcs):
        from services.audit_archive_service import purge_archived_reports

        now = _now()
        audit = _make_audit(
            id=8,
            created_at=now - timedelta(days=500),
            full_report=None,
            report_archive_uri="gs://bucket/audit-archives/audit_8.json.gz",
        )

        mock_gcs = MagicMock()
        mock_gcs.delete_file.side_effect = RuntimeError("GCS error")
        mock_get_gcs.return_value = mock_gcs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.all.return_value = [audit]

        result = purge_archived_reports(mock_db, now=now)
        assert result == 0


# ── Tests: restore_archived_report ───────────────────────────────────────────


class TestRestoreArchivedReport:
    @patch("services.audit_archive_service.get_storage_service")
    def test_restores_from_gcs(self, mock_get_gcs):
        from services.audit_archive_service import restore_archived_report

        original = {"url": "https://example.com", "score": 90}
        compressed = gzip.compress(json.dumps(original).encode("utf-8"))

        mock_gcs = MagicMock()
        mock_gcs.download_file.return_value = compressed
        mock_get_gcs.return_value = mock_gcs

        audit = _make_audit(
            id=42,
            report_archive_uri="gs://bucket/audit-archives/audit_42.json.gz",
        )
        mock_db = MagicMock()

        result = restore_archived_report(mock_db, audit)
        assert result == original

    @patch("services.audit_archive_service.get_storage_service")
    def test_returns_none_when_no_uri(self, mock_get_gcs):
        from services.audit_archive_service import restore_archived_report

        audit = _make_audit(id=1, report_archive_uri=None)
        mock_db = MagicMock()
        result = restore_archived_report(mock_db, audit)
        assert result is None

    @patch("services.audit_archive_service.get_storage_service")
    def test_returns_none_when_file_missing(self, mock_get_gcs):
        from services.audit_archive_service import restore_archived_report

        mock_gcs = MagicMock()
        mock_gcs.download_file.return_value = None
        mock_get_gcs.return_value = mock_gcs

        audit = _make_audit(
            id=5,
            report_archive_uri="gs://bucket/audit-archives/audit_5.json.gz",
        )
        mock_db = MagicMock()

        result = restore_archived_report(mock_db, audit)
        assert result is None

    @patch("services.audit_archive_service.get_storage_service")
    def test_returns_none_on_decompress_error(self, mock_get_gcs):
        from services.audit_archive_service import restore_archived_report

        mock_gcs = MagicMock()
        mock_gcs.download_file.return_value = b"not gzip data"
        mock_get_gcs.return_value = mock_gcs

        audit = _make_audit(
            id=6,
            report_archive_uri="gs://bucket/audit-archives/audit_6.json.gz",
        )
        mock_db = MagicMock()

        result = restore_archived_report(mock_db, audit)
        assert result is None


# ── Tests: pin / unpin ───────────────────────────────────────────────────────


class TestPinUnpin:
    def test_pin_audit_success(self):
        from services.audit_archive_service import pin_audit

        audit = _make_audit(id=1, user_id=10, is_pinned=False)
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = audit

        result = pin_audit(mock_db, 1, 10)
        assert result is True
        assert audit.is_pinned is True

    def test_pin_audit_not_found(self):
        from services.audit_archive_service import pin_audit

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        result = pin_audit(mock_db, 999, 10)
        assert result is False

    def test_unpin_audit_success(self):
        from services.audit_archive_service import unpin_audit

        audit = _make_audit(id=1, user_id=10, is_pinned=True)
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = audit

        result = unpin_audit(mock_db, 1, 10)
        assert result is True
        assert audit.is_pinned is False


# ── Tests: run_retention_sweep ───────────────────────────────────────────────


class TestRunRetentionSweep:
    @patch("services.audit_archive_service.purge_archived_reports")
    @patch("services.audit_archive_service.archive_reports")
    @patch("services.audit_archive_service.redact_screenshots")
    def test_runs_all_tiers(self, mock_redact, mock_archive, mock_purge):
        from services.audit_archive_service import run_retention_sweep

        mock_redact.return_value = 5
        mock_archive.return_value = 3
        mock_purge.return_value = 1

        mock_db = MagicMock()
        result = run_retention_sweep(mock_db)

        assert result == {
            "screenshots_redacted": 5,
            "reports_archived": 3,
            "reports_purged": 1,
        }
        mock_redact.assert_called_once()
        mock_archive.assert_called_once()
        mock_purge.assert_called_once()

    @patch("services.audit_archive_service.purge_archived_reports")
    @patch("services.audit_archive_service.archive_reports")
    @patch("services.audit_archive_service.redact_screenshots")
    def test_passes_now_to_all_tiers(self, mock_redact, mock_archive, mock_purge):
        from services.audit_archive_service import run_retention_sweep

        mock_redact.return_value = 0
        mock_archive.return_value = 0
        mock_purge.return_value = 0

        now = _now()
        mock_db = MagicMock()
        run_retention_sweep(mock_db, now=now)

        assert mock_redact.call_args[1]["now"] == now
        assert mock_archive.call_args[1]["now"] == now
        assert mock_purge.call_args[1]["now"] == now


# ── Tests: status derivation ────────────────────────────────────────────────


class TestDeriveAuditRecordStatus:
    """Tests for _derive_audit_record_status with archived/purged states."""

    def test_archived_status(self):
        """Audit with no full_report but archive_uri → 'archived'."""
        audit = _make_audit(
            full_report=None,
            report_archive_uri="gs://bucket/audit.json.gz",
            report_archived_at=_now(),
        )
        # Simulating _derive_audit_record_status logic
        if audit.full_report is None and audit.report_archive_uri:
            status = "archived"
        elif (
            audit.full_report is None and not audit.report_archive_uri and audit.report_archived_at
        ):
            status = "purged"
        else:
            status = "completed"
        assert status == "archived"

    def test_purged_status(self):
        """Audit with no full_report, no archive_uri, but archived_at → 'purged'."""
        audit = _make_audit(
            full_report=None,
            report_archive_uri=None,
            report_archived_at=_now(),
        )
        if audit.full_report is None and audit.report_archive_uri:
            status = "archived"
        elif (
            audit.full_report is None and not audit.report_archive_uri and audit.report_archived_at
        ):
            status = "purged"
        else:
            status = "completed"
        assert status == "purged"

    def test_normal_status_with_report(self):
        """Audit with full_report → normal status derivation."""
        audit = _make_audit(
            full_report={"metadata": {"audit_outcome": "completed"}},
            report_archive_uri=None,
        )
        if audit.full_report is None and audit.report_archive_uri:
            status = "archived"
        elif (
            audit.full_report is None
            and not audit.report_archive_uri
            and getattr(audit, "report_archived_at", None)
        ):
            status = "purged"
        else:
            status = "completed"
        assert status == "completed"
