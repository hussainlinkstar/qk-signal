from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

LOG_LINE_PATTERN = re.compile(
    r"^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<timestamp>[^\]]+)\]\s+\"(?P<request>[^\"]*)\"\s+(?P<status>\d{3})\s+\S+\s+\"[^\"]*\"\s+\"(?P<user_agent>[^\"]*)\""
)

REQUEST_PATTERN = re.compile(r"^[A-Z]+\s+(?P<path>\S+)")

BOT_LOG_UPLOAD_MAX_BYTES = int(os.getenv("BOT_LOG_UPLOAD_MAX_BYTES", str(150 * 1024 * 1024)))
BOT_LOG_RDNS_TIMEOUT_SECONDS = float(os.getenv("BOT_LOG_RDNS_TIMEOUT_SECONDS", "1.2"))
BOT_LOG_RDNS_MAX_LOOKUPS = max(1, int(os.getenv("BOT_LOG_RDNS_MAX_LOOKUPS", "500")))
BOT_LOG_RDNS_THREADS = max(1, int(os.getenv("BOT_LOG_RDNS_THREADS", "4")))

BOT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "ai_bot_user_agents.json"

_RDNS_EXECUTOR = ThreadPoolExecutor(max_workers=BOT_LOG_RDNS_THREADS)


@dataclass(frozen=True)
class BotRegistryEntry:
    name: str
    ua_contains: tuple[str, ...]
    rdns_suffixes: tuple[str, ...]
    category: str = "unknown"


@dataclass(frozen=True)
class BotRegistry:
    schema_version: str
    entries: tuple[BotRegistryEntry, ...]


@dataclass
class BotLogUploadResult:
    upload_id: int
    status: str
    bytes_processed: int
    lines_processed: int
    bot_hits: int
    skipped_lines: int
    aggregate_rows: int
    summary_rows: int
    degraded: bool
    degraded_reasons: list[str]


def _parse_timestamp(raw_value: str) -> date | None:
    normalized = raw_value.strip()
    if not normalized:
        return None
    for format_string in ("%d/%b/%Y:%H:%M:%S %z", "%d/%b/%Y:%H:%M:%S"):
        try:
            return datetime.strptime(normalized, format_string).date()
        except ValueError:
            continue
    return None


def _status_class(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"


def _normalize_section(path_value: str) -> str:
    parsed = urlsplit(path_value)
    path = (parsed.path or "/").strip()
    if not path or path == "/":
        return "/"
    pieces = [piece for piece in path.split("/") if piece]
    if not pieces:
        return "/"
    return f"/{pieces[0].lower()}/"


def _build_line_stream(upload_file: UploadFile) -> io.TextIOBase:
    raw_stream: BinaryIO
    file_name = str(upload_file.filename or "").strip().lower()
    if file_name.endswith(".gz"):
        raw_stream = gzip.GzipFile(fileobj=upload_file.file, mode="rb")
    else:
        raw_stream = upload_file.file
    return io.TextIOWrapper(raw_stream, encoding="utf-8", errors="ignore", newline="")


def _resolve_reverse_hostname(ip_address: str) -> str | None:
    future = _RDNS_EXECUTOR.submit(socket.gethostbyaddr, ip_address)
    try:
        host, _, _ = future.result(timeout=BOT_LOG_RDNS_TIMEOUT_SECONDS)
        return str(host or "").strip().lower().rstrip(".") or None
    except (FutureTimeoutError, OSError):
        return None


def _resolve_forward_ips(hostname: str) -> tuple[str, ...]:
    future = _RDNS_EXECUTOR.submit(socket.gethostbyname_ex, hostname)
    try:
        _, _, ips = future.result(timeout=BOT_LOG_RDNS_TIMEOUT_SECONDS)
    except (FutureTimeoutError, OSError):
        return ()
    return tuple(str(ip).strip() for ip in ips if str(ip).strip())


@lru_cache(maxsize=2048)
def _verify_ip_against_suffixes(ip_address: str, suffixes: tuple[str, ...]) -> bool:
    if not suffixes:
        return True

    reverse_hostname = _resolve_reverse_hostname(ip_address)
    if not reverse_hostname:
        return False

    normalized_suffixes = tuple(
        suffix.strip().lower().lstrip(".") for suffix in suffixes if suffix.strip()
    )
    if not normalized_suffixes:
        return True

    if not any(
        reverse_hostname == suffix or reverse_hostname.endswith(f".{suffix}")
        for suffix in normalized_suffixes
    ):
        return False

    forward_ips = _resolve_forward_ips(reverse_hostname)
    return ip_address in forward_ips if forward_ips else False


def _parse_registry_entry(raw_entry: dict[str, object]) -> BotRegistryEntry | None:
    name = str(raw_entry.get("name") or "").strip()
    if not name:
        return None

    ua_contains_raw = raw_entry.get("ua_contains")
    if not isinstance(ua_contains_raw, list):
        return None

    ua_contains = tuple(
        str(value).strip().lower()
        for value in ua_contains_raw
        if isinstance(value, str) and value.strip()
    )
    if not ua_contains:
        return None

    rdns_raw = raw_entry.get("rdns_suffixes")
    rdns_suffixes: tuple[str, ...]
    if isinstance(rdns_raw, list):
        rdns_suffixes = tuple(
            str(value).strip().lower().lstrip(".")
            for value in rdns_raw
            if isinstance(value, str) and value.strip()
        )
    else:
        rdns_suffixes = ()

    return BotRegistryEntry(
        name=name,
        ua_contains=ua_contains,
        rdns_suffixes=rdns_suffixes,
        category=str(raw_entry.get("category") or "unknown").strip(),
    )


@lru_cache(maxsize=1)
def load_bot_registry() -> BotRegistry:
    try:
        payload = json.loads(BOT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load bot registry from %s: %s", BOT_REGISTRY_PATH, exc)
        payload = {}

    schema_version = str(payload.get("schema_version") or "1").strip() or "1"
    entries_raw = payload.get("bots") if isinstance(payload, dict) else []

    entries: list[BotRegistryEntry] = []
    if isinstance(entries_raw, list):
        for entry in entries_raw:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_registry_entry(entry)
            if parsed is not None:
                entries.append(parsed)

    return BotRegistry(schema_version=schema_version, entries=tuple(entries))


def _match_bot_entry(user_agent: str, registry: BotRegistry) -> BotRegistryEntry | None:
    normalized = user_agent.strip().lower()
    if not normalized:
        return None

    for entry in registry.entries:
        if any(token in normalized for token in entry.ua_contains):
            return entry
    return None


def _serialize_source(source: models.ProjectBotLogSource) -> dict[str, object]:
    return {
        "id": source.id,
        "source_type": source.source_type.value,
        "display_name": source.display_name,
        "config": source.config_json if isinstance(source.config_json, dict) else {},
        "is_active": bool(source.is_active),
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
        "last_status": source.last_status,
        "last_error": source.last_error,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def list_project_bot_log_sources(db: Session, *, project_id: int) -> list[dict[str, object]]:
    sources = (
        db.query(models.ProjectBotLogSource)
        .filter(models.ProjectBotLogSource.project_id == project_id)
        .order_by(models.ProjectBotLogSource.source_type.asc())
        .all()
    )
    return [_serialize_source(source) for source in sources]


def upsert_project_bot_log_source(
    db: Session,
    *,
    project_id: int,
    source_type: models.BotLogIngestionSourceType,
    display_name: str | None,
    config: dict[str, object],
    is_active: bool,
) -> dict[str, object]:
    source = (
        db.query(models.ProjectBotLogSource)
        .filter(
            models.ProjectBotLogSource.project_id == project_id,
            models.ProjectBotLogSource.source_type == source_type,
        )
        .first()
    )

    if source is None:
        source = models.ProjectBotLogSource(
            project_id=project_id, source_type=source_type, schema_version="1"
        )
        db.add(source)

    source.display_name = (display_name or "").strip() or None
    source.config_json = config or {}
    source.is_active = bool(is_active)
    source.last_status = "configured"
    source.last_error = None

    db.commit()
    db.refresh(source)
    return _serialize_source(source)


def rebuild_project_bot_daily_summaries(
    db: Session,
    *,
    project_id: int,
    start_date: date,
    end_date: date,
) -> int:
    if end_date < start_date:
        return 0

    db.query(models.ProjectBotLogDailySummary).filter(
        models.ProjectBotLogDailySummary.project_id == project_id,
        models.ProjectBotLogDailySummary.snapshot_date >= start_date,
        models.ProjectBotLogDailySummary.snapshot_date <= end_date,
    ).delete(synchronize_session=False)

    rows = (
        db.query(
            models.ProjectBotLogAggregate.snapshot_date.label("snapshot_date"),
            models.ProjectBotLogAggregate.source_type.label("source_type"),
            models.ProjectBotLogAggregate.bot_name.label("bot_name"),
            models.ProjectBotLogAggregate.section.label("section"),
            models.ProjectBotLogAggregate.status_class.label("status_class"),
            models.ProjectBotLogAggregate.is_verified.label("is_verified"),
            func.sum(models.ProjectBotLogAggregate.hits).label("hits"),
            func.sum(models.ProjectBotLogAggregate.distinct_ips).label("distinct_ips"),
        )
        .filter(
            models.ProjectBotLogAggregate.project_id == project_id,
            models.ProjectBotLogAggregate.snapshot_date >= start_date,
            models.ProjectBotLogAggregate.snapshot_date <= end_date,
        )
        .group_by(
            models.ProjectBotLogAggregate.snapshot_date,
            models.ProjectBotLogAggregate.source_type,
            models.ProjectBotLogAggregate.bot_name,
            models.ProjectBotLogAggregate.section,
            models.ProjectBotLogAggregate.status_class,
            models.ProjectBotLogAggregate.is_verified,
        )
        .all()
    )

    now = datetime.now(timezone.utc)
    inserted = 0
    for row in rows:
        db.add(
            models.ProjectBotLogDailySummary(
                project_id=project_id,
                source_type=row.source_type,
                snapshot_date=row.snapshot_date,
                bot_name=row.bot_name,
                section=row.section,
                status_class=row.status_class,
                is_verified=bool(row.is_verified),
                hits=int(row.hits or 0),
                distinct_ips=int(row.distinct_ips or 0),
                computed_at=now,
                schema_version="1",
            )
        )
        inserted += 1

    return inserted


def ingest_project_bot_log_upload(
    db: Session,
    *,
    project_id: int,
    upload_file: UploadFile,
    source_type: models.BotLogIngestionSourceType = models.BotLogIngestionSourceType.MANUAL_UPLOAD,
    source_id: int | None = None,
) -> BotLogUploadResult:
    file_name = str(upload_file.filename or "server.log").strip() or "server.log"
    upload = models.ProjectBotLogUpload(
        project_id=project_id,
        source_id=source_id,
        source_type=source_type,
        filename=file_name,
        status="processing",
        schema_version="1",
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)

    registry = load_bot_registry()
    aggregate_buckets: dict[tuple[date, str, str, str, bool], dict[str, object]] = {}

    lines_processed = 0
    skipped_lines = 0
    bot_hits = 0
    bytes_processed = 0
    rdns_lookup_count = 0
    rdns_cache: dict[tuple[str, tuple[str, ...]], bool] = {}
    degraded_reasons: list[str] = []

    min_date: date | None = None
    max_date: date | None = None

    try:
        upload_file.file.seek(0)
        stream = _build_line_stream(upload_file)
        with stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line:
                    continue

                lines_processed += 1
                bytes_processed += len(raw_line.encode("utf-8", errors="ignore"))

                if bytes_processed > BOT_LOG_UPLOAD_MAX_BYTES:
                    raise ValueError(
                        f"Upload exceeds the {BOT_LOG_UPLOAD_MAX_BYTES // (1024 * 1024)}MB processing limit."
                    )

                match = LOG_LINE_PATTERN.match(line)
                if match is None:
                    skipped_lines += 1
                    continue

                request_field = str(match.group("request") or "")
                request_match = REQUEST_PATTERN.match(request_field)
                if request_match is None:
                    skipped_lines += 1
                    continue

                raw_status = str(match.group("status") or "").strip()
                try:
                    status_code = int(raw_status)
                except ValueError:
                    skipped_lines += 1
                    continue

                snapshot_date = _parse_timestamp(str(match.group("timestamp") or ""))
                if snapshot_date is None:
                    skipped_lines += 1
                    continue

                user_agent = str(match.group("user_agent") or "").strip()
                matched_bot = _match_bot_entry(user_agent, registry)
                if matched_bot is None:
                    continue

                bot_hits += 1
                min_date = snapshot_date if min_date is None else min(min_date, snapshot_date)
                max_date = snapshot_date if max_date is None else max(max_date, snapshot_date)

                section = _normalize_section(str(request_match.group("path") or "/"))
                verification_key = (str(match.group("ip") or "").strip(), matched_bot.rdns_suffixes)
                is_verified = True
                if matched_bot.rdns_suffixes and verification_key[0]:
                    if verification_key in rdns_cache:
                        is_verified = rdns_cache[verification_key]
                    else:
                        if rdns_lookup_count >= BOT_LOG_RDNS_MAX_LOOKUPS:
                            is_verified = True
                            if "rDNS lookup budget exceeded" not in degraded_reasons:
                                degraded_reasons.append("rDNS lookup budget exceeded")
                        else:
                            is_verified = _verify_ip_against_suffixes(
                                verification_key[0], verification_key[1]
                            )
                            rdns_lookup_count += 1
                        rdns_cache[verification_key] = is_verified

                bucket_key = (
                    snapshot_date,
                    matched_bot.name,
                    section,
                    _status_class(status_code),
                    is_verified,
                )
                bucket = aggregate_buckets.setdefault(bucket_key, {"hits": 0, "ips": set()})
                bucket["hits"] = int(bucket["hits"]) + 1
                ip_bucket = bucket.get("ips")
                if isinstance(ip_bucket, set):
                    ip_bucket.add(verification_key[0])

        aggregate_rows = 0
        for key, bucket in aggregate_buckets.items():
            snapshot_date, bot_name, section, status_class, is_verified = key
            ips = bucket.get("ips")
            distinct_ips = len(ips) if isinstance(ips, set) else 0
            db.add(
                models.ProjectBotLogAggregate(
                    project_id=project_id,
                    upload_id=upload.id,
                    source_type=source_type,
                    snapshot_date=snapshot_date,
                    bot_name=bot_name,
                    section=section,
                    status_class=status_class,
                    is_verified=is_verified,
                    hits=int(bucket.get("hits", 0)),
                    distinct_ips=distinct_ips,
                    metadata_json={"registry_version": registry.schema_version},
                    schema_version="1",
                )
            )
            aggregate_rows += 1

        if aggregate_rows > 0:
            db.flush()

        summary_rows = 0
        if min_date and max_date:
            summary_rows = rebuild_project_bot_daily_summaries(
                db,
                project_id=project_id,
                start_date=min_date,
                end_date=max_date,
            )

        upload.status = "processed"
        upload.bytes_processed = bytes_processed
        upload.lines_processed = lines_processed
        upload.bot_hits = bot_hits
        upload.skipped_lines = skipped_lines
        upload.completed_at = datetime.now(timezone.utc)
        upload.metadata_json = {
            "registry_version": registry.schema_version,
            "rdns_lookups": rdns_lookup_count,
            "degraded_reasons": degraded_reasons,
            "aggregate_rows": aggregate_rows,
        }
        if source_id is not None:
            source = (
                db.query(models.ProjectBotLogSource)
                .filter(models.ProjectBotLogSource.id == source_id)
                .first()
            )
            if source is not None:
                source.last_sync_at = upload.completed_at
                source.last_status = "processed"
                source.last_error = None

        db.commit()
        db.refresh(upload)

        return BotLogUploadResult(
            upload_id=upload.id,
            status=upload.status,
            bytes_processed=bytes_processed,
            lines_processed=lines_processed,
            bot_hits=bot_hits,
            skipped_lines=skipped_lines,
            aggregate_rows=aggregate_rows,
            summary_rows=summary_rows,
            degraded=bool(degraded_reasons),
            degraded_reasons=degraded_reasons,
        )
    except Exception as exc:
        logger.exception("Bot log upload failed for project=%s upload=%s", project_id, upload.id)
        db.rollback()

        failed_upload = (
            db.query(models.ProjectBotLogUpload)
            .filter(models.ProjectBotLogUpload.id == upload.id)
            .first()
        )
        if failed_upload is not None:
            failed_upload.status = "failed"
            failed_upload.error_message = str(exc)
            failed_upload.bytes_processed = bytes_processed
            failed_upload.lines_processed = lines_processed
            failed_upload.bot_hits = bot_hits
            failed_upload.skipped_lines = skipped_lines
            failed_upload.completed_at = datetime.now(timezone.utc)
            failed_upload.metadata_json = {
                "registry_version": registry.schema_version,
                "rdns_lookups": rdns_lookup_count,
            }

            if source_id is not None:
                source = (
                    db.query(models.ProjectBotLogSource)
                    .filter(models.ProjectBotLogSource.id == source_id)
                    .first()
                )
                if source is not None:
                    source.last_sync_at = failed_upload.completed_at
                    source.last_status = "failed"
                    source.last_error = str(exc)
            db.commit()

        raise


def build_project_bot_log_summary(
    db: Session,
    *,
    project_id: int,
    days: int = 30,
) -> dict[str, object]:
    safe_days = max(1, min(int(days), 365))
    today = date.today()
    start_date = today - timedelta(days=safe_days - 1)

    rows = (
        db.query(models.ProjectBotLogDailySummary)
        .filter(
            models.ProjectBotLogDailySummary.project_id == project_id,
            models.ProjectBotLogDailySummary.snapshot_date >= start_date,
            models.ProjectBotLogDailySummary.snapshot_date <= today,
        )
        .order_by(models.ProjectBotLogDailySummary.snapshot_date.asc())
        .all()
    )

    sources = list_project_bot_log_sources(db, project_id=project_id)
    latest_upload = (
        db.query(models.ProjectBotLogUpload)
        .filter(models.ProjectBotLogUpload.project_id == project_id)
        .order_by(
            models.ProjectBotLogUpload.uploaded_at.desc(), models.ProjectBotLogUpload.id.desc()
        )
        .first()
    )

    if not rows:
        degraded_reasons: list[str] = []
        if latest_upload is None:
            degraded_reasons.append("No bot log uploads yet")
        elif latest_upload.status == "failed":
            degraded_reasons.append("Latest bot log upload failed")

        return {
            "project_id": project_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": safe_days,
            "no_data": True,
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "totals": {
                "total_hits": 0,
                "verified_hits": 0,
                "spoofed_hits": 0,
                "error_4xx_hits": 0,
                "error_5xx_hits": 0,
            },
            "time_series": [],
            "bot_breakdown": [],
            "section_heatmap": [],
            "spoofing_radar": [],
            "ingestion_sources": sources,
            "latest_upload": _serialize_upload(latest_upload),
        }

    timeline: dict[str, dict[str, int | str]] = {}
    bot_breakdown: dict[str, dict[str, int | str]] = {}
    section_hits: dict[str, int] = {}
    spoofing_hits: dict[str, int] = {}

    total_hits = 0
    verified_hits = 0
    spoofed_hits = 0
    error_4xx_hits = 0
    error_5xx_hits = 0
    latest_snapshot_date: date | None = None

    for row in rows:
        latest_snapshot_date = (
            row.snapshot_date
            if latest_snapshot_date is None
            else max(latest_snapshot_date, row.snapshot_date)
        )
        date_key = row.snapshot_date.isoformat()
        timeline_row = timeline.setdefault(
            date_key,
            {
                "date": date_key,
                "hits": 0,
                "verified_hits": 0,
                "spoofed_hits": 0,
            },
        )

        hits = int(row.hits or 0)
        total_hits += hits
        timeline_row["hits"] = int(timeline_row["hits"]) + hits

        if row.is_verified:
            verified_hits += hits
            timeline_row["verified_hits"] = int(timeline_row["verified_hits"]) + hits
        else:
            spoofed_hits += hits
            timeline_row["spoofed_hits"] = int(timeline_row["spoofed_hits"]) + hits
            spoofing_hits[row.bot_name] = spoofing_hits.get(row.bot_name, 0) + hits

        if row.status_class == "4xx":
            error_4xx_hits += hits
        elif row.status_class == "5xx":
            error_5xx_hits += hits

        section_hits[row.section] = section_hits.get(row.section, 0) + hits

        bot_row = bot_breakdown.setdefault(
            row.bot_name,
            {
                "bot_name": row.bot_name,
                "hits": 0,
                "verified_hits": 0,
                "spoofed_hits": 0,
                "error_4xx_hits": 0,
                "error_5xx_hits": 0,
            },
        )
        bot_row["hits"] = int(bot_row["hits"]) + hits
        if row.is_verified:
            bot_row["verified_hits"] = int(bot_row["verified_hits"]) + hits
        else:
            bot_row["spoofed_hits"] = int(bot_row["spoofed_hits"]) + hits
        if row.status_class == "4xx":
            bot_row["error_4xx_hits"] = int(bot_row["error_4xx_hits"]) + hits
        elif row.status_class == "5xx":
            bot_row["error_5xx_hits"] = int(bot_row["error_5xx_hits"]) + hits

    degraded_reasons = []
    if latest_upload and latest_upload.status == "failed":
        degraded_reasons.append("Latest bot log upload failed")
    if latest_snapshot_date and latest_snapshot_date < (today - timedelta(days=7)):
        degraded_reasons.append("Bot log data is older than seven days")

    return {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": safe_days,
        "latest_snapshot_date": latest_snapshot_date.isoformat() if latest_snapshot_date else None,
        "no_data": False,
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "totals": {
            "total_hits": total_hits,
            "verified_hits": verified_hits,
            "spoofed_hits": spoofed_hits,
            "error_4xx_hits": error_4xx_hits,
            "error_5xx_hits": error_5xx_hits,
        },
        "time_series": sorted(timeline.values(), key=lambda row: str(row["date"])),
        "bot_breakdown": sorted(
            bot_breakdown.values(), key=lambda row: int(row["hits"]), reverse=True
        ),
        "section_heatmap": [
            {"section": section, "hits": hits}
            for section, hits in sorted(
                section_hits.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "spoofing_radar": [
            {"bot_name": bot_name, "spoofed_hits": hits}
            for bot_name, hits in sorted(
                spoofing_hits.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "ingestion_sources": sources,
        "latest_upload": _serialize_upload(latest_upload),
    }


def _serialize_upload(upload: models.ProjectBotLogUpload | None) -> dict[str, object] | None:
    if upload is None:
        return None
    return {
        "id": upload.id,
        "source_type": upload.source_type.value,
        "filename": upload.filename,
        "status": upload.status,
        "bytes_processed": int(upload.bytes_processed or 0),
        "lines_processed": int(upload.lines_processed or 0),
        "bot_hits": int(upload.bot_hits or 0),
        "skipped_lines": int(upload.skipped_lines or 0),
        "uploaded_at": upload.uploaded_at.isoformat() if upload.uploaded_at else None,
        "completed_at": upload.completed_at.isoformat() if upload.completed_at else None,
        "error_message": upload.error_message,
        "metadata": upload.metadata_json if isinstance(upload.metadata_json, dict) else {},
    }


def refresh_recent_bot_log_daily_summaries(
    db: Session,
    *,
    lookback_days: int = 30,
) -> dict[str, object]:
    safe_days = max(1, min(int(lookback_days), 180))
    today = date.today()
    start_date = today - timedelta(days=safe_days - 1)

    project_id_rows = (
        db.query(models.ProjectBotLogAggregate.project_id)
        .filter(models.ProjectBotLogAggregate.snapshot_date >= start_date)
        .distinct()
        .all()
    )
    project_ids = [int(row[0]) for row in project_id_rows if row and row[0] is not None]

    refreshed = 0
    failed = 0
    details: list[dict[str, object]] = []

    for project_id in project_ids:
        try:
            rows = rebuild_project_bot_daily_summaries(
                db,
                project_id=project_id,
                start_date=start_date,
                end_date=today,
            )
            refreshed += 1
            details.append(
                {
                    "project_id": project_id,
                    "status": "ok",
                    "summary_rows": rows,
                }
            )
        except Exception as exc:
            failed += 1
            details.append(
                {
                    "project_id": project_id,
                    "status": "error",
                    "error": str(exc),
                }
            )
            logger.exception("Bot log daily summary refresh failed for project=%s", project_id)

    if refreshed or failed:
        db.commit()

    return {
        "projects_considered": len(project_ids),
        "projects_refreshed": refreshed,
        "projects_failed": failed,
        "details": details,
    }
