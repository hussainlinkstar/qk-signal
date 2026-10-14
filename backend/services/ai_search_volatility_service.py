from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

import models
from services.project_visibility_service import WITHDRAWN_VISIBILITY_PROVIDERS


VOLATILITY_METHOD_VERSION = "v1-jaccard-cosine"
VOLATILITY_CHANGE_CITATION_THRESHOLD = 0.35
VOLATILITY_CHANGE_TEXT_THRESHOLD = 0.88
MIN_VOLATILITY_SAMPLE = 5


DEFAULT_VOLATILITY_SEED_QUERIES: list[tuple[str, str]] = [
    ("finance", "best small business accounting software"),
    ("finance", "best crm for real estate teams"),
    ("finance", "how to reduce churn in saas"),
    ("finance", "best invoice automation platforms"),
    ("health", "best telemedicine software for clinics"),
    ("health", "how to improve patient retention"),
    ("health", "ehr software comparison for private practice"),
    ("health", "best ai tools for radiology workflow"),
    ("tech", "best devops monitoring tools"),
    ("tech", "best llm observability platforms"),
    ("tech", "how to choose vector database"),
    ("tech", "best data warehouse for startups"),
    ("ecommerce", "best shopify seo apps"),
    ("ecommerce", "how to increase ecommerce conversion rate"),
    ("ecommerce", "best product recommendation engines"),
    ("ecommerce", "best headless commerce platforms"),
    ("travel", "best hotel booking engines for agencies"),
    ("travel", "how to increase direct hotel bookings"),
    ("travel", "best travel management software"),
    ("travel", "best ai itinerary planners"),
    ("legal", "best legal practice management software"),
    ("legal", "how law firms generate qualified leads"),
    ("legal", "best contract lifecycle management tools"),
    ("legal", "best legal research ai tools"),
    ("education", "best learning management systems for universities"),
    ("education", "how to improve student engagement online"),
    ("education", "best ai tutoring platforms"),
    ("education", "best online course platforms for creators"),
    ("saas", "best customer success software"),
    ("saas", "how to reduce support ticket volume"),
    ("saas", "best product analytics platforms"),
    ("saas", "best b2b lead enrichment tools"),
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_query(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_provider(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _hash_payload(value: Any) -> str:
    payload = str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extract_answer_text(raw_response: Any) -> str:
    if isinstance(raw_response, str):
        return _normalize_text(raw_response)
    if not isinstance(raw_response, dict):
        return ""

    direct = raw_response.get("answer") or raw_response.get("text") or raw_response.get("content")
    if isinstance(direct, str):
        return _normalize_text(direct)

    choices = raw_response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return _normalize_text(content)
                if isinstance(content, list):
                    parts = [
                        str(item.get("text")).strip()
                        for item in content
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    ]
                    return _normalize_text("\n".join(parts))

    candidates = raw_response.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, dict):
            content = first.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    texts = [
                        str(item.get("text")).strip()
                        for item in parts
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    ]
                    return _normalize_text("\n".join(texts))
    return ""


def _extract_citation_candidates(raw_response: Any) -> list[str]:
    if not isinstance(raw_response, dict):
        return []
    raw_citations = raw_response.get("citations") or raw_response.get("sources") or []
    if isinstance(raw_citations, list):
        values = [str(value).strip() for value in raw_citations if str(value).strip()]
        if values:
            return values

    search_results = raw_response.get("search_results") or raw_response.get("searchResults") or []
    if isinstance(search_results, list):
        values = []
        for row in search_results:
            if not isinstance(row, dict):
                continue
            candidate = row.get("url") or row.get("link")
            if isinstance(candidate, str) and candidate.strip():
                values.append(candidate.strip())
        if values:
            return values

    web_pages = raw_response.get("webPages")
    if isinstance(web_pages, dict):
        values = web_pages.get("value")
        if isinstance(values, list):
            extracted = []
            for row in values:
                if isinstance(row, dict) and isinstance(row.get("url"), str):
                    candidate = row["url"].strip()
                    if candidate:
                        extracted.append(candidate)
            if extracted:
                return extracted
    return []


def _normalize_domain(value: str | None) -> str | None:
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


def _extract_citation_domains(citations: list[str]) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        domain = _normalize_domain(citation)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return sorted(domains)


def _detect_answer_format(answer_text: str) -> str:
    if not answer_text:
        return "unknown"
    has_bullets = bool(re.search(r"(^|\n)\s*([-*]\s+|\d+\.\s+)", answer_text))
    has_paragraphs = "\n\n" in answer_text or len(answer_text.split(".")) >= 3
    if has_bullets and has_paragraphs:
        return "mixed"
    if has_bullets:
        return "list"
    if has_paragraphs:
        return "paragraph"
    return "short"


def _tokenize(value: str) -> Counter[str]:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return Counter(tokens)


def _cosine_similarity(text_a: str, text_b: str) -> float | None:
    vec_a = _tokenize(text_a)
    vec_b = _tokenize(text_b)
    if not vec_a or not vec_b:
        return None
    all_keys = set(vec_a.keys()) | set(vec_b.keys())
    dot = sum(float(vec_a.get(key, 0) * vec_b.get(key, 0)) for key in all_keys)
    mag_a = math.sqrt(sum(float(value * value) for value in vec_a.values()))
    mag_b = math.sqrt(sum(float(value * value) for value in vec_b.values()))
    if mag_a <= 0 or mag_b <= 0:
        return None
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    if union <= 0:
        return 0.0
    return intersection / float(union)


def _score_to_weather(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 2.0:
        return "calm"
    if score < 4.0:
        return "steady"
    if score < 6.0:
        return "breezy"
    if score < 8.0:
        return "turbulent"
    return "stormy"


def _safe_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _run_domain_set(run: models.DailySeedQueryRun) -> set[str]:
    return {
        str(value).strip().lower()
        for value in list(run.citation_domains_json or [])
        if str(value).strip()
    }


def _compare_seed_runs(
    current_run: models.DailySeedQueryRun,
    baseline_run: models.DailySeedQueryRun,
) -> dict[str, Any]:
    current_domains = _run_domain_set(current_run)
    baseline_domains = _run_domain_set(baseline_run)
    citation_jaccard = _jaccard(current_domains, baseline_domains)
    citation_churn = 1.0 - citation_jaccard
    text_similarity = _cosine_similarity(
        str(current_run.answer_text or ""),
        str(baseline_run.answer_text or ""),
    )
    format_changed = (
        str(current_run.answer_format or "unknown") != str(baseline_run.answer_format or "unknown")
        and str(current_run.answer_format or "unknown") != "unknown"
        and str(baseline_run.answer_format or "unknown") != "unknown"
    )
    text_changed = (
        text_similarity is not None and text_similarity < VOLATILITY_CHANGE_TEXT_THRESHOLD
    )
    citation_changed = citation_churn >= VOLATILITY_CHANGE_CITATION_THRESHOLD
    return {
        "current_domains": current_domains,
        "baseline_domains": baseline_domains,
        "citation_jaccard": citation_jaccard,
        "citation_churn": citation_churn,
        "text_similarity": text_similarity,
        "format_changed": format_changed,
        "changed": bool(text_changed or citation_changed or format_changed),
        "gained_domains": sorted(current_domains - baseline_domains),
        "lost_domains": sorted(baseline_domains - current_domains),
    }


class AISearchVolatilityService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_default_seed_queries(self) -> int:
        existing = {
            (str(row.normalized_query), str(row.industry))
            for row in self.db.query(
                models.GlobalVolatilitySeedQuery.normalized_query,
                models.GlobalVolatilitySeedQuery.industry,
            ).all()
        }
        inserted = 0
        for industry, query_text in DEFAULT_VOLATILITY_SEED_QUERIES:
            normalized_query = _normalize_query(query_text)
            normalized_industry = _normalize_query(industry) or "general"
            key = (normalized_query, normalized_industry)
            if not normalized_query or key in existing:
                continue
            self.db.add(
                models.GlobalVolatilitySeedQuery(
                    query_text=query_text.strip(),
                    normalized_query=normalized_query,
                    industry=normalized_industry,
                    priority_weight=1.0,
                    is_active=True,
                    source="default_catalog",
                    schema_version="1",
                )
            )
            inserted += 1
            existing.add(key)
        if inserted:
            self.db.commit()
        return inserted

    def list_seed_queries(
        self,
        *,
        limit: int = 500,
        auto_seed: bool = True,
    ) -> list[models.GlobalVolatilitySeedQuery]:
        if auto_seed:
            self.ensure_default_seed_queries()
        normalized_limit = max(1, min(int(limit), 5000))
        return (
            self.db.query(models.GlobalVolatilitySeedQuery)
            .filter(models.GlobalVolatilitySeedQuery.is_active.is_(True))
            .order_by(
                models.GlobalVolatilitySeedQuery.priority_weight.desc(),
                models.GlobalVolatilitySeedQuery.id.asc(),
            )
            .limit(normalized_limit)
            .all()
        )

    def ingest_visibility_batch(
        self, *, batch: models.VisibilityRunBatch
    ) -> models.DailySeedQueryRun | None:
        if batch.project_id is not None:
            return None

        normalized_topic = _normalize_query(batch.topic)
        if not normalized_topic:
            return None
        provider = _normalize_provider(batch.provider)
        if not provider:
            return None

        seed_query = (
            self.db.query(models.GlobalVolatilitySeedQuery)
            .filter(
                models.GlobalVolatilitySeedQuery.normalized_query == normalized_topic,
                models.GlobalVolatilitySeedQuery.is_active.is_(True),
            )
            .first()
        )
        if seed_query is None:
            return None

        runs = [row for row in list(batch.runs or []) if row.status == "succeeded"] or list(
            batch.runs or []
        )
        if not runs:
            runs = (
                self.db.query(models.VisibilityRun)
                .filter(models.VisibilityRun.batch_id == batch.id)
                .order_by(models.VisibilityRun.id.desc())
                .all()
            )
        if not runs:
            return None

        selected_run = sorted(
            runs,
            key=lambda row: (
                len(list(row.valid_citations or [])),
                int(row.id or 0),
            ),
            reverse=True,
        )[0]
        run_date = (batch.completed_at or batch.created_at or _utc_now()).date()
        answer_text = _extract_answer_text(selected_run.raw_response)
        candidate_citations = _extract_citation_candidates(selected_run.raw_response)
        citations = candidate_citations or [
            str(value).strip()
            for value in list(selected_run.valid_citations or [])
            if str(value).strip()
        ]
        citation_domains = _extract_citation_domains(citations)
        answer_format = _detect_answer_format(answer_text)

        existing = (
            self.db.query(models.DailySeedQueryRun)
            .filter(
                models.DailySeedQueryRun.seed_query_id == seed_query.id,
                models.DailySeedQueryRun.provider == provider,
                models.DailySeedQueryRun.run_date == run_date,
            )
            .first()
        )
        if existing is None:
            existing = models.DailySeedQueryRun(
                seed_query_id=seed_query.id,
                provider=provider,
                run_date=run_date,
                schema_version="1",
            )
            self.db.add(existing)

        existing.visibility_run_batch_id = batch.id
        existing.visibility_run_id = selected_run.id
        existing.answer_text = answer_text
        existing.answer_text_hash = _hash_payload(answer_text) if answer_text else None
        existing.citations_hash = (
            _hash_payload("|".join(citation_domains)) if citation_domains else None
        )
        existing.citation_domains_json = citation_domains
        existing.citations_count = len(citation_domains)
        existing.answer_format = answer_format
        self.db.flush()
        return existing

    def rebuild_snapshots_for_date(self, *, run_date: date) -> int:
        providers = [
            str(row[0])
            for row in (
                self.db.query(models.DailySeedQueryRun.provider)
                .filter(models.DailySeedQueryRun.run_date == run_date)
                .distinct()
                .all()
            )
            if str(row[0]).strip()
        ]
        industries = [
            str(row[0])
            for row in (
                self.db.query(models.GlobalVolatilitySeedQuery.industry)
                .join(
                    models.DailySeedQueryRun,
                    models.DailySeedQueryRun.seed_query_id == models.GlobalVolatilitySeedQuery.id,
                )
                .filter(models.DailySeedQueryRun.run_date == run_date)
                .distinct()
                .all()
            )
            if str(row[0]).strip()
        ]
        if not providers:
            return 0

        provider_keys = sorted(set(providers + ["all"]))
        industry_keys = sorted(set(industries + ["all"]))
        written = 0
        for provider in provider_keys:
            for industry in industry_keys:
                payload = self._compute_snapshot_payload(
                    run_date=run_date,
                    provider=provider,
                    industry=industry,
                )
                if payload is None:
                    continue
                row = (
                    self.db.query(models.GlobalVolatilitySnapshot)
                    .filter(
                        models.GlobalVolatilitySnapshot.snapshot_date == run_date,
                        models.GlobalVolatilitySnapshot.provider == provider,
                        models.GlobalVolatilitySnapshot.industry == industry,
                    )
                    .first()
                )
                if row is None:
                    row = models.GlobalVolatilitySnapshot(
                        snapshot_date=run_date,
                        provider=provider,
                        industry=industry,
                        schema_version="1",
                    )
                    self.db.add(row)
                    written += 1

                row.volatility_score = payload["volatility_score"]
                row.compared_queries = payload["compared_queries"]
                row.changed_query_count = payload["changed_query_count"]
                row.changed_ratio = payload["changed_ratio"]
                row.avg_text_similarity = payload["avg_text_similarity"]
                row.avg_citation_jaccard = payload["avg_citation_jaccard"]
                row.citation_churn_rate = payload["citation_churn_rate"]
                row.format_change_rate = payload["format_change_rate"]
                row.top_winners_json = payload["top_winners"]
                row.top_losers_json = payload["top_losers"]
                row.changes_json = payload["changes"]
                row.computed_at = _utc_now()
        self.db.flush()
        return written

    def build_summary(self, *, days: int = 30, provider: str = "all") -> dict[str, Any]:
        normalized_provider = _normalize_provider(provider) or "all"

        latest = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.industry == "all",
            )
            .order_by(
                models.GlobalVolatilitySnapshot.snapshot_date.desc(),
                models.GlobalVolatilitySnapshot.id.desc(),
            )
            .first()
        )
        if latest is None:
            return {
                "provider": normalized_provider,
                "generated_at": _utc_now().isoformat(),
                "latest_snapshot_date": None,
                "no_data": True,
                "degraded": False,
                "degraded_reasons": [],
                "weather_label": "unknown",
                "volatility_score": None,
                "compared_queries": 0,
                "changed_ratio": None,
                "avg_text_similarity": None,
                "avg_citation_jaccard": None,
                "citation_churn_rate": None,
                "format_change_rate": None,
                "top_winners": [],
                "top_losers": [],
                "industries": [],
            }

        industry_rows = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.snapshot_date == latest.snapshot_date,
                models.GlobalVolatilitySnapshot.industry != "all",
            )
            .order_by(
                models.GlobalVolatilitySnapshot.volatility_score.desc().nullslast(),
                models.GlobalVolatilitySnapshot.industry.asc(),
            )
            .all()
        )

        degraded_reasons: list[str] = []
        if int(latest.compared_queries or 0) < MIN_VOLATILITY_SAMPLE:
            degraded_reasons.append("Low comparison sample size for this window.")
        if latest.volatility_score is None:
            degraded_reasons.append("No prior baseline run available for volatility comparison.")

        return {
            "provider": normalized_provider,
            "generated_at": _utc_now().isoformat(),
            "latest_snapshot_date": _safe_iso(latest.snapshot_date),
            "no_data": latest.volatility_score is None,
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "weather_label": _score_to_weather(latest.volatility_score),
            "volatility_score": round(float(latest.volatility_score), 2)
            if latest.volatility_score is not None
            else None,
            "compared_queries": int(latest.compared_queries or 0),
            "changed_ratio": round(float(latest.changed_ratio), 4)
            if latest.changed_ratio is not None
            else None,
            "avg_text_similarity": round(float(latest.avg_text_similarity), 4)
            if latest.avg_text_similarity is not None
            else None,
            "avg_citation_jaccard": round(float(latest.avg_citation_jaccard), 4)
            if latest.avg_citation_jaccard is not None
            else None,
            "citation_churn_rate": round(float(latest.citation_churn_rate), 4)
            if latest.citation_churn_rate is not None
            else None,
            "format_change_rate": round(float(latest.format_change_rate), 4)
            if latest.format_change_rate is not None
            else None,
            "top_winners": list(latest.top_winners_json or []),
            "top_losers": list(latest.top_losers_json or []),
            "industries": [
                {
                    "industry": str(row.industry),
                    "volatility_score": round(float(row.volatility_score), 2)
                    if row.volatility_score is not None
                    else None,
                    "compared_queries": int(row.compared_queries or 0),
                    "changed_ratio": round(float(row.changed_ratio), 4)
                    if row.changed_ratio is not None
                    else None,
                }
                for row in industry_rows
            ],
        }

    def build_trends(self, *, days: int = 30, provider: str = "all") -> dict[str, Any]:
        normalized_days = max(7, min(int(days), 365))
        normalized_provider = _normalize_provider(provider) or "all"
        today = _utc_now().date()
        start_date = today - timedelta(days=normalized_days - 1)
        rows = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.industry == "all",
                models.GlobalVolatilitySnapshot.snapshot_date >= start_date,
                models.GlobalVolatilitySnapshot.snapshot_date <= today,
            )
            .order_by(models.GlobalVolatilitySnapshot.snapshot_date.asc())
            .all()
        )
        by_date = {row.snapshot_date: row for row in rows}
        points: list[dict[str, Any]] = []
        cursor = start_date
        while cursor <= today:
            row = by_date.get(cursor)
            points.append(
                {
                    "date": cursor.isoformat(),
                    "volatility_score": round(float(row.volatility_score), 2)
                    if row and row.volatility_score is not None
                    else None,
                    "compared_queries": int(row.compared_queries or 0) if row else 0,
                    "changed_ratio": round(float(row.changed_ratio), 4)
                    if row and row.changed_ratio is not None
                    else None,
                }
            )
            cursor += timedelta(days=1)
        return {
            "provider": normalized_provider,
            "days": normalized_days,
            "points": points,
        }

    def build_industry_matrix(self, *, days: int = 30, provider: str = "all") -> dict[str, Any]:
        normalized_days = max(7, min(int(days), 365))
        normalized_provider = _normalize_provider(provider) or "all"
        today = _utc_now().date()
        start_date = today - timedelta(days=normalized_days - 1)
        rows = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.industry != "all",
                models.GlobalVolatilitySnapshot.snapshot_date >= start_date,
                models.GlobalVolatilitySnapshot.snapshot_date <= today,
            )
            .order_by(
                models.GlobalVolatilitySnapshot.snapshot_date.asc(),
                models.GlobalVolatilitySnapshot.industry.asc(),
            )
            .all()
        )
        points = [
            {
                "date": row.snapshot_date.isoformat(),
                "industry": str(row.industry),
                "provider": normalized_provider,
                "volatility_score": round(float(row.volatility_score), 2)
                if row.volatility_score is not None
                else None,
                "compared_queries": int(row.compared_queries or 0),
                "changed_ratio": round(float(row.changed_ratio), 4)
                if row.changed_ratio is not None
                else None,
                "moving_queries": self._list_changed_queries_for_snapshot(
                    run_date=row.snapshot_date,
                    provider=normalized_provider,
                    industry=str(row.industry),
                    limit=3,
                ),
            }
            for row in rows
            if row.snapshot_date is not None
        ]
        return {
            "provider": normalized_provider,
            "days": normalized_days,
            "points": points,
        }

    def build_citation_ledger(self, *, days: int = 30, provider: str = "all") -> dict[str, Any]:
        normalized_provider = _normalize_provider(provider) or "all"
        latest = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.industry == "all",
            )
            .order_by(
                models.GlobalVolatilitySnapshot.snapshot_date.desc(),
                models.GlobalVolatilitySnapshot.id.desc(),
            )
            .first()
        )
        if latest is None or latest.snapshot_date is None:
            return {
                "provider": normalized_provider,
                "generated_at": _utc_now().isoformat(),
                "latest_snapshot_date": None,
                "rows": [],
            }

        latest_rows = self._build_domain_delta_snapshot(
            run_date=latest.snapshot_date,
            provider=normalized_provider,
        )
        trend_window = max(7, min(int(days), 30))
        trend_map = self._build_domain_delta_trends(
            provider=normalized_provider,
            end_date=latest.snapshot_date,
            days=min(trend_window, 7),
        )
        industry_scores = {
            str(row.industry): round(float(row.volatility_score), 2)
            if row.volatility_score is not None
            else None
            for row in (
                self.db.query(models.GlobalVolatilitySnapshot)
                .filter(
                    models.GlobalVolatilitySnapshot.provider == normalized_provider,
                    models.GlobalVolatilitySnapshot.snapshot_date == latest.snapshot_date,
                    models.GlobalVolatilitySnapshot.industry != "all",
                )
                .all()
            )
        }
        rows = []
        for domain, payload in latest_rows.items():
            delta = int(payload["delta"])
            if delta == 0:
                continue
            base_citations = int(payload["base_citations"])
            current_citations = int(payload["current_citations"])
            dominant_industry = "general"
            industry_counter = payload.get("industry_counts")
            if isinstance(industry_counter, Counter) and industry_counter:
                dominant_industry = str(industry_counter.most_common(1)[0][0])
            if base_citations <= 0 and current_citations > 0:
                delta_pct = 100.0
            elif current_citations <= 0 and base_citations > 0:
                delta_pct = -100.0
            elif base_citations <= 0:
                delta_pct = 0.0
            else:
                delta_pct = (float(delta) / float(base_citations)) * 100.0
            rows.append(
                {
                    "domain": domain,
                    "industry": dominant_industry,
                    "base_citations": base_citations,
                    "current_citations": current_citations,
                    "delta": delta,
                    "delta_pct": round(delta_pct, 2),
                    "provider": normalized_provider,
                    "volatility_score": industry_scores.get(dominant_industry),
                    "direction": "winner" if delta > 0 else "loser",
                    "trend": trend_map.get(domain, [0] * min(trend_window, 7)),
                }
            )
        rows.sort(
            key=lambda row: (
                abs(int(row["delta"])),
                abs(float(row["delta_pct"])),
                str(row["domain"]),
            ),
            reverse=True,
        )
        return {
            "provider": normalized_provider,
            "generated_at": _utc_now().isoformat(),
            "latest_snapshot_date": latest.snapshot_date.isoformat(),
            "rows": rows,
        }

    def list_available_public_providers(self) -> list[str]:
        # ``bing`` stays out of the order list AND the discovered set: the
        # engine was withdrawn from the offer (SIGV2-1215), so historical
        # snapshots must not resurface it as a public filter.
        preferred_order = ["google", "openai", "perplexity", "anthropic", "xai", "deepseek"]
        discovered = [
            str(row[0]).strip().lower()
            for row in (
                self.db.query(models.GlobalVolatilitySnapshot.provider)
                .filter(models.GlobalVolatilitySnapshot.provider != "all")
                .filter(
                    models.GlobalVolatilitySnapshot.provider.notin_(WITHDRAWN_VISIBILITY_PROVIDERS)
                )
                .distinct()
                .all()
            )
            if str(row[0]).strip()
        ]
        discovered_set = set(discovered)
        ordered = [provider for provider in preferred_order if provider in discovered_set]
        ordered.extend(sorted(discovered_set - set(ordered)))
        return ordered

    def build_public_dashboard(self, *, days: int = 30, provider: str = "all") -> dict[str, Any]:
        return {
            "available_providers": self.list_available_public_providers(),
            "summary": self.build_summary(days=days, provider=provider),
            "trends": self.build_trends(days=days, provider=provider),
            "industry_matrix": self.build_industry_matrix(days=days, provider=provider),
            "citation_ledger": self.build_citation_ledger(days=days, provider=provider),
        }

    def build_overlay_map(
        self,
        *,
        start_date: date,
        end_date: date,
        provider: str = "all",
    ) -> dict[str, float]:
        normalized_provider = _normalize_provider(provider) or "all"
        rows = (
            self.db.query(models.GlobalVolatilitySnapshot)
            .filter(
                models.GlobalVolatilitySnapshot.provider == normalized_provider,
                models.GlobalVolatilitySnapshot.industry == "all",
                models.GlobalVolatilitySnapshot.snapshot_date >= start_date,
                models.GlobalVolatilitySnapshot.snapshot_date <= end_date,
                models.GlobalVolatilitySnapshot.volatility_score.isnot(None),
            )
            .order_by(models.GlobalVolatilitySnapshot.snapshot_date.asc())
            .all()
        )
        return {
            row.snapshot_date.isoformat(): round(float(row.volatility_score), 2)
            for row in rows
            if row.snapshot_date is not None and row.volatility_score is not None
        }

    def _compute_snapshot_payload(
        self,
        *,
        run_date: date,
        provider: str,
        industry: str,
    ) -> dict[str, Any] | None:
        today_rows = self._query_daily_seed_runs(
            run_date=run_date, provider=provider, industry=industry
        )
        if not today_rows:
            return None

        comparison_pairs, previous_dates = self._build_run_comparison_pairs(
            run_date=run_date,
            provider=provider,
            industry=industry,
            today_rows=today_rows,
        )
        if not previous_dates:
            return {
                "volatility_score": None,
                "compared_queries": 0,
                "changed_query_count": 0,
                "changed_ratio": None,
                "avg_text_similarity": None,
                "avg_citation_jaccard": None,
                "citation_churn_rate": None,
                "format_change_rate": None,
                "top_winners": [],
                "top_losers": [],
                "changes": {
                    "methodology": VOLATILITY_METHOD_VERSION,
                    "previous_date": None,
                    "previous_dates_by_provider": {},
                    "sample_size_today": len(today_rows),
                    "compared_queries": 0,
                    "note": "No prior baseline available.",
                },
            }

        compared_queries = 0
        changed_query_count = 0
        format_change_count = 0
        citation_jaccard_values: list[float] = []
        citation_churn_values: list[float] = []
        text_similarity_values: list[float] = []
        top_winner_counter: Counter[str] = Counter()
        top_loser_counter: Counter[str] = Counter()

        for today_run, baseline in comparison_pairs:
            compared_queries += 1
            comparison = _compare_seed_runs(today_run, baseline)
            citation_jaccard = float(comparison["citation_jaccard"])
            citation_churn = float(comparison["citation_churn"])
            citation_jaccard_values.append(citation_jaccard)
            citation_churn_values.append(citation_churn)

            text_similarity = comparison["text_similarity"]
            if text_similarity is not None:
                text_similarity_values.append(text_similarity)

            format_changed = bool(comparison["format_changed"])
            if format_changed:
                format_change_count += 1

            if comparison["changed"]:
                changed_query_count += 1

            for gained_domain in comparison["gained_domains"]:
                top_winner_counter[gained_domain] += 1
            for lost_domain in comparison["lost_domains"]:
                top_loser_counter[lost_domain] += 1

        if compared_queries <= 0:
            return {
                "volatility_score": None,
                "compared_queries": 0,
                "changed_query_count": 0,
                "changed_ratio": None,
                "avg_text_similarity": None,
                "avg_citation_jaccard": None,
                "citation_churn_rate": None,
                "format_change_rate": None,
                "top_winners": [],
                "top_losers": [],
                "changes": {
                    "methodology": VOLATILITY_METHOD_VERSION,
                    "previous_date": self._summarize_previous_dates(previous_dates)[
                        "previous_date"
                    ],
                    "previous_dates_by_provider": self._summarize_previous_dates(previous_dates)[
                        "dates_by_provider"
                    ],
                    "sample_size_today": len(today_rows),
                    "compared_queries": 0,
                    "note": "No overlapping seed queries with prior run.",
                },
            }

        avg_text_similarity = (
            sum(text_similarity_values) / float(len(text_similarity_values))
            if text_similarity_values
            else None
        )
        avg_citation_jaccard = (
            sum(citation_jaccard_values) / float(len(citation_jaccard_values))
            if citation_jaccard_values
            else None
        )
        citation_churn_rate = (
            sum(citation_churn_values) / float(len(citation_churn_values))
            if citation_churn_values
            else None
        )
        format_change_rate = float(format_change_count) / float(compared_queries)
        changed_ratio = float(changed_query_count) / float(compared_queries)
        text_change_rate = (1.0 - avg_text_similarity) if avg_text_similarity is not None else 0.0

        raw_score = (
            (float(citation_churn_rate or 0.0) * 0.45)
            + (float(text_change_rate) * 0.40)
            + (float(format_change_rate) * 0.15)
        )
        volatility_score = max(
            0.0,
            min(
                10.0,
                (raw_score * 10.0) + (changed_ratio * 1.5),
            ),
        )
        previous_date_summary = self._summarize_previous_dates(previous_dates)

        return {
            "volatility_score": round(volatility_score, 2),
            "compared_queries": compared_queries,
            "changed_query_count": changed_query_count,
            "changed_ratio": round(changed_ratio, 4),
            "avg_text_similarity": round(avg_text_similarity, 4)
            if avg_text_similarity is not None
            else None,
            "avg_citation_jaccard": round(avg_citation_jaccard, 4)
            if avg_citation_jaccard is not None
            else None,
            "citation_churn_rate": round(citation_churn_rate, 4)
            if citation_churn_rate is not None
            else None,
            "format_change_rate": round(format_change_rate, 4),
            "top_winners": [
                {"domain": domain, "delta": int(delta)}
                for domain, delta in top_winner_counter.most_common(8)
            ],
            "top_losers": [
                {"domain": domain, "delta": int(delta)}
                for domain, delta in top_loser_counter.most_common(8)
            ],
            "changes": {
                "methodology": VOLATILITY_METHOD_VERSION,
                "previous_date": previous_date_summary["previous_date"],
                "previous_dates_by_provider": previous_date_summary["dates_by_provider"],
                "sample_size_today": len(today_rows),
                "compared_queries": compared_queries,
                "changed_ratio": round(changed_ratio, 4),
                "thresholds": {
                    "citation_churn": VOLATILITY_CHANGE_CITATION_THRESHOLD,
                    "text_similarity": VOLATILITY_CHANGE_TEXT_THRESHOLD,
                },
            },
        }

    def _query_daily_seed_runs(
        self,
        *,
        run_date: date,
        provider: str,
        industry: str,
    ) -> list[models.DailySeedQueryRun]:
        query = (
            self.db.query(models.DailySeedQueryRun)
            .options(joinedload(models.DailySeedQueryRun.seed_query))
            .join(
                models.GlobalVolatilitySeedQuery,
                models.GlobalVolatilitySeedQuery.id == models.DailySeedQueryRun.seed_query_id,
            )
            .filter(
                models.DailySeedQueryRun.run_date == run_date,
                models.GlobalVolatilitySeedQuery.is_active.is_(True),
            )
            .order_by(models.DailySeedQueryRun.seed_query_id.asc())
        )
        if provider != "all":
            query = query.filter(models.DailySeedQueryRun.provider == provider)
        if industry != "all":
            query = query.filter(models.GlobalVolatilitySeedQuery.industry == industry)
        return query.all()

    def _resolve_previous_run_date(
        self,
        *,
        run_date: date,
        provider: str,
        industry: str,
    ) -> date | None:
        query = (
            self.db.query(func.max(models.DailySeedQueryRun.run_date))
            .join(
                models.GlobalVolatilitySeedQuery,
                models.GlobalVolatilitySeedQuery.id == models.DailySeedQueryRun.seed_query_id,
            )
            .filter(
                models.DailySeedQueryRun.run_date < run_date,
                models.GlobalVolatilitySeedQuery.is_active.is_(True),
            )
        )
        if provider != "all":
            query = query.filter(models.DailySeedQueryRun.provider == provider)
        if industry != "all":
            query = query.filter(models.GlobalVolatilitySeedQuery.industry == industry)
        return query.scalar()

    def _comparison_row_key(self, row: models.DailySeedQueryRun) -> tuple[int, str]:
        return (
            int(row.seed_query_id),
            _normalize_provider(str(row.provider)) or "unknown",
        )

    def _build_run_comparison_pairs(
        self,
        *,
        run_date: date,
        provider: str,
        industry: str,
        today_rows: list[models.DailySeedQueryRun] | None = None,
    ) -> tuple[list[tuple[models.DailySeedQueryRun, models.DailySeedQueryRun]], dict[str, date]]:
        current_rows = today_rows or self._query_daily_seed_runs(
            run_date=run_date,
            provider=provider,
            industry=industry,
        )
        if not current_rows:
            return [], {}

        rows_by_provider: dict[str, list[models.DailySeedQueryRun]] = defaultdict(list)
        for row in current_rows:
            provider_key = _normalize_provider(str(row.provider)) or "unknown"
            rows_by_provider[provider_key].append(row)

        provider_keys = [provider] if provider != "all" else sorted(rows_by_provider.keys())
        pairs: list[tuple[models.DailySeedQueryRun, models.DailySeedQueryRun]] = []
        previous_dates: dict[str, date] = {}
        for provider_key in provider_keys:
            provider_rows = rows_by_provider.get(provider_key, [])
            if not provider_rows:
                continue
            previous_date = self._resolve_previous_run_date(
                run_date=run_date,
                provider=provider_key,
                industry=industry,
            )
            if previous_date is None:
                continue
            previous_dates[provider_key] = previous_date
            baseline_rows = self._query_daily_seed_runs(
                run_date=previous_date,
                provider=provider_key,
                industry=industry,
            )
            baseline_by_key = {self._comparison_row_key(row): row for row in baseline_rows}
            for current_run in provider_rows:
                baseline = baseline_by_key.get(self._comparison_row_key(current_run))
                if baseline is not None:
                    pairs.append((current_run, baseline))
        return pairs, previous_dates

    def _summarize_previous_dates(self, previous_dates: dict[str, date]) -> dict[str, Any]:
        dates_by_provider = {
            str(provider): _safe_iso(previous_date)
            for provider, previous_date in sorted(previous_dates.items())
            if previous_date is not None
        }
        unique_dates = sorted({value for value in dates_by_provider.values() if value})
        return {
            "previous_date": unique_dates[0] if len(unique_dates) == 1 else None,
            "dates_by_provider": dates_by_provider,
        }

    def _list_changed_queries_for_snapshot(
        self,
        *,
        run_date: date,
        provider: str,
        industry: str,
        limit: int = 3,
    ) -> list[str]:
        comparison_pairs, _previous_dates = self._build_run_comparison_pairs(
            run_date=run_date,
            provider=provider,
            industry=industry,
        )
        changed_queries: list[str] = []
        for current_run, baseline in comparison_pairs:
            comparison = _compare_seed_runs(current_run, baseline)
            if not comparison["changed"]:
                continue
            query_text = str(
                current_run.seed_query.query_text if current_run.seed_query else ""
            ).strip()
            if query_text and query_text not in changed_queries:
                changed_queries.append(query_text)
            if len(changed_queries) >= limit:
                break
        return changed_queries

    def _build_domain_delta_snapshot(
        self,
        *,
        run_date: date,
        provider: str,
    ) -> dict[str, dict[str, Any]]:
        comparison_pairs, _previous_dates = self._build_run_comparison_pairs(
            run_date=run_date,
            provider=provider,
            industry="all",
        )
        domain_rows: dict[str, dict[str, Any]] = {}
        for current_run, baseline in comparison_pairs:
            comparison = _compare_seed_runs(current_run, baseline)
            industry = str(current_run.seed_query.industry if current_run.seed_query else "general")
            for domain in comparison["current_domains"]:
                entry = domain_rows.setdefault(
                    domain,
                    {
                        "base_citations": 0,
                        "current_citations": 0,
                        "delta": 0,
                        "industry_counts": Counter(),
                    },
                )
                entry["current_citations"] += 1
                entry["industry_counts"][industry] += 1
            for domain in comparison["baseline_domains"]:
                entry = domain_rows.setdefault(
                    domain,
                    {
                        "base_citations": 0,
                        "current_citations": 0,
                        "delta": 0,
                        "industry_counts": Counter(),
                    },
                )
                entry["base_citations"] += 1
                entry["industry_counts"][industry] += 1
        for payload in domain_rows.values():
            payload["delta"] = int(payload["current_citations"]) - int(payload["base_citations"])
        return domain_rows

    def _build_domain_delta_trends(
        self,
        *,
        provider: str,
        end_date: date,
        days: int = 7,
    ) -> dict[str, list[int]]:
        normalized_days = max(1, min(int(days), 7))
        trend_map: dict[str, list[int]] = defaultdict(list)
        cursor = end_date - timedelta(days=normalized_days - 1)
        offset = 0
        while cursor <= end_date:
            snapshot = self._build_domain_delta_snapshot(run_date=cursor, provider=provider)
            for domain in snapshot:
                if domain not in trend_map:
                    trend_map[domain] = [0] * offset
            domains = set(trend_map.keys()) | set(snapshot.keys())
            for domain in domains:
                trend_map[domain].append(int(snapshot.get(domain, {}).get("delta", 0)))
            cursor += timedelta(days=1)
            offset += 1
        return {domain: values for domain, values in trend_map.items()}


def refresh_recent_global_volatility_snapshots(
    db: Session,
    *,
    lookback_days: int = 30,
) -> dict[str, int]:
    service = AISearchVolatilityService(db)
    service.ensure_default_seed_queries()
    normalized_days = max(7, min(int(lookback_days), 365))
    start_date = _utc_now().date() - timedelta(days=normalized_days - 1)
    run_dates = [
        row[0]
        for row in (
            db.query(models.DailySeedQueryRun.run_date)
            .filter(models.DailySeedQueryRun.run_date >= start_date)
            .distinct()
            .order_by(models.DailySeedQueryRun.run_date.asc())
            .all()
        )
        if row[0] is not None
    ]
    refreshed_dates = 0
    written_rows = 0
    for run_date in run_dates:
        refreshed_dates += 1
        written_rows += service.rebuild_snapshots_for_date(run_date=run_date)
    db.commit()
    return {
        "dates_considered": len(run_dates),
        "dates_refreshed": refreshed_dates,
        "rows_written": written_rows,
    }
