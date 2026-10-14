from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from services.entity_graph_service import EntityGraphService
from services.project_audit_scope import own_project_audit_clause
from services.site_entity_facts import SiteEntityFactService


COMPUTATION_VERSION = "v1"


@dataclass(frozen=True)
class EntityGap:
    entity_key: str
    entity_name: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "entity_key": self.entity_key,
            "entity_name": self.entity_name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EntityScoreSnapshot:
    authority_score: float
    coverage_score: float
    depth_score: float
    consistency_score: float
    uniqueness_score: float
    target_entity_count: int
    detected_entity_count: int
    gap_count: int
    computed_at: datetime
    computation_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "authority_score": self.authority_score,
            "coverage_score": self.coverage_score,
            "depth_score": self.depth_score,
            "consistency_score": self.consistency_score,
            "uniqueness_score": self.uniqueness_score,
            "target_entity_count": self.target_entity_count,
            "detected_entity_count": self.detected_entity_count,
            "gap_count": self.gap_count,
            "computed_at": self.computed_at.isoformat(),
            "computation_version": self.computation_version,
        }


@dataclass(frozen=True)
class EntityAuthorityResult:
    project_id: int
    authority_score: float
    coverage_score: float
    depth_score: float
    consistency_score: float
    uniqueness_score: float
    target_entity_count: int
    detected_entity_count: int
    gap_count: int
    computed_at: datetime
    computation_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "authority_score": self.authority_score,
            "breakdown": {
                "coverage": self.coverage_score,
                "depth": self.depth_score,
                "consistency": self.consistency_score,
                "uniqueness": self.uniqueness_score,
            },
            "target_entities": self.target_entity_count,
            "detected_entities": self.detected_entity_count,
            "gap_count": self.gap_count,
            "computed_at": self.computed_at.isoformat(),
            "computation_version": self.computation_version,
        }


@dataclass
class _EntitySignal:
    entity_key: str
    entity_name: str
    category: str
    frequency: int = 0
    relevance_scores: list[float] | None = None
    audits: set[int] | None = None

    def __post_init__(self) -> None:
        if self.relevance_scores is None:
            self.relevance_scores = []
        if self.audits is None:
            self.audits = set()

    @property
    def avg_relevance(self) -> float:
        if not self.relevance_scores:
            return 0.0
        return sum(self.relevance_scores) / len(self.relevance_scores)


class EntityAuthorityService:
    def __init__(self) -> None:
        self._graph_service = EntityGraphService()

    def compute_score(self, *, db: Session, project_id: int) -> EntityAuthorityResult:
        project = self._require_project(db=db, project_id=project_id)
        audits = self._load_project_audits(db=db, project_id=project.id)
        entity_signals, per_audit_entities = self._collect_entity_signals(audits=audits)
        target_entities = self._target_entities(project=project)
        target_keys = set(target_entities.keys())
        detected_keys = set(entity_signals.keys())

        matched_targets = target_keys.intersection(detected_keys)
        missing_targets = target_keys.difference(detected_keys)

        coverage_score = self._coverage_score(
            target_count=len(target_keys),
            matched_count=len(matched_targets),
        )
        depth_score = self._depth_score(entity_signals=entity_signals)
        consistency_score = self._consistency_score(
            audit_ids=[audit.id for audit in audits],
            per_audit_entities=per_audit_entities,
            target_keys=target_keys,
            detected_keys=detected_keys,
        )
        uniqueness_score = self._uniqueness_score(
            db=db,
            project=project,
            detected_keys=detected_keys,
        )

        authority_score = round(
            (coverage_score * 0.40)
            + (depth_score * 0.35)
            + (consistency_score * 0.15)
            + (uniqueness_score * 0.10),
            2,
        )

        snapshot = models.EntityAuthoritySnapshot(
            project_id=project.id,
            authority_score=authority_score,
            coverage_score=coverage_score,
            depth_score=depth_score,
            consistency_score=consistency_score,
            uniqueness_score=uniqueness_score,
            target_entity_count=len(target_keys),
            detected_entity_count=len(detected_keys),
            gap_count=len(missing_targets),
            computation_version=COMPUTATION_VERSION,
        )
        db.add(snapshot)
        db.flush()

        computed_at = snapshot.computed_at or datetime.now(timezone.utc)
        return EntityAuthorityResult(
            project_id=project.id,
            authority_score=authority_score,
            coverage_score=coverage_score,
            depth_score=depth_score,
            consistency_score=consistency_score,
            uniqueness_score=uniqueness_score,
            target_entity_count=len(target_keys),
            detected_entity_count=len(detected_keys),
            gap_count=len(missing_targets),
            computed_at=computed_at,
            computation_version=COMPUTATION_VERSION,
        )

    def compute_gaps(self, *, db: Session, project_id: int) -> list[EntityGap]:
        project = self._require_project(db=db, project_id=project_id)
        audits = self._load_project_audits(db=db, project_id=project.id)
        entity_signals, _per_audit_entities = self._collect_entity_signals(audits=audits)
        detected_keys = set(entity_signals.keys())
        target_entities = self._target_entities(project=project)

        gaps = [
            EntityGap(
                entity_key=entity_key,
                entity_name=entity_name,
                reason="Target entity is missing from project audit coverage.",
            )
            for entity_key, entity_name in target_entities.items()
            if entity_key not in detected_keys
        ]
        return sorted(gaps, key=lambda item: item.entity_name.casefold())

    def compute_trend(
        self,
        *,
        db: Session,
        project_id: int,
        limit: int = 12,
    ) -> list[EntityScoreSnapshot]:
        self._require_project(db=db, project_id=project_id)
        snapshots = (
            db.query(models.EntityAuthoritySnapshot)
            .filter(models.EntityAuthoritySnapshot.project_id == project_id)
            .order_by(
                models.EntityAuthoritySnapshot.computed_at.desc(),
                models.EntityAuthoritySnapshot.id.desc(),
            )
            .limit(max(1, min(52, int(limit))))
            .all()
        )
        ordered = list(reversed(snapshots))
        return [
            EntityScoreSnapshot(
                authority_score=round(float(snapshot.authority_score or 0.0), 2),
                coverage_score=round(float(snapshot.coverage_score or 0.0), 2),
                depth_score=round(float(snapshot.depth_score or 0.0), 2),
                consistency_score=round(float(snapshot.consistency_score or 0.0), 2),
                uniqueness_score=round(float(snapshot.uniqueness_score or 0.0), 2),
                target_entity_count=int(snapshot.target_entity_count or 0),
                detected_entity_count=int(snapshot.detected_entity_count or 0),
                gap_count=int(snapshot.gap_count or 0),
                computed_at=snapshot.computed_at or datetime.now(timezone.utc),
                computation_version=str(snapshot.computation_version or COMPUTATION_VERSION),
            )
            for snapshot in ordered
        ]

    def get_latest_snapshot(
        self,
        *,
        db: Session,
        project_id: int,
    ) -> EntityAuthorityResult | None:
        snapshot = (
            db.query(models.EntityAuthoritySnapshot)
            .filter(models.EntityAuthoritySnapshot.project_id == project_id)
            .order_by(
                models.EntityAuthoritySnapshot.computed_at.desc(),
                models.EntityAuthoritySnapshot.id.desc(),
            )
            .first()
        )
        if snapshot is None:
            return None
        return EntityAuthorityResult(
            project_id=project_id,
            authority_score=round(float(snapshot.authority_score or 0.0), 2),
            coverage_score=round(float(snapshot.coverage_score or 0.0), 2),
            depth_score=round(float(snapshot.depth_score or 0.0), 2),
            consistency_score=round(float(snapshot.consistency_score or 0.0), 2),
            uniqueness_score=round(float(snapshot.uniqueness_score or 0.0), 2),
            target_entity_count=int(snapshot.target_entity_count or 0),
            detected_entity_count=int(snapshot.detected_entity_count or 0),
            gap_count=int(snapshot.gap_count or 0),
            computed_at=snapshot.computed_at or datetime.now(timezone.utc),
            computation_version=str(snapshot.computation_version or COMPUTATION_VERSION),
        )

    def build_project_graph(
        self,
        *,
        db: Session,
        project_id: int,
        max_audits: int = 30,
    ) -> dict[str, Any]:
        project = self._require_project(db=db, project_id=project_id)
        audits = self._load_project_audits(
            db=db,
            project_id=project.id,
            limit=max(1, min(100, int(max_audits))),
            latest=True,
        )
        entity_signals, _per_audit_entities = self._collect_entity_signals(audits=audits)
        gap_entities = self.compute_gaps(db=db, project_id=project.id)
        gap_keys = {gap.entity_key for gap in gap_entities}

        nodes_by_key: dict[str, dict[str, Any]] = {}
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        categories: set[str] = set()
        url_mentions: set[str] = set()

        for audit in audits:
            graph = self._graph_service.build_graph(
                self._graph_input_for_audit(audit=audit, project=project)
            )
            for raw_node in graph.get("nodes", []):
                key = str(raw_node.get("key") or "").strip()
                if not key:
                    continue
                node = nodes_by_key.setdefault(
                    key,
                    {
                        "key": key,
                        "name": str(raw_node.get("name") or "Unknown"),
                        "category": str(raw_node.get("category") or "Concept"),
                        "normalized_name": str(raw_node.get("normalized_name") or ""),
                        "sourceURLs": set(),
                    },
                )
                for source_url in raw_node.get("sourceURLs", []):
                    if isinstance(source_url, str) and source_url.strip():
                        node["sourceURLs"].add(source_url.strip())
                categories.add(node["category"])

            for raw_edge in graph.get("edges", []):
                from_key = str(raw_edge.get("from") or "").strip()
                to_key = str(raw_edge.get("to") or "").strip()
                relation = str(raw_edge.get("relation") or "RELATED_TO").strip()
                if not from_key or not to_key:
                    continue
                edge_key = (from_key, to_key, relation)
                edge = edges_by_key.setdefault(
                    edge_key,
                    {
                        "from": from_key,
                        "to": to_key,
                        "relation": relation,
                        "frequency": 0,
                    },
                )
                edge["frequency"] += 1

            for mention in graph.get("url_mentions", []):
                if isinstance(mention, str) and mention.strip():
                    url_mentions.add(mention.strip())

        for gap in gap_entities:
            gap_node_key = f"gap:{gap.entity_key}"
            nodes_by_key[gap_node_key] = {
                "key": gap_node_key,
                "name": gap.entity_name,
                "category": "Gap",
                "normalized_name": gap.entity_key,
                "sourceURLs": set(),
                "is_missing_target": True,
            }
            categories.add("Gap")

        nodes: list[dict[str, Any]] = []
        for node in nodes_by_key.values():
            name = str(node.get("name") or "")
            normalized_key = SiteEntityFactService.normalize_key(name) if name else ""
            signal = entity_signals.get(normalized_key)
            relevance = round(float(signal.avg_relevance), 2) if signal else 0.0
            frequency = int(signal.frequency) if signal else 0
            is_missing = bool(node.get("is_missing_target")) or (normalized_key in gap_keys)
            nodes.append(
                {
                    "key": node["key"],
                    "name": name,
                    "category": node["category"],
                    "normalized_name": node.get("normalized_name") or normalized_key,
                    "sourceURLs": sorted(node["sourceURLs"]),
                    "entity_key": normalized_key,
                    "relevance_score": relevance,
                    "mention_count": frequency,
                    "node_size": round(0.5 + min(1.0, relevance / 100.0), 2),
                    "is_missing_target": is_missing,
                }
            )

        edges: list[dict[str, Any]] = []
        for edge in edges_by_key.values():
            frequency = int(edge["frequency"])
            edges.append(
                {
                    "from": edge["from"],
                    "to": edge["to"],
                    "relation": edge["relation"],
                    "frequency": frequency,
                    "thickness": float(max(1, min(5, frequency))),
                }
            )

        return {
            "project_id": project.id,
            "nodes": sorted(nodes, key=lambda item: item["key"]),
            "edges": sorted(edges, key=lambda item: (item["from"], item["to"], item["relation"])),
            "categories": sorted(categories),
            "url_mentions": sorted(url_mentions),
            "missing_target_entities": [gap.as_dict() for gap in gap_entities],
            "audit_count": len(audits),
        }

    @staticmethod
    def _require_project(*, db: Session, project_id: int) -> models.Project:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project is None:
            raise ValueError("Project not found.")
        return project

    @staticmethod
    def _load_project_audits(
        *,
        db: Session,
        project_id: int,
        limit: int | None = None,
        latest: bool = False,
    ) -> list[models.Audit]:
        if latest and limit is not None and limit > 0:
            recent = (
                db.query(models.Audit)
                .filter(models.Audit.project_id == project_id, own_project_audit_clause())
                .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
                .limit(limit)
                .all()
            )
            return list(reversed(recent))

        query = (
            db.query(models.Audit)
            .filter(models.Audit.project_id == project_id, own_project_audit_clause())
            .order_by(models.Audit.created_at.asc(), models.Audit.id.asc())
        )
        if limit is not None and limit > 0:
            query = query.limit(limit)
        return query.all()

    def _collect_entity_signals(
        self,
        *,
        audits: list[models.Audit],
    ) -> tuple[dict[str, _EntitySignal], dict[int, set[str]]]:
        if not audits:
            return {}, {}

        by_key: dict[str, _EntitySignal] = {}
        per_audit_entities: dict[int, set[str]] = {audit.id: set() for audit in audits}

        facts_by_audit_id: dict[int, list[models.SiteEntityFact]] = {}
        for audit in audits:
            facts = list(getattr(audit, "entity_facts", []) or [])
            if facts:
                facts_by_audit_id[audit.id] = facts

        for audit in audits:
            for record in self._entity_records_from_report(audit=audit):
                self._merge_entity_record(
                    by_key=by_key,
                    per_audit_entities=per_audit_entities,
                    audit_id=audit.id,
                    entity_key=record["entity_key"],
                    entity_name=record["entity_name"],
                    category=record["category"],
                    relevance=record["relevance"],
                    frequency=record["frequency"],
                )

            for fact in facts_by_audit_id.get(audit.id, []):
                entity_key = str(fact.entity_key or "").strip()
                if not entity_key:
                    continue
                self._merge_entity_record(
                    by_key=by_key,
                    per_audit_entities=per_audit_entities,
                    audit_id=audit.id,
                    entity_key=entity_key,
                    entity_name=str(fact.entity_name or entity_key),
                    category=str(fact.entity_category or "Concept"),
                    relevance=self._normalize_relevance_score(fact.relevance_score),
                    frequency=1,
                )

        return by_key, per_audit_entities

    @staticmethod
    def _merge_entity_record(
        *,
        by_key: dict[str, _EntitySignal],
        per_audit_entities: dict[int, set[str]],
        audit_id: int,
        entity_key: str,
        entity_name: str,
        category: str,
        relevance: float | None,
        frequency: int,
    ) -> None:
        normalized_key = SiteEntityFactService.normalize_key(entity_key)
        if not normalized_key:
            return

        signal = by_key.get(normalized_key)
        if signal is None:
            signal = _EntitySignal(
                entity_key=normalized_key,
                entity_name=entity_name.strip() or normalized_key,
                category=category.strip() or "Concept",
            )
            by_key[normalized_key] = signal

        signal.frequency += max(1, int(frequency))
        signal.audits.add(audit_id)
        if relevance is not None:
            signal.relevance_scores.append(relevance)
        per_audit_entities.setdefault(audit_id, set()).add(normalized_key)

    @classmethod
    def _entity_records_from_report(cls, *, audit: models.Audit) -> list[dict[str, Any]]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}

        payloads: list[Any] = [
            analysis.get("entities_detected"),
            analysis.get("entities"),
            report.get("entities_detected"),
            report.get("entities"),
            report.get("entity_data"),
            analysis.get("entity_data"),
        ]

        records: list[dict[str, Any]] = []
        for payload in payloads:
            records.extend(cls._parse_entity_payload(payload))
        return records

    @classmethod
    def _parse_entity_payload(cls, payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, str):
            normalized = SiteEntityFactService.normalize_key(payload)
            if not normalized:
                return []
            return [
                {
                    "entity_key": normalized,
                    "entity_name": payload.strip(),
                    "category": "Concept",
                    "relevance": None,
                    "frequency": 1,
                }
            ]

        if isinstance(payload, list):
            rows: list[dict[str, Any]] = []
            for item in payload:
                rows.extend(cls._parse_entity_payload(item))
            return rows

        if isinstance(payload, dict):
            if "entities" in payload:
                return cls._parse_entity_payload(payload.get("entities"))
            if "items" in payload:
                return cls._parse_entity_payload(payload.get("items"))

            name = cls._extract_entity_name(payload)
            if name is None:
                return []
            key = SiteEntityFactService.normalize_key(name)
            if not key:
                return []
            return [
                {
                    "entity_key": key,
                    "entity_name": name,
                    "category": cls._extract_entity_category(payload),
                    "relevance": cls._extract_entity_relevance(payload),
                    "frequency": cls._extract_entity_frequency(payload),
                }
            ]

        return []

    @staticmethod
    def _extract_entity_name(payload: dict[str, Any]) -> str | None:
        for field in ("name", "entity", "label", "text", "term"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_entity_category(payload: dict[str, Any]) -> str:
        for field in ("category", "type", "entity_type"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                normalized = value.strip().upper()
                if normalized in {"PERSON"}:
                    return "Person"
                if normalized in {"ORG", "ORGANIZATION", "LOCALBUSINESS", "COMPANY"}:
                    return "Organization"
                if normalized in {"PRODUCT"}:
                    return "Product"
                return value.strip().title()
        return "Concept"

    @classmethod
    def _extract_entity_relevance(cls, payload: dict[str, Any]) -> float | None:
        for field in ("relevance_score", "relevance", "score", "confidence", "weight"):
            if field in payload:
                return cls._normalize_relevance_score(payload.get(field))
        return None

    @staticmethod
    def _extract_entity_frequency(payload: dict[str, Any]) -> int:
        for field in ("mention_count", "mentions", "frequency", "count"):
            value = payload.get(field)
            if isinstance(value, (int, float)):
                return max(1, int(value))
        return 1

    @staticmethod
    def _normalize_relevance_score(raw_value: Any) -> float | None:
        value = raw_value
        if isinstance(raw_value, dict):
            value = raw_value.get("score")
        if not isinstance(value, (int, float)):
            return None
        numeric = float(value)
        if numeric <= 1.0:
            numeric *= 100.0
        return max(0.0, min(100.0, numeric))

    def _target_entities(self, *, project: models.Project) -> dict[str, str]:
        values: list[str] = []

        if isinstance(project.icp_roles, list):
            values.extend(
                str(item).strip()
                for item in project.icp_roles
                if isinstance(item, str) and item.strip()
            )
        elif isinstance(project.icp_roles, str) and project.icp_roles.strip():
            values.extend(self._split_target_text(project.icp_roles))

        if isinstance(project.usp, str) and project.usp.strip():
            values.extend(self._split_target_text(project.usp))

        targets: dict[str, str] = {}
        for value in values:
            normalized_value = " ".join(value.split())
            if not normalized_value:
                continue
            key = SiteEntityFactService.normalize_key(normalized_value)
            if not key:
                continue
            targets.setdefault(key, normalized_value)
        return targets

    @staticmethod
    def _split_target_text(value: str) -> list[str]:
        chunks = re.split(r"[,;\n|]+|\s+\band\b\s+", value, flags=re.IGNORECASE)
        normalized = [
            " ".join(chunk.split()) for chunk in chunks if isinstance(chunk, str) and chunk.strip()
        ]
        return [item for item in normalized if 2 <= len(item) <= 80]

    @staticmethod
    def _coverage_score(*, target_count: int, matched_count: int) -> float:
        if target_count <= 0:
            return 0.0
        return round((matched_count / target_count) * 100.0, 2)

    @staticmethod
    def _depth_score(*, entity_signals: dict[str, _EntitySignal]) -> float:
        if not entity_signals:
            return 0.0

        weighted_sum = 0.0
        total_weight = 0.0
        for signal in entity_signals.values():
            frequency = max(1, int(signal.frequency))
            weight = math.log(frequency + 1.0)
            if weight <= 0:
                continue
            weighted_sum += signal.avg_relevance * weight
            total_weight += weight

        if total_weight <= 0:
            return 0.0
        return round(max(0.0, min(100.0, weighted_sum / total_weight)), 2)

    @staticmethod
    def _consistency_score(
        *,
        audit_ids: list[int],
        per_audit_entities: dict[int, set[str]],
        target_keys: set[str],
        detected_keys: set[str],
    ) -> float:
        if not audit_ids:
            return 0.0
        if len(audit_ids) == 1:
            return 100.0 if detected_keys else 0.0

        denominator = len(target_keys) if target_keys else len(detected_keys)
        if denominator <= 0:
            return 0.0

        ratios: list[float] = []
        for audit_id in audit_ids:
            present = per_audit_entities.get(audit_id, set())
            if target_keys:
                matched = len(present.intersection(target_keys))
            else:
                matched = len(present)
            ratios.append(matched / denominator)

        mean_ratio = sum(ratios) / len(ratios)
        if mean_ratio <= 0:
            return 0.0
        cov = pstdev(ratios) / mean_ratio
        bounded_cov = min(1.0, max(0.0, cov))
        return round((1.0 - bounded_cov) * 100.0, 2)

    def _uniqueness_score(
        self,
        *,
        db: Session,
        project: models.Project,
        detected_keys: set[str],
    ) -> float:
        if not detected_keys:
            return 0.0
        competitor_keys = self._collect_competitor_entity_keys(db=db, project=project)
        if not competitor_keys:
            return 0.0
        unique_count = len(detected_keys.difference(competitor_keys))
        return round((unique_count / len(detected_keys)) * 100.0, 2)

    def _collect_competitor_entity_keys(
        self,
        *,
        db: Session,
        project: models.Project,
    ) -> set[str]:
        competitor_audit_ids: set[int] = set()

        snapshot_rows = (
            db.query(models.ProjectCompetitorSnapshot.competitor_audit_id)
            .filter(
                models.ProjectCompetitorSnapshot.project_id == project.id,
                models.ProjectCompetitorSnapshot.competitor_audit_id.isnot(None),
                models.ProjectCompetitorSnapshot.status == "succeeded",
            )
            .all()
        )
        competitor_audit_ids.update(
            int(row.competitor_audit_id)
            for row in snapshot_rows
            if row.competitor_audit_id is not None
        )

        fallback_domains = self._extract_competitor_domains(project.competitors_json)
        if fallback_domains:
            site_rows = (
                db.query(models.Site.id)
                .filter(func.lower(models.Site.domain).in_(sorted(fallback_domains)))
                .all()
            )
            site_ids = [int(row.id) for row in site_rows]
            if site_ids:
                latest_audits = (
                    db.query(models.Audit)
                    .filter(models.Audit.site_id.in_(site_ids))
                    .order_by(models.Audit.site_id.asc(), models.Audit.created_at.desc())
                    .all()
                )
                seen_site_ids: set[int] = set()
                for audit in latest_audits:
                    if audit.site_id is None or audit.site_id in seen_site_ids:
                        continue
                    seen_site_ids.add(int(audit.site_id))
                    competitor_audit_ids.add(int(audit.id))

        if not competitor_audit_ids:
            return set()

        competitor_audits = (
            db.query(models.Audit).filter(models.Audit.id.in_(sorted(competitor_audit_ids))).all()
        )
        competitor_signals, _per_audit_entities = self._collect_entity_signals(
            audits=competitor_audits
        )
        return set(competitor_signals.keys())

    @staticmethod
    def _extract_competitor_domains(raw: Any) -> set[str]:
        if not isinstance(raw, list):
            return set()
        domains: set[str] = set()
        for item in raw:
            candidate: str | None = None
            if isinstance(item, str):
                candidate = item
            elif isinstance(item, dict):
                for field in ("domain", "url", "target_url", "website"):
                    value = item.get(field)
                    if isinstance(value, str) and value.strip():
                        candidate = value
                        break
            normalized = EntityAuthorityService._normalize_domain(candidate)
            if normalized:
                domains.add(normalized)
        return domains

    @staticmethod
    def _normalize_domain(raw: str | None) -> str | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip().lower()
        if "://" not in value:
            value = f"https://{value}"
        hostname = urlparse(value).hostname
        if not hostname:
            return None
        return hostname.lower().replace("www.", "")

    @staticmethod
    def _graph_input_for_audit(
        *,
        audit: models.Audit,
        project: models.Project,
    ) -> dict[str, Any]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}

        return {
            "url": str(audit.url or report.get("url") or project.domain_url or ""),
            "same_as_urls": analysis.get("same_as_urls") or report.get("same_as_urls") or [],
            "mention_relations": analysis.get("mention_relations")
            or report.get("mention_relations")
            or [],
            "entities": (
                analysis.get("entities_detected")
                or analysis.get("entities")
                or report.get("entities_detected")
                or report.get("entities")
                or []
            ),
            "primary_entity": analysis.get("primary_entity")
            or report.get("primary_entity")
            or {
                "name": project.name or project.domain_url or "Project",
                "type": "ORG",
            },
        }
