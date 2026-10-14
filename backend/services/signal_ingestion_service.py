from __future__ import annotations

from datetime import date, datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

import models
from services.project_audit_scope import own_project_audit_clause


DEFAULT_BATCH_SIZE = 100


def _safe_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _safe_date(value: datetime | None) -> date:
    return _safe_datetime(value).date()


def _normalize_text(value: object | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _normalize_domain(value: str | None) -> str | None:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return None
    try:
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        hostname = normalized.rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or None


def _hash_payload(value: object | None) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _extract_response_text(raw_response: Any) -> str:
    if isinstance(raw_response, str):
        return _normalize_text(raw_response)
    if not isinstance(raw_response, dict):
        return ""

    direct = raw_response.get("answer") or raw_response.get("text") or raw_response.get("content")
    if isinstance(direct, str):
        return _normalize_text(direct)

    choices = raw_response.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return _normalize_text(content)

    candidates = raw_response.get("candidates")
    if isinstance(candidates, list) and candidates:
        first_candidate = candidates[0]
        if isinstance(first_candidate, dict):
            content = first_candidate.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    text_parts = [
                        _normalize_text(part.get("text"))
                        for part in parts
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    ]
                    return _normalize_text(" ".join(part for part in text_parts if part))
    return ""


def _normalize_citation_urls(values: list[Any] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return sorted(normalized)


def _resolve_tier_class(value: str | None) -> str | None:
    normalized = _normalize_text(value).lower()
    if normalized in {"fast", "lite"}:
        return "fast"
    if normalized in {"deep", "smart", "deep_judgment"}:
        return "deep"
    return normalized or None


def _safe_int(value: object | None) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: object | None) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_debate_metadata(report: dict[str, Any]) -> dict[str, Any]:
    if isinstance(report.get("debate"), dict):
        return dict(report["debate"])
    metadata = report.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("debate"), dict):
        return dict(metadata["debate"])
    return {}


class SignalIngestionService:
    def ingest_audit(
        self,
        *,
        db: Session,
        audit: models.Audit,
        provider: str | None = None,
        tier_class: str | None = None,
        routing_mode: str | None = None,
    ) -> int:
        if audit.project_id is None:
            return 0

        project = audit.project
        if project is None:
            project = db.query(models.Project).filter(models.Project.id == audit.project_id).first()
        if project is None:
            return 0

        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}

        resolved_provider = (
            _normalize_text(
                provider or metadata.get("billing_provider") or metadata.get("provider")
            )
            or None
        )
        resolved_tier_class = _resolve_tier_class(
            tier_class
            or metadata.get("tier_class")
            or metadata.get("billing_tier")
            or metadata.get("tier")
        )
        resolved_routing_mode = (
            _normalize_text(routing_mode or metadata.get("routing_mode")) or None
        )

        snapshot_date = _safe_date(audit.created_at)
        rows_inserted = 0
        debate_metadata = _extract_debate_metadata(report)
        pipeline_type = _normalize_text(debate_metadata.get("pipeline_type")) or None
        agent_count = _safe_int(debate_metadata.get("agent_count"))
        parallel_layers = _safe_int(debate_metadata.get("parallel_layers"))
        total_debate_cost_usd = _safe_float(debate_metadata.get("total_estimated_cost_usd"))
        total_debate_latency_ms = _safe_int(debate_metadata.get("total_latency_ms"))
        evidence_anchor = (
            dict(debate_metadata.get("evidence_anchor"))
            if isinstance(debate_metadata.get("evidence_anchor"), dict)
            else None
        )

        existing_snapshots = {
            str(row.score_dimension): row
            for row in (
                db.query(models.SignalAuditSnapshot)
                .filter(models.SignalAuditSnapshot.audit_id == audit.id)
                .all()
            )
        }

        for score_dimension, score_value in (
            ("geo", audit.geo_score),
            ("seo", audit.seo_score),
            ("aeo", audit.aeo_score),
        ):
            if score_value is None:
                continue
            existing_snapshot = existing_snapshots.get(score_dimension)
            if existing_snapshot is None:
                db.add(
                    models.SignalAuditSnapshot(
                        audit_id=audit.id,
                        project_id=project.id,
                        workspace_id=project.workspace_id,
                        snapshot_date=snapshot_date,
                        score_dimension=score_dimension,
                        score_value=float(score_value),
                        provider=resolved_provider,
                        tier_class=resolved_tier_class,
                        routing_mode=resolved_routing_mode,
                        pipeline_type=pipeline_type,
                        agent_count=agent_count,
                        parallel_layers=parallel_layers,
                        total_debate_cost_usd=total_debate_cost_usd,
                        total_debate_latency_ms=total_debate_latency_ms,
                        evidence_anchor_json=evidence_anchor,
                    )
                )
                rows_inserted += 1
                continue

            changed = False
            if existing_snapshot.provider != resolved_provider and resolved_provider is not None:
                existing_snapshot.provider = resolved_provider
                changed = True
            if (
                existing_snapshot.tier_class != resolved_tier_class
                and resolved_tier_class is not None
            ):
                existing_snapshot.tier_class = resolved_tier_class
                changed = True
            if (
                existing_snapshot.routing_mode != resolved_routing_mode
                and resolved_routing_mode is not None
            ):
                existing_snapshot.routing_mode = resolved_routing_mode
                changed = True
            if existing_snapshot.pipeline_type != pipeline_type and pipeline_type is not None:
                existing_snapshot.pipeline_type = pipeline_type
                changed = True
            if existing_snapshot.agent_count != agent_count and agent_count is not None:
                existing_snapshot.agent_count = agent_count
                changed = True
            if existing_snapshot.parallel_layers != parallel_layers and parallel_layers is not None:
                existing_snapshot.parallel_layers = parallel_layers
                changed = True
            if (
                existing_snapshot.total_debate_cost_usd != total_debate_cost_usd
                and total_debate_cost_usd is not None
            ):
                existing_snapshot.total_debate_cost_usd = total_debate_cost_usd
                changed = True
            if (
                existing_snapshot.total_debate_latency_ms != total_debate_latency_ms
                and total_debate_latency_ms is not None
            ):
                existing_snapshot.total_debate_latency_ms = total_debate_latency_ms
                changed = True
            if (
                existing_snapshot.evidence_anchor_json != evidence_anchor
                and evidence_anchor is not None
            ):
                existing_snapshot.evidence_anchor_json = evidence_anchor
                changed = True
            if changed:
                rows_inserted += 1

        if pipeline_type:
            rows_inserted += self._ingest_v3_debate_signals(
                db=db,
                audit=audit,
                debate_metadata=debate_metadata,
                pipeline_type=pipeline_type,
                snapshot_date=snapshot_date,
            )

        rows_inserted += self._ingest_entity_observations(db=db, audit=audit)
        rows_inserted += self._ingest_task_outcomes_for_audit(db=db, audit=audit)
        return rows_inserted

    def ingest_visibility_batch(self, *, db: Session, batch: models.VisibilityRunBatch) -> int:
        if batch.project_id is None:
            return 0

        runs = list(batch.runs or [])
        if not runs:
            runs = (
                db.query(models.VisibilityRun)
                .filter(models.VisibilityRun.batch_id == batch.id)
                .order_by(models.VisibilityRun.id.asc())
                .all()
            )
        if not runs:
            return 0

        previous_batch = (
            db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == batch.project_id,
                models.VisibilityRunBatch.topic == batch.topic,
                models.VisibilityRunBatch.provider == batch.provider,
                models.VisibilityRunBatch.id != batch.id,
                models.VisibilityRunBatch.created_at < _safe_datetime(batch.created_at),
            )
            .order_by(
                models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc()
            )
            .first()
        )

        previous_citations_hash: str | None = None
        previous_response_text: str | None = None
        if previous_batch is not None:
            previous_event = (
                db.query(models.SignalCitationEvent)
                .filter(models.SignalCitationEvent.visibility_run_batch_id == previous_batch.id)
                .order_by(models.SignalCitationEvent.id.desc())
                .first()
            )
            if previous_event is not None:
                previous_citations_hash = previous_event.citations_hash

            previous_run = (
                db.query(models.VisibilityRun)
                .filter(models.VisibilityRun.batch_id == previous_batch.id)
                .order_by(models.VisibilityRun.id.desc())
                .first()
            )
            if previous_run is not None:
                previous_response_text = _extract_response_text(previous_run.raw_response)

        rows_inserted = 0
        snapshot_date = _safe_date(batch.completed_at or batch.created_at)
        normalized_target = _normalize_domain(batch.target_domain)

        for run in runs:
            already_exists = (
                db.query(models.SignalCitationEvent.id)
                .filter(models.SignalCitationEvent.visibility_run_id == run.id)
                .first()
            )
            if already_exists is not None:
                continue

            citations = _normalize_citation_urls(list(run.valid_citations or []))
            citations_hash = _hash_payload(citations) if citations else None
            response_text = _extract_response_text(run.raw_response)
            similarity_score = (
                SequenceMatcher(None, previous_response_text, response_text).ratio()
                if previous_response_text and response_text
                else None
            )

            cited_domain: str | None = None
            citation_present = len(citations) > 0
            if normalized_target is not None:
                citation_present = False
                for citation in citations:
                    citation_domain = _normalize_domain(citation)
                    if citation_domain is None:
                        continue
                    if citation_domain == normalized_target or citation_domain.endswith(
                        f".{normalized_target}"
                    ):
                        cited_domain = citation_domain
                        citation_present = True
                        break
            elif citations:
                cited_domain = _normalize_domain(citations[0])

            answer_changed = False
            if (
                previous_citations_hash
                and citations_hash
                and previous_citations_hash != citations_hash
            ):
                answer_changed = True
            if similarity_score is not None and similarity_score < 0.92:
                answer_changed = True

            db.add(
                models.SignalCitationEvent(
                    visibility_run_batch_id=batch.id,
                    visibility_run_id=run.id,
                    project_id=batch.project_id,
                    snapshot_date=snapshot_date,
                    provider=str(batch.provider or run.provider or "unknown"),
                    query_hash=_hash_payload(_normalize_text(batch.topic)),
                    domain_cited=cited_domain,
                    citation_present=citation_present,
                    answer_changed=answer_changed,
                    citations_hash=citations_hash,
                    text_similarity_score=round(float(similarity_score), 4)
                    if similarity_score is not None
                    else None,
                )
            )
            rows_inserted += 1

        return rows_inserted

    def _ingest_v3_debate_signals(
        self,
        *,
        db: Session,
        audit: models.Audit,
        debate_metadata: dict[str, Any],
        pipeline_type: str,
        snapshot_date: date,
    ) -> int:
        if audit.project_id is None:
            return 0

        rows_inserted = 0
        existing_agent_facts = {
            str(row.agent_role): row
            for row in (
                db.query(models.SignalDebateAgentFact)
                .filter(models.SignalDebateAgentFact.audit_id == audit.id)
                .all()
            )
        }

        for agent_data in debate_metadata.get("per_agent_costs") or []:
            if not isinstance(agent_data, dict):
                continue
            agent_role = _normalize_text(agent_data.get("role")) or "unknown"
            tokens = agent_data.get("tokens") if isinstance(agent_data.get("tokens"), dict) else {}
            agent_layer = _safe_int(agent_data.get("layer")) or 0
            provider = _normalize_text(agent_data.get("provider")) or "unknown"
            model = _normalize_text(agent_data.get("model")) or "unknown"
            latency_ms = _safe_int(agent_data.get("latency_ms"))
            cost_usd = _safe_float(agent_data.get("cost_usd"))
            prompt_tokens = _safe_int(tokens.get("prompt"))
            completion_tokens = _safe_int(tokens.get("completion"))

            existing_fact = existing_agent_facts.get(agent_role)
            if existing_fact is None:
                db.add(
                    models.SignalDebateAgentFact(
                        audit_id=audit.id,
                        project_id=audit.project_id,
                        snapshot_date=snapshot_date,
                        pipeline_type=pipeline_type,
                        agent_role=agent_role,
                        agent_layer=agent_layer,
                        provider=provider,
                        model=model,
                        latency_ms=latency_ms,
                        cost_usd=cost_usd,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                )
                rows_inserted += 1
                continue

            changed = False
            if existing_fact.pipeline_type != pipeline_type:
                existing_fact.pipeline_type = pipeline_type
                changed = True
            if existing_fact.agent_layer != agent_layer:
                existing_fact.agent_layer = agent_layer
                changed = True
            if existing_fact.provider != provider:
                existing_fact.provider = provider
                changed = True
            if existing_fact.model != model:
                existing_fact.model = model
                changed = True
            if existing_fact.latency_ms != latency_ms:
                existing_fact.latency_ms = latency_ms
                changed = True
            if existing_fact.cost_usd != cost_usd:
                existing_fact.cost_usd = cost_usd
                changed = True
            if existing_fact.prompt_tokens != prompt_tokens:
                existing_fact.prompt_tokens = prompt_tokens
                changed = True
            if existing_fact.completion_tokens != completion_tokens:
                existing_fact.completion_tokens = completion_tokens
                changed = True
            if changed:
                rows_inserted += 1

        rows_inserted += self._ingest_claim_disposition_facts(
            db=db,
            audit=audit,
            pipeline_type=pipeline_type,
            snapshot_date=snapshot_date,
            debate_metadata=debate_metadata,
        )
        return rows_inserted

    def _ingest_claim_disposition_facts(
        self,
        *,
        db: Session,
        audit: models.Audit,
        pipeline_type: str,
        snapshot_date: date,
        debate_metadata: dict[str, Any],
    ) -> int:
        if audit.project_id is None:
            return 0

        domain_stats: dict[str, dict[str, int]] = {}
        consolidated = (
            debate_metadata.get("consolidated_claim_disposition")
            if isinstance(debate_metadata.get("consolidated_claim_disposition"), list)
            else []
        )
        for claim in consolidated:
            if not isinstance(claim, dict):
                continue
            domain = _normalize_text(claim.get("domain")) or "mixed"
            stats = domain_stats.setdefault(
                domain,
                {
                    "generated": 0,
                    "accepted": 0,
                    "downgraded": 0,
                    "rejected": 0,
                    "needs_manual_review": 0,
                    "deduplicated": 0,
                },
            )
            stats["generated"] += 1
            disposition = (_normalize_text(claim.get("disposition")) or "").lower()
            if disposition in stats:
                stats[disposition] += 1

        if not domain_stats:
            judge_summary = (
                debate_metadata.get("judge_summary")
                if isinstance(debate_metadata.get("judge_summary"), dict)
                else {}
            )
            accepted = _safe_int(judge_summary.get("accepted_claims")) or 0
            downgraded = _safe_int(judge_summary.get("downgraded_claims")) or 0
            rejected = _safe_int(judge_summary.get("rejected_claims")) or 0
            manual_review = _safe_int(judge_summary.get("unresolved_disputes")) or 0
            generated = accepted + downgraded + rejected + manual_review
            if generated > 0:
                domain_stats["mixed"] = {
                    "generated": generated,
                    "accepted": accepted,
                    "downgraded": downgraded,
                    "rejected": rejected,
                    "needs_manual_review": manual_review,
                    "deduplicated": 0,
                }

        if not domain_stats:
            return 0

        existing_rows = {
            str(row.domain): row
            for row in (
                db.query(models.SignalClaimDispositionFact)
                .filter(models.SignalClaimDispositionFact.audit_id == audit.id)
                .all()
            )
        }
        debate_confidence_score = _safe_float(debate_metadata.get("debate_confidence_score"))
        rows_inserted = 0

        for domain, stats in domain_stats.items():
            existing_row = existing_rows.get(domain)
            if existing_row is None:
                db.add(
                    models.SignalClaimDispositionFact(
                        audit_id=audit.id,
                        project_id=audit.project_id,
                        snapshot_date=snapshot_date,
                        pipeline_type=pipeline_type,
                        domain=domain,
                        claims_generated=stats["generated"],
                        claims_accepted=stats["accepted"],
                        claims_downgraded=stats["downgraded"],
                        claims_rejected=stats["rejected"],
                        claims_needs_manual_review=stats["needs_manual_review"],
                        claims_deduplicated=stats["deduplicated"],
                        debate_confidence_score=debate_confidence_score,
                    )
                )
                rows_inserted += 1
                continue

            changed = False
            if existing_row.pipeline_type != pipeline_type:
                existing_row.pipeline_type = pipeline_type
                changed = True
            if existing_row.claims_generated != stats["generated"]:
                existing_row.claims_generated = stats["generated"]
                changed = True
            if existing_row.claims_accepted != stats["accepted"]:
                existing_row.claims_accepted = stats["accepted"]
                changed = True
            if existing_row.claims_downgraded != stats["downgraded"]:
                existing_row.claims_downgraded = stats["downgraded"]
                changed = True
            if existing_row.claims_rejected != stats["rejected"]:
                existing_row.claims_rejected = stats["rejected"]
                changed = True
            if existing_row.claims_needs_manual_review != stats["needs_manual_review"]:
                existing_row.claims_needs_manual_review = stats["needs_manual_review"]
                changed = True
            if existing_row.claims_deduplicated != stats["deduplicated"]:
                existing_row.claims_deduplicated = stats["deduplicated"]
                changed = True
            if existing_row.debate_confidence_score != debate_confidence_score:
                existing_row.debate_confidence_score = debate_confidence_score
                changed = True
            if changed:
                rows_inserted += 1
        return rows_inserted

    def record_remediation_outcome(
        self,
        *,
        db: Session,
        task: models.ProjectTask,
        audit_before: models.Audit,
        audit_after: models.Audit,
    ) -> models.SignalRemediationOutcome | None:
        existing = (
            db.query(models.SignalRemediationOutcome)
            .filter(
                models.SignalRemediationOutcome.project_task_id == task.id,
                models.SignalRemediationOutcome.audit_after_id == audit_after.id,
            )
            .first()
        )
        if existing is not None:
            return None

        before_geo = float(audit_before.geo_score) if audit_before.geo_score is not None else None
        after_geo = float(audit_after.geo_score) if audit_after.geo_score is not None else None
        before_aeo = float(audit_before.aeo_score) if audit_before.aeo_score is not None else None
        after_aeo = float(audit_after.aeo_score) if audit_after.aeo_score is not None else None

        completed_at = _safe_datetime(task.resolved_at) if task.resolved_at else None
        after_created = _safe_datetime(audit_after.created_at)
        days_to_impact = None
        if completed_at is not None:
            days_to_impact = max(0, (after_created.date() - completed_at.date()).days)

        outcome = models.SignalRemediationOutcome(
            project_task_id=task.id,
            project_id=task.project_id,
            completed_at=completed_at,
            recommendation_category=_normalize_text(task.category) or None,
            before_score_geo=before_geo,
            after_score_geo=after_geo,
            score_delta_geo=(after_geo - before_geo)
            if before_geo is not None and after_geo is not None
            else None,
            before_score_aeo=before_aeo,
            after_score_aeo=after_aeo,
            score_delta_aeo=(after_aeo - before_aeo)
            if before_aeo is not None and after_aeo is not None
            else None,
            days_to_impact=days_to_impact,
            audit_before_id=audit_before.id,
            audit_after_id=audit_after.id,
        )
        db.add(outcome)
        return outcome

    def backfill_all(
        self,
        *,
        db: Session,
        dry_run: bool = False,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> dict[str, Any]:
        rows_inserted = 0
        audits_processed = 0
        v3_audits_processed = 0
        batches_processed = 0
        errors: list[str] = []

        last_audit_id = 0
        while True:
            audits = (
                db.query(models.Audit)
                .filter(
                    models.Audit.id > last_audit_id,
                    models.Audit.project_id.isnot(None),
                )
                .order_by(models.Audit.id.asc())
                .limit(max(1, int(batch_size)))
                .all()
            )
            if not audits:
                break

            for audit in audits:
                audits_processed += 1
                try:
                    debate_metadata = _extract_debate_metadata(
                        audit.full_report if isinstance(audit.full_report, dict) else {}
                    )
                    if _normalize_text(debate_metadata.get("pipeline_type")):
                        v3_audits_processed += 1
                    rows_inserted += self.ingest_audit(db=db, audit=audit)
                except Exception as exc:  # pragma: no cover - defensive telemetry path
                    errors.append(f"audit:{audit.id}:{exc}")
            last_audit_id = audits[-1].id

        last_batch_id = 0
        while True:
            batches = (
                db.query(models.VisibilityRunBatch)
                .filter(
                    models.VisibilityRunBatch.id > last_batch_id,
                    models.VisibilityRunBatch.project_id.isnot(None),
                )
                .order_by(models.VisibilityRunBatch.id.asc())
                .limit(max(1, int(batch_size)))
                .all()
            )
            if not batches:
                break

            for batch in batches:
                batches_processed += 1
                try:
                    rows_inserted += self.ingest_visibility_batch(db=db, batch=batch)
                except Exception as exc:  # pragma: no cover - defensive telemetry path
                    errors.append(f"visibility_batch:{batch.id}:{exc}")
            last_batch_id = batches[-1].id

        if dry_run:
            db.rollback()
        else:
            db.flush()

        return {
            "audits_processed": audits_processed,
            "v3_audits_processed": v3_audits_processed,
            "batches_processed": batches_processed,
            "rows_inserted": rows_inserted,
            "errors": errors,
        }

    def _ingest_entity_observations(self, *, db: Session, audit: models.Audit) -> int:
        if audit.project_id is None:
            return 0

        facts = (
            db.query(models.SiteEntityFact)
            .filter(models.SiteEntityFact.audit_id == audit.id)
            .order_by(models.SiteEntityFact.id.asc())
            .all()
        )
        if not facts:
            return 0

        existing_keys = {
            str(row.entity_key)
            for row in (
                db.query(models.SignalEntityObservation.entity_key)
                .filter(models.SignalEntityObservation.audit_id == audit.id)
                .all()
            )
        }

        aggregated: dict[str, dict[str, Any]] = {}
        for fact in facts:
            entity_key = _normalize_text(fact.entity_key)
            if not entity_key:
                continue
            item = aggregated.setdefault(
                entity_key,
                {
                    "entity_category": _normalize_text(fact.entity_category) or "Unknown",
                    "scores": [],
                    "mention_frequency": 0,
                },
            )
            if isinstance(fact.relevance_score, (int, float)):
                item["scores"].append(float(fact.relevance_score))
            item["mention_frequency"] = int(item["mention_frequency"]) + 1

        rows_inserted = 0
        snapshot_date = _safe_date(audit.created_at)
        for entity_key, payload in aggregated.items():
            if entity_key in existing_keys:
                continue
            relevance_scores = payload["scores"]
            relevance_score = (
                round(sum(relevance_scores) / len(relevance_scores), 4)
                if relevance_scores
                else None
            )
            db.add(
                models.SignalEntityObservation(
                    audit_id=audit.id,
                    project_id=audit.project_id,
                    snapshot_date=snapshot_date,
                    entity_key=entity_key,
                    entity_category=str(payload["entity_category"]),
                    relevance_score=relevance_score,
                    mention_frequency=max(1, int(payload["mention_frequency"])),
                )
            )
            rows_inserted += 1
        return rows_inserted

    def _ingest_task_outcomes_for_audit(self, *, db: Session, audit: models.Audit) -> int:
        if audit.project_id is None:
            return 0

        tasks = (
            db.query(models.ProjectTask)
            .filter(
                models.ProjectTask.project_id == audit.project_id,
                models.ProjectTask.verification_audit_id == audit.id,
                models.ProjectTask.status == models.ProjectTaskStatus.DONE,
            )
            .all()
        )
        if not tasks:
            return 0

        rows_inserted = 0
        for task in tasks:
            before_audit = None
            if task.source_audit_id is not None and task.source_audit_id != audit.id:
                before_audit = (
                    db.query(models.Audit).filter(models.Audit.id == task.source_audit_id).first()
                )
            if before_audit is None:
                # SIGV2-1117: the "before" baseline is a score of this project,
                # so it must be one of the project's own audits.
                before_audit = (
                    db.query(models.Audit)
                    .filter(
                        models.Audit.project_id == audit.project_id,
                        own_project_audit_clause(),
                        models.Audit.id < audit.id,
                    )
                    .order_by(models.Audit.id.desc())
                    .first()
                )
            if before_audit is None:
                continue

            created = self.record_remediation_outcome(
                db=db,
                task=task,
                audit_before=before_audit,
                audit_after=audit,
            )
            if created is not None:
                rows_inserted += 1
        return rows_inserted
