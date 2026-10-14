from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

import models
from app.services.aio_view import derive_aio
from services.notification_router import NotificationRouter
from services.project_audit_scope import own_project_audit_clause
from services.workflow_engine import evaluate_workflows_for_event

PROJECT_COMPETITOR_REQUEST_PREFIX = "competitive-benchmark"
MAX_PROJECT_COMPETITORS = 5
COMPETITIVE_GAP_THRESHOLD = 5.0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _round_score(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _mean_scores(values: list[float | None]) -> float | None:
    filtered = [float(value) for value in values if value is not None]
    if not filtered:
        return None
    return round(mean(filtered), 2)


def normalize_competitor_target(raw_value: str) -> tuple[str, str, str]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        raise ValueError("Competitor URL is required.")

    normalized_url = (
        candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
    )
    parsed = urlparse(normalized_url)
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Competitor URL must include a valid domain.")

    normalized_domain = hostname[4:] if hostname.startswith("www.") else hostname
    path = (parsed.path or "").rstrip("/")
    normalized_target_url = (
        f"https://{normalized_domain}{path}" if path else f"https://{normalized_domain}"
    )
    return normalized_target_url, normalized_domain, normalized_domain


def sync_project_competitors_json(project: models.Project) -> None:
    ordered = sorted(
        project.competitors,
        key=lambda competitor: (competitor.created_at or datetime.min, competitor.id),
    )
    project.competitors_json = [competitor.target_url for competitor in ordered]


def replace_project_competitors_from_urls(
    db: Session,
    *,
    project: models.Project,
    competitors: list[str],
) -> list[models.ProjectCompetitor]:
    cleaned = [str(item).strip() for item in competitors if str(item).strip()]
    if len(cleaned) > MAX_PROJECT_COMPETITORS:
        raise ValueError(
            f"Competitive Intelligence supports up to {MAX_PROJECT_COMPETITORS} competitors per project."
        )

    project_domain = (
        normalize_competitor_target(project.domain_url or "")[1] if project.domain_url else None
    )
    seen_domains: set[str] = set()
    desired_by_domain: dict[str, tuple[str, str]] = {}
    for candidate in cleaned:
        target_url, normalized_domain, display_name = normalize_competitor_target(candidate)
        if project_domain and normalized_domain == project_domain:
            raise ValueError("The client domain cannot be added as a competitor.")
        if normalized_domain in seen_domains:
            continue
        seen_domains.add(normalized_domain)
        desired_by_domain[normalized_domain] = (target_url, display_name)

    existing_by_domain = {
        competitor.normalized_domain: competitor for competitor in project.competitors
    }
    for normalized_domain, (target_url, display_name) in desired_by_domain.items():
        row = existing_by_domain.get(normalized_domain)
        if row is None:
            db.add(
                models.ProjectCompetitor(
                    project_id=project.id,
                    target_url=target_url,
                    normalized_domain=normalized_domain,
                    display_name=display_name,
                    auto_audit_enabled=True,
                )
            )
        else:
            row.target_url = target_url
            row.display_name = display_name

    for normalized_domain, row in list(existing_by_domain.items()):
        if normalized_domain not in desired_by_domain:
            db.delete(row)

    db.flush()
    db.refresh(project)
    sync_project_competitors_json(project)
    return sorted(project.competitors, key=lambda competitor: competitor.created_at or datetime.min)


def add_project_competitor(
    db: Session,
    *,
    project: models.Project,
    target_url: str,
    display_name: str | None = None,
) -> models.ProjectCompetitor:
    if len(project.competitors) >= MAX_PROJECT_COMPETITORS:
        raise ValueError(
            f"Competitive Intelligence supports up to {MAX_PROJECT_COMPETITORS} competitors per project."
        )

    normalized_target_url, normalized_domain, fallback_name = normalize_competitor_target(
        target_url
    )
    project_domain = (
        normalize_competitor_target(project.domain_url or "")[1] if project.domain_url else None
    )
    if project_domain and normalized_domain == project_domain:
        raise ValueError("The client domain cannot be added as a competitor.")

    existing = (
        db.query(models.ProjectCompetitor)
        .filter(
            models.ProjectCompetitor.project_id == project.id,
            models.ProjectCompetitor.normalized_domain == normalized_domain,
        )
        .first()
    )
    if existing is not None:
        raise ValueError("Competitor already exists for this project.")

    competitor = models.ProjectCompetitor(
        project_id=project.id,
        target_url=normalized_target_url,
        normalized_domain=normalized_domain,
        display_name=(display_name or "").strip() or fallback_name,
        auto_audit_enabled=True,
    )
    db.add(competitor)
    db.flush()
    db.refresh(project)
    sync_project_competitors_json(project)
    return competitor


def delete_project_competitor(
    db: Session,
    *,
    project: models.Project,
    competitor_id: int,
) -> None:
    competitor = (
        db.query(models.ProjectCompetitor)
        .filter(
            models.ProjectCompetitor.project_id == project.id,
            models.ProjectCompetitor.id == competitor_id,
        )
        .first()
    )
    if competitor is None:
        raise ValueError("Competitor not found for this project.")

    db.delete(competitor)
    db.flush()
    db.refresh(project)
    sync_project_competitors_json(project)


def build_project_competitor_request_id(
    *, source_audit_id: int, competitor_id: int, job_id: str
) -> str:
    return f"{PROJECT_COMPETITOR_REQUEST_PREFIX}:{source_audit_id}:{competitor_id}:{job_id}"


def parse_project_competitor_request_id(request_id: str | None) -> tuple[int, int] | None:
    if not request_id or not request_id.startswith(f"{PROJECT_COMPETITOR_REQUEST_PREFIX}:"):
        return None
    parts = request_id.split(":")
    if len(parts) < 4:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def ensure_project_competitor_snapshot_pending(
    db: Session,
    *,
    project_id: int,
    competitor_id: int,
    source_audit_id: int,
    metadata: dict[str, Any] | None = None,
) -> models.ProjectCompetitorSnapshot:
    snapshot = (
        db.query(models.ProjectCompetitorSnapshot)
        .filter(
            models.ProjectCompetitorSnapshot.project_id == project_id,
            models.ProjectCompetitorSnapshot.competitor_id == competitor_id,
            models.ProjectCompetitorSnapshot.source_audit_id == source_audit_id,
        )
        .first()
    )
    if snapshot is None:
        snapshot = models.ProjectCompetitorSnapshot(
            project_id=project_id,
            competitor_id=competitor_id,
            source_audit_id=source_audit_id,
            status="pending",
            metadata_json=metadata or {},
        )
        db.add(snapshot)
    else:
        snapshot.status = "pending"
        snapshot.failure_reason = None
        if metadata:
            current_metadata = (
                snapshot.metadata_json if isinstance(snapshot.metadata_json, dict) else {}
            )
            snapshot.metadata_json = {**current_metadata, **metadata}
    db.flush()
    return snapshot


def mark_project_competitor_snapshot_succeeded(
    db: Session,
    *,
    project_id: int,
    competitor_id: int,
    source_audit_id: int,
    competitor_audit: models.Audit,
) -> models.ProjectCompetitorSnapshot:
    snapshot = ensure_project_competitor_snapshot_pending(
        db,
        project_id=project_id,
        competitor_id=competitor_id,
        source_audit_id=source_audit_id,
    )
    snapshot.status = "succeeded"
    snapshot.failure_reason = None
    snapshot.competitor_audit_id = competitor_audit.id
    snapshot.geo_score = _round_score(competitor_audit.geo_score)
    snapshot.seo_score = _round_score(competitor_audit.seo_score)
    snapshot.aeo_score = _round_score(competitor_audit.aeo_score)
    snapshot.captured_at = _as_utc(competitor_audit.created_at) or datetime.now(timezone.utc)
    db.add(snapshot)
    db.flush()
    return snapshot


def mark_project_competitor_snapshot_failed(
    db: Session,
    *,
    project_id: int,
    competitor_id: int,
    source_audit_id: int,
    reason: str,
) -> models.ProjectCompetitorSnapshot:
    snapshot = ensure_project_competitor_snapshot_pending(
        db,
        project_id=project_id,
        competitor_id=competitor_id,
        source_audit_id=source_audit_id,
    )
    snapshot.status = "failed"
    snapshot.failure_reason = reason.strip() or "Benchmark failed."
    db.add(snapshot)
    db.flush()
    return snapshot


def _latest_snapshot_maps(
    db: Session,
    *,
    project_id: int,
) -> tuple[
    dict[int, models.ProjectCompetitorSnapshot], dict[int, models.ProjectCompetitorSnapshot]
]:
    snapshots = (
        db.query(models.ProjectCompetitorSnapshot)
        .filter(models.ProjectCompetitorSnapshot.project_id == project_id)
        .order_by(
            models.ProjectCompetitorSnapshot.created_at.desc(),
            models.ProjectCompetitorSnapshot.id.desc(),
        )
        .all()
    )
    latest_any: dict[int, models.ProjectCompetitorSnapshot] = {}
    latest_ready: dict[int, models.ProjectCompetitorSnapshot] = {}
    for snapshot in snapshots:
        latest_any.setdefault(snapshot.competitor_id, snapshot)
        if snapshot.status == "succeeded":
            latest_ready.setdefault(snapshot.competitor_id, snapshot)
    return latest_any, latest_ready


def list_project_competitive_source_audits(
    db: Session,
    *,
    project_id: int,
    newest_first: bool = False,
) -> list[models.Audit]:
    """Return the project's own audits, newest or oldest first.

    SIGV2-1117: this used to return every audit under ``project_id`` minus the
    competitor audit ids found on the project's competitor snapshots. Subtraction
    failed open. A ``lite-refresh`` benchmark never gets a snapshot, and deleting
    a competitor deletes its snapshots, so a competitor's audit could be read back
    here as one of the project's own. The project's own audits are now identified
    positively instead.
    """
    return (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .order_by(
            models.Audit.created_at.desc() if newest_first else models.Audit.created_at.asc(),
            models.Audit.id.desc() if newest_first else models.Audit.id.asc(),
        )
        .all()
    )


def get_latest_project_competitive_source_audit(
    db: Session,
    *,
    project_id: int,
) -> models.Audit | None:
    audits = list_project_competitive_source_audits(db, project_id=project_id, newest_first=True)
    return audits[0] if audits else None


def _audit_scores(audit: models.Audit | None) -> dict[str, float | None]:
    if audit is None:
        return {"geo": None, "seo": None, "aeo": None, "overall": None}
    geo = _round_score(audit.geo_score)
    seo = _round_score(audit.seo_score)
    aeo = _round_score(audit.aeo_score)
    overall = _mean_scores([geo, seo, aeo])
    return {"geo": geo, "seo": seo, "aeo": aeo, "overall": overall}


def _snapshot_scores(snapshot: models.ProjectCompetitorSnapshot | None) -> dict[str, float | None]:
    if snapshot is None:
        return {"geo": None, "seo": None, "aeo": None, "overall": None}
    geo = _round_score(snapshot.geo_score)
    seo = _round_score(snapshot.seo_score)
    aeo = _round_score(snapshot.aeo_score)
    overall = _mean_scores([geo, seo, aeo])
    return {"geo": geo, "seo": seo, "aeo": aeo, "overall": overall}


def _aio_score(scores: dict[str, float | None]) -> int | None:
    return derive_aio({"aeo_score": scores.get("aeo"), "geo_score": scores.get("geo")}).get(
        "aio_score"
    )


def _rank_metrics(
    project_scores: dict[str, float | None], competitor_scores: list[dict[str, float | None]]
) -> dict[str, int | None]:
    # AIO is a rank on the derived roll-up, not an average of component ranks:
    # ranks are nonlinear, so each side is ranked on its own derived AIO score.
    project_scores = {**project_scores, "aio": _aio_score(project_scores)}
    competitor_scores = [{**scores, "aio": _aio_score(scores)} for scores in competitor_scores]
    ranks: dict[str, int | None] = {}
    for metric in ("aio", "geo", "seo", "aeo", "overall"):
        target_score = project_scores.get(metric)
        if target_score is None:
            ranks[metric] = None
            continue
        values = [float(target_score)]
        values.extend(
            float(score[metric]) for score in competitor_scores if score.get(metric) is not None
        )
        higher_count = sum(1 for value in values if value > float(target_score))
        ranks[metric] = higher_count + 1
    return ranks


def list_project_competitors(
    db: Session,
    *,
    project: models.Project,
) -> list[dict[str, Any]]:
    latest_any, latest_ready = _latest_snapshot_maps(db, project_id=project.id)
    rows: list[dict[str, Any]] = []
    for competitor in sorted(
        project.competitors, key=lambda row: (row.created_at or datetime.min, row.id)
    ):
        latest_snapshot = latest_any.get(competitor.id)
        ready_snapshot = latest_ready.get(competitor.id)
        snapshot_for_scores = ready_snapshot or latest_snapshot
        competitor_audit = (
            ready_snapshot.competitor_audit
            if ready_snapshot is not None and ready_snapshot.competitor_audit is not None
            else latest_snapshot.competitor_audit
            if latest_snapshot is not None and latest_snapshot.competitor_audit is not None
            else None
        )
        rows.append(
            {
                "id": competitor.id,
                "project_id": project.id,
                "competitor_site_id": (
                    int(competitor_audit.site_id)
                    if competitor_audit is not None and competitor_audit.site_id is not None
                    else None
                ),
                "target_url": competitor.target_url,
                "normalized_domain": competitor.normalized_domain,
                "display_name": competitor.display_name,
                "auto_audit_enabled": bool(competitor.auto_audit_enabled),
                "created_at": _isoformat(competitor.created_at),
                "latest_status": latest_snapshot.status
                if latest_snapshot is not None
                else "not_started",
                "latest_failure_reason": latest_snapshot.failure_reason
                if latest_snapshot is not None
                else None,
                "last_benchmarked_at": _isoformat(
                    ready_snapshot.captured_at if ready_snapshot is not None else None
                ),
                "latest_source_audit_id": (
                    latest_snapshot.source_audit_id if latest_snapshot is not None else None
                ),
                "latest_scores": _snapshot_scores(snapshot_for_scores),
            }
        )
    return rows


def build_project_competitive_analysis(
    db: Session,
    *,
    project: models.Project,
) -> dict[str, Any]:
    latest_project_audit = get_latest_project_competitive_source_audit(db, project_id=project.id)
    project_scores = _audit_scores(latest_project_audit)
    latest_any, latest_ready = _latest_snapshot_maps(db, project_id=project.id)

    competitors_payload: list[dict[str, Any]] = []
    pending_count = 0
    failed_count = 0

    for competitor in sorted(
        project.competitors, key=lambda row: (row.created_at or datetime.min, row.id)
    ):
        latest_snapshot = latest_any.get(competitor.id)
        ready_snapshot = latest_ready.get(competitor.id)
        snapshot_for_scores = ready_snapshot or latest_snapshot
        scores = _snapshot_scores(snapshot_for_scores)

        status = latest_snapshot.status if latest_snapshot is not None else "not_started"
        if status == "pending":
            pending_count += 1
        elif status == "failed":
            failed_count += 1

        delta = {
            metric: (
                _round_score(project_scores.get(metric, 0.0) - scores.get(metric, 0.0))
                if project_scores.get(metric) is not None and scores.get(metric) is not None
                else None
            )
            for metric in ("geo", "seo", "aeo", "overall")
        }

        competitors_payload.append(
            {
                "id": competitor.id,
                "name": competitor.display_name,
                "url": competitor.target_url,
                "status": status,
                "last_benchmarked_at": _isoformat(
                    ready_snapshot.captured_at if ready_snapshot is not None else None
                ),
                "failure_reason": latest_snapshot.failure_reason
                if latest_snapshot is not None
                else None,
                "scores": scores,
                "delta": delta,
            }
        )

    updated_at_candidates = [
        _as_utc(latest_project_audit.created_at) if latest_project_audit else None
    ]
    updated_at_candidates.extend(
        _as_utc(snapshot.captured_at)
        for snapshot in latest_ready.values()
        if snapshot.captured_at is not None
    )
    updated_at = max((value for value in updated_at_candidates if value is not None), default=None)

    return {
        "project_id": project.id,
        "project": {
            "id": project.id,
            "name": project.name,
            "url": project.domain_url,
            "scores": project_scores,
            "last_audit_at": _isoformat(
                latest_project_audit.created_at if latest_project_audit else None
            ),
        },
        "competitors": competitors_payload,
        "rank": _rank_metrics(project_scores, [entry["scores"] for entry in competitors_payload]),
        "updated_at": _isoformat(updated_at),
        "benchmark_status": {
            "auto_competitor_audits_enabled": bool(project.auto_competitor_audits_enabled),
            "competitive_digest_frequency": (
                project.competitive_digest_frequency.value
                if isinstance(
                    project.competitive_digest_frequency, models.CompetitiveDigestFrequency
                )
                else str(project.competitive_digest_frequency or "weekly")
            ),
            "pending_competitors": pending_count,
            "failed_competitors": failed_count,
            "configured_competitors": len(project.competitors),
            "has_data": any(
                entry["scores"].get("overall") is not None for entry in competitors_payload
            ),
        },
    }


def _period_cutoff(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "90d":
        return now - timedelta(days=90)
    if period == "1y":
        return now - timedelta(days=365)
    return None


def build_project_competitive_trends(
    db: Session,
    *,
    project: models.Project,
    period: str = "90d",
    metric: str = "overall",
) -> dict[str, Any]:
    metric_key = metric if metric in {"geo", "seo", "aeo", "overall"} else "overall"
    cutoff = _period_cutoff(period)

    source_audits = list_project_competitive_source_audits(
        db,
        project_id=project.id,
        newest_first=False,
    )
    if cutoff is not None:
        source_audits = [
            audit
            for audit in source_audits
            if (_as_utc(audit.created_at) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]

    source_audit_ids = [audit.id for audit in source_audits]
    snapshots = (
        db.query(models.ProjectCompetitorSnapshot)
        .filter(
            models.ProjectCompetitorSnapshot.project_id == project.id,
            models.ProjectCompetitorSnapshot.source_audit_id.in_(source_audit_ids or [-1]),
            models.ProjectCompetitorSnapshot.status == "succeeded",
        )
        .order_by(
            models.ProjectCompetitorSnapshot.source_audit_id.asc(),
            models.ProjectCompetitorSnapshot.id.asc(),
        )
        .all()
    )
    snapshots_by_source: dict[int, list[models.ProjectCompetitorSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        snapshots_by_source[snapshot.source_audit_id].append(snapshot)

    project_points = [
        {
            "date": _isoformat(audit.created_at),
            "value": _audit_scores(audit).get(metric_key),
        }
        for audit in source_audits
    ]

    competitor_lookup = {competitor.id: competitor for competitor in project.competitors}
    competitor_points_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for audit in source_audits:
        for snapshot in snapshots_by_source.get(audit.id, []):
            scores = _snapshot_scores(snapshot)
            competitor_points_map[snapshot.competitor_id].append(
                {
                    "date": _isoformat(audit.created_at),
                    "value": scores.get(metric_key),
                }
            )

    lines = [
        {
            "key": "project",
            "label": project.name,
            "is_project": True,
            "points": project_points,
        }
    ]
    for competitor_id, competitor in sorted(
        competitor_lookup.items(), key=lambda item: item[1].display_name.lower()
    ):
        lines.append(
            {
                "key": f"competitor:{competitor_id}",
                "label": competitor.display_name,
                "is_project": False,
                "points": competitor_points_map.get(competitor_id, []),
            }
        )

    return {
        "project_id": project.id,
        "metric": metric_key,
        "period": period,
        "lines": lines,
    }


def _extract_schema_coverage_percent(audit: models.Audit | None) -> float | None:
    if audit is None or not isinstance(audit.full_report, dict):
        return None
    aeo = audit.full_report.get("aeo")
    if not isinstance(aeo, dict):
        return None
    schema_coverage = aeo.get("schema_coverage")
    if isinstance(schema_coverage, dict) and isinstance(
        schema_coverage.get("coverage_percent"), (int, float)
    ):
        return _round_score(float(schema_coverage["coverage_percent"]))
    schema_health = aeo.get("schema_health")
    if isinstance(schema_health, dict) and isinstance(schema_health.get("score"), (int, float)):
        return _round_score(float(schema_health["score"]))
    return None


def _extract_performance_score(audit: models.Audit | None) -> float | None:
    if audit is None or not isinstance(audit.full_report, dict):
        return None
    seo = audit.full_report.get("seo")
    if isinstance(seo, dict) and isinstance(seo.get("performance"), (int, float)):
        return _round_score(float(seo["performance"]))
    analysis = audit.full_report.get("analysis")
    if isinstance(analysis, dict):
        performance = analysis.get("performance")
        if isinstance(performance, dict) and isinstance(performance.get("score"), (int, float)):
            return _round_score(float(performance["score"]))
    return None


def _extract_citation_share(audit: models.Audit | None) -> float | None:
    if audit is None or not isinstance(audit.full_report, dict):
        return None
    geo = audit.full_report.get("geo")
    if isinstance(geo, dict) and isinstance(geo.get("citation_share"), (int, float)):
        return _round_score(float(geo["citation_share"]))
    return None


def _gap_reason_and_recommendation(
    *,
    metric: str,
    project_audit: models.Audit | None,
    competitor_audit: models.Audit | None,
) -> tuple[str, str, list[str]]:
    evidence: list[str] = []
    if metric == "aeo":
        project_schema = _extract_schema_coverage_percent(project_audit)
        competitor_schema = _extract_schema_coverage_percent(competitor_audit)
        if project_schema is not None and competitor_schema is not None:
            evidence.append(
                f"Schema coverage: {competitor_schema:.1f}% competitor vs {project_schema:.1f}% client."
            )
        return (
            "Competitor content is more answerable for AI retrieval and schema-driven extraction.",
            "Prioritize FAQ, HowTo, and trust-bearing schema on high-value pages, then refresh answer-led content blocks.",
            evidence,
        )
    if metric == "seo":
        project_perf = _extract_performance_score(project_audit)
        competitor_perf = _extract_performance_score(competitor_audit)
        if project_perf is not None and competitor_perf is not None:
            evidence.append(
                f"Performance score: {competitor_perf:.1f} competitor vs {project_perf:.1f} client."
            )
        return (
            "Competitor pages show stronger crawlability, on-page structure, or performance support signals.",
            "Tighten technical SEO debt, strengthen internal linking, and improve page speed on the client domain's priority templates.",
            evidence,
        )
    project_share = _extract_citation_share(project_audit)
    competitor_share = _extract_citation_share(competitor_audit)
    if project_share is not None and competitor_share is not None:
        evidence.append(
            f"Citation share: {competitor_share:.1f}% competitor vs {project_share:.1f}% client."
        )
    return (
        "Competitor visibility signals are stronger in generative search surfaces and citation capture.",
        "Expand entity reinforcement, cited proof points, and prompt-aligned coverage for the topics where competitors currently dominate.",
        evidence,
    )


def build_project_competitive_gaps(
    db: Session,
    *,
    project: models.Project,
) -> dict[str, Any]:
    latest_project_audit = get_latest_project_competitive_source_audit(db, project_id=project.id)
    project_scores = _audit_scores(latest_project_audit)
    latest_any, latest_ready = _latest_snapshot_maps(db, project_id=project.id)

    gaps: list[dict[str, Any]] = []
    pending_competitors: list[str] = []
    failed_competitors: list[dict[str, Any]] = []

    for competitor in sorted(project.competitors, key=lambda row: row.display_name.lower()):
        latest_snapshot = latest_any.get(competitor.id)
        ready_snapshot = latest_ready.get(competitor.id)
        if latest_snapshot is not None and latest_snapshot.status == "pending":
            pending_competitors.append(competitor.display_name)
        if latest_snapshot is not None and latest_snapshot.status == "failed":
            failed_competitors.append(
                {
                    "competitor_id": competitor.id,
                    "competitor_name": competitor.display_name,
                    "reason": latest_snapshot.failure_reason,
                }
            )

        if ready_snapshot is None:
            continue

        competitor_audit = (
            db.query(models.Audit)
            .filter(models.Audit.id == ready_snapshot.competitor_audit_id)
            .first()
            if ready_snapshot.competitor_audit_id is not None
            else None
        )
        competitor_scores = _snapshot_scores(ready_snapshot)
        for metric in ("geo", "seo", "aeo"):
            project_metric_score = project_scores.get(metric)
            competitor_metric_score = competitor_scores.get(metric)
            if project_metric_score is None or competitor_metric_score is None:
                continue
            delta = round(float(competitor_metric_score) - float(project_metric_score), 2)
            if delta < COMPETITIVE_GAP_THRESHOLD:
                continue

            reason, recommendation, evidence = _gap_reason_and_recommendation(
                metric=metric,
                project_audit=latest_project_audit,
                competitor_audit=competitor_audit,
            )
            severity = "high" if delta >= 15 else "medium" if delta >= 8 else "watch"
            gaps.append(
                {
                    "competitor_id": competitor.id,
                    "competitor_name": competitor.display_name,
                    "metric": metric,
                    "project_score": project_metric_score,
                    "competitor_score": competitor_metric_score,
                    "delta": delta,
                    "severity": severity,
                    "reason": reason,
                    "recommendation": recommendation,
                    "evidence": evidence,
                }
            )

    gaps.sort(key=lambda item: (item["delta"], item["competitor_name"]), reverse=True)
    strongest_gap = gaps[0] if gaps else None
    return {
        "project_id": project.id,
        "generated_at": _isoformat(datetime.now(timezone.utc)),
        "summary": {
            "gap_count": len(gaps),
            "largest_gap_metric": strongest_gap["metric"] if strongest_gap else None,
            "largest_gap_delta": strongest_gap["delta"] if strongest_gap else None,
        },
        "gaps": gaps,
        "pending_competitors": pending_competitors,
        "failed_competitors": failed_competitors,
    }


def build_project_competitive_ai_prompt(
    db: Session,
    *,
    project: models.Project,
    competitor_id: int,
) -> tuple[dict[str, Any], str]:
    gaps_payload = build_project_competitive_gaps(db, project=project)
    gap = next(
        (item for item in gaps_payload["gaps"] if int(item["competitor_id"]) == competitor_id),
        None,
    )
    if gap is None:
        raise ValueError("No competitive gap is available for this competitor yet.")

    evidence_lines = (
        "\n".join(f"- {line}" for line in gap.get("evidence", []))
        or "- No structured evidence captured."
    )
    recommendation_text = (
        f"{gap['competitor_name']} is ahead of {project.name} in {str(gap['metric']).upper()} by {gap['delta']} points. "
        f"Reason: {gap['reason']} Recommendation: {gap['recommendation']}"
    )
    prompt = (
        f"Create a concise execution brief for closing the {str(gap['metric']).upper()} gap against {gap['competitor_name']}.\n"
        f"Client: {project.name}\n"
        f"Client URL: {project.domain_url or 'n/a'}\n"
        f"Gap delta: {gap['delta']}\n"
        f"Evidence:\n{evidence_lines}\n"
        "Return practical, prioritized actions the agency can execute over the next 30 days."
    )
    return gap, f"{recommendation_text}\n\n{prompt}"


def _scores_from_snapshot_rows(
    source_audit: models.Audit,
    rows: list[models.ProjectCompetitorSnapshot],
) -> tuple[dict[str, float | None], list[dict[str, Any]]]:
    project_scores = _audit_scores(source_audit)
    competitor_entries = [
        {
            "competitor_id": row.competitor_id,
            "scores": _snapshot_scores(row),
        }
        for row in rows
    ]
    return project_scores, competitor_entries


def _current_frequency_value(project: models.Project) -> str:
    if isinstance(project.competitive_digest_frequency, models.CompetitiveDigestFrequency):
        return project.competitive_digest_frequency.value
    return str(project.competitive_digest_frequency or "weekly")


def maybe_queue_project_competitive_digest(
    db: Session,
    *,
    project: models.Project,
    source_audit_id: int,
    frontend_base_url: str,
) -> bool:
    frequency = _current_frequency_value(project)
    if frequency == models.CompetitiveDigestFrequency.OFF.value:
        return False

    existing_log = (
        db.query(models.ProjectCompetitiveDigestLog)
        .filter(models.ProjectCompetitiveDigestLog.source_audit_id == source_audit_id)
        .first()
    )
    if existing_log is not None:
        return False

    source_audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.id == source_audit_id,
            models.Audit.project_id == project.id,
            own_project_audit_clause(),
        )
        .first()
    )
    if source_audit is None or not str(source_audit.request_id or "").startswith(
        "scheduled-audit:"
    ):
        return False

    active_competitor_ids = [
        competitor.id for competitor in project.competitors if competitor.auto_audit_enabled
    ]
    if not active_competitor_ids:
        return False

    current_rows = (
        db.query(models.ProjectCompetitorSnapshot)
        .filter(
            models.ProjectCompetitorSnapshot.project_id == project.id,
            models.ProjectCompetitorSnapshot.source_audit_id == source_audit_id,
            models.ProjectCompetitorSnapshot.competitor_id.in_(active_competitor_ids),
        )
        .all()
    )
    if len(current_rows) < len(active_competitor_ids):
        return False
    if any(row.status == "pending" for row in current_rows):
        return False

    last_log = (
        db.query(models.ProjectCompetitiveDigestLog)
        .filter(models.ProjectCompetitiveDigestLog.project_id == project.id)
        .order_by(
            models.ProjectCompetitiveDigestLog.created_at.desc(),
            models.ProjectCompetitiveDigestLog.id.desc(),
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if last_log is not None and last_log.created_at is not None:
        last_log_at = _as_utc(last_log.created_at) or now
        if (
            frequency == models.CompetitiveDigestFrequency.WEEKLY.value
            and now - last_log_at < timedelta(days=7)
        ):
            return False
        if frequency == models.CompetitiveDigestFrequency.MONTHLY.value:
            if last_log_at.year == now.year and last_log_at.month == now.month:
                return False

    competitor_lookup = {competitor.id: competitor for competitor in project.competitors}
    project_scores, competitor_entries = _scores_from_snapshot_rows(source_audit, current_rows)
    current_rank = _rank_metrics(project_scores, [item["scores"] for item in competitor_entries])

    previous_source_audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.project_id == project.id,
            own_project_audit_clause(),
            models.Audit.created_at < source_audit.created_at,
        )
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )

    previous_rank: dict[str, int | None] = {
        "aio": None,
        "geo": None,
        "seo": None,
        "aeo": None,
        "overall": None,
    }
    previous_by_competitor: dict[int, dict[str, float | None]] = {}
    if previous_source_audit is not None:
        previous_rows = (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(
                models.ProjectCompetitorSnapshot.project_id == project.id,
                models.ProjectCompetitorSnapshot.source_audit_id == previous_source_audit.id,
                models.ProjectCompetitorSnapshot.status == "succeeded",
            )
            .all()
        )
        previous_scores, previous_entries = _scores_from_snapshot_rows(
            previous_source_audit, previous_rows
        )
        previous_rank = _rank_metrics(
            previous_scores, [item["scores"] for item in previous_entries]
        )
        previous_by_competitor = {
            int(item["competitor_id"]): item["scores"] for item in previous_entries
        }

    highlights: list[str] = []
    metric_labels = {"aio": "AIO", "seo": "SEO"}
    for metric in ("aio", "seo"):
        current_value = current_rank.get(metric)
        previous_value = previous_rank.get(metric)
        if current_value is None or previous_value is None or current_value == previous_value:
            continue
        if current_value < previous_value:
            highlights.append(
                f"{project.name} moved from #{previous_value} to #{current_value} in {metric_labels[metric]}."
            )
        else:
            highlights.append(
                f"{project.name} slipped from #{previous_value} to #{current_value} in {metric_labels[metric]}."
            )

    for row in current_rows:
        current_scores = _snapshot_scores(row)
        previous_scores = previous_by_competitor.get(row.competitor_id)
        if not previous_scores:
            continue
        current_overall = current_scores.get("overall")
        previous_overall = previous_scores.get("overall")
        if current_overall is None or previous_overall is None:
            continue
        delta = round(current_overall - previous_overall, 2)
        if delta <= -10:
            competitor = competitor_lookup.get(row.competitor_id)
            highlights.append(
                f"{(competitor.display_name if competitor else 'A competitor')} dropped {abs(delta):.1f} points overall."
            )

    if not highlights:
        highlights.append(
            f"Competitive benchmark refreshed for {project.name}. Review the latest score deltas and gap cards in the dashboard."
        )

    dashboard_url = f"{frontend_base_url.rstrip('/')}/dashboard/projects/{project.id}/competitive"
    workspace = project.workspace
    owner = workspace.owner if workspace is not None else None
    if owner is None or not owner.email or not bool(owner.notifications_enabled):
        return False

    notification_context = {
        "email": owner.email,
        "project_name": project.name,
        "language": project.language or "en",
        "report_language": project.language or "en",
        "workspace_name": workspace.name if workspace is not None else "Workspace",
        "report_period": frequency,
        "dashboard_url": dashboard_url,
        "current_rank": current_rank,
        "previous_rank": previous_rank,
        "highlights": highlights,
        "competitor_count": len(active_competitor_ids),
        "updated_at": _isoformat(source_audit.created_at),
    }
    NotificationRouter(db).dispatch_event(
        workspace_id=project.workspace_id,
        event_key="competitive.digest",
        context=notification_context,
        user=owner,
        to_email=owner.email,
        correlation_id=f"competitive.digest:{project.id}:{source_audit_id}",
    )
    evaluate_workflows_for_event(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        event_key="competitive.digest",
        context=notification_context,
    )
    db.add(
        models.ProjectCompetitiveDigestLog(
            project_id=project.id,
            source_audit_id=source_audit_id,
            frequency=frequency,
        )
    )
    db.flush()
    return True
