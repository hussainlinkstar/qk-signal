from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import models
from sqlalchemy.orm import Session

MetricName = str
Row = dict[str, Any]


class CompetitorBenchmarkService:
    """Builds a dashboard-ready benchmark table for target vs. competitors."""

    _METRICS: tuple[MetricName, ...] = ("geo_visibility", "aeo_score", "entity_strength")
    _COMPARE_AXES: tuple[str, ...] = ("SEO", "AEO", "GEO", "Speed")

    @staticmethod
    def _normalize_query(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    @staticmethod
    def _extract_query_from_audit(audit: models.Audit) -> str:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
        return str(
            metadata.get("query")
            or metadata.get("prompt")
            or report.get("query")
            or audit.url
            or ""
        ).strip()

    @staticmethod
    def _extract_aeo_answer_excerpt(audit: models.Audit) -> str | None:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        aeo_section = report.get("aeo") if isinstance(report.get("aeo"), dict) else {}
        for candidate in (
            aeo_section.get("answer_excerpt"),
            aeo_section.get("answer"),
            report.get("answer_excerpt"),
            report.get("answer"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    @classmethod
    def _extract_answer_relevance_with_source(
        cls, audit: models.Audit
    ) -> tuple[float | None, str | None]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        aeo_section = report.get("aeo") if isinstance(report.get("aeo"), dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        candidates = [
            ("aeo.answer_relevance", aeo_section.get("answer_relevance")),
            ("aeo.answer_relevance_score", aeo_section.get("answer_relevance_score")),
            ("answer_relevance", report.get("answer_relevance")),
            ("analysis.answer_relevance", analysis.get("answer_relevance")),
        ]
        for source, candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("score")
            if isinstance(candidate, (float, int)):
                return cls._normalize_metric(candidate), source
        return None, None

    @classmethod
    def _extract_answer_relevance(cls, audit: models.Audit) -> float | None:
        score, _ = cls._extract_answer_relevance_with_source(audit)
        return score

    @staticmethod
    def _audit_created_at_iso(audit: models.Audit) -> str | None:
        return audit.created_at.isoformat() if audit.created_at else None

    @classmethod
    def _pick_latest_audit_for_query(
        cls,
        *,
        audits: list[models.Audit],
        query: str,
    ) -> models.Audit | None:
        normalized_query = cls._normalize_query(query)
        matching = [
            audit
            for audit in audits
            if cls._normalize_query(cls._extract_query_from_audit(audit)) == normalized_query
        ]
        if not matching:
            return None
        matching.sort(
            key=lambda audit: (
                audit.created_at is not None,
                audit.created_at,
                audit.id,
            ),
            reverse=True,
        )
        return matching[0]

    def build_query_answer_relevance_benchmark(
        self,
        *,
        site_id: int,
        site_domain: str,
        competitors: list[models.Site],
        queries: list[str],
        site_audits: list[models.Audit],
        competitor_audits: list[models.Audit],
    ) -> dict[str, Any]:
        if not queries:
            return {
                "site_id": site_id,
                "site_domain": site_domain,
                "competitor_count": len(competitors),
                "queries": [],
            }

        competitor_by_id = {competitor.id: competitor for competitor in competitors}
        comparisons: list[dict[str, Any]] = []

        for query in queries:
            site_audit = self._pick_latest_audit_for_query(audits=site_audits, query=query)
            site_score, site_score_source = (
                self._extract_answer_relevance_with_source(site_audit)
                if site_audit
                else (None, None)
            )

            comp_candidates: list[tuple[float | None, str | None, models.Audit, models.Site]] = []
            for audit in competitor_audits:
                competitor = competitor_by_id.get(audit.site_id)
                if competitor is None:
                    continue
                if self._normalize_query(
                    self._extract_query_from_audit(audit)
                ) != self._normalize_query(query):
                    continue
                score, source = self._extract_answer_relevance_with_source(audit)
                comp_candidates.append((score, source, audit, competitor))

            comp_candidates.sort(
                key=lambda item: (
                    item[0] is not None,
                    item[0] if item[0] is not None else -1.0,
                    item[2].created_at is not None,
                    item[2].created_at,
                    item[2].id,
                ),
                reverse=True,
            )
            top_competitor = comp_candidates[0] if comp_candidates else None

            competitors_payload: list[dict[str, Any]] = [
                {
                    "site_id": competitor.id,
                    "domain": competitor.domain,
                    "display_name": competitor.display_name or competitor.domain,
                    "answer_relevance": score,
                    "answer_relevance_source": source,
                    "answer_relevance_fallback_used": source is not None
                    and source != "aeo.answer_relevance",
                    "answer_excerpt": self._extract_aeo_answer_excerpt(audit),
                    "audit_id": audit.id,
                    "created_at": self._audit_created_at_iso(audit),
                    "selected_audit_timestamp": self._audit_created_at_iso(audit),
                }
                for score, source, audit, competitor in comp_candidates
            ]

            competitor_payload: dict[str, Any] | None = None
            competitor_score: float | None = None
            competitor_audit: models.Audit | None = None
            competitor_site: models.Site | None = None
            competitor_score_source: str | None = None

            if top_competitor is not None:
                competitor_score, competitor_score_source, competitor_audit, competitor_site = (
                    top_competitor
                )
                competitor_payload = {
                    "site_id": competitor_site.id,
                    "domain": competitor_site.domain,
                    "display_name": competitor_site.display_name or competitor_site.domain,
                    "answer_relevance": competitor_score,
                    "answer_relevance_source": competitor_score_source,
                    "answer_relevance_fallback_used": (
                        competitor_score_source is not None
                        and competitor_score_source != "aeo.answer_relevance"
                    ),
                    "answer_excerpt": self._extract_aeo_answer_excerpt(competitor_audit),
                    "audit_id": competitor_audit.id,
                    "created_at": self._audit_created_at_iso(competitor_audit),
                    "selected_audit_timestamp": self._audit_created_at_iso(competitor_audit),
                }

            winner_reason: str
            if site_score is None and competitor_score is None:
                winner = "no_data"
                delta = None
                winner_reason = "missing_site_data"
            elif competitor_score is None:
                winner = "site"
                delta = None
                winner_reason = "missing_competitor_data"
            elif site_score is None:
                winner = "competitor"
                delta = None
                winner_reason = "missing_site_data"
            else:
                delta = round(site_score - competitor_score, 2)
                winner_reason = "score_delta"
                if delta > 0:
                    winner = "site"
                elif delta < 0:
                    winner = "competitor"
                else:
                    winner = "tie"

            comparisons.append(
                {
                    "query": query,
                    "site": {
                        "site_id": site_id,
                        "domain": site_domain,
                        "answer_relevance": site_score,
                        "answer_relevance_source": site_score_source,
                        "answer_relevance_fallback_used": (
                            site_score_source is not None
                            and site_score_source != "aeo.answer_relevance"
                        ),
                        "answer_excerpt": self._extract_aeo_answer_excerpt(site_audit)
                        if site_audit
                        else None,
                        "audit_id": site_audit.id if site_audit else None,
                        "created_at": self._audit_created_at_iso(site_audit)
                        if site_audit
                        else None,
                        "selected_audit_timestamp": self._audit_created_at_iso(site_audit)
                        if site_audit
                        else None,
                    },
                    "competitor": competitor_payload,
                    "competitors": competitors_payload,
                    "delta": delta,
                    "winner": winner,
                    "winner_reason": winner_reason,
                    "battle_for_snippet": {
                        "query": query,
                        "site": {
                            "domain": site_domain,
                            "answer_relevance": site_score,
                            "answer_relevance_source": site_score_source,
                            "answer_relevance_fallback_used": (
                                site_score_source is not None
                                and site_score_source != "aeo.answer_relevance"
                            ),
                            "answer_excerpt": self._extract_aeo_answer_excerpt(site_audit)
                            if site_audit
                            else None,
                            "selected_audit_timestamp": (
                                self._audit_created_at_iso(site_audit) if site_audit else None
                            ),
                        },
                        "competitor": {
                            "domain": competitor_site.domain if competitor_site else None,
                            "answer_relevance": competitor_score,
                            "answer_relevance_source": competitor_score_source,
                            "answer_relevance_fallback_used": (
                                competitor_score_source is not None
                                and competitor_score_source != "aeo.answer_relevance"
                            ),
                            "answer_excerpt": (
                                self._extract_aeo_answer_excerpt(competitor_audit)
                                if competitor_audit
                                else None
                            ),
                            "selected_audit_timestamp": (
                                self._audit_created_at_iso(competitor_audit)
                                if competitor_audit
                                else None
                            ),
                        },
                        "winner": winner,
                        "winner_reason": winner_reason,
                        "competitors": competitors_payload,
                    },
                }
            )

        return {
            "site_id": site_id,
            "site_domain": site_domain,
            "competitor_count": len(competitors),
            "queries": comparisons,
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.split())

    @staticmethod
    def _normalize_metric(value: Any) -> float:
        numeric = float(value)
        bounded = max(0.0, min(100.0, numeric))
        return round(bounded, 2)

    @classmethod
    def _normalize_metrics(cls, payload: dict[str, Any]) -> dict[str, float]:
        missing = [metric for metric in cls._METRICS if metric not in payload]
        if missing:
            raise ValueError(f"Missing required metrics: {', '.join(missing)}")

        return {metric: cls._normalize_metric(payload[metric]) for metric in cls._METRICS}

    @classmethod
    def _overall_score(cls, metrics: dict[str, float]) -> float:
        score = sum(metrics[metric] for metric in cls._METRICS) / len(cls._METRICS)
        return round(score, 2)

    @classmethod
    def _build_row(
        cls,
        *,
        name: str,
        metrics: dict[str, float],
        is_target: bool,
        target_metrics: dict[str, float],
    ) -> Row:
        row: Row = {
            "name": name,
            "is_target": is_target,
            **metrics,
            "overall_score": cls._overall_score(metrics),
            "deltas_vs_target": {
                metric: round(metrics[metric] - target_metrics[metric], 2)
                for metric in cls._METRICS
            },
        }
        return row

    def build_benchmark_table(
        self,
        *,
        target: dict[str, Any],
        competitors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        target_name = self._normalize_name(str(target.get("name", "")))
        if not target_name:
            raise ValueError("target name is required")

        target_metrics = self._normalize_metrics(target)

        rows: list[Row] = [
            self._build_row(
                name=target_name,
                metrics=target_metrics,
                is_target=True,
                target_metrics=target_metrics,
            )
        ]

        for competitor in competitors:
            competitor_name = self._normalize_name(str(competitor.get("name", "")))
            if not competitor_name:
                continue
            if competitor_name.lower() == target_name.lower():
                continue

            competitor_metrics = self._normalize_metrics(competitor)
            rows.append(
                self._build_row(
                    name=competitor_name,
                    metrics=competitor_metrics,
                    is_target=False,
                    target_metrics=target_metrics,
                )
            )

        rows.sort(key=lambda item: item["overall_score"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank

        return {
            "columns": [
                {"key": "rank", "label": "Rank", "type": "number"},
                {"key": "name", "label": "Brand", "type": "text"},
                {"key": "geo_visibility", "label": "GEO Visibility", "type": "score"},
                {"key": "aeo_score", "label": "AEO Score", "type": "score"},
                {"key": "entity_strength", "label": "Entity Strength", "type": "score"},
                {"key": "overall_score", "label": "Overall", "type": "score"},
            ],
            "rows": rows,
            "summary": {
                "target": target_name,
                "competitor_count": max(0, len(rows) - 1),
                "target_rank": next(
                    (row["rank"] for row in rows if row["is_target"]),
                    1,
                ),
            },
        }

    @classmethod
    def _latest_site_audit(cls, db: Session, site_id: int) -> models.Audit | None:
        return (
            db.query(models.Audit)
            .filter(models.Audit.site_id == site_id)
            .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
            .first()
        )

    @classmethod
    def _extract_speed_score(cls, audit: models.Audit) -> float:
        full_report = audit.full_report if isinstance(audit.full_report, dict) else {}
        performance = full_report.get("performance", {})
        analysis = full_report.get("analysis", {})

        candidates = [
            performance.get("performance_score") if isinstance(performance, dict) else None,
            full_report.get("performance_score"),
            analysis.get("performance_score") if isinstance(analysis, dict) else None,
            analysis.get("speed_score") if isinstance(analysis, dict) else None,
        ]

        for candidate in candidates:
            if candidate is None:
                continue
            return cls._normalize_metric(candidate)

        # Explicit fallback when speed data is missing from full_report.
        return 0.0

    @classmethod
    def _normalize_audit_axis_scores(cls, audit: models.Audit) -> list[float]:
        return [
            cls._normalize_metric(audit.seo_score or 0.0),
            cls._normalize_metric(audit.aeo_score or 0.0),
            cls._normalize_metric(audit.geo_score or 0.0),
            cls._extract_speed_score(audit),
        ]

    @staticmethod
    def _extract_entities(audit: models.Audit) -> list[str]:
        facts = getattr(audit, "entity_facts", None)
        if isinstance(facts, list) and facts:
            seen: set[str] = set()
            ordered: list[str] = []
            sorted_facts = sorted(
                facts,
                key=lambda item: (
                    float(item.ai_importance or 0.0),
                    float(item.relevance_score or 0.0),
                ),
                reverse=True,
            )
            for fact in sorted_facts:
                value = str(fact.entity_name or "").strip()
                if not value:
                    continue
                normalized = value.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                ordered.append(value)
            if ordered:
                return ordered

        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        candidates = [
            report.get("entities"),
            report.get("analysis", {}).get("entities")
            if isinstance(report.get("analysis"), dict)
            else None,
            report.get("analysis", {}).get("entities_detected")
            if isinstance(report.get("analysis"), dict)
            else None,
        ]
        for candidate in candidates:
            if not isinstance(candidate, list):
                continue
            values = [str(item).strip() for item in candidate if str(item).strip()]
            if values:
                return values
        return []

    @staticmethod
    def _extract_geo_results(audit: models.Audit) -> list[dict[str, Any]]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        geo_visibility = report.get("geo_visibility")
        if not isinstance(geo_visibility, dict):
            return []
        results = geo_visibility.get("results")
        return results if isinstance(results, list) else []

    @staticmethod
    def _normalize_entity_key(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    @classmethod
    def _extract_entity_mentions(cls, audit: models.Audit) -> list[dict[str, Any]]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}

        candidates = [
            report.get("entities"),
            analysis.get("entities"),
            analysis.get("entities_detected"),
        ]

        mentions: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, list):
                continue

            for item in candidate:
                raw_name: str | None = None
                relevance_candidate: Any = None

                if isinstance(item, str):
                    raw_name = item
                elif isinstance(item, dict):
                    for field in ("entity", "name", "label", "text", "term"):
                        value = item.get(field)
                        if isinstance(value, str) and value.strip():
                            raw_name = value
                            break
                    for score_field in ("relevance", "score", "weight", "importance"):
                        if score_field in item:
                            relevance_candidate = item.get(score_field)
                            break

                if not raw_name:
                    continue

                normalized_key = cls._normalize_entity_key(raw_name)
                if not normalized_key:
                    continue

                relevance: float | None = None
                if isinstance(relevance_candidate, dict):
                    relevance_candidate = relevance_candidate.get("score")
                if isinstance(relevance_candidate, (int, float)):
                    numeric = float(relevance_candidate)
                    relevance = numeric if numeric <= 1.0 else numeric / 100.0
                    relevance = max(0.0, min(1.0, relevance))

                mentions.append(
                    {
                        "key": normalized_key,
                        "entity": " ".join(str(raw_name).split()),
                        "relevance": relevance,
                    }
                )
        return mentions

    @staticmethod
    def _extract_result_query(item: dict[str, Any]) -> str | None:
        query = item.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()
        return None

    @classmethod
    def _extract_result_numeric_signal(cls, item: dict[str, Any]) -> float | None:
        for field in (
            "answer_relevance",
            "answer_relevance_score",
            "aeo_score",
            "score",
            "relevance",
        ):
            value = item.get(field)
            if isinstance(value, dict):
                value = value.get("score")
            if isinstance(value, (int, float)):
                numeric = float(value)
                normalized = numeric if numeric <= 1.0 else numeric / 100.0
                return max(0.0, min(1.0, normalized))
        return None

    @classmethod
    def _build_semantic_footprint(cls, audits: list[models.Audit]) -> dict[str, dict[str, Any]]:
        footprint: dict[str, dict[str, Any]] = {}
        for audit in audits:
            mentions = cls._extract_entity_mentions(audit)
            if not mentions:
                continue

            audit_answer_relevance = cls._extract_answer_relevance(audit)
            normalized_audit_answer = (
                max(0.0, min(1.0, audit_answer_relevance / 100.0))
                if isinstance(audit_answer_relevance, (int, float))
                else None
            )
            geo_results = cls._extract_geo_results(audit)

            for mention in mentions:
                key = mention["key"]
                entry = footprint.setdefault(
                    key,
                    {
                        "entity": mention["entity"],
                        "frequency": 0,
                        "relevance_scores": [],
                        "answer_relevance_scores": [],
                        "brand_cited_hits": 0,
                        "result_hits": 0,
                        "evidence_queries": set(),
                    },
                )
                entry["frequency"] += 1
                if mention["relevance"] is not None:
                    entry["relevance_scores"].append(mention["relevance"])
                if normalized_audit_answer is not None:
                    entry["answer_relevance_scores"].append(normalized_audit_answer)

                for result in geo_results:
                    if not isinstance(result, dict):
                        continue
                    query = cls._extract_result_query(result)
                    if not query:
                        continue
                    normalized_query = query.lower()
                    if key not in normalized_query:
                        continue
                    entry["result_hits"] += 1
                    entry["evidence_queries"].add(query)
                    if bool(result.get("brand_cited")):
                        entry["brand_cited_hits"] += 1
                    numeric_signal = cls._extract_result_numeric_signal(result)
                    if numeric_signal is not None:
                        entry["answer_relevance_scores"].append(numeric_signal)

        return footprint

    @classmethod
    def _average(cls, values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    @classmethod
    def _build_importance_breakdown(
        cls, entry: dict[str, Any], max_frequency: int
    ) -> dict[str, float]:
        frequency = int(entry.get("frequency") or 0)
        frequency_score = min(1.0, frequency / max_frequency) if max_frequency > 0 else 0.0
        relevance_score = cls._average(entry.get("relevance_scores", []))
        answer_relevance_score = cls._average(entry.get("answer_relevance_scores", []))

        result_hits = int(entry.get("result_hits") or 0)
        brand_cited_hits = int(entry.get("brand_cited_hits") or 0)
        brand_cited_rate = (brand_cited_hits / result_hits) if result_hits > 0 else 0.0

        ai_importance = (
            0.35 * frequency_score
            + 0.25 * relevance_score
            + 0.2 * brand_cited_rate
            + 0.2 * answer_relevance_score
        )

        return {
            "ai_importance": round(ai_importance, 4),
            "frequency": float(frequency),
            "frequency_score": round(frequency_score, 4),
            "avg_relevance": round(relevance_score, 4),
            "brand_cited_rate": round(brand_cited_rate, 4),
            "avg_answer_relevance": round(answer_relevance_score, 4),
        }

    @staticmethod
    def _build_recommended_topic(entity: str, evidence_queries: list[str]) -> str:
        if evidence_queries:
            return f"Create or improve a page answering: {evidence_queries[0]}"
        return f"Create dedicated content targeting the entity: {entity}."

    @staticmethod
    def _domains_from_result(item: dict[str, Any]) -> list[str]:
        citations = item.get("provider_citations")
        if not isinstance(citations, list):
            return []
        domains: list[str] = []
        for citation in citations:
            parsed = urlparse(str(citation).strip())
            domain = parsed.netloc.lower().strip()
            if domain:
                domains.append(domain)
        return domains

    def _build_common_entity_gaps(
        self,
        *,
        base_audit: models.Audit,
        comp_audit: models.Audit,
    ) -> list[dict[str, Any]]:
        base_entities = {entity.lower(): entity for entity in self._extract_entities(base_audit)}
        comp_entities = {entity.lower(): entity for entity in self._extract_entities(comp_audit)}
        common_keys = sorted(set(base_entities).intersection(comp_entities))
        if not common_keys:
            return []

        base_results = self._extract_geo_results(base_audit)
        comp_results = self._extract_geo_results(comp_audit)

        def count_entity_citations(results: list[dict[str, Any]], entity_key: str) -> int:
            count = 0
            for item in results:
                query = str(item.get("query") or "").lower()
                if entity_key in query and bool(item.get("brand_cited")):
                    count += max(1, len(self._domains_from_result(item)))
            return count

        return [
            {
                "entity": base_entities.get(key, comp_entities[key]),
                "site_citations": count_entity_citations(base_results, key),
                "comp_citations": count_entity_citations(comp_results, key),
            }
            for key in common_keys
        ]

    def _build_missing_answers(
        self,
        *,
        base_audit: models.Audit,
        comp_audit: models.Audit,
    ) -> list[dict[str, Any]]:
        base_results = self._extract_geo_results(base_audit)
        comp_results = self._extract_geo_results(comp_audit)

        base_map: dict[str, bool] = {}
        for item in base_results:
            query = str(item.get("query") or "").strip().lower()
            if query:
                base_map[query] = base_map.get(query, False) or bool(item.get("brand_cited"))

        missing: list[dict[str, Any]] = []
        for item in comp_results:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            normalized_query = query.lower()
            competitor_cited = bool(item.get("brand_cited"))
            if competitor_cited and not base_map.get(normalized_query, False):
                missing.append(
                    {
                        "query": query,
                        "competitor_citations": self._domains_from_result(item),
                    }
                )

        deduped: dict[str, dict[str, Any]] = {}
        for item in missing:
            existing = deduped.get(item["query"])
            if existing is None:
                deduped[item["query"]] = item
                continue
            existing["competitor_citations"] = sorted(
                set(existing["competitor_citations"]).union(item["competitor_citations"])
            )

        return list(deduped.values())

    def build_competitor_matrix(
        self,
        *,
        db: Session,
        site: models.Site,
    ) -> list[dict[str, Any]]:
        base_audit = self._latest_site_audit(db, site.id)
        base_overall = self._overall_score(
            {
                "geo_visibility": self._normalize_metric(base_audit.geo_score or 0.0)
                if base_audit
                else 0.0,
                "aeo_score": self._normalize_metric(base_audit.aeo_score or 0.0)
                if base_audit
                else 0.0,
                "entity_strength": self._normalize_metric(base_audit.seo_score or 0.0)
                if base_audit
                else 0.0,
            }
        )

        rows: list[dict[str, Any]] = []
        for competitor_site in site.competitors:
            audit = self._latest_site_audit(db, competitor_site.id)
            geo_score = self._normalize_metric(audit.geo_score or 0.0) if audit else 0.0
            aeo_score = self._normalize_metric(audit.aeo_score or 0.0) if audit else 0.0
            seo_score = self._normalize_metric(audit.seo_score or 0.0) if audit else 0.0
            overall = round((geo_score + aeo_score + seo_score) / 3.0, 2)
            rows.append(
                {
                    "id": competitor_site.id,
                    "name": competitor_site.display_name or competitor_site.domain,
                    "geo_score": geo_score,
                    "aeo_score": aeo_score,
                    "seo_score": seo_score,
                    "gap_to_you": round(overall - base_overall, 2),
                }
            )

        rows.sort(key=lambda item: item["gap_to_you"], reverse=True)
        return rows

    def compare_latest_site_audits(
        self,
        *,
        db: Session,
        base_site_id: int,
        comp_site_id: int,
    ) -> dict[str, Any]:
        base_audit = self._latest_site_audit(db, base_site_id)
        if not base_audit:
            raise ValueError("No audits found for base site.")

        comp_audit = self._latest_site_audit(db, comp_site_id)
        if not comp_audit:
            raise ValueError("No audits found for competitor site.")

        return {
            "labels": list(self._COMPARE_AXES),
            "site_scores": self._normalize_audit_axis_scores(base_audit),
            "comp_scores": self._normalize_audit_axis_scores(comp_audit),
            "audit_timestamps": [
                base_audit.created_at.isoformat() if base_audit.created_at else "",
                comp_audit.created_at.isoformat() if comp_audit.created_at else "",
            ],
            "common_entities": self._build_common_entity_gaps(
                base_audit=base_audit, comp_audit=comp_audit
            ),
            "missing_answers": self._build_missing_answers(
                base_audit=base_audit, comp_audit=comp_audit
            ),
        }

    def compare_semantic_footprint(
        self,
        site_id_1: int,
        site_id_2: int,
        db: Session,
    ) -> dict[str, Any]:
        audits_site_1 = db.query(models.Audit).filter(models.Audit.site_id == site_id_1).all()
        audits_site_2 = db.query(models.Audit).filter(models.Audit.site_id == site_id_2).all()

        if not audits_site_1:
            raise ValueError("No audits found for base site.")
        if not audits_site_2:
            raise ValueError("No audits found for competitor site.")

        footprint_1 = self._build_semantic_footprint(audits_site_1)
        footprint_2 = self._build_semantic_footprint(audits_site_2)

        missing_keys = sorted(set(footprint_2).difference(footprint_1))
        max_frequency = max(
            (int(footprint_2[key].get("frequency") or 0) for key in missing_keys), default=0
        )

        missing_entities: list[dict[str, Any]] = []
        for key in missing_keys:
            entry = footprint_2[key]
            importance = self._build_importance_breakdown(entry, max_frequency=max_frequency)
            evidence_queries = sorted(entry.get("evidence_queries", set()))
            missing_entities.append(
                {
                    "entity": entry.get("entity") or key,
                    "normalized_key": key,
                    "importance": importance,
                    "evidence_queries": evidence_queries,
                    "recommended_topic": self._build_recommended_topic(
                        str(entry.get("entity") or key),
                        evidence_queries,
                    ),
                }
            )

        missing_entities.sort(
            key=lambda item: (
                item["importance"]["ai_importance"],
                item["importance"]["frequency"],
                item["entity"],
            ),
            reverse=True,
        )

        return {
            "base_site_id": site_id_1,
            "comp_site_id": site_id_2,
            "missing_entities": missing_entities,
        }
