from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

import models
from app.services.brand_facts_service import get_brand_facts_evidence
from services.benchmark_engine import BenchmarkEngine
from services.claim_taxonomy_service import ClaimTaxonomyService
from services.knowledge_service import knowledge_service
from services.proprietary_score_registry import ProprietaryScoreRegistry


UTC_SCHEMA_VERSION = "utc-1"
MAX_DOMAIN_STANDARD_EXCERPTS = 5
MAX_RELEVANT_SNIPPETS = 5
MAX_ENTITY_INSIGHTS = 5
MAX_SUPPORTED_TRACK_A_CLAIMS = 15
BENCHMARK_METRICS: tuple[str, ...] = ("geo_score", "seo_score", "aeo_score")

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")

_CATEGORY_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "technical": ("technical", "seo", "performance", "indexing", "schema", "crawl"),
    "content": ("content", "aeo", "geo", "semantic", "answer", "copy"),
    "backlinks": ("backlinks", "offpage", "off-page", "authority", "links", "mentions"),
    "strategy": ("strategy", "competitive", "entity", "brand", "visibility"),
}


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalize_category(value: str | None) -> str:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return "unknown"
    for canonical, aliases in _CATEGORY_ALIAS_GROUPS.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


class UnifiedTruthContextService:
    def __init__(self, db: Session | None):
        self.db = db
        self.benchmark_engine = BenchmarkEngine()
        self.score_registry = ProprietaryScoreRegistry()
        self.claim_taxonomy_service = ClaimTaxonomyService()

    @staticmethod
    def empty_signal_intelligence() -> dict[str, Any]:
        return {
            "available": False,
            "benchmarks": {},
            "citation_stability": None,
            "remediation_impact": None,
            "entity_history": {
                "observation_count_90d": 0,
                "top_entities": [],
            },
            "remediation_category_performance": [],
        }

    def build_project_signal_intelligence(
        self,
        *,
        project_id: int | None,
    ) -> dict[str, Any]:
        if project_id is None or self.db is None:
            return self.empty_signal_intelligence()

        benchmarks: dict[str, dict[str, Any]] = {}
        for metric in BENCHMARK_METRICS:
            result = self.benchmark_engine.get_project_percentile(
                db=self.db,
                project_id=project_id,
                metric=metric,
            )
            if result is not None:
                benchmarks[metric] = result.as_dict()

        citation_stability = self.score_registry.summarize_citation_stability(
            db=self.db,
            project_id=project_id,
        ).as_dict()
        remediation_impact = self.score_registry.summarize_remediation_impact(
            db=self.db,
            project_id=project_id,
        ).as_dict()
        entity_history = self._build_entity_history(project_id=project_id)
        remediation_category_performance = self._build_remediation_category_performance(
            project_id=project_id
        )

        available = any(
            (
                any(item.get("status") == "ok" for item in benchmarks.values()),
                citation_stability.get("data_points_used", 0) > 0,
                remediation_impact.get("data_points_used", 0) > 0,
                entity_history.get("observation_count_90d", 0) > 0,
                bool(remediation_category_performance),
            )
        )

        return {
            "available": available,
            "benchmarks": benchmarks,
            "citation_stability": citation_stability,
            "remediation_impact": remediation_impact,
            "entity_history": entity_history,
            "remediation_category_performance": remediation_category_performance,
        }

    def build_context(
        self,
        *,
        project_id: int | None,
        audit_target_type: str,
        target_name: str | None,
        target_url: str | None,
        category: str | None,
        market: str | None,
        source_content: str | None,
        target_metadata: dict[str, Any] | None = None,
        brand_truth_payload: dict[str, Any] | None = None,
        performance_metrics: dict[str, Any] | None = None,
        network_data: dict[str, Any] | None = None,
        data_source_context: dict[str, Any] | None = None,
        supported_track_a_claims: list[dict[str, Any]] | None = None,
        vision_agent_insights: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        signal_intelligence = self.build_project_signal_intelligence(project_id=project_id)
        return {
            "schema_version": UTC_SCHEMA_VERSION,
            "target_profile": {
                "audit_target_type": _normalize_text(audit_target_type) or "website",
                "target_name": _normalize_text(target_name) or None,
                "target_url": _normalize_text(target_url) or None,
                "target_metadata": (
                    dict(target_metadata) if isinstance(target_metadata, dict) else {}
                ),
                "brand_truth_payload": (
                    dict(brand_truth_payload) if isinstance(brand_truth_payload, dict) else {}
                ),
            },
            "supported_track_a_claims": self._normalize_supported_claims(
                supported_track_a_claims or []
            ),
            "technical_agent_insights": self._build_technical_agent_insights(
                category=category,
                market=market,
                performance_metrics=performance_metrics,
                network_data=network_data,
                data_source_context=data_source_context,
                signal_intelligence=signal_intelligence,
            ),
            "vision_agent_insights": self._normalize_vision_insights(vision_agent_insights or []),
            "scraped_text": self._build_scraped_text(
                source_content=source_content or "",
                target_name=target_name,
                category=category,
                market=market,
                signal_intelligence=signal_intelligence,
            ),
            "brand_truth_payload": (
                dict(brand_truth_payload) if isinstance(brand_truth_payload, dict) else {}
            ),
            "target_metadata": (dict(target_metadata) if isinstance(target_metadata, dict) else {}),
            "domain_standards": self._build_domain_standards(category=category),
            "brand_facts": self._build_brand_facts_evidence(project_id=project_id),
        }

    def _build_brand_facts_evidence(self, *, project_id: int | None) -> list[dict[str, Any]]:
        """Per-project brand facts as ADDITIVE structured evidence (Task 6.3).

        Defensive: any failure yields an empty list so a missing/unavailable
        guardrails table can never break a live audit. Does not alter thresholds,
        prompts or the canonical contract.
        """
        if project_id is None or self.db is None:
            return []
        try:
            return get_brand_facts_evidence(self.db, project_id)
        except Exception:
            logger.warning(
                "Brand facts evidence unavailable for project_id=%s",
                project_id,
                exc_info=True,
            )
            return []

    def _build_entity_history(self, *, project_id: int, window_days: int = 90) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, int(window_days)))
        rows = (
            self.db.query(models.SignalEntityObservation)
            .filter(
                models.SignalEntityObservation.project_id == project_id,
                models.SignalEntityObservation.snapshot_date >= cutoff,
            )
            .order_by(
                models.SignalEntityObservation.snapshot_date.desc(),
                models.SignalEntityObservation.id.desc(),
            )
            .all()
        )

        aggregated: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.entity_key or "").strip()
            if not key:
                continue
            bucket = aggregated.setdefault(
                key,
                {
                    "entity_key": key,
                    "entity_category": str(row.entity_category or "Unknown"),
                    "mention_frequency": 0,
                    "relevance_scores": [],
                    "last_seen_at": row.snapshot_date.isoformat() if row.snapshot_date else None,
                },
            )
            bucket["mention_frequency"] += max(1, int(row.mention_frequency or 1))
            if isinstance(row.relevance_score, (int, float)):
                bucket["relevance_scores"].append(float(row.relevance_score))

        top_entities = sorted(
            (
                {
                    "entity_key": payload["entity_key"],
                    "entity_category": payload["entity_category"],
                    "mention_frequency": int(payload["mention_frequency"]),
                    "avg_relevance": round(
                        sum(payload["relevance_scores"]) / len(payload["relevance_scores"]),
                        4,
                    )
                    if payload["relevance_scores"]
                    else None,
                    "last_seen_at": payload["last_seen_at"],
                }
                for payload in aggregated.values()
            ),
            key=lambda item: (
                int(item["mention_frequency"]),
                float(item["avg_relevance"] or 0.0),
                str(item["last_seen_at"] or ""),
            ),
            reverse=True,
        )[:MAX_ENTITY_INSIGHTS]

        return {
            "observation_count_90d": len(rows),
            "top_entities": top_entities,
        }

    def _build_remediation_category_performance(
        self,
        *,
        project_id: int,
        lookback_days: int = 180,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
        rows = (
            self.db.query(models.SignalRemediationOutcome)
            .filter(
                models.SignalRemediationOutcome.project_id == project_id,
                models.SignalRemediationOutcome.completed_at.isnot(None),
                models.SignalRemediationOutcome.completed_at >= cutoff,
            )
            .order_by(
                models.SignalRemediationOutcome.completed_at.desc(),
                models.SignalRemediationOutcome.id.desc(),
            )
            .all()
        )

        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "sample_size": 0,
                "deltas": [],
                "positive_deltas": 0,
            }
        )
        for row in rows:
            category = _normalize_category(row.recommendation_category)
            bucket = grouped[category]
            bucket["sample_size"] += 1
            for value in (row.score_delta_geo, row.score_delta_aeo):
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    bucket["deltas"].append(numeric)
                    if numeric > 0:
                        bucket["positive_deltas"] += 1

        summaries: list[dict[str, Any]] = []
        for category, bucket in grouped.items():
            deltas = list(bucket["deltas"])
            avg_combined_delta = sum(deltas) / len(deltas) if deltas else 0.0
            positive_rate = bucket["positive_deltas"] / len(deltas) if deltas else 0.0
            summaries.append(
                {
                    "category": category,
                    "sample_size": int(bucket["sample_size"]),
                    "avg_combined_delta": round(float(avg_combined_delta), 4),
                    "positive_rate": round(float(positive_rate), 4),
                    "note": (
                        f"Resolved {bucket['sample_size']} {category} item(s) with an average "
                        f"GEO/AEO lift of {round(avg_combined_delta, 1)} points."
                    ),
                }
            )

        summaries.sort(
            key=lambda item: (
                float(item["avg_combined_delta"]),
                float(item["positive_rate"]),
                int(item["sample_size"]),
            ),
            reverse=True,
        )
        return summaries

    @staticmethod
    def _normalize_supported_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in claims:
            if not isinstance(item, dict):
                continue
            claim_text = _normalize_text(item.get("claim_text") or item.get("text"))
            if not claim_text:
                continue
            evidence_refs = (
                item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            )
            normalized.append(
                {
                    "claim_id": _normalize_text(item.get("claim_id")) or None,
                    "claim_text": claim_text,
                    "field_path": _normalize_text(item.get("field_path")) or None,
                    "reason": _normalize_text(item.get("reason")) or None,
                    "evidence_refs": [ref for ref in evidence_refs if isinstance(ref, dict)],
                }
            )
        return normalized

    def build_supported_track_a_claims_from_hallucination(
        self,
        hallucination_result: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(hallucination_result, dict):
            return []

        raw_claims = hallucination_result.get("claim_verifications")
        if not isinstance(raw_claims, list):
            raw_claims = hallucination_result.get("claims")
        if not isinstance(raw_claims, list):
            return []

        supported_claims: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_claims:
            if not isinstance(item, dict):
                continue

            claim_text = _normalize_text(item.get("claim_text") or item.get("text"))
            if not claim_text:
                continue

            disposition = _normalize_text(item.get("disposition")).lower() or "supported"
            if disposition != "supported" or bool(item.get("hallucination", False)):
                continue

            track = _normalize_text(item.get("track")).lower()
            if track not in {"track_a", "track_b", "mixed"}:
                field_path = _normalize_text(item.get("field_path"))
                field_group = field_path.split("[", 1)[0].split(".", 1)[0] if field_path else ""
                track = str(
                    self.claim_taxonomy_service.annotate_claim(
                        {
                            "text": claim_text,
                            "field_group": field_group,
                        }
                    ).get("track")
                    or ""
                ).lower()
            if track != "track_a":
                continue

            evidence_refs = (
                item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            )
            field_path = _normalize_text(item.get("field_path")) or None
            claim_id = _normalize_text(item.get("claim_id")) or None
            dedupe_key = (field_path or "", claim_text.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            supported_claims.append(
                {
                    "claim_id": claim_id,
                    "claim_text": claim_text,
                    "field_path": field_path,
                    "reason": "Supported Track A claim retained from grounding validation.",
                    "evidence_refs": [ref for ref in evidence_refs if isinstance(ref, dict)],
                }
            )
            if len(supported_claims) >= MAX_SUPPORTED_TRACK_A_CLAIMS:
                break

        return self._normalize_supported_claims(supported_claims)

    @staticmethod
    def _normalize_vision_insights(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(insights, start=1):
            if not isinstance(item, dict):
                continue
            insight_text = _normalize_text(item.get("insight_text") or item.get("text"))
            if not insight_text:
                continue
            limitations = (
                item.get("limitations") if isinstance(item.get("limitations"), list) else []
            )
            normalized.append(
                {
                    "source_id": _normalize_text(item.get("source_id")) or f"vision-{index}",
                    "source_label": _normalize_text(item.get("source_label")) or "Vision insight",
                    "source_type": "vision",
                    "trust_tier": "T4",
                    "insight_text": insight_text,
                    "limitations": [
                        _normalize_text(limit) for limit in limitations if _normalize_text(limit)
                    ],
                }
            )
        return normalized

    def _build_technical_agent_insights(
        self,
        *,
        category: str | None,
        market: str | None,
        performance_metrics: dict[str, Any] | None,
        network_data: dict[str, Any] | None,
        data_source_context: dict[str, Any] | None,
        signal_intelligence: dict[str, Any],
    ) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []

        performance_payload = performance_metrics if isinstance(performance_metrics, dict) else {}
        performance_score = _to_float(
            performance_payload.get("performance_score")
            or performance_payload.get("overall_score")
            or performance_payload.get("score")
        )
        if performance_score is not None:
            insights.append(
                {
                    "source_id": "performance-lab-score",
                    "source_label": "Performance Lab",
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": f"Latest performance lab score is {round(performance_score)} / 100.",
                    "evidence_refs": [
                        {
                            "source_type": "performance_metrics",
                            "source_key": "performance_score",
                            "excerpt": str(round(performance_score, 2)),
                        }
                    ],
                }
            )

        network_payload = network_data if isinstance(network_data, dict) else {}
        enabled_protocols = [
            protocol.upper()
            for protocol, enabled in network_payload.items()
            if isinstance(protocol, str) and isinstance(enabled, bool) and enabled
        ]
        if enabled_protocols:
            insights.append(
                {
                    "source_id": "network-protocols",
                    "source_label": "Network Analyzer",
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": (
                        f"Observed network support includes {', '.join(enabled_protocols[:3])}."
                    ),
                    "evidence_refs": [
                        {
                            "source_type": "network_data",
                            "source_key": protocol.lower(),
                            "excerpt": protocol,
                        }
                        for protocol in enabled_protocols[:3]
                    ],
                }
            )

        source_context = data_source_context if isinstance(data_source_context, dict) else {}
        source_mode = _normalize_text(source_context.get("mode"))
        if source_mode:
            insights.append(
                {
                    "source_id": "project-data-sources",
                    "source_label": "Project data sources",
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": (
                        f"Project audit data source mode is {source_mode.replace('_', ' ')}."
                    ),
                    "evidence_refs": [
                        {
                            "source_type": "project_data_sources",
                            "source_key": "mode",
                            "excerpt": source_mode,
                        }
                    ],
                }
            )

        insights.extend(self._build_search_metric_insights(source_context))

        insights.extend(
            self._build_signal_insights(
                signal_intelligence=signal_intelligence,
                category=category,
                market=market,
            )
        )
        return insights[:12]

    def _build_search_metric_insights(
        self,
        source_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Stored Search Console and Bing performance as T1 evidence (SIGV2-1265).

        The two providers stay separate sentences backed by separate tables. A
        connected provider holding no rows says so, because silence there would
        read as no traffic. A provider that was never connected is left to the
        data-source mode insight above.
        """
        metrics = source_context.get("search_metrics")
        if not isinstance(metrics, dict):
            return []

        window_days = metrics.get("window_days")
        window_phrase = f"the last {window_days} days" if window_days else "the stored window"
        insights: list[dict[str, Any]] = []

        gsc = metrics.get("google_search_console")
        if isinstance(gsc, dict):
            insights.extend(
                self._provider_metric_insight(
                    payload=gsc,
                    source_id="search-console-performance",
                    source_label="Google Search Console",
                    evidence_source_type="project_gsc_page_metrics",
                    window_phrase=window_phrase,
                    absence_text=(
                        "Search Console is connected but holds no stored Search Console rows "
                        f"for {window_phrase}, so its traffic is unknown rather than zero."
                    ),
                )
            )

        bing = metrics.get("bing_webmaster")
        if isinstance(bing, dict):
            insights.extend(
                self._provider_metric_insight(
                    payload=bing,
                    source_id="bing-webmaster-performance",
                    source_label="Bing Webmaster Tools",
                    evidence_source_type="project_bing_metrics",
                    window_phrase=window_phrase,
                    absence_text=(
                        "Bing Webmaster Tools is connected but holds no stored Bing rows for "
                        f"{window_phrase}, so its traffic is unknown rather than zero."
                    ),
                )
            )

        return insights

    @staticmethod
    def _provider_metric_insight(
        *,
        payload: dict[str, Any],
        source_id: str,
        source_label: str,
        evidence_source_type: str,
        window_phrase: str,
        absence_text: str,
    ) -> list[dict[str, Any]]:
        if not payload.get("available"):
            # Only a binding that exists and measured nothing is worth saying.
            if payload.get("reason") != "no_stored_rows":
                return []
            return [
                {
                    "source_id": source_id,
                    "source_label": source_label,
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": absence_text,
                    "evidence_refs": [
                        {
                            "source_type": evidence_source_type,
                            "source_key": "row_count",
                            "excerpt": "0",
                        }
                    ],
                }
            ]

        clicks = _to_float(payload.get("clicks"))
        impressions = _to_float(payload.get("impressions"))
        if clicks is None or impressions is None:
            return []

        period = payload.get("period") if isinstance(payload.get("period"), dict) else {}
        start = _normalize_text(period.get("start"))
        end = _normalize_text(period.get("end"))
        covered = f" covering {start} to {end}" if start and end else ""
        sentence = (
            f"{source_label} recorded {round(clicks):,} clicks and "
            f"{round(impressions):,} impressions over {window_phrase}{covered}."
        )

        # Search Console publishes an average position; Bing's integer scale is
        # undocumented, so no position sentence is ever produced for Bing.
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        position_value = _to_float(position.get("value"))
        if position.get("status") == "available" and position_value is not None:
            sentence += f" Average position was {position_value}."

        evidence_refs = [
            {
                "source_type": evidence_source_type,
                "source_key": "clicks",
                "excerpt": str(round(clicks, 2)),
            },
            {
                "source_type": evidence_source_type,
                "source_key": "impressions",
                "excerpt": str(round(impressions, 2)),
            },
        ]

        return [
            {
                "source_id": source_id,
                "source_label": source_label,
                "source_type": "technical",
                "trust_tier": "T1",
                "insight_text": sentence,
                "evidence_refs": evidence_refs,
            }
        ]

    def _build_signal_insights(
        self,
        *,
        signal_intelligence: dict[str, Any],
        category: str | None,
        market: str | None,
    ) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []
        benchmarks = (
            signal_intelligence.get("benchmarks") if isinstance(signal_intelligence, dict) else {}
        )
        if isinstance(benchmarks, dict):
            for metric, payload in benchmarks.items():
                if not isinstance(payload, dict) or payload.get("status") != "ok":
                    continue
                top_percent = payload.get("top_percent")
                cohort_label = _normalize_text(payload.get("cohort_label"))
                project_value = _to_float(payload.get("project_value"))
                if top_percent is None:
                    continue
                metric_label = str(metric).replace("_score", "").upper()
                insights.append(
                    {
                        "source_id": f"signal-benchmark-{metric}",
                        "source_label": "Signal Warehouse benchmark",
                        "source_type": "technical",
                        "trust_tier": "T1",
                        "insight_text": (
                            f"Signal Warehouse places the project in the top {top_percent}% for "
                            f"{metric_label} against the latest {cohort_label or 'available'} cohort."
                        ),
                        "evidence_refs": [
                            {
                                "source_type": "signal_benchmark",
                                "source_key": str(payload.get("cohort_key") or metric),
                                "excerpt": (
                                    f"value={round(project_value, 2) if project_value is not None else 'n/a'}, "
                                    f"cohort_size={int(payload.get('cohort_size') or 0)}"
                                ),
                            }
                        ],
                    }
                )

        citation_payload = signal_intelligence.get("citation_stability")
        if (
            isinstance(citation_payload, dict)
            and int(citation_payload.get("data_points_used") or 0) > 0
        ):
            insights.append(
                {
                    "source_id": "signal-citation-stability",
                    "source_label": "Signal Warehouse citation stability",
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": (
                        f"Citation stability is {round(float(citation_payload.get('value') or 0.0))} / 100 "
                        f"across {int(citation_payload.get('data_points_used') or 0)} recent monitoring runs."
                    ),
                    "evidence_refs": [
                        {
                            "source_type": "signal_score",
                            "source_key": "citation_stability",
                            "excerpt": str(citation_payload.get("components") or {}),
                        }
                    ],
                }
            )

        remediation_payload = signal_intelligence.get("remediation_impact")
        if (
            isinstance(remediation_payload, dict)
            and int(remediation_payload.get("data_points_used") or 0) > 0
        ):
            insights.append(
                {
                    "source_id": "signal-remediation-impact",
                    "source_label": "Signal Warehouse remediation impact",
                    "source_type": "technical",
                    "trust_tier": "T1",
                    "insight_text": (
                        f"Historical remediation impact is {round(float(remediation_payload.get('value') or 0.0))} / 100 "
                        f"with {int(remediation_payload.get('data_points_used') or 0)} resolved items."
                    ),
                    "evidence_refs": [
                        {
                            "source_type": "signal_score",
                            "source_key": "remediation_impact",
                            "excerpt": str(remediation_payload.get("components") or {}),
                        }
                    ],
                }
            )

        entity_history = signal_intelligence.get("entity_history")
        top_entities = (
            entity_history.get("top_entities")
            if isinstance(entity_history, dict)
            and isinstance(entity_history.get("top_entities"), list)
            else []
        )
        if top_entities:
            label = ", ".join(
                str(item.get("entity_key") or "")
                for item in top_entities[:3]
                if str(item.get("entity_key") or "").strip()
            )
            if label:
                scope = "global"
                if _normalize_text(category):
                    scope = _normalize_text(category)
                elif _normalize_text(market):
                    scope = _normalize_text(market)
                insights.append(
                    {
                        "source_id": "signal-entity-history",
                        "source_label": "Signal Warehouse entity history",
                        "source_type": "technical",
                        "trust_tier": "T1",
                        "insight_text": (
                            f"Recent entity coverage in {scope} signals clusters around {label}."
                        ),
                        "evidence_refs": [
                            {
                                "source_type": "signal_entities",
                                "source_key": str(item.get("entity_key") or ""),
                                "excerpt": (
                                    f"mentions={int(item.get('mention_frequency') or 0)}, "
                                    f"avg_relevance={item.get('avg_relevance')}"
                                ),
                            }
                            for item in top_entities[:3]
                        ],
                    }
                )

        return insights

    def _build_scraped_text(
        self,
        *,
        source_content: str,
        target_name: str | None,
        category: str | None,
        market: str | None,
        signal_intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_content = source_content if isinstance(source_content, str) else ""
        digest = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        chunks = self._chunk_text(normalized_content)
        query_terms = self._build_snippet_terms(
            target_name=target_name,
            category=category,
            market=market,
            signal_intelligence=signal_intelligence,
        )
        scored: list[tuple[float, int, str]] = []
        for index, chunk in enumerate(chunks):
            score = self._score_snippet(chunk=chunk, query_terms=query_terms)
            scored.append((score, index, chunk))
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        snippets = [
            {
                "source_id": f"scraped-text-{index + 1}",
                "source_key": f"chunk-{index + 1}",
                "excerpt": chunk,
                "retrieval_score": round(score, 4),
            }
            for score, index, chunk in scored[:MAX_RELEVANT_SNIPPETS]
            if chunk
        ]
        return {
            "corpus_digest": digest,
            "relevant_snippets": snippets,
        }

    @staticmethod
    def _chunk_text(value: str, *, chunk_size: int = 420) -> list[str]:
        paragraphs = [
            _normalize_text(part)
            for part in re.split(r"\n\s*\n+", value or "")
            if _normalize_text(part)
        ]
        chunks: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= chunk_size:
                chunks.append(paragraph)
                continue
            start = 0
            while start < len(paragraph):
                chunk = paragraph[start : start + chunk_size].strip()
                if chunk:
                    chunks.append(chunk)
                start += chunk_size
        return chunks[:20]

    def _build_snippet_terms(
        self,
        *,
        target_name: str | None,
        category: str | None,
        market: str | None,
        signal_intelligence: dict[str, Any],
    ) -> set[str]:
        raw_terms: list[str] = []
        for value in (target_name, category, market):
            raw_terms.extend(_TOKEN_PATTERN.findall(_normalize_text(value).lower()))

        entity_history = signal_intelligence.get("entity_history")
        top_entities = (
            entity_history.get("top_entities")
            if isinstance(entity_history, dict)
            and isinstance(entity_history.get("top_entities"), list)
            else []
        )
        for item in top_entities[:3]:
            raw_terms.extend(_TOKEN_PATTERN.findall(str(item.get("entity_key") or "").lower()))
        return {term for term in raw_terms if term}

    @staticmethod
    def _score_snippet(*, chunk: str, query_terms: set[str]) -> float:
        if not chunk:
            return 0.0
        if not query_terms:
            return 0.1
        tokens = _TOKEN_PATTERN.findall(chunk.lower())
        if not tokens:
            return 0.0
        token_set = set(tokens)
        matches = len(query_terms & token_set)
        return matches / max(1, len(query_terms))

    def _build_domain_standards(self, *, category: str | None) -> list[dict[str, Any]]:
        context = (
            knowledge_service.get_domain_context(category) or knowledge_service.get_domain_context()
        )
        if not context:
            return []

        excerpts: list[str] = []
        for block in re.split(r"\n\s*\n+", context):
            cleaned = _normalize_text(block)
            if not cleaned:
                continue
            if cleaned.startswith("#"):
                continue
            excerpts.append(cleaned[:420])
            if len(excerpts) >= MAX_DOMAIN_STANDARD_EXCERPTS:
                break

        resolved_category = _normalize_text(category) or "general"
        return [
            {
                "source_id": f"domain-standard-{index}",
                "category": resolved_category,
                "excerpt": excerpt,
            }
            for index, excerpt in enumerate(excerpts, start=1)
        ]
