from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any

from sqlalchemy.orm import Session

import models
from app.config.plans import resolve_entitled_subscription_plan, resolve_plan_alias
from services.project_audit_scope import own_project_audit_clause


MIN_COHORT_PROJECTS = 10
MIN_COHORT_WORKSPACES = 3
MIN_AUDITS_FOR_PERCENTILES = 30

SUPPORTED_METRICS = {"geo_score": "geo", "seo_score": "seo", "aeo_score": "aeo"}

# Only this entity-authority computation version is admitted into cohorts;
# values from other provider versions are not interchangeable (AC1).
AUTHORITY_PROVIDER_VERSION = "v1"

# AC1: every benchmarked metric is defined (source, unit, range, denominator)
# BEFORE it may enter a cohort. win_rate is defined but deliberately
# unavailable: no field in the audit contract records recommendation wins
# over a denominator of measured comparisons. answer_dominance is not a
# recorded metric anywhere in the codebase, and the AEO answerability score
# is a single-URL probability out of 100, not a share of competitor wins -
# mapping either to win rate would be an unverifiable approximation.
METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "geo_score": {
        "source": "signal_audit_snapshots.score_dimension='geo'",
        "unit": "score",
        "range": (0.0, 100.0),
        "denominator": None,
        "available": True,
    },
    "seo_score": {
        "source": "signal_audit_snapshots.score_dimension='seo'",
        "unit": "score",
        "range": (0.0, 100.0),
        "denominator": None,
        "available": True,
    },
    "aeo_score": {
        "source": "signal_audit_snapshots.score_dimension='aeo'",
        "unit": "score",
        "range": (0.0, 100.0),
        "denominator": None,
        "available": True,
    },
    "authority_score": {
        "source": "entity_authority_snapshots.authority_score",
        "unit": "score",
        "range": (0.0, 100.0),
        "denominator": None,
        "provider_version": AUTHORITY_PROVIDER_VERSION,
        "available": True,
    },
    "win_rate": {
        "source": None,
        "unit": "ratio",
        "range": (0.0, 1.0),
        "denominator": "measured recommendation comparisons",
        "available": False,
        "unavailable_reason": (
            "Recommendation win rate is unavailable: no measured win/loss "
            "source exists (answer_dominance is not a recorded metric, and "
            "the answerability score is a single-URL score, not a share of "
            "competitor wins)."
        ),
    },
}


@dataclass(frozen=True)
class BenchmarkResult:
    project_id: int
    metric: str
    status: str
    percentile: float | None
    top_percent: int | None
    cohort_key: str | None
    cohort_label: str | None
    cohort_size: int
    project_value: float | None
    period_date: date | None
    cohort_mean: float | None = None
    unit: str | None = None
    denominator: str | None = None
    source: str | None = None
    unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "metric": self.metric,
            "status": self.status,
            "percentile": round(float(self.percentile), 2) if self.percentile is not None else None,
            "top_percent": self.top_percent,
            "cohort_key": self.cohort_key,
            "cohort_label": self.cohort_label,
            "cohort_size": self.cohort_size,
            "project_value": round(float(self.project_value), 2)
            if self.project_value is not None
            else None,
            "period_date": self.period_date.isoformat() if self.period_date is not None else None,
            "cohort_mean": round(float(self.cohort_mean), 2)
            if self.cohort_mean is not None
            else None,
            "unit": self.unit,
            "denominator": self.denominator,
            "source": self.source,
            "unavailable_reason": self.unavailable_reason,
        }


class BenchmarkEngine:
    def ensure_current_period_aggregates(self, *, db: Session, period_date: date) -> int:
        already_computed = (
            db.query(models.BenchmarkCohortAggregate.id)
            .filter(models.BenchmarkCohortAggregate.period_date == period_date)
            .first()
        )
        if already_computed is not None:
            return 0
        return self.compute_cohort_aggregates(db=db, period_date=period_date)

    def compute_cohort_aggregates(self, *, db: Session, period_date: date) -> int:
        snapshots = (
            db.query(models.SignalAuditSnapshot)
            .filter(models.SignalAuditSnapshot.snapshot_date <= period_date)
            .order_by(
                models.SignalAuditSnapshot.snapshot_date.desc(),
                models.SignalAuditSnapshot.id.desc(),
            )
            .all()
        )
        # One eligible observation per project per metric per period (AC4):
        # rows arrive newest-first and only the first (latest) is kept, so a
        # tenant running repeated audits cannot overweight the cohort. The
        # queried project is a member of its own cohort; this is intentional
        # and documented in the benchmark response.
        latest_values: dict[tuple[int, str], float] = {}
        for snapshot in snapshots:
            metric = f"{snapshot.score_dimension}_score"
            if metric not in SUPPORTED_METRICS:
                continue
            key = (int(snapshot.project_id), metric)
            if key in latest_values:
                continue
            value = float(snapshot.score_value or 0.0)
            low, high = METRIC_DEFINITIONS[metric]["range"]
            if not (low <= value <= high):
                continue  # invalid observation, excluded (AC4)
            latest_values[key] = value

        period_end = datetime.combine(
            period_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )
        authority_snapshots = (
            db.query(models.EntityAuthoritySnapshot)
            .filter(
                models.EntityAuthoritySnapshot.computation_version == AUTHORITY_PROVIDER_VERSION,
                models.EntityAuthoritySnapshot.computed_at < period_end,
            )
            .order_by(
                models.EntityAuthoritySnapshot.computed_at.desc(),
                models.EntityAuthoritySnapshot.id.desc(),
            )
            .all()
        )
        for snapshot in authority_snapshots:
            key = (int(snapshot.project_id), "authority_score")
            if key in latest_values:
                continue
            value = float(snapshot.authority_score or 0.0)
            low, high = METRIC_DEFINITIONS["authority_score"]["range"]
            if not (low <= value <= high):
                continue
            latest_values[key] = value

        if not latest_values:
            return 0

        context_map = self._load_project_contexts(
            db=db,
            project_ids={project_id for project_id, _metric in latest_values.keys()},
        )
        cohort_values: dict[str, dict[str, Any]] = {}

        for (project_id, metric), value in latest_values.items():
            context = context_map.get(project_id)
            if context is None:
                continue
            cohort_keys = [
                f"industry:{context['industry']}:{metric}",
                f"plan:{context['plan']}:{metric}",
                f"global:{metric}",
            ]
            for cohort_key in cohort_keys:
                bucket = cohort_values.setdefault(
                    cohort_key,
                    {
                        "metric": metric,
                        "values": [],
                        "projects": set(),
                        "workspaces": set(),
                    },
                )
                bucket["values"].append(value)
                bucket["projects"].add(project_id)
                bucket["workspaces"].add(context["workspace_id"])

        rows_written = 0
        for cohort_key, payload in cohort_values.items():
            values = sorted(float(v) for v in payload["values"])
            project_count = len(payload["projects"])
            workspace_count = len(payload["workspaces"])
            cohort_size = project_count
            suppressed = (
                project_count < MIN_COHORT_PROJECTS or workspace_count < MIN_COHORT_WORKSPACES
            )
            allow_percentiles = len(values) >= MIN_AUDITS_FOR_PERCENTILES

            p10 = p25 = p50 = p75 = p90 = None
            avg = stddev = None
            if values and not suppressed:
                # Mean and stddev are stored only when the cohort clears the
                # suppression thresholds: n * mean reconstructs the cohort sum,
                # so below threshold it is suppressed like the percentiles
                # (AC3). A percentile is never labelled average.
                avg = round(float(mean(values)), 4)
                stddev = round(float(pstdev(values)), 4) if len(values) > 1 else 0.0
            if values and allow_percentiles and not suppressed:
                p10 = self._percentile(values, 10)
                p25 = self._percentile(values, 25)
                p50 = self._percentile(values, 50)
                p75 = self._percentile(values, 75)
                p90 = self._percentile(values, 90)

            aggregate = (
                db.query(models.BenchmarkCohortAggregate)
                .filter(
                    models.BenchmarkCohortAggregate.cohort_key == cohort_key,
                    models.BenchmarkCohortAggregate.metric == payload["metric"],
                    models.BenchmarkCohortAggregate.period_date == period_date,
                )
                .first()
            )
            if aggregate is None:
                aggregate = models.BenchmarkCohortAggregate(
                    cohort_key=cohort_key,
                    metric=payload["metric"],
                    period_date=period_date,
                )
                db.add(aggregate)

            aggregate.cohort_size = cohort_size
            aggregate.p10 = p10
            aggregate.p25 = p25
            aggregate.p50 = p50
            aggregate.p75 = p75
            aggregate.p90 = p90
            aggregate.mean = avg
            aggregate.stddev = stddev
            aggregate.suppressed = suppressed
            rows_written += 1

        return rows_written

    def get_project_percentile(
        self,
        *,
        db: Session,
        project_id: int,
        metric: str,
    ) -> BenchmarkResult | None:
        normalized_metric = _normalize_metric(metric)
        definition = METRIC_DEFINITIONS.get(normalized_metric)
        if definition is None:
            return None

        if not definition["available"]:
            return BenchmarkResult(
                project_id=project_id,
                metric=normalized_metric,
                status="unavailable",
                percentile=None,
                top_percent=None,
                cohort_key=None,
                cohort_label=None,
                cohort_size=0,
                project_value=None,
                period_date=None,
                unit=definition["unit"],
                denominator=definition["denominator"],
                source=None,
                unavailable_reason=definition["unavailable_reason"],
            )

        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project is None:
            return None

        project_value: float | None = None
        if normalized_metric == "authority_score":
            authority_snapshot = (
                db.query(models.EntityAuthoritySnapshot)
                .filter(
                    models.EntityAuthoritySnapshot.project_id == project_id,
                    models.EntityAuthoritySnapshot.computation_version
                    == AUTHORITY_PROVIDER_VERSION,
                )
                .order_by(
                    models.EntityAuthoritySnapshot.computed_at.desc(),
                    models.EntityAuthoritySnapshot.id.desc(),
                )
                .first()
            )
            if authority_snapshot is not None:
                candidate = float(authority_snapshot.authority_score or 0.0)
                low, high = definition["range"]
                if low <= candidate <= high:
                    project_value = candidate
        else:
            score_dimension = SUPPORTED_METRICS[normalized_metric]
            snapshot = (
                db.query(models.SignalAuditSnapshot)
                .filter(
                    models.SignalAuditSnapshot.project_id == project_id,
                    models.SignalAuditSnapshot.score_dimension == score_dimension,
                )
                .order_by(
                    models.SignalAuditSnapshot.snapshot_date.desc(),
                    models.SignalAuditSnapshot.id.desc(),
                )
                .first()
            )
            if snapshot is not None:
                candidate = float(snapshot.score_value or 0.0)
                low, high = definition["range"]
                if low <= candidate <= high:
                    project_value = candidate

        if project_value is None:
            return BenchmarkResult(
                project_id=project_id,
                metric=normalized_metric,
                status="insufficient_data",
                percentile=None,
                top_percent=None,
                cohort_key=None,
                cohort_label=None,
                cohort_size=0,
                project_value=None,
                period_date=None,
                unit=definition["unit"],
                denominator=definition["denominator"],
                source=definition["source"],
            )

        context_map = self._load_project_contexts(db=db, project_ids={project_id})
        context = context_map.get(project_id)
        if context is None:
            return None

        candidate_keys = [
            f"industry:{context['industry']}:{normalized_metric}",
            f"plan:{context['plan']}:{normalized_metric}",
            f"global:{normalized_metric}",
        ]

        selected: models.BenchmarkCohortAggregate | None = None
        suppressed_candidate: models.BenchmarkCohortAggregate | None = None
        for key in candidate_keys:
            row = (
                db.query(models.BenchmarkCohortAggregate)
                .filter(
                    models.BenchmarkCohortAggregate.cohort_key == key,
                    models.BenchmarkCohortAggregate.metric == normalized_metric,
                )
                .order_by(
                    models.BenchmarkCohortAggregate.period_date.desc(),
                    models.BenchmarkCohortAggregate.id.desc(),
                )
                .first()
            )
            if row is None:
                continue
            if bool(row.suppressed):
                suppressed_candidate = row
                continue
            selected = row
            break

        if selected is None:
            selected = suppressed_candidate

        if selected is None:
            return BenchmarkResult(
                project_id=project_id,
                metric=normalized_metric,
                status="insufficient_data",
                percentile=None,
                top_percent=None,
                cohort_key=None,
                cohort_label=None,
                cohort_size=0,
                project_value=project_value,
                period_date=None,
                unit=definition["unit"],
                denominator=definition["denominator"],
                source=definition["source"],
            )

        if bool(selected.suppressed):
            return BenchmarkResult(
                project_id=project_id,
                metric=normalized_metric,
                status="insufficient_data",
                percentile=None,
                top_percent=None,
                cohort_key=selected.cohort_key,
                cohort_label=_cohort_label(selected.cohort_key),
                cohort_size=int(selected.cohort_size or 0),
                project_value=project_value,
                period_date=selected.period_date,
                unit=definition["unit"],
                denominator=definition["denominator"],
                source=definition["source"],
            )

        percentile = self._estimate_percentile(project_value, selected)
        top_percent = max(1, int(round(100 - percentile))) if percentile is not None else None

        return BenchmarkResult(
            project_id=project_id,
            metric=normalized_metric,
            status="ok",
            percentile=percentile,
            top_percent=top_percent,
            cohort_key=selected.cohort_key,
            cohort_label=_cohort_label(selected.cohort_key),
            cohort_size=int(selected.cohort_size or 0),
            project_value=project_value,
            period_date=selected.period_date,
            cohort_mean=float(selected.mean) if selected.mean is not None else None,
            unit=definition["unit"],
            denominator=definition["denominator"],
            source=definition["source"],
        )

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return round(values[0], 4)
        rank = (len(values) - 1) * (percentile / 100.0)
        lower = int(rank)
        upper = min(lower + 1, len(values) - 1)
        weight = rank - lower
        return round((values[lower] * (1 - weight)) + (values[upper] * weight), 4)

    @staticmethod
    def _estimate_percentile(
        value: float,
        aggregate: models.BenchmarkCohortAggregate,
    ) -> float | None:
        points = [
            (aggregate.p10, 10.0),
            (aggregate.p25, 25.0),
            (aggregate.p50, 50.0),
            (aggregate.p75, 75.0),
            (aggregate.p90, 90.0),
        ]
        if any(point[0] is None for point in points):
            return None
        normalized_points = [
            (float(score), percentile) for score, percentile in points if score is not None
        ]

        first_score, first_percentile = normalized_points[0]
        if value <= first_score:
            if first_score == 0:
                return first_percentile
            return max(0.0, min(first_percentile, (value / first_score) * first_percentile))

        for index in range(len(normalized_points) - 1):
            low_score, low_percentile = normalized_points[index]
            high_score, high_percentile = normalized_points[index + 1]
            if low_score <= value <= high_score:
                if high_score == low_score:
                    return low_percentile
                weight = (value - low_score) / (high_score - low_score)
                return low_percentile + ((high_percentile - low_percentile) * weight)

        last_score = normalized_points[-1][0]
        if value >= last_score:
            if last_score == 0:
                return 90.0
            extension = ((value - last_score) / max(abs(last_score), 1.0)) * 10.0
            return max(90.0, min(99.0, 90.0 + extension))
        return None

    @staticmethod
    def _load_project_contexts(
        *,
        db: Session,
        project_ids: set[int],
    ) -> dict[int, dict[str, Any]]:
        if not project_ids:
            return {}

        projects = db.query(models.Project).filter(models.Project.id.in_(sorted(project_ids))).all()
        project_map = {int(project.id): project for project in projects}

        latest_audits = (
            db.query(models.Audit)
            .filter(
                models.Audit.project_id.in_(sorted(project_ids)),
                own_project_audit_clause(),
            )
            .order_by(models.Audit.project_id.asc(), models.Audit.id.desc())
            .all()
        )
        latest_audit_by_project: dict[int, models.Audit] = {}
        for audit in latest_audits:
            project_id = int(audit.project_id or 0)
            if project_id == 0 or project_id in latest_audit_by_project:
                continue
            latest_audit_by_project[project_id] = audit

        context_map: dict[int, dict[str, Any]] = {}
        for project_id, project in project_map.items():
            owner = project.workspace.owner if project.workspace else None
            subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(owner))
            trial_plan = resolve_plan_alias(getattr(owner, "trial_plan", None))
            plan = subscription_plan or trial_plan or "plan_starter"

            latest_audit = latest_audit_by_project.get(project_id)
            industry = "general"
            if latest_audit is not None and isinstance(latest_audit.query_category, str):
                industry = latest_audit.query_category.strip().lower() or "general"
            if industry == "none":
                industry = "general"

            context_map[project_id] = {
                "workspace_id": int(project.workspace_id),
                "plan": plan,
                "industry": industry,
            }
        return context_map


def _normalize_metric(metric: str) -> str:
    normalized = str(metric or "geo_score").strip().lower()
    if normalized in METRIC_DEFINITIONS:
        return normalized
    return "geo_score"


def _cohort_label(cohort_key: str) -> str:
    if cohort_key.startswith("industry:"):
        _prefix, industry, metric = cohort_key.split(":", 2)
        return f"Industry: {industry} ({metric})"
    if cohort_key.startswith("plan:"):
        _prefix, plan, metric = cohort_key.split(":", 2)
        return f"Plan: {plan} ({metric})"
    if cohort_key.startswith("global:"):
        return f"Global ({cohort_key.replace('global:', '')})"
    return cohort_key
