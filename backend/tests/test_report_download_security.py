"""SEC-06: Report download storage path authorization & file access hardening tests.

Tests verify:
- Path traversal attacks are blocked by _safe_local_path
- Raw filesystem paths outside storage root are rejected
- download_file and delete_file only operate within storage root
- download_complex_report endpoint authorization and error states
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure GCP bootstrap doesn't fail in test environments
os.environ.setdefault("SSM_ENABLED", "false")

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.s3_storage_service import S3StorageService


# ---------------------------------------------------------------------------
# _safe_local_path tests
# ---------------------------------------------------------------------------


class TestSafeLocalPath:
    def test_file_inside_storage_root_is_allowed(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        target = tmp_path / "reports" / "audit.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"pdf-content")

        result = service._safe_local_path(str(target))
        assert result is not None
        assert result == target.resolve()

    def test_path_traversal_dot_dot_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        # Create a file outside the storage root
        outside_file = tmp_path.parent / "secret.txt"
        outside_file.write_text("secret")
        traversal_path = str(tmp_path / ".." / "secret.txt")

        result = service._safe_local_path(traversal_path)
        assert result is None

        outside_file.unlink()

    def test_absolute_path_outside_root_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        result = service._safe_local_path("/etc/passwd")
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        result = service._safe_local_path(str(tmp_path / "does-not-exist.pdf"))
        assert result is None

    def test_directory_path_returns_none(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = service._safe_local_path(str(subdir))
        assert result is None

    def test_symlink_escaping_root_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        outside_file = tmp_path.parent / "outside-secret.txt"
        outside_file.write_text("secret-via-symlink")
        symlink = tmp_path / "sneaky-link.txt"
        symlink.symlink_to(outside_file)

        result = service._safe_local_path(str(symlink))
        assert result is None

        symlink.unlink()
        outside_file.unlink()


# ---------------------------------------------------------------------------
# download_file hardened path tests
# ---------------------------------------------------------------------------


class TestDownloadFileHardened:
    def test_download_local_uri_works(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        uri = service.upload_file(
            prefix="reports/",
            filename="report.pdf",
            data=b"pdf-data",
            content_type="application/pdf",
        )
        assert uri == "local://reports/report.pdf"
        assert service.download_file(storage_uri=uri) == b"pdf-data"

    def test_download_bare_path_inside_root_works(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        target = tmp_path / "reports" / "safe.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"safe-content")

        result = service.download_file(storage_uri=str(target))
        assert result == b"safe-content"

    def test_download_bare_path_outside_root_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        result = service.download_file(storage_uri="/etc/passwd")
        assert result is None

    def test_download_traversal_path_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        outside = tmp_path.parent / "secret-download.txt"
        outside.write_text("secret")

        result = service.download_file(storage_uri=str(tmp_path / ".." / "secret-download.txt"))
        assert result is None

        outside.unlink()

    def test_download_empty_uri_returns_none(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        assert service.download_file(storage_uri="") is None
        assert service.download_file(storage_uri="   ") is None


# ---------------------------------------------------------------------------
# delete_file hardened path tests
# ---------------------------------------------------------------------------


class TestDeleteFileHardened:
    def test_delete_local_uri_works(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        uri = service.upload_file(
            prefix="reports/",
            filename="to-delete.pdf",
            data=b"delete-me",
            content_type="application/pdf",
        )
        assert service.delete_file(storage_uri=uri) is True
        assert service.download_file(storage_uri=uri) is None

    def test_delete_bare_path_inside_root_works(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        target = tmp_path / "reports" / "deletable.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"to-delete")

        assert service.delete_file(storage_uri=str(target)) is True
        assert not target.exists()

    def test_delete_bare_path_outside_root_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        outside = tmp_path.parent / "protected-file.txt"
        outside.write_text("protected")

        assert service.delete_file(storage_uri=str(outside)) is False
        assert outside.exists()

        outside.unlink()

    def test_delete_traversal_path_is_blocked(self, tmp_path: Path) -> None:
        service = S3StorageService(bucket_name="", local_storage_root=tmp_path)
        outside = tmp_path.parent / "secret-delete.txt"
        outside.write_text("do-not-delete")

        assert service.delete_file(storage_uri=str(tmp_path / ".." / "secret-delete.txt")) is False
        assert outside.exists()

        outside.unlink()


# ---------------------------------------------------------------------------
# download_complex_report endpoint tests
# ---------------------------------------------------------------------------


class TestDownloadComplexReportEndpoint:
    """Tests for the download endpoint authorization and error states.

    These mock the DB and storage service to verify control flow.
    """

    def _make_report_job(self, **overrides):
        job = MagicMock()
        job.id = overrides.get("id", "report-123")
        job.user_id = overrides.get("user_id", "user-1")
        job.status = overrides.get("status", "succeeded")
        job.file_path = overrides.get("file_path", "local://reports/test.pdf")
        job.created_at = overrides.get("created_at", None)
        job.completed_at = overrides.get("completed_at", None)
        return job

    @pytest.fixture
    def mock_deps(self):
        """Set up common mocks for the download endpoint."""
        with (
            patch("routers.api_router.get_storage_service") as mock_gcs,
            patch("routers.api_router.get_db") as mock_get_db,
            patch("routers.api_router._resolve_report_job_expired") as mock_expired,
            patch("routers.api_router._mark_report_job_expired") as mock_mark,
        ):
            mock_expired.return_value = False
            yield {
                "gcs": mock_gcs,
                "get_db": mock_get_db,
                "expired": mock_expired,
                "mark": mock_mark,
            }

    def test_no_raw_path_fallback_when_storage_returns_none(self, tmp_path: Path) -> None:
        """Verify that when gcs_service.download_file returns None,
        the endpoint does NOT fall back to reading raw filesystem paths.
        Instead it marks the report as expired and returns 410."""
        from routers.api_router import download_complex_report

        job = self._make_report_job(
            file_path=str(tmp_path / "reports" / "sneaky.pdf"),
        )
        # Create the file on disk to prove the endpoint doesn't read it
        target = tmp_path / "reports" / "sneaky.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"should-not-be-served")

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_db.query.return_value.filter.return_value.first.return_value = job

        mock_gcs_service = MagicMock()
        mock_gcs_service.download_file.return_value = None

        with (
            patch("routers.api_router.get_storage_service", return_value=mock_gcs_service),
            patch("routers.api_router._resolve_report_job_expired", return_value=False),
            patch("routers.api_router._mark_report_job_expired") as mock_mark,
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                download_complex_report(
                    report_id="report-123",
                    user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 410
            mock_mark.assert_called_once()

    def test_missing_file_path_returns_404(self) -> None:
        from routers.api_router import download_complex_report

        job = self._make_report_job(file_path=None)
        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_db.query.return_value.filter.return_value.first.return_value = job

        with patch("routers.api_router._resolve_report_job_expired", return_value=False):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                download_complex_report(
                    report_id="report-123",
                    user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 404

    def test_wrong_user_returns_404(self) -> None:
        from routers.api_router import download_complex_report

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "wrong-user"
        mock_db.query.return_value.filter.return_value.first.return_value = None

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            download_complex_report(
                report_id="report-123",
                user=mock_user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 404

    def test_expired_report_returns_410(self) -> None:
        from routers.api_router import download_complex_report

        job = self._make_report_job(status="expired")
        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_db.query.return_value.filter.return_value.first.return_value = job

        with patch("routers.api_router._resolve_report_job_expired", return_value=False):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                download_complex_report(
                    report_id="report-123",
                    user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 410

    def test_not_ready_report_returns_409(self) -> None:
        from routers.api_router import download_complex_report

        job = self._make_report_job(status="processing")
        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_db.query.return_value.filter.return_value.first.return_value = job

        with patch("routers.api_router._resolve_report_job_expired", return_value=False):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                download_complex_report(
                    report_id="report-123",
                    user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 409
