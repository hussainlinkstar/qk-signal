from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    metrics: dict[str, Any]
    history: list[dict[str, Any]]
    fetched_from_api: bool


class PerformanceSnapshotService:
    def __init__(self, performance_service, *, lookback_days: int | None = None):
        self.performance_service = performance_service
        self.lookback_days = lookback_days or int(os.getenv("PERFORMANCE_HISTORY_DAYS", "30"))

    @staticmethod
    def normalize_url(url: str) -> str:
        parsed = urlsplit(url.strip())
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port

        if port and ((scheme == "http" and port != 80) or (scheme == "https" and port != 443)):
            netloc = f"{host}:{port}"
        else:
            netloc = host

        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"

        return urlunsplit((scheme, netloc, path, parsed.query, ""))

    def get_snapshot_for_date(
        self,
        db: Session,
        *,
        normalized_url: str,
        snapshot_date: date,
    ) -> models.PerformanceSnapshot | None:
        return (
            db.query(models.PerformanceSnapshot)
            .filter(
                models.PerformanceSnapshot.normalized_url == normalized_url,
                models.PerformanceSnapshot.snapshot_date == snapshot_date,
            )
            .one_or_none()
        )

    def upsert_snapshot(
        self,
        db: Session,
        *,
        normalized_url: str,
        snapshot_date: date,
        metrics_payload: dict[str, Any],
        source_status: str,
        error_message: str | None = None,
    ) -> models.PerformanceSnapshot:
        record = self.get_snapshot_for_date(
            db,
            normalized_url=normalized_url,
            snapshot_date=snapshot_date,
        )
        now = datetime.now(timezone.utc)
        if record is None:
            record = models.PerformanceSnapshot(
                normalized_url=normalized_url,
                snapshot_date=snapshot_date,
                metrics_payload=metrics_payload,
                source_status=source_status,
                error_message=error_message,
                fetched_at=now,
                updated_at=now,
            )
            db.add(record)
        else:
            record.metrics_payload = metrics_payload
            record.source_status = source_status
            record.error_message = error_message
            record.fetched_at = now
            record.updated_at = now

        db.commit()
        db.refresh(record)
        return record

    def get_latest_snapshot(
        self, db: Session, *, normalized_url: str
    ) -> models.PerformanceSnapshot | None:
        return (
            db.query(models.PerformanceSnapshot)
            .filter(models.PerformanceSnapshot.normalized_url == normalized_url)
            .order_by(models.PerformanceSnapshot.snapshot_date.desc())
            .first()
        )

    def get_history(self, db: Session, *, normalized_url: str) -> list[dict[str, Any]]:
        cutoff = date.today() - timedelta(days=max(1, self.lookback_days))
        rows = (
            db.query(models.PerformanceSnapshot)
            .filter(
                models.PerformanceSnapshot.normalized_url == normalized_url,
                models.PerformanceSnapshot.snapshot_date >= cutoff,
            )
            .order_by(models.PerformanceSnapshot.snapshot_date.asc())
            .all()
        )

        history: list[dict[str, Any]] = []
        for row in rows:
            metrics = row.metrics_payload if isinstance(row.metrics_payload, dict) else {}
            history.append(
                {
                    "date": row.snapshot_date.isoformat(),
                    "performance_score": metrics.get("performance_score"),
                    "status": row.source_status,
                }
            )
        return history

    async def get_or_fetch_snapshot(
        self, db: Session, *, url: str, include_seo: bool = False
    ) -> SnapshotResult:
        normalized_url = self.normalize_url(url)
        today = date.today()

        today_snapshot = self.get_snapshot_for_date(
            db,
            normalized_url=normalized_url,
            snapshot_date=today,
        )
        if today_snapshot is not None:
            metrics = (
                today_snapshot.metrics_payload
                if isinstance(today_snapshot.metrics_payload, dict)
                else {}
            )
            metrics = dict(metrics)
            metrics.setdefault("source", "db_cache")
            metrics["history"] = self.get_history(db, normalized_url=normalized_url)
            return SnapshotResult(
                metrics=metrics, history=metrics["history"], fetched_from_api=False
            )

        fresh_metrics = await self.performance_service.get_performance_metrics(
            url, include_seo=include_seo
        )
        source_status = "success" if fresh_metrics.get("status") == "success" else "error"
        error_message = fresh_metrics.get("message") if source_status == "error" else None
        self.upsert_snapshot(
            db,
            normalized_url=normalized_url,
            snapshot_date=today,
            metrics_payload=fresh_metrics,
            source_status=source_status,
            error_message=error_message,
        )

        latest = self.get_latest_snapshot(db, normalized_url=normalized_url)
        latest_metrics = (
            latest.metrics_payload
            if latest and isinstance(latest.metrics_payload, dict)
            else fresh_metrics
        )
        latest_metrics = dict(latest_metrics)
        latest_metrics.setdefault("source", "live")
        latest_metrics["history"] = self.get_history(db, normalized_url=normalized_url)
        return SnapshotResult(
            metrics=latest_metrics, history=latest_metrics["history"], fetched_from_api=True
        )


class PerformanceSyncWorker:
    def __init__(
        self,
        snapshot_service: PerformanceSnapshotService,
        *,
        max_retries: int | None = None,
        base_backoff_seconds: float | None = None,
        max_backoff_seconds: float | None = None,
        min_interval_seconds: float | None = None,
    ):
        self.snapshot_service = snapshot_service
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("PERFORMANCE_SYNC_MAX_RETRIES", "3"))
        )
        self.base_backoff_seconds = (
            base_backoff_seconds
            if base_backoff_seconds is not None
            else float(os.getenv("PERFORMANCE_SYNC_BASE_BACKOFF", "1.0"))
        )
        self.max_backoff_seconds = (
            max_backoff_seconds
            if max_backoff_seconds is not None
            else float(os.getenv("PERFORMANCE_SYNC_MAX_BACKOFF", "8.0"))
        )
        self.min_interval_seconds = (
            min_interval_seconds
            if min_interval_seconds is not None
            else float(os.getenv("PERFORMANCE_SYNC_MIN_INTERVAL", "0.5"))
        )
        self._last_request_ts = 0.0

    async def _pace_requests(self) -> None:
        elapsed = asyncio.get_running_loop().time() - self._last_request_ts
        if elapsed < self.min_interval_seconds:
            await asyncio.sleep(self.min_interval_seconds - elapsed)

    async def sync_url(self, db: Session, *, url: str) -> bool:
        for attempt in range(1, self.max_retries + 1):
            try:
                await self._pace_requests()
                result = await self.snapshot_service.get_or_fetch_snapshot(db, url=url)
                self._last_request_ts = asyncio.get_running_loop().time()
                metrics = result.metrics
                if (
                    metrics.get("status") == "error"
                    and "quota" in str(metrics.get("message", "")).lower()
                ):
                    logger.warning(
                        "PageSpeed quota reached for %s; skipping remaining retries.", url
                    )
                    return False
                return True
            except Exception as exc:
                if attempt >= self.max_retries:
                    logger.warning(
                        "Performance sync failed for %s after %s attempts: %s", url, attempt, exc
                    )
                    return False
                backoff = min(
                    self.max_backoff_seconds, self.base_backoff_seconds * (2 ** (attempt - 1))
                )
                await asyncio.sleep(backoff)
        return False

    async def run_once(self, db: Session, *, urls: list[str]) -> dict[str, int]:
        counters = {"attempted": 0, "synced": 0, "quota_limited": 0}
        for raw_url in urls:
            url = raw_url.strip()
            if not url:
                continue
            counters["attempted"] += 1
            synced = await self.sync_url(db, url=url)
            if synced:
                counters["synced"] += 1
            else:
                counters["quota_limited"] += 1
        return counters
