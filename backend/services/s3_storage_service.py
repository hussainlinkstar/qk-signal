"""S3-backed storage service (AWS-native, no GCP).

Uses boto3 with the EC2 instance role (no static credentials). Reads/writes
s3:// URIs and keeps the local:// + path fallbacks for development. Legacy gs://
URIs are resolved against the configured S3 bucket using the same object key, so
any historical reference still downloads from S3 after migration.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.config import settings

try:  # pragma: no cover - availability differs by runtime
    import boto3
    from botocore.config import Config as _BotoConfig
    from botocore.exceptions import ClientError
except Exception:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment]
    _BotoConfig = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_STORAGE_ROOT = BACKEND_DIR / "generated_storage"
_STORAGE_SERVICE: "S3StorageService | None" = None


def _s3_region() -> str:
    return (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-central-1").strip()


def _resolve_local_storage_root(local_storage_root: Path | None) -> Path:
    if local_storage_root is not None:
        root_candidate = local_storage_root
    else:
        configured_root = (settings.LOCAL_STORAGE_ROOT or "").strip()
        root_candidate = Path(configured_root) if configured_root else DEFAULT_LOCAL_STORAGE_ROOT
    expanded_root = root_candidate.expanduser()
    if expanded_root.is_absolute():
        return expanded_root.resolve()
    return (BACKEND_DIR / expanded_root).resolve()


def _normalize_prefix(prefix: str) -> str:
    cleaned = (prefix or "").strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def _normalize_object_path(raw_path: str) -> str:
    parts: list[str] = []
    for part in Path(raw_path).parts:
        if part in {"", ".", ".."}:
            continue
        parts.append(part)
    return "/".join(parts)


def _parse_storage_uri(storage_uri: str) -> tuple[str, str, str]:
    """Return (type, bucket, object_path). gs:// maps to s3 (same key) for transition."""
    normalized = (storage_uri or "").strip()
    if normalized.startswith("s3://"):
        bucket_name, _, object_path = normalized[5:].partition("/")
        return ("s3", bucket_name, _normalize_object_path(object_path))
    if normalized.startswith("gs://"):
        _bucket, _, object_path = normalized[5:].partition("/")
        return ("s3", "", _normalize_object_path(object_path))
    if normalized.startswith("local://"):
        return ("local", "", _normalize_object_path(normalized[8:]))
    return ("path", "", normalized)


class S3StorageService:
    def __init__(self, *, bucket_name: str, local_storage_root: Path | None = None) -> None:
        self.bucket_name = (bucket_name or "").strip()
        self.region = _s3_region()
        self.local_storage_root = _resolve_local_storage_root(local_storage_root)
        self._client = None

    @property
    def is_enabled(self) -> bool:
        return bool(self.bucket_name) and boto3 is not None

    def build_object_path(self, *, prefix: str, filename: str) -> str:
        safe_prefix = _normalize_prefix(prefix)
        safe_filename = _normalize_object_path(filename) or "asset"
        return f"{safe_prefix}{safe_filename}"

    def _local_path_from_object_path(self, object_path: str) -> Path:
        return self.local_storage_root / _normalize_object_path(object_path)

    def _upload_to_local(self, *, object_path: str, data: bytes) -> str:
        local_path = self._local_path_from_object_path(object_path)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(data)
        except PermissionError as exc:
            raise RuntimeError(
                f"Local storage root '{self.local_storage_root}' is not writable. "
                "Set LOCAL_STORAGE_ROOT to a writable shared directory."
            ) from exc
        return f"local://{object_path}"

    def _safe_local_path(self, raw_path: str) -> Path | None:
        try:
            resolved = Path(raw_path).resolve()
        except (ValueError, OSError):
            return None
        root = self.local_storage_root.resolve()
        if not str(resolved).startswith(str(root) + "/") and resolved != root:
            logger.warning(
                "Blocked file access outside storage root: path=%s root=%s", raw_path, root
            )
            return None
        return resolved if resolved.is_file() else None

    def _get_client(self):
        if not self.is_enabled:
            return None
        if self._client is None:
            cfg = _BotoConfig(signature_version="s3v4") if _BotoConfig else None
            self._client = boto3.client("s3", region_name=self.region, config=cfg)
        return self._client

    def upload_file(
        self,
        *,
        prefix: str,
        filename: str,
        data: bytes,
        content_type: str,
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        object_path = self.build_object_path(prefix=prefix, filename=filename)
        client = self._get_client()
        if client is None:
            return self._upload_to_local(object_path=object_path, data=data)
        try:
            extra: dict = {"ContentType": content_type}
            if cache_control:
                extra["CacheControl"] = cache_control
            if metadata:
                extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
            client.put_object(Bucket=self.bucket_name, Key=object_path, Body=data, **extra)
            return f"s3://{self.bucket_name}/{object_path}"
        except Exception:
            logger.exception(
                "S3 upload failed for object_path=%s. Falling back to local.", object_path
            )
            return self._upload_to_local(object_path=object_path, data=data)

    def download_file(self, *, storage_uri: str) -> bytes | None:
        uri_type, bucket_name, object_path = _parse_storage_uri(storage_uri)
        if uri_type == "s3":
            client = self._get_client()
            if client is None or not object_path:
                return None
            try:
                obj = client.get_object(Bucket=bucket_name or self.bucket_name, Key=object_path)
                return obj["Body"].read()
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                    return None
                logger.exception("S3 download failed for uri=%s", storage_uri)
                return None
            except Exception:
                logger.exception("S3 download failed for uri=%s", storage_uri)
                return None
        if uri_type == "local" and object_path:
            local_path = self._local_path_from_object_path(object_path)
            return local_path.read_bytes() if local_path.is_file() else None
        if uri_type == "path":
            safe_path = self._safe_local_path(storage_uri)
            return safe_path.read_bytes() if safe_path is not None else None
        return None

    def generate_signed_url(
        self, *, storage_uri: str, expiry_minutes: int | None = None
    ) -> str | None:
        uri_type, bucket_name, object_path = _parse_storage_uri(storage_uri)
        client = self._get_client()
        if uri_type != "s3" or not object_path or client is None:
            return None
        minutes = expiry_minutes or int(settings.STORAGE_SIGNED_URL_EXPIRY_MINUTES or 60)
        if minutes <= 0:
            minutes = 60
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name or self.bucket_name, "Key": object_path},
                ExpiresIn=minutes * 60,
            )
        except Exception:
            logger.exception("Failed to generate presigned URL for uri=%s", storage_uri)
            return None

    def delete_file(self, *, storage_uri: str) -> bool:
        uri_type, bucket_name, object_path = _parse_storage_uri(storage_uri)
        if uri_type == "s3" and object_path:
            client = self._get_client()
            if client is None:
                return False
            try:
                client.delete_object(Bucket=bucket_name or self.bucket_name, Key=object_path)
                return True
            except Exception:
                logger.exception("Failed deleting S3 object uri=%s", storage_uri)
                return False
        if uri_type == "local" and object_path:
            local_path = self._local_path_from_object_path(object_path)
            if not local_path.exists():
                return False
            try:
                local_path.unlink()
                return True
            except Exception:
                logger.exception("Failed deleting local object uri=%s", storage_uri)
                return False
        if uri_type == "path":
            safe_path = self._safe_local_path(storage_uri)
            if safe_path is not None:
                try:
                    safe_path.unlink()
                    return True
                except Exception:
                    logger.exception("Failed deleting local path=%s", storage_uri)
                    return False
        return False

    def list_files(self, *, prefix: str, older_than: datetime | None = None) -> list[str]:
        safe_prefix = _normalize_prefix(prefix)
        files: list[str] = []
        client = self._get_client()
        if client is not None:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=safe_prefix):
                for obj in page.get("Contents", []) or []:
                    if older_than and obj.get("LastModified"):
                        updated = obj["LastModified"]
                        if updated.tzinfo is None:
                            updated = updated.replace(tzinfo=timezone.utc)
                        if updated >= older_than:
                            continue
                    files.append(f"s3://{self.bucket_name}/{obj['Key']}")
            return files
        local_directory = self._local_path_from_object_path(safe_prefix)
        if not local_directory.is_dir():
            return files
        for file_path in local_directory.rglob("*"):
            if not file_path.is_file():
                continue
            if older_than:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                if mtime >= older_than:
                    continue
            files.append(f"local://{file_path.relative_to(self.local_storage_root).as_posix()}")
        return files

    def cleanup_expired(self, *, prefix: str, max_age_days: int) -> int:
        if max_age_days <= 0:
            return 0
        older_than = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        deleted = 0
        for storage_uri in self.list_files(prefix=prefix, older_than=older_than):
            if self.delete_file(storage_uri=storage_uri):
                deleted += 1
        return deleted

    def filename_from_uri(self, storage_uri: str) -> str:
        uri_type, _, object_path = _parse_storage_uri(storage_uri)
        if uri_type in {"s3", "local"} and object_path:
            return Path(object_path).name or "download.bin"
        return Path(storage_uri).name or "download.bin"

    def to_public_url(self, storage_uri: str) -> str | None:
        uri_type, bucket_name, object_path = _parse_storage_uri(storage_uri)
        if uri_type != "s3" or not object_path:
            return None
        safe_bucket = bucket_name or self.bucket_name
        encoded = quote(object_path, safe="/")
        return f"https://{safe_bucket}.s3.{self.region}.amazonaws.com/{encoded}"


def get_storage_service() -> S3StorageService:
    global _STORAGE_SERVICE
    bucket = (os.getenv("S3_BUCKET_NAME") or "").strip()
    if _STORAGE_SERVICE is None or _STORAGE_SERVICE.bucket_name != bucket:
        _STORAGE_SERVICE = S3StorageService(bucket_name=bucket)
    return _STORAGE_SERVICE


def resolve_report_retention_days(default: int = 30) -> int:
    raw_days: Any = settings.STORAGE_REPORT_RETENTION_DAYS
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        days = default
    return default if days <= 0 else days
