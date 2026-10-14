from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

import models
from services.visibility_scoring import matches_target_domain
from services.reports.audit_result_adapter import to_canonical_audit_result
from services.unified_truth_context_service import UnifiedTruthContextService
from services.workspace_rbac import resolve_project_access

LOW_SCORE_THRESHOLD = 55.0
MEDIUM_SCORE_THRESHOLD = 70.0
MAX_AEO_QUERY_IDEAS = 10
MAX_GEO_PROMPT_IDEAS = 10
MAX_CONTENT_GAPS = 3
MAX_ROADMAP_ITEMS = 3
SUPPORTED_CONFIDENCE_LEVELS = {"high", "medium", "low"}
SUPPORTED_IDEA_LABELS = {"measured", "inferred", "hypothesis"}


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _as_string(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        normalized = _as_string(item)
        if normalized:
            items.append(normalized)
    return items


def _normalize_target_domain(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
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


def _context_matches_domain(context_key: str | None, domain: str | None) -> bool:
    normalized_context = str(context_key or "").strip().lower()
    normalized_domain = _normalize_target_domain(domain)
    if not normalized_context or not normalized_domain:
        return False
    return normalized_context == normalized_domain or normalized_context.startswith(
        f"{normalized_domain}/"
    )


def _dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


def _split_text_fragments(value: str | None, *, limit: int = 3) -> list[str]:
    source = _as_string(value)
    if source is None:
        return []

    fragments = [
        fragment.strip(" -")
        for fragment in re.split(r"[.\n;|]", source)
        if fragment and fragment.strip(" -")
    ]
    return fragments[:limit]


def _coerce_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric < 0:
            return 0.0
        if numeric > 100:
            return 100.0
        return numeric
    if isinstance(value, str) and value.strip():
        try:
            numeric = float(value)
        except ValueError:
            return None
        if numeric < 0:
            return 0.0
        if numeric > 100:
            return 100.0
        return numeric
    return None


def _confidence_level(value: Any, *, default: str = "medium") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_CONFIDENCE_LEVELS:
        return normalized
    return default


def _idea_label(value: str, *, fallback: str = "hypothesis") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_IDEA_LABELS:
        return normalized
    return fallback


def _effort_score(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "low":
        return 2
    if normalized == "high":
        return 4
    return 3


def _impact_level(expected_score_impact: Any, *, fallback: str = "medium") -> str:
    if isinstance(expected_score_impact, dict):
        scores = [
            _coerce_score(expected_score_impact.get(key))
            for key in ("overall", "seo", "geo", "aeo")
        ]
        numeric_values = [value for value in scores if value is not None]
        if numeric_values:
            highest = max(numeric_values)
            if highest >= 10:
                return "high"
            if highest >= 4:
                return "medium"
            return "low"
    return fallback


def _count_target_citations(batch: models.VisibilityRunBatch) -> int:
    """Count valid citations belonging to the batch's target domain."""
    total = 0
    for run in batch.runs or []:
        for citation in run.valid_citations or []:
            if batch.target_domain:
                if matches_target_domain(citation, batch.target_domain):
                    total += 1
            else:
                total += 1
    return total


def _visibility_status(batch: models.VisibilityRunBatch | None) -> str:
    if batch is None:
        return "pending"
    if batch.status in {"queued", "running", "retrying"}:
        return "pending"
    if batch.status == "failed":
        return "failed"
    citations_found = _count_target_citations(batch)
    return "cited" if citations_found > 0 else "not_cited"


def _monitoring_note(*, citations_found: int, score: float | None, status: str) -> str:
    if status == "cited":
        return f"Latest monitoring runs found {citations_found} citation(s)."
    if status == "not_cited":
        if score is None:
            return "Latest monitoring runs completed without citation wins."
        return f"Latest monitoring score is {round(score)} / 100 with no citation wins yet."
    if status == "failed":
        return "Latest monitoring run failed and needs a retry."
    return "Tracking exists, but a completed monitoring run is not available yet."


def _manual_tracker_note(*, kind: str) -> str:
    return (
        f"Saved {kind} as a manual hypothesis. Add project monitoring to validate it with "
        "measured citation telemetry."
    )


def _build_source(
    *,
    label: str,
    source_type: str,
    measured: bool,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "source_type": source_type,
        "measured": measured,
        "updated_at": _isoformat(updated_at),
    }


def _build_idea(
    *,
    text: str,
    confidence: str,
    label: str,
    source_basis: list[str],
    status_note: str | None = None,
    last_verified_at: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "confidence": _confidence_level(confidence, default="medium"),
        "label": _idea_label(label),
        "source_basis": _dedupe_ordered(source_basis),
        "status_note": _as_string(status_note),
        "last_verified_at": last_verified_at,
    }


class StrategicInsightsService:
    def __init__(self, db: Session):
        self.db = db

    def generate_for_audit(
        self,
        *,
        user: models.User,
        audit_id: int,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        audit, project = self._resolve_audit(user=user, audit_id=audit_id, project_id=project_id)
        canonical_report = to_canonical_audit_result(
            audit.full_report if isinstance(audit.full_report, dict) else {},
            audit_url=audit.url,
            audit_target_type=str(
                getattr(audit.audit_target_type, "value", audit.audit_target_type or "website")
            ),
            target_name=audit.target_name,
            target_url=audit.target_url,
            target_metadata=audit.target_metadata
            if isinstance(audit.target_metadata, dict)
            else {},
            created_at=audit.created_at,
        )

        target = (
            canonical_report.get("target")
            if isinstance(canonical_report.get("target"), dict)
            else {}
        )
        scores = (
            canonical_report.get("scores")
            if isinstance(canonical_report.get("scores"), dict)
            else {}
        )
        confidence = (
            canonical_report.get("confidence")
            if isinstance(canonical_report.get("confidence"), dict)
            else {}
        )
        metadata = (
            canonical_report.get("metadata")
            if isinstance(canonical_report.get("metadata"), dict)
            else {}
        )

        target_name = (
            _as_string(target.get("name"))
            or _as_string(audit.target_name)
            or (project.name if project is not None else None)
            or _normalize_target_domain(
                _as_string(target.get("url")) or audit.target_url or audit.url
            )
            or "This target"
        )
        target_url = (
            _as_string(target.get("url"))
            or _as_string(audit.target_url)
            or _as_string(audit.url)
            or (project.domain_url if project is not None else None)
        )
        target_domain = _normalize_target_domain(
            target_url or (project.domain_url if project else None)
        )

        visibility_context = self._load_visibility_context(
            project=project, target_domain=target_domain
        )
        tracker_context = self._load_tracker_context(user=user, target_domain=target_domain)
        project_profile = self._build_project_profile(project=project)
        signal_intelligence = UnifiedTruthContextService(self.db).build_project_signal_intelligence(
            project_id=project.id if project is not None else None
        )
        recommendations = self._apply_signal_history_to_recommendations(
            recommendations=self._extract_recommendations(canonical_report=canonical_report),
            signal_intelligence=signal_intelligence,
        )
        content_gaps = self._build_content_gap_theory(
            target_name=target_name,
            project_profile=project_profile,
            visibility_context=visibility_context,
            tracker_context=tracker_context,
        )
        sources = self._build_grounding_sources(
            audit=audit,
            project=project,
            visibility_context=visibility_context,
            tracker_context=tracker_context,
            signal_intelligence=signal_intelligence,
        )

        aeo_query_ideas = self._build_aeo_query_ideas(
            target_name=target_name,
            project_profile=project_profile,
            visibility_context=visibility_context,
            tracker_context=tracker_context,
        )
        geo_prompt_ideas = self._build_geo_prompt_ideas(
            target_name=target_name,
            project_profile=project_profile,
            visibility_context=visibility_context,
            tracker_context=tracker_context,
        )

        return {
            "generated_at": _isoformat(datetime.now(timezone.utc)),
            "audit_id": audit.id,
            "project_id": project.id if project is not None else None,
            "signal_intelligence": signal_intelligence,
            "grounding_sources": sources,
            "executive_summary": self._build_executive_summary(
                target_name=target_name,
                scores=scores,
                visibility_context=visibility_context,
                signal_intelligence=signal_intelligence,
            ),
            "critical_alerts": self._build_critical_alerts(
                scores=scores,
                confidence=confidence,
                metadata=metadata,
                visibility_context=visibility_context,
            ),
            "priority_roadmap": recommendations,
            "content_gap_theory": content_gaps,
            "technical_debt_explanation": self._build_technical_debt_explanation(scores=scores),
            "aeo_query_ideas": aeo_query_ideas,
            "geo_prompt_ideas": geo_prompt_ideas,
        }

    def _resolve_audit(
        self,
        *,
        user: models.User,
        audit_id: int,
        project_id: int | None,
    ) -> tuple[models.Audit, models.Project | None]:
        audit = (
            self.db.query(models.Audit)
            .options(joinedload(models.Audit.project).joinedload(models.Project.workspace))
            .filter(models.Audit.id == audit_id)
            .first()
        )
        if audit is None:
            raise HTTPException(status_code=404, detail="Audit not found.")

        resolved_project: models.Project | None = None
        if project_id is not None:
            access = resolve_project_access(
                self.db, user=user, project_id=project_id, allow_client_readonly=False
            )
            resolved_project = access.project
            if audit.project_id != resolved_project.id:
                raise HTTPException(status_code=404, detail="Audit not found for this project.")
            return audit, resolved_project

        if audit.project_id is not None:
            access = resolve_project_access(
                self.db,
                user=user,
                project_id=int(audit.project_id),
                allow_client_readonly=False,
            )
            resolved_project = access.project
            return audit, resolved_project

        if int(audit.user_id or 0) != int(user.id):
            raise HTTPException(status_code=403, detail="Not authorized for this audit.")

        return audit, None

    def _build_project_profile(self, *, project: models.Project | None) -> dict[str, Any]:
        if project is None:
            return {
                "icp_roles": [],
                "pain_points": [],
                "priority_pulse_tags": [],
                "sme_profiles": [],
                "competitors": [],
                "target_keywords": [],
                "target_country": None,
                "language": None,
            }

        keywords = (
            self.db.query(models.TargetKeyword)
            .filter(
                models.TargetKeyword.project_id == project.id,
                models.TargetKeyword.is_active.is_(True),
            )
            .order_by(models.TargetKeyword.created_at.asc(), models.TargetKeyword.id.asc())
            .limit(10)
            .all()
        )

        competitor_names: list[str] = []
        for item in project.competitors_json or []:
            if isinstance(item, dict):
                name = _as_string(item.get("name") or item.get("domain") or item.get("url"))
            else:
                name = _as_string(item)
            if name:
                competitor_names.append(name)

        return {
            "icp_roles": _as_string_list(list(project.icp_roles or [])),
            "pain_points": _split_text_fragments(project.pain_points),
            "priority_pulse_tags": _as_string_list(list(project.priority_pulse_tags or [])),
            "sme_profiles": _as_string_list(list(project.sme_profiles or [])),
            "competitors": _dedupe_ordered(competitor_names),
            "target_keywords": _dedupe_ordered(
                [_as_string(keyword.keyword) or "" for keyword in keywords]
            ),
            "target_country": _as_string(project.target_country),
            "language": _as_string(project.language),
            "usp": _as_string(project.usp),
        }

    def _load_visibility_context(
        self,
        *,
        project: models.Project | None,
        target_domain: str | None,
    ) -> dict[str, list[dict[str, Any]]]:
        if project is None:
            return {"aeo": [], "geo": []}

        queries = (
            self.db.query(models.ProjectVisibilityQuery)
            .filter(
                models.ProjectVisibilityQuery.project_id == project.id,
                models.ProjectVisibilityQuery.is_active.is_(True),
            )
            .order_by(
                models.ProjectVisibilityQuery.created_at.asc(),
                models.ProjectVisibilityQuery.id.asc(),
            )
            .all()
        )
        if not queries:
            return {"aeo": [], "geo": []}

        topics = [query.query_text for query in queries if _as_string(query.query_text)]
        batches = (
            self.db.query(models.VisibilityRunBatch)
            .options(joinedload(models.VisibilityRunBatch.runs))
            .filter(
                models.VisibilityRunBatch.project_id == project.id,
                models.VisibilityRunBatch.topic.in_(topics),
            )
            .order_by(
                models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc()
            )
            .all()
        )

        latest_by_topic_provider: dict[tuple[str, str], models.VisibilityRunBatch] = {}
        for batch in batches:
            if target_domain and batch.target_domain not in {None, target_domain}:
                continue
            key = (str(batch.topic or ""), str(batch.provider or ""))
            latest_by_topic_provider.setdefault(key, batch)

        grouped: dict[str, list[dict[str, Any]]] = {"aeo": [], "geo": []}
        for query in queries:
            query_text = _as_string(query.query_text)
            if query_text is None:
                continue
            query_type = str(query.query_type or "aeo").strip().lower() or "aeo"
            providers = _as_string_list(list(query.providers or []))
            provider_batches = [
                latest_by_topic_provider.get((query_text, provider))
                for provider in providers
                if latest_by_topic_provider.get((query_text, provider)) is not None
            ]
            if not provider_batches:
                provider_batches = [
                    batch
                    for (topic, _provider), batch in latest_by_topic_provider.items()
                    if topic == query_text
                ]

            citations_found = sum(_count_target_citations(batch) for batch in provider_batches)
            scores = [float(batch.score) for batch in provider_batches if batch.score is not None]
            latest_timestamp = max(
                (
                    batch.completed_at or batch.updated_at or batch.created_at
                    for batch in provider_batches
                    if batch.completed_at or batch.updated_at or batch.created_at
                ),
                default=None,
            )
            status = "pending"
            if provider_batches:
                statuses = [_visibility_status(batch) for batch in provider_batches]
                if "cited" in statuses:
                    status = "cited"
                elif "not_cited" in statuses:
                    status = "not_cited"
                elif "failed" in statuses:
                    status = "failed"

            grouped.setdefault(query_type, []).append(
                {
                    "query_text": query_text,
                    "providers": providers
                    or _dedupe_ordered([str(batch.provider) for batch in provider_batches]),
                    "citations_found": citations_found,
                    "score": round(sum(scores) / len(scores), 2) if scores else None,
                    "status": status,
                    "last_checked_at": _isoformat(latest_timestamp),
                }
            )

        for key in list(grouped.keys()):
            grouped[key].sort(
                key=lambda item: (
                    int(item.get("citations_found") or 0),
                    float(item.get("score") or -1),
                    str(item.get("last_checked_at") or ""),
                ),
                reverse=True,
            )
        return grouped

    def _load_tracker_context(
        self,
        *,
        user: models.User,
        target_domain: str | None,
    ) -> dict[str, list[dict[str, Any]]]:
        aeo_rows = (
            self.db.query(models.AeoQueryTrackerEntry)
            .filter(models.AeoQueryTrackerEntry.user_id == user.id)
            .order_by(
                models.AeoQueryTrackerEntry.tracked_at.desc(), models.AeoQueryTrackerEntry.id.desc()
            )
            .limit(50)
            .all()
        )
        geo_rows = (
            self.db.query(models.GeoPromptTrackerEntry)
            .filter(models.GeoPromptTrackerEntry.user_id == user.id)
            .order_by(
                models.GeoPromptTrackerEntry.tracked_at.desc(),
                models.GeoPromptTrackerEntry.id.desc(),
            )
            .limit(50)
            .all()
        )

        return {
            "aeo": [
                {
                    "text": str(row.query or "").strip(),
                    "citation_hits": max(0, int(row.citation_hits or 0)),
                    "tracked_at": _isoformat(row.tracked_at),
                }
                for row in aeo_rows
                if str(row.query or "").strip()
                and _context_matches_domain(row.context_key, target_domain)
            ],
            "geo": [
                {
                    "text": str(row.prompt or "").strip(),
                    "citation_hits": max(0, int(row.citation_hits or 0)),
                    "tracked_at": _isoformat(row.tracked_at),
                }
                for row in geo_rows
                if str(row.prompt or "").strip()
                and _context_matches_domain(row.context_key, target_domain)
            ],
        }

    def _build_grounding_sources(
        self,
        *,
        audit: models.Audit,
        project: models.Project | None,
        visibility_context: dict[str, list[dict[str, Any]]],
        tracker_context: dict[str, list[dict[str, Any]]],
        signal_intelligence: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sources = [
            _build_source(
                label=f"Latest canonical audit #{audit.id}",
                source_type="audit",
                measured=False,
                updated_at=audit.created_at,
            )
        ]
        if project is not None:
            sources.append(
                _build_source(
                    label="Project profile fields",
                    source_type="project_profile",
                    measured=False,
                )
            )
        if visibility_context.get("aeo") or visibility_context.get("geo"):
            latest_visibility_at = max(
                (
                    datetime.fromisoformat(str(item["last_checked_at"]).replace("Z", "+00:00"))
                    for entries in visibility_context.values()
                    for item in entries
                    if item.get("last_checked_at")
                ),
                default=None,
            )
            sources.append(
                _build_source(
                    label="Project visibility monitoring",
                    source_type="monitoring",
                    measured=True,
                    updated_at=latest_visibility_at,
                )
            )
        if tracker_context.get("aeo"):
            latest_aeo_tracker = max(
                (
                    datetime.fromisoformat(str(item["tracked_at"]).replace("Z", "+00:00"))
                    for item in tracker_context["aeo"]
                    if item.get("tracked_at")
                ),
                default=None,
            )
            sources.append(
                _build_source(
                    label="Saved AEO tracker queries",
                    source_type="aeo_tracker",
                    measured=False,
                    updated_at=latest_aeo_tracker,
                )
            )
        if tracker_context.get("geo"):
            latest_geo_tracker = max(
                (
                    datetime.fromisoformat(str(item["tracked_at"]).replace("Z", "+00:00"))
                    for item in tracker_context["geo"]
                    if item.get("tracked_at")
                ),
                default=None,
            )
            sources.append(
                _build_source(
                    label="Saved GEO tracker prompts",
                    source_type="geo_tracker",
                    measured=False,
                    updated_at=latest_geo_tracker,
                )
            )
        if bool(signal_intelligence.get("available")):
            sources.append(
                _build_source(
                    label="Signal warehouse intelligence",
                    source_type="signal_warehouse",
                    measured=True,
                )
            )
        return sources

    def _extract_recommendations(self, *, canonical_report: dict[str, Any]) -> list[dict[str, Any]]:
        recommendations_block = (
            canonical_report.get("recommendations")
            if isinstance(canonical_report.get("recommendations"), dict)
            else {}
        )
        recommendation_items = (
            recommendations_block.get("items")
            if isinstance(recommendations_block.get("items"), list)
            else []
        )
        normalized: list[dict[str, Any]] = []
        for item in recommendation_items:
            if not isinstance(item, dict):
                continue
            title = _as_string(item.get("title"))
            action = _as_string(item.get("action"))
            if title is None and action is None:
                continue
            normalized.append(
                {
                    "task": title or action or "Recommendation",
                    "category": _as_string(item.get("category")) or "strategy",
                    "impact": _impact_level(item.get("expected_score_impact")),
                    "effort_score": _effort_score(item.get("estimated_effort")),
                    "reasoning": _as_string(item.get("summary"))
                    or _as_string(item.get("rationale"))
                    or action
                    or "Derived from the latest canonical audit.",
                    "confidence": _confidence_level(item.get("confidence"), default="medium"),
                    "label": (
                        "hypothesis"
                        if str(item.get("source_type") or "").strip().lower() == "ai_inference"
                        else "inferred"
                    ),
                    "source_basis": _dedupe_ordered(
                        _as_string_list(item.get("grounded_by_findings"))
                        + _as_string_list(item.get("derived_from"))
                        + ["Latest canonical audit recommendations"]
                    ),
                }
            )

        if normalized:
            return normalized[:MAX_ROADMAP_ITEMS]

        scores = (
            canonical_report.get("scores")
            if isinstance(canonical_report.get("scores"), dict)
            else {}
        )
        score_rows = [
            (
                "Technical",
                "Improve crawl, indexing, and performance foundations.",
                _coerce_score(scores.get("seo")),
            ),
            (
                "AEO",
                "Ship answer-first schema and extractable answer blocks.",
                _coerce_score(scores.get("aeo")),
            ),
            (
                "GEO",
                "Strengthen citation-ready comparisons and entity trust cues.",
                _coerce_score(scores.get("geo")),
            ),
        ]
        fallback_items: list[dict[str, Any]] = []
        for category, reasoning, score in score_rows:
            if score is None:
                continue
            if score >= MEDIUM_SCORE_THRESHOLD and fallback_items:
                continue
            fallback_items.append(
                {
                    "task": reasoning,
                    "category": category,
                    "impact": "high" if score < LOW_SCORE_THRESHOLD else "medium",
                    "effort_score": 3,
                    "reasoning": f"Latest score for {category.upper()} is {round(score)} / 100.",
                    "confidence": "medium",
                    "label": "inferred",
                    "source_basis": ["Latest canonical audit scores"],
                }
            )
            if len(fallback_items) >= MAX_ROADMAP_ITEMS:
                break
        return fallback_items

    def _build_executive_summary(
        self,
        *,
        target_name: str,
        scores: dict[str, Any],
        visibility_context: dict[str, list[dict[str, Any]]],
        signal_intelligence: dict[str, Any],
    ) -> str:
        seo_score = _coerce_score(scores.get("seo"))
        aeo_score = _coerce_score(scores.get("aeo"))
        geo_score = _coerce_score(scores.get("geo"))
        aeo_cited = sum(
            1 for item in visibility_context.get("aeo", []) if item.get("status") == "cited"
        )
        geo_cited = sum(
            1 for item in visibility_context.get("geo", []) if item.get("status") == "cited"
        )

        score_bits = [
            f"SEO {round(seo_score)} / 100" if seo_score is not None else None,
            f"AEO {round(aeo_score)} / 100" if aeo_score is not None else None,
            f"GEO {round(geo_score)} / 100" if geo_score is not None else None,
        ]
        summary = f"{target_name} currently benchmarks at {', '.join([bit for bit in score_bits if bit])} in the latest canonical audit."
        monitoring_bits: list[str] = []
        if visibility_context.get("aeo"):
            monitoring_bits.append(
                f"{aeo_cited} of {len(visibility_context['aeo'])} monitored AEO queries have citation wins."
            )
        if visibility_context.get("geo"):
            monitoring_bits.append(
                f"{geo_cited} of {len(visibility_context['geo'])} monitored GEO prompts have citation wins."
            )
        if monitoring_bits:
            summary = f"{summary} {' '.join(monitoring_bits)}"
        else:
            summary = (
                f"{summary} No measured visibility monitoring data is available yet, so idea generation "
                "stays evidence-led but hypothesis-heavy."
            )

        signal_bits: list[str] = []
        benchmarks = (
            signal_intelligence.get("benchmarks") if isinstance(signal_intelligence, dict) else {}
        )
        geo_benchmark = benchmarks.get("geo_score") if isinstance(benchmarks, dict) else None
        if isinstance(geo_benchmark, dict) and geo_benchmark.get("status") == "ok":
            signal_bits.append(
                f"Historical cohort positioning is top {int(geo_benchmark.get('top_percent') or 0)}% for GEO."
            )
        citation_stability = (
            signal_intelligence.get("citation_stability")
            if isinstance(signal_intelligence, dict)
            else None
        )
        if (
            isinstance(citation_stability, dict)
            and int(citation_stability.get("data_points_used") or 0) > 0
        ):
            signal_bits.append(
                f"Citation stability is {round(float(citation_stability.get('value') or 0.0))} / 100."
            )
        if signal_bits:
            return f"{summary} {' '.join(signal_bits)}"
        return summary

    @staticmethod
    def _impact_weight(value: str) -> float:
        normalized = str(value or "").strip().lower()
        if normalized == "high":
            return 3.0
        if normalized == "medium":
            return 2.0
        if normalized == "low":
            return 1.0
        return 0.0

    @staticmethod
    def _confidence_weight(value: str) -> float:
        normalized = str(value or "").strip().lower()
        if normalized == "high":
            return 1.0
        if normalized == "medium":
            return 0.6
        if normalized == "low":
            return 0.3
        return 0.0

    def _apply_signal_history_to_recommendations(
        self,
        *,
        recommendations: list[dict[str, Any]],
        signal_intelligence: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not recommendations:
            return recommendations

        history_rows = (
            signal_intelligence.get("remediation_category_performance")
            if isinstance(signal_intelligence, dict)
            else None
        )
        history_by_category = {
            str(item.get("category") or ""): item
            for item in history_rows or []
            if isinstance(item, dict)
        }

        ranked: list[dict[str, Any]] = []
        for index, recommendation in enumerate(recommendations):
            item = dict(recommendation)
            category_key = self._normalize_recommendation_history_category(item.get("category"))
            history = history_by_category.get(category_key)

            source_basis = _dedupe_ordered(_as_string_list(item.get("source_basis")))
            reasoning = _as_string(item.get("reasoning")) or ""
            history_score = 0.0
            if history is not None:
                avg_delta = float(history.get("avg_combined_delta") or 0.0)
                positive_rate = float(history.get("positive_rate") or 0.0)
                history_score = max(0.0, min(3.0, (avg_delta / 3.0) + positive_rate))
                source_basis.append("Historical remediation outcomes")
                note = _as_string(history.get("note"))
                if note:
                    reasoning = f"{reasoning} {note}".strip()

            item["reasoning"] = reasoning or "Derived from the latest canonical audit."
            item["source_basis"] = source_basis
            item["_rank_score"] = (
                self._impact_weight(str(item.get("impact") or "medium"))
                + self._confidence_weight(str(item.get("confidence") or "medium"))
                + history_score
                - (float(item.get("effort_score") or 3) / 10.0)
            )
            item["_index"] = index
            ranked.append(item)

        ranked.sort(
            key=lambda item: (
                float(item.get("_rank_score") or 0.0),
                -int(item.get("_index") or 0),
            ),
            reverse=True,
        )

        normalized_ranked: list[dict[str, Any]] = []
        for item in ranked[:MAX_ROADMAP_ITEMS]:
            item.pop("_rank_score", None)
            item.pop("_index", None)
            normalized_ranked.append(item)
        return normalized_ranked

    @staticmethod
    def _normalize_recommendation_history_category(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"seo", "technical", "performance", "indexing", "schema"}:
            return "technical"
        if normalized in {"content", "aeo", "geo", "semantic"}:
            return "content"
        if normalized in {"backlinks", "authority", "offpage", "off-page", "mentions"}:
            return "backlinks"
        if normalized in {"strategy", "competitive", "entity", "brand"}:
            return "strategy"
        return normalized or "unknown"

    def _build_critical_alerts(
        self,
        *,
        scores: dict[str, Any],
        confidence: dict[str, Any],
        metadata: dict[str, Any],
        visibility_context: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        alerts: list[str] = []

        aeo_score = _coerce_score(scores.get("aeo"))
        geo_score = _coerce_score(scores.get("geo"))
        seo_score = _coerce_score(scores.get("seo"))

        if aeo_score is not None and aeo_score < LOW_SCORE_THRESHOLD:
            alerts.append(
                f"AEO remains below threshold at {round(aeo_score)} / 100, so answer extraction ideas should be treated as high-priority."
            )
        if geo_score is not None and geo_score < LOW_SCORE_THRESHOLD:
            alerts.append(
                f"GEO remains below threshold at {round(geo_score)} / 100, which limits citation trust in AI answer surfaces."
            )
        if seo_score is not None and seo_score < LOW_SCORE_THRESHOLD:
            alerts.append(
                f"SEO foundations are still weak at {round(seo_score)} / 100, which constrains both crawl understanding and downstream AI visibility."
            )

        if not visibility_context.get("aeo"):
            alerts.append(
                "No measured AEO monitoring queries are configured yet; AEO idea labels remain inferred or hypothesis-only."
            )
        if not visibility_context.get("geo"):
            alerts.append(
                "No measured GEO monitoring prompts are configured yet; GEO idea labels remain inferred or hypothesis-only."
            )

        for warning in _as_string_list(confidence.get("warnings"))[:2]:
            alerts.append(warning)

        if not alerts:
            outcome = _as_string(metadata.get("audit_outcome")) or "completed"
            alerts.append(
                f"The latest audit completed with outcome '{outcome}' and no critical strategic blockers were detected."
            )

        return _dedupe_ordered(alerts)[:2]

    def _build_content_gap_theory(
        self,
        *,
        target_name: str,
        project_profile: dict[str, Any],
        visibility_context: dict[str, list[dict[str, Any]]],
        tracker_context: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        gaps: list[str] = []

        for item in visibility_context.get("aeo", []):
            if item.get("status") == "not_cited":
                gaps.append(
                    f"Build answer-first coverage around '{item['query_text']}' because it is already monitored without recent citation wins."
                )
            if len(gaps) >= MAX_CONTENT_GAPS:
                return gaps

        for keyword in project_profile.get("target_keywords", [])[:MAX_CONTENT_GAPS]:
            gaps.append(
                f"Expand supporting proof and comparison content around '{keyword}' to strengthen {target_name}'s citation relevance."
            )
            if len(gaps) >= MAX_CONTENT_GAPS:
                return gaps

        for query in tracker_context.get("aeo", [])[:MAX_CONTENT_GAPS]:
            gaps.append(
                f"Convert the tracked question '{query['text']}' into a durable answer block or FAQ section."
            )
            if len(gaps) >= MAX_CONTENT_GAPS:
                return gaps

        for tag in project_profile.get("priority_pulse_tags", [])[:MAX_CONTENT_GAPS]:
            gaps.append(
                f"Publish evidence-backed pages that connect {target_name} to the project priority area '{tag}'."
            )
            if len(gaps) >= MAX_CONTENT_GAPS:
                return gaps

        if not gaps:
            gaps.append(
                "No grounded content-gap themes were available; connect monitoring queries or project keywords to unlock evidence-backed ideation."
            )
        return gaps[:MAX_CONTENT_GAPS]

    def _build_technical_debt_explanation(self, *, scores: dict[str, Any]) -> str:
        seo_score = _coerce_score(scores.get("seo"))
        aeo_score = _coerce_score(scores.get("aeo"))
        geo_score = _coerce_score(scores.get("geo"))

        notes: list[str] = []
        if seo_score is not None and seo_score < MEDIUM_SCORE_THRESHOLD:
            notes.append(
                f"SEO foundations sit at {round(seo_score)} / 100, so crawl/index freshness can still suppress downstream AI understanding."
            )
        if aeo_score is not None and aeo_score < MEDIUM_SCORE_THRESHOLD:
            notes.append(
                f"AEO sits at {round(aeo_score)} / 100, which suggests extractable answer blocks and schema depth still need work."
            )
        if geo_score is not None and geo_score < MEDIUM_SCORE_THRESHOLD:
            notes.append(
                f"GEO sits at {round(geo_score)} / 100, so entity trust cues and comparison-ready citations are still underdeveloped."
            )
        if not notes:
            notes.append(
                "Technical debt is not the dominant blocker right now; keep templates fast and indexable while concentrating on citation-ready evidence and entity coverage."
            )
        return " ".join(notes)

    def _build_aeo_query_ideas(
        self,
        *,
        target_name: str,
        project_profile: dict[str, Any],
        visibility_context: dict[str, list[dict[str, Any]]],
        tracker_context: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        ideas: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_idea(candidate: dict[str, Any]) -> None:
            text = _as_string(candidate.get("text"))
            if text is None:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            ideas.append(candidate)

        for entry in visibility_context.get("aeo", []):
            add_idea(
                _build_idea(
                    text=entry["query_text"],
                    confidence="high" if int(entry.get("citations_found") or 0) > 0 else "medium",
                    label="measured",
                    source_basis=[
                        "Project visibility monitoring",
                        f"Providers: {', '.join(entry.get('providers') or ['configured providers'])}",
                    ],
                    status_note=_monitoring_note(
                        citations_found=int(entry.get("citations_found") or 0),
                        score=_coerce_score(entry.get("score")),
                        status=str(entry.get("status") or "pending"),
                    ),
                    last_verified_at=_as_string(entry.get("last_checked_at")),
                )
            )

        for entry in tracker_context.get("aeo", []):
            add_idea(
                _build_idea(
                    text=entry["text"],
                    confidence="low",
                    label="hypothesis",
                    source_basis=["Saved AEO tracker queries"],
                    status_note=_manual_tracker_note(kind="query"),
                    last_verified_at=_as_string(entry.get("tracked_at")),
                )
            )

        roles = project_profile.get("icp_roles", [])
        pain_points = project_profile.get("pain_points", [])
        competitors = project_profile.get("competitors", [])
        target_keywords = project_profile.get("target_keywords", [])

        for role in roles[:2]:
            if pain_points:
                add_idea(
                    _build_idea(
                        text=f"How does {target_name} help {role} solve {pain_points[0]}?",
                        confidence="medium",
                        label="hypothesis",
                        source_basis=["Project ICP roles", "Project pain points"],
                        status_note="Derived from project profile context and should be validated with monitoring.",
                    )
                )
            add_idea(
                _build_idea(
                    text=f"What should {role} teams verify before choosing {target_name}?",
                    confidence="low",
                    label="hypothesis",
                    source_basis=["Project ICP roles"],
                    status_note="Derived from project ICP data and should be validated with monitoring.",
                )
            )

        for competitor in competitors[:2]:
            add_idea(
                _build_idea(
                    text=f"How does {target_name} compare with {competitor}?",
                    confidence="medium",
                    label="hypothesis",
                    source_basis=["Project competitor list"],
                    status_note="Comparison intent was derived from tracked project competitors.",
                )
            )

        for keyword in target_keywords[:3]:
            add_idea(
                _build_idea(
                    text=f"What should buyers know about {keyword} before choosing {target_name}?",
                    confidence="medium",
                    label="hypothesis",
                    source_basis=["Project target keywords"],
                    status_note="Derived from active project keywords and should be monitored before prioritization.",
                )
            )

        return ideas[:MAX_AEO_QUERY_IDEAS]

    def _build_geo_prompt_ideas(
        self,
        *,
        target_name: str,
        project_profile: dict[str, Any],
        visibility_context: dict[str, list[dict[str, Any]]],
        tracker_context: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        ideas: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_idea(candidate: dict[str, Any]) -> None:
            text = _as_string(candidate.get("text"))
            if text is None:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            ideas.append(candidate)

        for entry in visibility_context.get("geo", []):
            add_idea(
                _build_idea(
                    text=entry["query_text"],
                    confidence="high" if int(entry.get("citations_found") or 0) > 0 else "medium",
                    label="measured",
                    source_basis=[
                        "Project visibility monitoring",
                        f"Providers: {', '.join(entry.get('providers') or ['configured providers'])}",
                    ],
                    status_note=_monitoring_note(
                        citations_found=int(entry.get("citations_found") or 0),
                        score=_coerce_score(entry.get("score")),
                        status=str(entry.get("status") or "pending"),
                    ),
                    last_verified_at=_as_string(entry.get("last_checked_at")),
                )
            )

        for entry in tracker_context.get("geo", []):
            add_idea(
                _build_idea(
                    text=entry["text"],
                    confidence="low",
                    label="hypothesis",
                    source_basis=["Saved GEO tracker prompts"],
                    status_note=_manual_tracker_note(kind="prompt"),
                    last_verified_at=_as_string(entry.get("tracked_at")),
                )
            )

        competitors = project_profile.get("competitors", [])
        target_keywords = project_profile.get("target_keywords", [])
        target_country = _as_string(project_profile.get("target_country"))
        priority_tags = project_profile.get("priority_pulse_tags", [])

        for competitor in competitors[:3]:
            add_idea(
                _build_idea(
                    text=f"{target_name} vs {competitor}",
                    confidence="medium",
                    label="hypothesis",
                    source_basis=["Project competitor list"],
                    status_note="Derived from tracked project competitors and should be validated with monitoring.",
                )
            )

        for keyword in target_keywords[:3]:
            add_idea(
                _build_idea(
                    text=f"Best providers for {keyword}",
                    confidence="medium",
                    label="hypothesis",
                    source_basis=["Project target keywords"],
                    status_note="Derived from active project keyword tracking and should be validated with monitoring.",
                )
            )

        for tag in priority_tags[:2]:
            suffix = f" in {target_country}" if target_country else ""
            add_idea(
                _build_idea(
                    text=f"Most trusted {tag} providers{suffix}",
                    confidence="low",
                    label="hypothesis",
                    source_basis=["Project priority pulse tags"]
                    + (["Project target country"] if target_country else []),
                    status_note="Derived from project profile fields and should be validated with monitoring.",
                )
            )

        return ideas[:MAX_GEO_PROMPT_IDEAS]
