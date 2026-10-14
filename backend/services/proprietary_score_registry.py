from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

import models


SCORE_VERSION = "v1"


@dataclass(frozen=True)
class ProprietaryScoreView:
    project_id: int
    score_type: str
    score_version: str
    status: str
    value: float | None
    confidence: str
    data_points_used: int
    components: dict[str, Any]
    weights: dict[str, Any]
    computed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "score_type": self.score_type,
            "score_version": self.score_version,
            "status": self.status,
            "value": round(float(self.value), 2) if self.value is not None else None,
            "confidence": self.confidence,
            "data_points_used": self.data_points_used,
            "components": self.components,
            "weights": self.weights,
            "computed_at": self.computed_at.isoformat(),
        }


class ProprietaryScoreRegistry:
    def summarize_citation_stability(
        self,
        *,
        db: Session,
        project_id: int,
        window_days: int = 30,
    ) -> ProprietaryScoreView:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, int(window_days)))
        rows = (
            db.query(models.SignalCitationEvent)
            .filter(
                models.SignalCitationEvent.project_id == project_id,
                models.SignalCitationEvent.snapshot_date >= cutoff,
            )
            .all()
        )
        runs = len(rows)
        changes = sum(1 for row in rows if bool(row.answer_changed))

        value = None
        status = "insufficient_data"
        if runs > 0:
            value = max(0.0, min(100.0, (1.0 - (changes / runs)) * 100.0))
            status = "ok" if runs >= 3 else "insufficient_data"

        confidence = _confidence_for_data_points(runs)
        latest_score = self.get_latest_score(
            db=db, project_id=project_id, score_type="citation_stability"
        )
        computed_at = (
            latest_score.computed_at
            if latest_score is not None and latest_score.computed_at is not None
            else datetime.now(timezone.utc)
        )
        return ProprietaryScoreView(
            project_id=project_id,
            score_type="citation_stability",
            score_version=SCORE_VERSION,
            status=status,
            value=value,
            confidence=confidence,
            data_points_used=runs,
            components={
                "citation_changes_30d": changes,
                "citation_runs_30d": runs,
            },
            weights={"stability_formula": 1.0},
            computed_at=computed_at,
        )

    def compute_citation_stability(
        self,
        *,
        db: Session,
        project_id: int,
        window_days: int = 30,
    ) -> ProprietaryScoreView:
        summary = self.summarize_citation_stability(
            db=db,
            project_id=project_id,
            window_days=window_days,
        )

        score_row = self._upsert_score(
            db=db,
            project_id=project_id,
            score_type="citation_stability",
            value=summary.value,
            confidence=summary.confidence,
            data_points_used=summary.data_points_used,
            components=summary.components,
            weights=summary.weights,
        )
        return replace(
            summary,
            computed_at=score_row.computed_at or datetime.now(timezone.utc),
        )

    def summarize_remediation_impact(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
        rows = (
            db.query(models.SignalRemediationOutcome)
            .filter(
                models.SignalRemediationOutcome.project_id == project_id,
                models.SignalRemediationOutcome.completed_at.isnot(None),
                models.SignalRemediationOutcome.completed_at >= cutoff,
            )
            .all()
        )

        geo_deltas = [
            float(row.score_delta_geo)
            for row in rows
            if isinstance(row.score_delta_geo, (int, float))
        ]
        aeo_deltas = [
            float(row.score_delta_aeo)
            for row in rows
            if isinstance(row.score_delta_aeo, (int, float))
        ]
        combined_deltas = geo_deltas + aeo_deltas
        sample_size = len(rows)

        avg_delta = sum(combined_deltas) / len(combined_deltas) if combined_deltas else 0.0
        positive_deltas = sum(1 for value in combined_deltas if value > 0)
        status = "ok" if sample_size >= 3 else "insufficient_data"

        value = None
        if sample_size > 0:
            value = max(0.0, min(100.0, 50.0 + (avg_delta * 5.0)))

        confidence = _confidence_for_data_points(sample_size)
        latest_score = self.get_latest_score(
            db=db, project_id=project_id, score_type="remediation_impact"
        )
        computed_at = (
            latest_score.computed_at
            if latest_score is not None and latest_score.computed_at is not None
            else datetime.now(timezone.utc)
        )
        return ProprietaryScoreView(
            project_id=project_id,
            score_type="remediation_impact",
            score_version=SCORE_VERSION,
            status=status,
            value=value,
            confidence=confidence,
            data_points_used=sample_size,
            components={
                "resolved_items_90d": sample_size,
                "avg_score_delta": round(float(avg_delta), 4),
                "positive_score_deltas": positive_deltas,
            },
            weights={"delta_component": 0.7, "consistency_component": 0.3},
            computed_at=computed_at,
        )

    def summarize_pipeline_quality(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, int(lookback_days)))
        rows = (
            db.query(models.SignalClaimDispositionFact)
            .filter(
                models.SignalClaimDispositionFact.project_id == project_id,
                models.SignalClaimDispositionFact.snapshot_date >= cutoff,
            )
            .all()
        )

        breakdown: dict[str, dict[str, Any]] = {}
        quality_scores: list[float] = []
        for row in rows:
            generated = max(
                int(row.claims_generated or 0),
                int(row.claims_accepted or 0)
                + int(row.claims_downgraded or 0)
                + int(row.claims_rejected or 0)
                + int(row.claims_needs_manual_review or 0)
                + int(row.claims_deduplicated or 0),
                1,
            )
            accepted = int(row.claims_accepted or 0) / generated
            downgraded = int(row.claims_downgraded or 0) / generated
            rejected = int(row.claims_rejected or 0) / generated
            manual_review = int(row.claims_needs_manual_review or 0) / generated
            deduplicated = int(row.claims_deduplicated or 0) / generated
            quality_score = max(
                0.0,
                min(
                    100.0,
                    50.0
                    + (accepted * 50.0)
                    - (downgraded * 10.0)
                    - (rejected * 30.0)
                    - (manual_review * 20.0)
                    - (deduplicated * 10.0),
                ),
            )
            quality_scores.append(quality_score)
            bucket = breakdown.setdefault(
                str(row.pipeline_type or "unknown"),
                {
                    "rows": 0,
                    "claims_generated": 0,
                    "claims_accepted": 0,
                    "claims_downgraded": 0,
                    "claims_rejected": 0,
                    "claims_needs_manual_review": 0,
                    "claims_deduplicated": 0,
                    "quality_scores": [],
                },
            )
            bucket["rows"] += 1
            bucket["claims_generated"] += int(row.claims_generated or 0)
            bucket["claims_accepted"] += int(row.claims_accepted or 0)
            bucket["claims_downgraded"] += int(row.claims_downgraded or 0)
            bucket["claims_rejected"] += int(row.claims_rejected or 0)
            bucket["claims_needs_manual_review"] += int(row.claims_needs_manual_review or 0)
            bucket["claims_deduplicated"] += int(row.claims_deduplicated or 0)
            bucket["quality_scores"].append(quality_score)

        pipeline_breakdown: dict[str, Any] = {}
        for pipeline_type, bucket in breakdown.items():
            generated = max(1, int(bucket["claims_generated"] or 0))
            pipeline_breakdown[pipeline_type] = {
                "rows": int(bucket["rows"]),
                "quality_score": round(
                    sum(bucket["quality_scores"]) / max(len(bucket["quality_scores"]), 1), 2
                ),
                "acceptance_rate": round(int(bucket["claims_accepted"]) / generated, 4),
                "rejection_rate": round(int(bucket["claims_rejected"]) / generated, 4),
                "manual_review_rate": round(
                    int(bucket["claims_needs_manual_review"]) / generated, 4
                ),
                "dedup_rate": round(int(bucket["claims_deduplicated"]) / generated, 4),
            }

        value = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None
        status = "ok" if len(rows) >= 3 else "insufficient_data"
        confidence = _confidence_for_data_points(len(rows))
        latest_score = self.get_latest_score(
            db=db, project_id=project_id, score_type="pipeline_quality"
        )
        computed_at = (
            latest_score.computed_at
            if latest_score is not None and latest_score.computed_at is not None
            else datetime.now(timezone.utc)
        )
        return ProprietaryScoreView(
            project_id=project_id,
            score_type="pipeline_quality",
            score_version=SCORE_VERSION,
            status=status,
            value=value,
            confidence=confidence,
            data_points_used=len(rows),
            components={
                "window_days": max(1, int(lookback_days)),
                "pipeline_breakdown": pipeline_breakdown,
            },
            weights={
                "accepted_claim_weight": 50.0,
                "downgraded_claim_penalty": 10.0,
                "rejected_claim_penalty": 30.0,
                "manual_review_penalty": 20.0,
                "dedup_penalty": 10.0,
            },
            computed_at=computed_at,
        )

    def compute_pipeline_quality(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        summary = self.summarize_pipeline_quality(
            db=db,
            project_id=project_id,
            lookback_days=lookback_days,
        )
        score_row = self._upsert_score(
            db=db,
            project_id=project_id,
            score_type="pipeline_quality",
            value=summary.value,
            confidence=summary.confidence,
            data_points_used=summary.data_points_used,
            components=summary.components,
            weights=summary.weights,
        )
        return replace(
            summary,
            computed_at=score_row.computed_at or datetime.now(timezone.utc),
        )

    def summarize_provider_cost_efficiency(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, int(lookback_days)))
        agent_rows = (
            db.query(models.SignalDebateAgentFact)
            .filter(
                models.SignalDebateAgentFact.project_id == project_id,
                models.SignalDebateAgentFact.snapshot_date >= cutoff,
            )
            .all()
        )
        score_rows = (
            db.query(models.SignalAuditSnapshot)
            .filter(
                models.SignalAuditSnapshot.project_id == project_id,
                models.SignalAuditSnapshot.snapshot_date >= cutoff,
            )
            .all()
        )

        audit_quality: dict[int, float] = {}
        per_audit_scores: dict[int, list[float]] = {}
        for row in score_rows:
            per_audit_scores.setdefault(int(row.audit_id), []).append(float(row.score_value or 0.0))
        for audit_id, values in per_audit_scores.items():
            if values:
                audit_quality[audit_id] = max(0.0, min(100.0, sum(values) / len(values))) / 100.0

        provider_breakdown: dict[str, dict[str, Any]] = {}
        provider_scores: list[float] = []
        for row in agent_rows:
            provider = str(row.provider or "unknown")
            bucket = provider_breakdown.setdefault(
                provider,
                {
                    "agent_count": 0,
                    "total_cost_usd": 0.0,
                    "total_latency_ms": 0,
                    "quality_points": 0.0,
                },
            )
            bucket["agent_count"] += 1
            bucket["total_cost_usd"] += float(row.cost_usd or 0.0)
            bucket["total_latency_ms"] += int(row.latency_ms or 0)
            bucket["quality_points"] += float(audit_quality.get(int(row.audit_id), 0.0))

        for provider, bucket in provider_breakdown.items():
            total_cost = float(bucket["total_cost_usd"])
            quality_points = float(bucket["quality_points"])
            agent_count = max(1, int(bucket["agent_count"]))
            avg_latency_ms = int(bucket["total_latency_ms"] / agent_count)
            cost_per_quality_point = total_cost / quality_points if quality_points > 0.0 else None
            efficiency_score = 0.0
            if cost_per_quality_point is not None:
                efficiency_score = max(
                    0.0,
                    min(
                        100.0,
                        100.0
                        - (cost_per_quality_point * 100.0)
                        - min(avg_latency_ms / 1000.0, 20.0),
                    ),
                )
            provider_scores.append(efficiency_score)
            bucket["avg_latency_ms"] = avg_latency_ms
            bucket["cost_per_quality_point"] = (
                round(cost_per_quality_point, 4) if cost_per_quality_point is not None else None
            )
            bucket["efficiency_score"] = round(efficiency_score, 2)
            bucket["total_cost_usd"] = round(total_cost, 4)
            bucket["quality_points"] = round(quality_points, 4)

        best_provider = None
        if provider_breakdown:
            best_provider = max(
                provider_breakdown.items(),
                key=lambda item: float(item[1].get("efficiency_score") or 0.0),
            )[0]

        value = round(sum(provider_scores) / len(provider_scores), 2) if provider_scores else None
        status = "ok" if len(agent_rows) >= 3 else "insufficient_data"
        confidence = _confidence_for_data_points(len(agent_rows))
        latest_score = self.get_latest_score(
            db=db,
            project_id=project_id,
            score_type="provider_cost_efficiency",
        )
        computed_at = (
            latest_score.computed_at
            if latest_score is not None and latest_score.computed_at is not None
            else datetime.now(timezone.utc)
        )
        return ProprietaryScoreView(
            project_id=project_id,
            score_type="provider_cost_efficiency",
            score_version=SCORE_VERSION,
            status=status,
            value=value,
            confidence=confidence,
            data_points_used=len(agent_rows),
            components={
                "window_days": max(1, int(lookback_days)),
                "best_provider": best_provider,
                "provider_breakdown": provider_breakdown,
            },
            weights={
                "cost_per_quality_point_penalty": 100.0,
                "latency_penalty_cap_seconds": 20.0,
            },
            computed_at=computed_at,
        )

    def compute_provider_cost_efficiency(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        summary = self.summarize_provider_cost_efficiency(
            db=db,
            project_id=project_id,
            lookback_days=lookback_days,
        )
        score_row = self._upsert_score(
            db=db,
            project_id=project_id,
            score_type="provider_cost_efficiency",
            value=summary.value,
            confidence=summary.confidence,
            data_points_used=summary.data_points_used,
            components=summary.components,
            weights=summary.weights,
        )
        return replace(
            summary,
            computed_at=score_row.computed_at or datetime.now(timezone.utc),
        )

    def compute_remediation_impact(
        self,
        *,
        db: Session,
        project_id: int,
        lookback_days: int = 90,
    ) -> ProprietaryScoreView:
        summary = self.summarize_remediation_impact(
            db=db,
            project_id=project_id,
            lookback_days=lookback_days,
        )

        score_row = self._upsert_score(
            db=db,
            project_id=project_id,
            score_type="remediation_impact",
            value=summary.value,
            confidence=summary.confidence,
            data_points_used=summary.data_points_used,
            components=summary.components,
            weights=summary.weights,
        )
        return replace(
            summary,
            computed_at=score_row.computed_at or datetime.now(timezone.utc),
        )

    def get_latest_score(
        self,
        *,
        db: Session,
        project_id: int,
        score_type: str,
    ) -> models.ProprietaryScore | None:
        return (
            db.query(models.ProprietaryScore)
            .filter(
                models.ProprietaryScore.project_id == project_id,
                models.ProprietaryScore.score_type == score_type,
            )
            .order_by(models.ProprietaryScore.computed_at.desc(), models.ProprietaryScore.id.desc())
            .first()
        )

    @staticmethod
    def _upsert_score(
        *,
        db: Session,
        project_id: int,
        score_type: str,
        value: float | None,
        confidence: str,
        data_points_used: int,
        components: dict[str, Any],
        weights: dict[str, Any],
    ) -> models.ProprietaryScore:
        row = (
            db.query(models.ProprietaryScore)
            .filter(
                models.ProprietaryScore.project_id == project_id,
                models.ProprietaryScore.score_type == score_type,
                models.ProprietaryScore.score_version == SCORE_VERSION,
            )
            .first()
        )
        if row is None:
            row = models.ProprietaryScore(
                project_id=project_id,
                score_type=score_type,
                score_version=SCORE_VERSION,
            )
            db.add(row)

        row.value = round(float(value), 4) if value is not None else None
        row.confidence = confidence
        row.data_points_used = max(0, int(data_points_used))
        row.components_json = components
        row.weights_json = weights
        row.computed_at = datetime.now(timezone.utc)
        return row


def _confidence_for_data_points(data_points: int) -> str:
    if data_points >= 10:
        return "high"
    if data_points >= 5:
        return "medium"
    if data_points >= 3:
        return "low"
    return "insufficient"
