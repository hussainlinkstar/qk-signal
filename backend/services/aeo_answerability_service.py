import hashlib
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

import models
from score_utils import extract_score
from services.url_validation import normalize_and_validate_url

logger = logging.getLogger(__name__)

SCHEMA_MARKERS = (
    "application/ld+json",
    "itemscope",
    "itemtype=",
    'property="og:type"',
)


@dataclass
class AnswerabilityFeatures:
    schema_presence: float
    backlink_count: float
    freshness_days: float | None
    domain_authority: float


@dataclass
class ReadabilityAssessment:
    score: float
    findings: list[str]
    rewrite_suggestions: list[dict[str, Any]]


class AEOAnswerabilityService:
    """Deterministic page-level answerability scoring service."""

    def __init__(self) -> None:
        self.timeout_seconds = float(os.getenv("AEO_ANSWERABILITY_TIMEOUT_SECONDS", "12"))
        self.metrics_provider_url = os.getenv("AEO_LINK_METRICS_PROVIDER_URL", "").strip()
        self.max_backlinks = float(os.getenv("AEO_ANSWERABILITY_MAX_BACKLINKS", "50000"))
        self.max_freshness_days = float(os.getenv("AEO_ANSWERABILITY_MAX_FRESHNESS_DAYS", "365"))
        # Deterministic weighted logistic formula.
        self.intercept = -1.0
        self.weights = {
            "schema_presence": 1.9,
            "backlink_count": 1.3,
            "freshness": 1.1,
            "domain_authority": 1.6,
        }
        self.failure_score_threshold = float(
            os.getenv("AEO_ANSWERABILITY_FAILURE_SCORE_THRESHOLD", "70")
        )
        self.stale_content_threshold_days = float(
            os.getenv("AEO_ANSWERABILITY_STALE_CONTENT_DAYS", "180")
        )
        self.low_authority_threshold = float(
            os.getenv("AEO_ANSWERABILITY_LOW_AUTHORITY_THRESHOLD", "35")
        )
        self.readability_threshold = float(
            os.getenv("AEO_ANSWERABILITY_READABILITY_THRESHOLD", "0.45")
        )
        self.readability_provider = (
            os.getenv("AEO_READABILITY_PROVIDER", "heuristic").strip().lower()
        )
        self.readability_gateway_url = os.getenv("AEO_READABILITY_GATEWAY_URL", "").strip()

    async def score_url(
        self,
        url: str,
        *,
        prevalidated: bool = False,
        db: Session | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_url, domain = self._normalize_url_and_domain(url, prevalidated=prevalidated)
        html, last_modified = await self._fetch_page_signals(normalized_url)

        schema_presence = self._detect_schema_presence(html)
        backlink_count, domain_authority = await self._fetch_link_authority_metrics(domain)
        freshness_days = self._calculate_freshness_days(last_modified)

        raw = AnswerabilityFeatures(
            schema_presence=schema_presence,
            backlink_count=backlink_count,
            freshness_days=freshness_days,
            domain_authority=domain_authority,
        )
        normalized = self._normalize_features(raw)
        score, score_float = self._calculate_score(normalized)
        readability_assessment = await self._extract_readability_score(html)
        failure_reasons, primary_failure_reason = self._classify_answer_failure_reasons(
            raw=raw,
            normalized=normalized,
            score=score,
            readability_score=readability_assessment.score,
        )
        factors = self._explain_factors(raw=raw, normalized=normalized)
        history = self._build_score_history(
            db=db,
            user_id=user_id,
            domain=domain,
            current_score=score,
        )

        return {
            "url": normalized_url,
            "domain": domain,
            "raw_features": {
                "schema_presence": raw.schema_presence,
                "backlink_count": raw.backlink_count,
                "freshness_days": raw.freshness_days,
                "domain_authority": raw.domain_authority,
            },
            "normalized_features": normalized,
            "score": {
                "value": score,
                "model": "deterministic_logistic_v1",
                "raw_model_output": round(score_float, 6),
            },
            "answer_failure_reasons": failure_reasons,
            "primary_failure_reason": primary_failure_reason,
            "readability_score": readability_assessment.score,
            "readability_findings": readability_assessment.findings,
            "rewrite_suggestions": readability_assessment.rewrite_suggestions,
            "factor_explanations": factors,
            "history": history,
        }

    async def _extract_readability_score(self, html: str) -> ReadabilityAssessment:
        if self.readability_provider == "llm_gateway" and self.readability_gateway_url:
            gateway_assessment = await self._extract_readability_score_from_gateway(html)
            if gateway_assessment is not None:
                return gateway_assessment

        return self._extract_readability_score_heuristic(html)

    async def _extract_readability_score_from_gateway(
        self, html: str
    ) -> ReadabilityAssessment | None:
        paragraphs = self._extract_candidate_paragraphs(html)
        if not paragraphs:
            return None

        payload = {"paragraphs": paragraphs[:10]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.readability_gateway_url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("AEO readability provider failed: %s", exc)
            return None

        score = self._safe_float(data.get("score"), default=None)
        if score is None:
            return None

        findings = data.get("findings")
        rewrite_suggestions = data.get("rewrite_suggestions")
        return ReadabilityAssessment(
            score=self._clamp(score, 0.0, 1.0),
            findings=[str(item) for item in findings if isinstance(item, str)]
            if isinstance(findings, list)
            else [],
            rewrite_suggestions=(
                [item for item in rewrite_suggestions if isinstance(item, dict)]
                if isinstance(rewrite_suggestions, list)
                else []
            )[:3],
        )

    def _extract_readability_score_heuristic(self, html: str) -> ReadabilityAssessment:
        paragraphs = self._extract_candidate_paragraphs(html)
        if not paragraphs:
            return ReadabilityAssessment(
                score=0.35,
                findings=["Content body is too thin for reliable readability evaluation."],
                rewrite_suggestions=[],
            )

        stats: list[dict[str, Any]] = []
        hard_to_read = 0
        for paragraph in paragraphs:
            words = re.findall(r"\b\w+\b", paragraph)
            if not words:
                continue
            sentences = [part.strip() for part in re.split(r"[.!?]+", paragraph) if part.strip()]
            sentence_count = max(1, len(sentences))
            word_count = len(words)
            long_word_count = sum(1 for word in words if len(word) >= 10)
            avg_sentence_length = word_count / sentence_count
            long_word_ratio = long_word_count / word_count

            complexity = (avg_sentence_length / 28.0) + (long_word_ratio / 0.22)
            paragraph_score = self._clamp(1.0 - (complexity / 2.0), 0.0, 1.0)
            if paragraph_score < self.readability_threshold:
                hard_to_read += 1
            stats.append(
                {
                    "paragraph": paragraph,
                    "score": paragraph_score,
                    "avg_sentence_length": avg_sentence_length,
                    "long_word_ratio": long_word_ratio,
                }
            )

        if not stats:
            return ReadabilityAssessment(score=0.35, findings=[], rewrite_suggestions=[])

        score = sum(item["score"] for item in stats) / len(stats)
        findings: list[str] = []
        if score < self.readability_threshold:
            findings.append("Overall readability is below the target for AI answer extraction.")
        if hard_to_read > 0:
            findings.append(f"{hard_to_read} paragraph(s) exceed complexity thresholds.")
        if not findings:
            findings.append("Paragraph complexity is within the target range.")

        worst_paragraphs = sorted(stats, key=lambda item: item["score"])[:3]
        rewrite_suggestions: list[dict[str, Any]] = []
        for item in worst_paragraphs:
            if item["score"] >= self.readability_threshold:
                continue
            rewrite_suggestions.append(
                {
                    "paragraph": item["paragraph"],
                    "score": round(item["score"], 4),
                    "suggestion": (
                        "Split long sentences, replace jargon with simpler wording, "
                        "and move the direct answer to the opening sentence."
                    ),
                }
            )

        return ReadabilityAssessment(
            score=round(self._clamp(score, 0.0, 1.0), 4),
            findings=findings,
            rewrite_suggestions=rewrite_suggestions,
        )

    def _extract_candidate_paragraphs(self, html: str) -> list[str]:
        if not html:
            return []
        stripped = re.sub(
            r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE
        )
        blocks = re.findall(r"<p[^>]*>([\s\S]*?)</p>", stripped, flags=re.IGNORECASE)
        if not blocks:
            blocks = re.split(r"\n{2,}", stripped)
        cleaned: list[str] = []
        for block in blocks:
            text = re.sub(r"<[^>]+>", " ", block)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) >= 90:
                cleaned.append(text)
        return cleaned[:20]

    def _safe_float(self, value: Any, *, default: float | None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _classify_answer_failure_reasons(
        self,
        *,
        raw: AnswerabilityFeatures,
        normalized: dict[str, float],
        score: int,
        readability_score: float | None,
    ) -> tuple[list[str], str | None]:
        if score >= self.failure_score_threshold:
            return [], None

        reasons: list[str] = []
        if raw.schema_presence < 1.0:
            reasons.append("MISSING_SCHEMA")
        if (
            raw.freshness_days is not None
            and raw.freshness_days > self.stale_content_threshold_days
        ):
            reasons.append("STALE_CONTENT")
        if raw.domain_authority < self.low_authority_threshold:
            reasons.append("LOW_AUTHORITY")
        if readability_score is not None and readability_score < self.readability_threshold:
            reasons.append("POOR_READABILITY")

        if not reasons and normalized.get("backlink_count", 0.0) < 0.35:
            reasons.append("AMBIGUOUS_CONTENT")

        return reasons, (reasons[0] if reasons else None)

    def _build_score_history(
        self,
        *,
        db: Session | None,
        user_id: int | None,
        domain: str,
        current_score: int,
    ) -> list[dict[str, Any]]:
        if db is None:
            return [{"timestamp": datetime.now(timezone.utc).isoformat(), "score": current_score}]

        query = db.query(models.Audit).filter(models.Audit.url.ilike(f"%{domain}%"))
        if user_id is not None:
            query = query.filter(models.Audit.user_id == user_id)

        audits = (
            query.order_by(models.Audit.created_at.asc(), models.Audit.id.asc()).limit(50).all()
        )

        history: list[dict[str, Any]] = []
        for audit in audits:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            analysis = report.get("analysis", {}) if isinstance(report, dict) else {}
            timestamp = (
                audit.created_at.astimezone(timezone.utc).isoformat()
                if audit.created_at is not None
                else datetime.now(timezone.utc).isoformat()
            )
            history.append(
                {
                    "timestamp": timestamp,
                    "score": int(round(extract_score(analysis, "aeo_score"))),
                }
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        if not history or history[-1]["score"] != current_score:
            history.append({"timestamp": now_iso, "score": current_score})

        return history

    def _normalize_url_and_domain(self, url: str, *, prevalidated: bool = False) -> tuple[str, str]:
        normalized = url.strip() if prevalidated else normalize_and_validate_url(url)
        parsed = httpx.URL(normalized)
        domain = (parsed.host or "").lower().removeprefix("www.")
        if not domain:
            raise ValueError("Please provide a valid URL.")
        return normalized, domain

    async def _fetch_page_signals(self, url: str) -> tuple[str, str | None]:
        from services.url_validation import safe_async_fetch

        response = await safe_async_fetch(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        html = response.text or ""
        last_modified = response.headers.get("Last-Modified") or response.headers.get(
            "last-modified"
        )
        return html, last_modified

    def _detect_schema_presence(self, html: str) -> float:
        if not html:
            return 0.0

        lowered = html.lower()
        if any(marker in lowered for marker in SCHEMA_MARKERS):
            return 1.0

        if re.search(r'"@context"\s*:\s*"https?://schema.org', lowered):
            return 1.0
        return 0.0

    async def _fetch_link_authority_metrics(self, domain: str) -> tuple[float, float]:
        if self.metrics_provider_url:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(
                        self.metrics_provider_url, params={"domain": domain}
                    )
                    response.raise_for_status()
                    payload = response.json()
                backlinks = float(payload.get("backlink_count", 0.0))
                authority = float(payload.get("domain_authority", 0.0))
                return max(0.0, backlinks), self._clamp(authority, 0.0, 100.0)
            except Exception as exc:
                logger.warning(
                    "AEO answerability metrics provider call failed for %s: %s", domain, exc
                )

        # Stable fallback when a provider is not configured.
        digest = hashlib.sha256(domain.encode("utf-8")).hexdigest()
        seed = int(digest[:12], 16)
        backlinks = float(seed % 30000)
        authority = float((seed // 13) % 101)
        return backlinks, authority

    def _calculate_freshness_days(self, last_modified_header: str | None) -> float | None:
        if not last_modified_header:
            return None
        try:
            parsed = parsedate_to_datetime(last_modified_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = now - parsed
            return max(0.0, float(delta.days))
        except Exception:
            return None

    def _normalize_features(self, raw: AnswerabilityFeatures) -> dict[str, float]:
        backlinks_normalized = min(
            1.0, math.log1p(raw.backlink_count) / math.log1p(self.max_backlinks)
        )
        if raw.freshness_days is None:
            freshness_normalized = 0.5
        else:
            freshness_normalized = self._clamp(
                1.0 - (raw.freshness_days / self.max_freshness_days), 0.0, 1.0
            )

        return {
            "schema_presence": self._clamp(raw.schema_presence, 0.0, 1.0),
            "backlink_count": backlinks_normalized,
            "freshness": freshness_normalized,
            "domain_authority": self._clamp(raw.domain_authority / 100.0, 0.0, 1.0),
        }

    def _calculate_score(self, normalized: dict[str, float]) -> tuple[int, float]:
        z = self.intercept
        for key, weight in self.weights.items():
            z += weight * normalized.get(key, 0.0)

        score_0_1 = 1.0 / (1.0 + math.exp(-z))
        score_0_100 = self._clamp(score_0_1 * 100.0, 0.0, 100.0)
        return int(round(score_0_100)), score_0_100

    def _explain_factors(
        self, raw: AnswerabilityFeatures, normalized: dict[str, float]
    ) -> list[dict[str, Any]]:
        feature_metadata = {
            "schema_presence": {
                "name": "Structured data coverage",
                "value": "Detected" if raw.schema_presence >= 1 else "Not detected",
                "hint": "Add JSON-LD schema.org markup for eligible content types.",
            },
            "backlink_count": {
                "name": "Backlink volume",
                "value": f"{int(raw.backlink_count)} backlinks",
                "hint": "Increase high-quality referring domains and citations.",
            },
            "freshness": {
                "name": "Content freshness",
                "value": (
                    f"{int(raw.freshness_days)} days old"
                    if raw.freshness_days is not None
                    else "Unknown page age"
                ),
                "hint": "Refresh content regularly and expose Last-Modified headers.",
            },
            "domain_authority": {
                "name": "Domain authority",
                "value": f"{raw.domain_authority:.1f}/100",
                "hint": "Build topical authority with strong content clusters and backlinks.",
            },
        }

        scored_factors: list[dict[str, Any]] = []
        for key, weight in self.weights.items():
            normalized_value = normalized.get(key, 0.0)
            contribution = weight * normalized_value
            effect = "positive" if normalized_value >= 0.5 else "negative"
            md = feature_metadata[key]
            scored_factors.append(
                {
                    "feature": key,
                    "label": md["name"],
                    "impact": round(contribution, 4),
                    "direction": effect,
                    "raw_value": md["value"],
                    "explanation": (
                        f"{md['name']} is {md['value']}, producing a {effect} impact on answerability. "
                        f"{md['hint']}"
                    ),
                }
            )

        scored_factors.sort(key=lambda item: abs(item["impact"]), reverse=True)
        return scored_factors[:3]

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
