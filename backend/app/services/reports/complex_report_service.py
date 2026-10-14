from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import models
from score_utils import extract_score


@dataclass(slots=True)
class AggregatedSiteReport:
    site_id: int
    start_date: datetime | None
    end_date: datetime | None
    audit_count: int
    seo_avg: float
    geo_avg: float
    aeo_avg: float
    overall_avg: float
    trend_direction: str

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "audit_count": self.audit_count,
            "scores": {
                "seo": round(self.seo_avg, 2),
                "geo": round(self.geo_avg, 2),
                "aeo": round(self.aeo_avg, 2),
                "overall": round(self.overall_avg, 2),
            },
            "trend_direction": self.trend_direction,
        }


def _extract_audit_score(audit: models.Audit, score_name: str) -> float:
    full_report = audit.full_report if isinstance(audit.full_report, dict) else {}
    scores = full_report.get("scores") if isinstance(full_report.get("scores"), dict) else {}
    if score_name in scores:
        try:
            return float(scores[score_name] or 0.0)
        except (TypeError, ValueError):
            return 0.0

    analysis = full_report.get("analysis") if isinstance(full_report.get("analysis"), dict) else {}
    return float(extract_score(analysis, f"{score_name}_score"))


def _normalize_comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _filter_audits_by_interval(
    audits: list[models.Audit],
    *,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[models.Audit]:
    if start_date is None and end_date is None:
        return audits

    normalized_from = _normalize_comparable_datetime(start_date) if start_date is not None else None
    normalized_to = _normalize_comparable_datetime(end_date) if end_date is not None else None

    filtered: list[models.Audit] = []
    for audit in audits:
        created_at = audit.created_at
        if created_at is None:
            continue
        normalized_created = _normalize_comparable_datetime(created_at)
        if normalized_from is not None and normalized_created < normalized_from:
            continue
        if normalized_to is not None and normalized_created > normalized_to:
            continue
        filtered.append(audit)
    return filtered


def build_monthly_performance_report(
    *,
    site_id: int,
    audits: list[models.Audit],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> AggregatedSiteReport:
    audits = _filter_audits_by_interval(audits, start_date=start_date, end_date=end_date)

    if not audits:
        return AggregatedSiteReport(
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
            audit_count=0,
            seo_avg=0.0,
            geo_avg=0.0,
            aeo_avg=0.0,
            overall_avg=0.0,
            trend_direction="stable",
        )

    ordered = sorted(audits, key=lambda audit: audit.created_at or datetime.min)
    seo_values = [_extract_audit_score(audit, "seo") for audit in ordered]
    geo_values = [_extract_audit_score(audit, "geo") for audit in ordered]
    aeo_values = [_extract_audit_score(audit, "aeo") for audit in ordered]

    count = float(len(ordered))
    seo_avg = sum(seo_values) / count
    geo_avg = sum(geo_values) / count
    aeo_avg = sum(aeo_values) / count
    overall_avg = (seo_avg + geo_avg + aeo_avg) / 3

    first_overall = (seo_values[0] + geo_values[0] + aeo_values[0]) / 3
    last_overall = (seo_values[-1] + geo_values[-1] + aeo_values[-1]) / 3
    delta = last_overall - first_overall
    if delta > 1.0:
        trend_direction = "up"
    elif delta < -1.0:
        trend_direction = "down"
    else:
        trend_direction = "stable"

    return AggregatedSiteReport(
        site_id=site_id,
        start_date=start_date,
        end_date=end_date,
        audit_count=len(ordered),
        seo_avg=seo_avg,
        geo_avg=geo_avg,
        aeo_avg=aeo_avg,
        overall_avg=overall_avg,
        trend_direction=trend_direction,
    )
