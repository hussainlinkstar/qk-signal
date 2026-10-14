from __future__ import annotations

from datetime import datetime
from typing import Any

import models
from services.site_entity_facts import SiteEntityFactService
from sqlalchemy import func
from sqlalchemy.orm import Session


class SiteMapService:
    def __init__(self) -> None:
        self._fact_service = SiteEntityFactService()

    def build_site_map(self, *, db: Session, site_id: int) -> dict[str, Any]:
        audit_count, last_seen_at = (
            db.query(func.count(models.Audit.id), func.max(models.Audit.created_at))
            .filter(models.Audit.site_id == site_id)
            .one()
        )

        if not audit_count:
            return {
                "site_id": site_id,
                "audit_count": 0,
                "last_seen_at": None,
                "entities": [],
            }

        facts = (
            db.query(models.SiteEntityFact)
            .filter(models.SiteEntityFact.site_id == site_id)
            .order_by(models.SiteEntityFact.created_at.desc(), models.SiteEntityFact.id.desc())
            .all()
        )

        if facts:
            entities = self._aggregate_from_facts(facts)
            return {
                "site_id": site_id,
                "audit_count": int(audit_count),
                "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
                "entities": entities,
            }

        return self._build_from_full_report(db=db, site_id=site_id)

    def _build_from_full_report(self, *, db: Session, site_id: int) -> dict[str, Any]:
        audits = (
            db.query(models.Audit)
            .filter(models.Audit.site_id == site_id)
            .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
            .all()
        )

        if not audits:
            return {
                "site_id": site_id,
                "audit_count": 0,
                "last_seen_at": None,
                "entities": [],
            }

        aggregated: dict[str, dict[str, Any]] = {}
        last_seen_at: datetime | None = None

        for audit in audits:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            mentions = self._fact_service.extract_mentions(report)
            for mention in mentions:
                normalized_key = self._fact_service.normalize_key(mention.name)
                if not normalized_key:
                    continue

                bucket = aggregated.get(normalized_key)
                if bucket is None:
                    bucket = {
                        "name": mention.name,
                        "normalized_key": normalized_key,
                        "frequency": 0,
                        "score_sum": 0.0,
                        "score_count": 0,
                        "category": mention.category,
                    }
                    aggregated[normalized_key] = bucket

                bucket["frequency"] += 1
                if mention.relevance_score is not None:
                    bucket["score_sum"] += mention.relevance_score
                    bucket["score_count"] += 1
                if bucket["category"] == "Unknown" and mention.category != "Unknown":
                    bucket["category"] = mention.category

            if audit.created_at and (last_seen_at is None or audit.created_at > last_seen_at):
                last_seen_at = audit.created_at

        return {
            "site_id": site_id,
            "audit_count": len(audits),
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
            "entities": self._build_sorted_payload(list(aggregated.values())),
        }

    def _aggregate_from_facts(self, facts: list[models.SiteEntityFact]) -> list[dict[str, Any]]:
        aggregated: dict[str, dict[str, Any]] = {}
        for fact in facts:
            key = self._fact_service.normalize_key(fact.entity_key or fact.entity_name)
            if not key:
                continue

            bucket = aggregated.get(key)
            if bucket is None:
                bucket = {
                    "name": fact.entity_name,
                    "normalized_key": key,
                    "frequency": 0,
                    "score_sum": 0.0,
                    "score_count": 0,
                    "category": fact.entity_category or "Unknown",
                }
                aggregated[key] = bucket

            bucket["frequency"] += 1
            if isinstance(fact.relevance_score, (int, float)):
                bucket["score_sum"] += float(fact.relevance_score)
                bucket["score_count"] += 1
            if (
                bucket["category"] == "Unknown"
                and fact.entity_category
                and fact.entity_category != "Unknown"
            ):
                bucket["category"] = fact.entity_category

        return self._build_sorted_payload(list(aggregated.values()))

    @staticmethod
    def _build_sorted_payload(aggregated_values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for item in aggregated_values:
            avg_score = (
                round(item["score_sum"] / item["score_count"], 3) if item["score_count"] else 0.0
            )
            entities.append(
                {
                    "name": item["name"],
                    "normalized_key": item["normalized_key"],
                    "frequency": item["frequency"],
                    "avg_relevance_score": avg_score,
                    "category": item["category"],
                }
            )

        entities.sort(
            key=lambda entry: (
                -entry["frequency"],
                -entry["avg_relevance_score"],
                entry["name"].lower(),
            )
        )
        return entities
