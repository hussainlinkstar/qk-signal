from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import models
from sqlalchemy.orm import Session


@dataclass
class EntityMention:
    name: str
    category: str
    relevance_score: float | None
    source: str


class SiteEntityFactService:
    _CATEGORY_MAP = {
        "PERSON": "Person",
        "ORG": "Org",
        "ORGANIZATION": "Org",
        "COMPANY": "Org",
        "CONCEPT": "Concept",
        "TOPIC": "Concept",
        "PRODUCT": "Product",
        "SERVICE": "Service",
        "LOCATION": "Location",
        "PLACE": "Location",
        "EVENT": "Event",
    }

    _RELEVANCE_KEYS = (
        "relevance_score",
        "relevance",
        "score",
        "confidence",
    )

    def replace_audit_facts(
        self,
        *,
        db: Session,
        site_id: int,
        audit_id: int,
        report: dict[str, Any],
        created_at: datetime | None,
    ) -> int:
        db.query(models.SiteEntityFact).filter(models.SiteEntityFact.audit_id == audit_id).delete()
        rows = self.build_fact_rows(
            site_id=site_id,
            audit_id=audit_id,
            report=report,
            created_at=created_at,
        )
        if rows:
            db.bulk_insert_mappings(models.SiteEntityFact, rows)
        return len(rows)

    @classmethod
    def build_fact_rows(
        cls,
        *,
        site_id: int,
        audit_id: int,
        report: dict[str, Any],
        created_at: datetime | None,
    ) -> list[dict[str, Any]]:
        mentions = cls.extract_mentions(report)
        if not mentions:
            return []

        geo_queries = cls._extract_geo_queries(report)
        aeo_relevance = cls._extract_aeo_relevance(report)
        answer_excerpt = cls._extract_aeo_answer_excerpt(report)

        aggregated: dict[str, dict[str, Any]] = {}
        for mention in mentions:
            key = cls.normalize_key(mention.name)
            if not key:
                continue
            bucket = aggregated.get(key)
            if bucket is None:
                bucket = {
                    "entity_name": mention.name,
                    "entity_key": key,
                    "entity_category": mention.category,
                    "score_sum": 0.0,
                    "score_count": 0,
                    "sources": set(),
                    "frequency": 0,
                }
                aggregated[key] = bucket

            bucket["frequency"] += 1
            bucket["sources"].add(mention.source)
            if bucket["entity_category"] == "Unknown" and mention.category != "Unknown":
                bucket["entity_category"] = mention.category
            if mention.relevance_score is not None:
                bucket["score_sum"] += mention.relevance_score
                bucket["score_count"] += 1

        rows: list[dict[str, Any]] = []
        for key, bucket in aggregated.items():
            relevance_score = (
                round(bucket["score_sum"] / bucket["score_count"], 3)
                if bucket["score_count"]
                else None
            )
            geo_signal = cls._entity_geo_signal(entity_key=key, geo_queries=geo_queries)
            aeo_signal = cls._entity_aeo_signal(
                entity_key=key,
                answer_excerpt=answer_excerpt,
                answer_relevance=aeo_relevance,
            )
            ai_importance = cls._compute_ai_importance(
                relevance_score=relevance_score,
                frequency=int(bucket["frequency"]),
                geo_signal=geo_signal,
                aeo_signal=aeo_signal,
            )
            rows.append(
                {
                    "site_id": site_id,
                    "audit_id": audit_id,
                    "entity_name": bucket["entity_name"],
                    "entity_key": key,
                    "entity_category": bucket["entity_category"],
                    "relevance_score": relevance_score,
                    "ai_importance": ai_importance,
                    "source": ",".join(sorted(bucket["sources"])),
                    "created_at": created_at,
                }
            )
        return rows

    @classmethod
    def extract_mentions(cls, report: dict[str, Any]) -> list[EntityMention]:
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        raw_candidates: list[tuple[str, Any]] = [
            ("full_report.entities", report.get("entities")),
            ("full_report.entities_detected", report.get("entities_detected")),
            ("analysis.entities", analysis.get("entities")),
            ("analysis.entities_detected", analysis.get("entities_detected")),
            ("full_report.entity_data", report.get("entity_data")),
            ("analysis.entity_data", analysis.get("entity_data")),
            ("full_report.entity_map", report.get("entity_map")),
            ("analysis.entity_map", analysis.get("entity_map")),
            ("full_report.entity_summary", report.get("entity_summary")),
            ("analysis.entity_summary", analysis.get("entity_summary")),
        ]

        mentions: list[EntityMention] = []
        for source, candidate in raw_candidates:
            mentions.extend(cls._parse_entity_payload(candidate, source=source))
        return mentions

    @classmethod
    def _parse_entity_payload(cls, payload: Any, *, source: str) -> list[EntityMention]:
        if payload is None:
            return []

        if isinstance(payload, str):
            name = payload.strip()
            return (
                [EntityMention(name=name, category="Unknown", relevance_score=None, source=source)]
                if name
                else []
            )

        if isinstance(payload, list):
            mentions: list[EntityMention] = []
            for item in payload:
                mentions.extend(cls._parse_entity_payload(item, source=source))
            return mentions

        if isinstance(payload, dict):
            if "entities" in payload:
                return cls._parse_entity_payload(payload.get("entities"), source=source)
            if "items" in payload:
                return cls._parse_entity_payload(payload.get("items"), source=source)

            direct_name = cls._extract_name(payload)
            if direct_name:
                return [
                    EntityMention(
                        name=direct_name,
                        category=cls._resolve_category(payload),
                        relevance_score=cls._extract_relevance(payload),
                        source=source,
                    )
                ]

            mentions: list[EntityMention] = []
            for key, value in payload.items():
                if not isinstance(key, str) or not key.strip():
                    continue
                if isinstance(value, dict):
                    mentions.append(
                        EntityMention(
                            name=key.strip(),
                            category=cls._resolve_category(value),
                            relevance_score=cls._extract_relevance(value),
                            source=source,
                        )
                    )
                elif isinstance(value, (int, float)):
                    mentions.append(
                        EntityMention(
                            name=key.strip(),
                            category="Unknown",
                            relevance_score=cls._coerce_score(value),
                            source=source,
                        )
                    )
                elif isinstance(value, str):
                    mentions.append(
                        EntityMention(
                            name=value.strip() or key.strip(),
                            category="Unknown",
                            relevance_score=None,
                            source=source,
                        )
                    )
            return mentions

        return []

    @classmethod
    def _extract_name(cls, payload: dict[str, Any]) -> str | None:
        for key in ("name", "entity", "label", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _extract_relevance(cls, payload: dict[str, Any]) -> float | None:
        for key in cls._RELEVANCE_KEYS:
            if key in payload:
                score = cls._coerce_score(payload.get(key))
                if score is not None:
                    return score
        return None

    @classmethod
    def _coerce_score(cls, raw_value: Any) -> float | None:
        candidate = raw_value
        if isinstance(raw_value, dict):
            candidate = raw_value.get("score")
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            return None
        return round(max(0.0, min(100.0, value)), 3)

    @classmethod
    def _resolve_category(cls, payload: dict[str, Any]) -> str:
        for key in ("category", "type", "entity_type"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
                return cls._CATEGORY_MAP.get(normalized, value.strip().title())
        return "Unknown"

    @staticmethod
    def normalize_key(name: str) -> str:
        return " ".join(name.casefold().split())

    @staticmethod
    def _extract_geo_queries(report: dict[str, Any]) -> list[tuple[str, bool]]:
        geo_visibility = (
            report.get("geo_visibility") if isinstance(report.get("geo_visibility"), dict) else {}
        )
        results = (
            geo_visibility.get("results") if isinstance(geo_visibility.get("results"), list) else []
        )
        queries: list[tuple[str, bool]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip().lower()
            if not query:
                continue
            queries.append((query, bool(item.get("brand_cited"))))
        return queries

    @classmethod
    def _extract_aeo_relevance(cls, report: dict[str, Any]) -> float | None:
        aeo_section = report.get("aeo") if isinstance(report.get("aeo"), dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}

        for candidate in (
            aeo_section.get("answer_relevance"),
            aeo_section.get("answer_relevance_score"),
            report.get("answer_relevance"),
            analysis.get("answer_relevance"),
        ):
            score = cls._coerce_score(candidate)
            if score is not None:
                return score
        return None

    @staticmethod
    def _extract_aeo_answer_excerpt(report: dict[str, Any]) -> str:
        aeo_section = report.get("aeo") if isinstance(report.get("aeo"), dict) else {}
        for candidate in (
            aeo_section.get("answer_excerpt"),
            aeo_section.get("answer"),
            report.get("answer_excerpt"),
            report.get("answer"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.casefold()
        return ""

    @classmethod
    def _entity_geo_signal(cls, *, entity_key: str, geo_queries: list[tuple[str, bool]]) -> float:
        signal = 0.0
        for query, brand_cited in geo_queries:
            if entity_key in query:
                signal += 10.0
                if brand_cited:
                    signal += 5.0
        return min(30.0, signal)

    @staticmethod
    def _entity_aeo_signal(
        *,
        entity_key: str,
        answer_excerpt: str,
        answer_relevance: float | None,
    ) -> float:
        signal = 0.0
        if answer_excerpt and entity_key in answer_excerpt:
            signal += 8.0
        if answer_relevance is not None:
            signal += min(12.0, answer_relevance * 0.12)
        return min(20.0, signal)

    @staticmethod
    def _compute_ai_importance(
        *,
        relevance_score: float | None,
        frequency: int,
        geo_signal: float,
        aeo_signal: float,
    ) -> float:
        normalized_relevance = (relevance_score or 0.0) * 0.55
        frequency_bonus = min(10.0, float(max(1, frequency)) * 2.5)
        return round(
            min(100.0, normalized_relevance + frequency_bonus + geo_signal + aeo_signal), 3
        )
