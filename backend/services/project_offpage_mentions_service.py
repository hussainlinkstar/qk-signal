from __future__ import annotations

import asyncio
import hashlib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

import models
from services.url_validation import SSRFBlockedError, safe_sync_fetch
from app.config.plans import resolve_entitled_subscription_plan, resolve_plan_alias
from auth.credits import apply_dynamic_ai_credit_charge
from services.ai_engine import AIFactory
from services.billing_calculator import calculate_dynamic_billing
from services.semantic_cache_service import semantic_cache_service

MENTION_ANALYSIS_FEATURE_KEY = "aeo_mentions.sentiment_entity"
MENTION_ANALYSIS_PROVIDER = "google"
MENTION_ANALYSIS_TIER = "fast"
AI_BATCH_SIZE = 20
SENTIMENT_LABELS = {"positive", "neutral", "negative", "unknown"}

HIGH_TRUST_DOMAIN_WEIGHTS: dict[str, float] = {
    "reddit.com": 1.00,
    "quora.com": 0.93,
    "wikipedia.org": 0.98,
    "stackoverflow.com": 0.90,
    "github.com": 0.87,
    "forbes.com": 0.94,
    "bloomberg.com": 0.92,
    "nytimes.com": 0.92,
    "techcrunch.com": 0.90,
    "medium.com": 0.78,
}
DEFAULT_DOMAIN_AUTHORITY_SCORE = 35.0

POSITIVE_TERMS = {
    "best",
    "great",
    "strong",
    "recommended",
    "reliable",
    "excellent",
    "trusted",
    "useful",
}
NEGATIVE_TERMS = {
    "bad",
    "poor",
    "weak",
    "broken",
    "slow",
    "unreliable",
    "complaint",
    "scam",
    "bug",
}

MENTION_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "sentiment_label",
                    "sentiment_score",
                    "linked_keywords",
                    "entities",
                    "action_recommendation",
                ],
                "properties": {
                    "id": {"type": "integer"},
                    "sentiment_label": {"type": "string"},
                    "sentiment_score": {"type": "number"},
                    "linked_keywords": {"type": "array", "items": {"type": "string"}},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "action_recommendation": {"type": "string"},
                },
            },
        }
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_owner_plan(owner: models.User | None) -> str:
    subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(owner))
    trial_plan = resolve_plan_alias(getattr(owner, "trial_plan", None))
    return subscription_plan or trial_plan or "plan_starter"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _clip_text(value: str | None, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_domain(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        hostname = raw.rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or None


def _domain_for_mention(mention_url: str | None, source_domain: str | None) -> str | None:
    return _normalize_domain(source_domain) or _normalize_domain(mention_url)


def _domain_weight(domain: str | None) -> float:
    normalized = _normalize_domain(domain)
    if not normalized:
        return DEFAULT_DOMAIN_AUTHORITY_SCORE / 100.0
    if normalized in HIGH_TRUST_DOMAIN_WEIGHTS:
        return HIGH_TRUST_DOMAIN_WEIGHTS[normalized]
    for known_domain, weight in HIGH_TRUST_DOMAIN_WEIGHTS.items():
        if normalized.endswith(f".{known_domain}"):
            return weight
    return DEFAULT_DOMAIN_AUTHORITY_SCORE / 100.0


def _authority_score(domain: str | None) -> float:
    return round(max(0.0, min(100.0, _domain_weight(domain) * 100.0)), 2)


def _normalize_sentiment_label(value: str | None) -> str:
    label = str(value or "").strip().lower()
    return label if label in SENTIMENT_LABELS else "unknown"


def _normalize_sentiment_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(-1.0, min(1.0, round(score, 4)))


def _coerce_string_list(value: Any, *, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()][:limit]
    return []


def _keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _extract_project_keywords(project: models.Project) -> list[str]:
    keywords: list[str] = []
    for value in list(project.icp_roles or []):
        cleaned = _keyword(str(value))
        if len(cleaned) >= 3:
            keywords.append(cleaned)
    usp_text = str(project.usp or "").strip()
    for token in re.split(r"[,/;\n]", usp_text):
        cleaned = _keyword(token)
        if len(cleaned) >= 3:
            keywords.append(cleaned)
    deduped: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        if keyword in seen:
            continue
        seen.add(keyword)
        deduped.append(keyword)
    return deduped[:16]


def _mention_fingerprint(
    *,
    source_type: str,
    source_domain: str | None,
    mention_url: str | None,
    external_id: str | None,
    title: str | None,
    snippet: str,
    published_at: datetime | None,
) -> str:
    payload = "|".join(
        [
            source_type.strip().lower(),
            str(source_domain or "").strip().lower(),
            str(mention_url or "").strip().lower(),
            str(external_id or "").strip().lower(),
            str(title or "").strip().lower(),
            snippet.strip().lower(),
            published_at.isoformat() if published_at else "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score_off_page_aeo(
    *,
    total_mentions: int,
    positive_mentions: int,
    negative_mentions: int,
    unique_domains: int,
    avg_authority_score: float,
) -> float:
    if total_mentions <= 0:
        return 0.0
    sentiment_ratio = (positive_mentions - negative_mentions) / float(max(1, total_mentions))
    sentiment_component = max(0.0, min(100.0, 50.0 + sentiment_ratio * 50.0))
    coverage_component = max(0.0, min(100.0, float(unique_domains) * 20.0))
    authority_component = max(0.0, min(100.0, float(avg_authority_score)))
    volume_component = max(0.0, min(100.0, float(total_mentions) * 5.0))
    weighted = (
        sentiment_component * 0.35
        + authority_component * 0.30
        + coverage_component * 0.20
        + volume_component * 0.15
    )
    return round(weighted, 2)


def _trend_delta(rows: list[models.ProjectOffPageMentionDailySummary]) -> float | None:
    if len(rows) < 4:
        return None
    ordered = sorted(rows, key=lambda row: row.snapshot_date)
    split = len(ordered) // 2
    first = ordered[:split]
    second = ordered[split:]
    if not first or not second:
        return None
    first_avg = sum(float(row.off_page_aeo_score or 0.0) for row in first) / float(len(first))
    second_avg = sum(float(row.off_page_aeo_score or 0.0) for row in second) / float(len(second))
    return round(second_avg - first_avg, 2)


def _heuristic_analysis(
    *, text: str, domain: str | None, target_keywords: list[str]
) -> dict[str, Any]:
    normalized = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    positive_hits = sum(1 for token in POSITIVE_TERMS if token in tokens)
    negative_hits = sum(1 for token in NEGATIVE_TERMS if token in tokens)
    if positive_hits > negative_hits:
        sentiment_label = "positive"
    elif negative_hits > positive_hits:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"
    sentiment_score = 0.0
    if positive_hits or negative_hits:
        sentiment_score = (positive_hits - negative_hits) / float(
            max(1, positive_hits + negative_hits)
        )
    linked_keywords = [keyword for keyword in target_keywords if keyword in normalized][:6]
    entities = []
    seen: set[str] = set()
    for match in re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", text):
        lowered = match.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        entities.append(match)
        if len(entities) >= 6:
            break
    recommendation = ""
    if sentiment_label == "negative":
        recommendation = (
            f"Investigate and respond to negative sentiment on {domain}."
            if domain
            else "Investigate and respond to this negative mention."
        )
    elif sentiment_label == "neutral" and _authority_score(domain) >= 80:
        recommendation = "Add an authoritative response to strengthen entity association."
    elif not linked_keywords:
        recommendation = (
            "Unclaimed entity mention. Add context linking your brand to target topics."
        )
    return {
        "sentiment_label": sentiment_label,
        "sentiment_score": round(sentiment_score, 4),
        "linked_keywords": linked_keywords,
        "entities": entities,
        "action_recommendation": recommendation,
    }


# SIGV2-1008: verified outbound-link-to-target state on existing mention records.
# "unknown" covers never-checked, fetch-failed, restricted and brand-unconfirmed
# pages. Only "unlinked" is a reclaimable publication opportunity; AI-response
# mentions are never counted here (AC4).
LINK_STATE_UNKNOWN = "unknown"
LINK_STATE_LINKED = "linked"
LINK_STATE_UNLINKED = "unlinked"
LINK_CHECK_METHOD = "safe_sync_fetch"
LINK_CHECK_MAX_BYTES = 2 * 1024 * 1024
LINK_CHECK_TIMEOUT = 15.0
_LINK_VERIFICATION_MAX_MENTIONS = 200


def _canonicalize_mention_url(value: str | None) -> str | None:
    """Canonical dedupe key for URL variants: lowercase host, strip a leading
    ``www.``, drop the scheme, fragment and default port, collapse a single
    trailing slash. Two variants of the same page dedupe to one record."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    if port not in (None, 80, 443):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    canonical = f"{host}{path}"
    if parsed.query:
        canonical = f"{canonical}?{parsed.query}"
    return canonical


def _project_target_hosts(project: models.Project) -> set[str]:
    """Registrable host variants of the project domain used to detect an
    outbound link pointing at the target site."""
    raw = str(getattr(project, "domain_url", "") or "").strip()
    if not raw:
        return set()
    try:
        host = (urlparse(raw if "://" in raw else f"https://{raw}").hostname or "").lower()
    except ValueError:
        return set()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return set()
    return {host, f"www.{host}"}


def _project_brand_terms(project: models.Project) -> list[str]:
    name = str(getattr(project, "name", "") or "").strip()
    terms = [name] if name else []
    for host in _project_target_hosts(project):
        if not host.startswith("www."):
            root = host.split(".")[0]
            if root and root.casefold() != name.casefold():
                terms.append(root)
    return terms


def _extract_target_links(html: str, target_hosts: set[str]) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    matches: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = str(tag["href"]).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            host = (urlparse(href if "://" in href else f"https://{href}").hostname or "").lower()
        except ValueError:
            continue
        if host in target_hosts:
            matches.append(href)
    return matches


def _brand_match_in_html(html: str, brand_terms: list[str]) -> bool:
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).casefold()
    return any(term.casefold() in text for term in brand_terms if term)


class ProjectOffPageMentionsService:
    def __init__(self, db: Session, *, ai_factory: AIFactory | None = None):
        self.db = db
        self.ai_factory = ai_factory or AIFactory()

    def ingest_mentions(
        self,
        *,
        project: models.Project,
        source_type: str,
        mention_payloads: list[dict[str, Any]],
        run_analysis: bool,
        skip_existing: bool,
    ) -> dict[str, Any]:
        source = str(source_type or "").strip().lower() or "manual_import"
        now = _utc_now()
        inserted: list[models.ProjectOffPageMention] = []
        pending_ids: list[int] = []
        skipped = 0
        affected_dates: set[date] = set()

        for payload in mention_payloads:
            title = _clip_text(payload.get("title"), max_length=300) or None
            snippet = _clip_text(payload.get("snippet"), max_length=8000) or _clip_text(
                title, max_length=8000
            )
            if not snippet:
                skipped += 1
                continue
            mention_url = _clip_text(payload.get("mention_url"), max_length=2000) or None
            external_id = _clip_text(payload.get("external_id"), max_length=255) or None
            source_domain = _domain_for_mention(mention_url, payload.get("source_domain"))
            published_at = _parse_datetime(payload.get("published_at"))
            fingerprint = _mention_fingerprint(
                source_type=source,
                source_domain=source_domain,
                mention_url=mention_url,
                external_id=external_id,
                title=title,
                snippet=snippet,
                published_at=published_at,
            )

            if skip_existing:
                exists = (
                    self.db.query(models.ProjectOffPageMention.id)
                    .filter(
                        models.ProjectOffPageMention.project_id == project.id,
                        models.ProjectOffPageMention.fingerprint_hash == fingerprint,
                    )
                    .first()
                )
                if exists is not None:
                    skipped += 1
                    continue

            sentiment_label = _normalize_sentiment_label(payload.get("sentiment_label"))
            sentiment_score = _normalize_sentiment_score(payload.get("sentiment_score"))
            analysis_status = (
                "completed"
                if sentiment_label != "unknown" and sentiment_score is not None
                else "pending"
            )
            mention = models.ProjectOffPageMention(
                project_id=project.id,
                source_type=source,
                source_domain=source_domain,
                mention_url=mention_url,
                external_id=external_id,
                title=title,
                snippet=snippet,
                fingerprint_hash=fingerprint,
                published_at=published_at,
                discovered_at=now,
                sentiment_label=sentiment_label,
                sentiment_score=sentiment_score,
                linked_keywords_json=_coerce_string_list(payload.get("linked_keywords"), limit=8),
                entities_json=_coerce_string_list(payload.get("entities"), limit=8),
                authority_score=_authority_score(source_domain),
                action_recommendation=_clip_text(
                    payload.get("action_recommendation"), max_length=1000
                )
                or None,
                analysis_status=analysis_status,
                metadata_json=payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {},
                schema_version="1",
            )
            self.db.add(mention)
            self.db.flush()
            inserted.append(mention)
            if analysis_status == "pending":
                pending_ids.append(int(mention.id))
            affected_dates.add((published_at or now).date())

        self.db.commit()

        analysis_report = {"analyzed_mentions": 0, "degraded": False, "degraded_reasons": []}
        if run_analysis and pending_ids:
            analysis_report = self.analyze_pending_mentions(
                project=project, mention_ids=pending_ids
            )
        if affected_dates:
            self.rebuild_daily_summaries(
                project_id=project.id,
                start_date=min(affected_dates),
                end_date=max(affected_dates),
            )
        return {
            "project_id": project.id,
            "ingested_mentions": len(inserted),
            "skipped_mentions": skipped,
            "analyzed_mentions": int(analysis_report.get("analyzed_mentions", 0)),
            "degraded": bool(analysis_report.get("degraded", False)),
            "degraded_reasons": list(analysis_report.get("degraded_reasons") or []),
        }

    def analyze_pending_mentions(
        self,
        *,
        project: models.Project,
        mention_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        query = (
            self.db.query(models.ProjectOffPageMention)
            .filter(
                models.ProjectOffPageMention.project_id == project.id,
                models.ProjectOffPageMention.analysis_status == "pending",
            )
            .order_by(models.ProjectOffPageMention.id.asc())
        )
        if mention_ids:
            query = query.filter(models.ProjectOffPageMention.id.in_(list(mention_ids)))
        pending = query.all()
        if not pending:
            return {"analyzed_mentions": 0, "degraded": False, "degraded_reasons": []}

        owner = project.workspace.owner if project.workspace else None
        keywords = _extract_project_keywords(project)
        model_info = self.ai_factory.get_model_instance(
            MENTION_ANALYSIS_PROVIDER, MENTION_ANALYSIS_TIER
        )
        degraded_reasons: list[str] = []
        analyzed = 0
        affected_dates: set[date] = set()

        for start in range(0, len(pending), AI_BATCH_SIZE):
            batch = pending[start : start + AI_BATCH_SIZE]
            results: dict[int, dict[str, Any]] = {}
            ai_rows: list[models.ProjectOffPageMention] = []

            for row in batch:
                cache_entry = semantic_cache_service.get_json(
                    feature_key=MENTION_ANALYSIS_FEATURE_KEY,
                    route_provider=MENTION_ANALYSIS_PROVIDER,
                    route_tier=MENTION_ANALYSIS_TIER,
                    semantic_payload=self._semantic_payload(row),
                )
                cached = cache_entry.get("response") if isinstance(cache_entry, dict) else None
                normalized = (
                    self._normalize_ai_result(cached, fallback_id=row.id)
                    if isinstance(cached, dict)
                    else None
                )
                if normalized is None:
                    ai_rows.append(row)
                else:
                    results[row.id] = normalized

            if ai_rows:
                if model_info is None:
                    degraded_reasons.append(
                        "AI provider route unavailable; used heuristic mention analysis."
                    )
                    for row in ai_rows:
                        results[row.id] = _heuristic_analysis(
                            text=f"{row.title or ''}\n{row.snippet}",
                            domain=row.source_domain,
                            target_keywords=keywords,
                        )
                else:
                    provider, model_name = model_info
                    estimate_billing = calculate_dynamic_billing(
                        model_name=model_name,
                        usage={"prompt_tokens": 1400, "completion_tokens": 550},
                        plan_type=_resolve_owner_plan(owner),
                        feature_key=MENTION_ANALYSIS_FEATURE_KEY,
                        tier_class=MENTION_ANALYSIS_TIER,
                    )
                    use_ai = owner is not None and int(owner.credits or 0) >= int(
                        estimate_billing.credits_to_deduct or 0
                    )
                    if not use_ai:
                        degraded_reasons.append(
                            "Insufficient credits for AI mention analysis; used heuristic fallback."
                        )
                        for row in ai_rows:
                            results[row.id] = _heuristic_analysis(
                                text=f"{row.title or ''}\n{row.snippet}",
                                domain=row.source_domain,
                                target_keywords=keywords,
                            )
                    else:
                        ai_items, metadata, ai_error = self._run_ai_batch(
                            batch=ai_rows,
                            target_keywords=keywords,
                            provider=provider,
                            model_name=model_name,
                        )
                        if ai_error:
                            degraded_reasons.append(ai_error)
                        ai_results_by_id = {
                            int(item["id"]): item
                            for item in (
                                self._normalize_ai_result(item, fallback_id=None)
                                for item in ai_items
                                if isinstance(item, dict)
                            )
                            if item is not None
                        }
                        for row in ai_rows:
                            candidate = ai_results_by_id.get(row.id)
                            if candidate is None:
                                candidate = _heuristic_analysis(
                                    text=f"{row.title or ''}\n{row.snippet}",
                                    domain=row.source_domain,
                                    target_keywords=keywords,
                                )
                            results[row.id] = candidate
                        usage = (
                            metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {}
                        )
                        if usage and owner is not None and not ai_error:
                            try:
                                billing = calculate_dynamic_billing(
                                    model_name=str(metadata.get("model") or model_name),
                                    usage=usage,
                                    plan_type=_resolve_owner_plan(owner),
                                    feature_key=MENTION_ANALYSIS_FEATURE_KEY,
                                    tier_class=MENTION_ANALYSIS_TIER,
                                )
                                apply_dynamic_ai_credit_charge(
                                    self.db,
                                    user=owner,
                                    billing=billing,
                                    provider=str(metadata.get("provider") or provider),
                                    reason_code="aeo_mentions.analyze_batch",
                                    feature_key=MENTION_ANALYSIS_FEATURE_KEY,
                                    tier_class=MENTION_ANALYSIS_TIER,
                                    routing_profile="server_policy",
                                    workspace_id=project.workspace_id,
                                    project_id=project.id,
                                    payload={
                                        "batch_size": len(ai_rows),
                                        "degraded": bool(ai_error),
                                    },
                                )
                            except HTTPException as exc:
                                if exc.status_code == 402:
                                    degraded_reasons.append(
                                        "Insufficient credits when charging AI mention analysis; applied heuristic fallback."
                                    )
                                    for row in ai_rows:
                                        results[row.id] = _heuristic_analysis(
                                            text=f"{row.title or ''}\n{row.snippet}",
                                            domain=row.source_domain,
                                            target_keywords=keywords,
                                        )
                                else:
                                    degraded_reasons.append(
                                        "Credit charge failed for AI mention analysis."
                                    )

            for row in batch:
                item = results.get(row.id) or _heuristic_analysis(
                    text=f"{row.title or ''}\n{row.snippet}",
                    domain=row.source_domain,
                    target_keywords=keywords,
                )
                row.sentiment_label = _normalize_sentiment_label(item.get("sentiment_label"))
                row.sentiment_score = _normalize_sentiment_score(item.get("sentiment_score"))
                row.linked_keywords_json = _coerce_string_list(item.get("linked_keywords"), limit=8)
                row.entities_json = _coerce_string_list(item.get("entities"), limit=8)
                row.action_recommendation = (
                    _clip_text(item.get("action_recommendation"), max_length=1000) or None
                )
                row.analysis_status = "completed"
                row.analysis_error = None
                row.updated_at = _utc_now()
                analyzed += 1
                affected_dates.add((row.published_at or row.discovered_at).date())
                semantic_cache_service.set_json(
                    feature_key=MENTION_ANALYSIS_FEATURE_KEY,
                    route_provider=MENTION_ANALYSIS_PROVIDER,
                    route_tier=MENTION_ANALYSIS_TIER,
                    semantic_payload=self._semantic_payload(row),
                    value={
                        "id": row.id,
                        "sentiment_label": row.sentiment_label,
                        "sentiment_score": row.sentiment_score,
                        "linked_keywords": list(row.linked_keywords_json or []),
                        "entities": list(row.entities_json or []),
                        "action_recommendation": row.action_recommendation or "",
                    },
                )

        self.db.commit()
        if affected_dates:
            self.rebuild_daily_summaries(
                project_id=project.id, start_date=min(affected_dates), end_date=max(affected_dates)
            )

        unique_reasons: list[str] = []
        seen_reasons: set[str] = set()
        for reason in degraded_reasons:
            text = str(reason or "").strip()
            if not text or text in seen_reasons:
                continue
            seen_reasons.add(text)
            unique_reasons.append(text)
        return {
            "analyzed_mentions": analyzed,
            "degraded": bool(unique_reasons),
            "degraded_reasons": unique_reasons,
        }

    def list_feed(
        self,
        *,
        project_id: int,
        days: int = 30,
        limit: int = 50,
        sentiment: str | None = None,
    ) -> list[dict[str, Any]]:
        start = _utc_now() - timedelta(days=max(1, int(days)))
        query = self.db.query(models.ProjectOffPageMention).filter(
            models.ProjectOffPageMention.project_id == project_id,
            or_(
                models.ProjectOffPageMention.published_at >= start,
                and_(
                    models.ProjectOffPageMention.published_at.is_(None),
                    models.ProjectOffPageMention.discovered_at >= start,
                ),
            ),
        )
        sentiment_label = _normalize_sentiment_label(sentiment)
        if sentiment_label in {"positive", "neutral", "negative"}:
            query = query.filter(models.ProjectOffPageMention.sentiment_label == sentiment_label)
        rows = (
            query.order_by(
                func.coalesce(
                    models.ProjectOffPageMention.published_at,
                    models.ProjectOffPageMention.discovered_at,
                ).desc()
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )
        return [self._serialize_mention(row) for row in rows]

    def verify_mention_link_state(
        self, *, project: models.Project, mention: models.ProjectOffPageMention
    ) -> dict[str, Any]:
        """Fetch the mention's source page through the existing SSRF-safe
        outbound path and record a verified link state plus evidence.

        Fetches that fail, are blocked, return an error status, or do not
        confirm the brand produce ``unknown`` - never ``unlinked``. Only a
        fetched page that confirms the brand AND carries no anchor to the
        target domain is reclaimable."""
        checked_at = _utc_now()
        mention.link_checked_at = checked_at
        evidence: dict[str, Any] = {
            "method": LINK_CHECK_METHOD,
            "checked_at": _iso(checked_at),
            "mention_url": mention.mention_url,
        }

        if not _canonicalize_mention_url(mention.mention_url):
            mention.link_state = LINK_STATE_UNKNOWN
            evidence["outcome"] = "no_source_url"
            mention.link_evidence_json = evidence
            return self._serialize_mention(mention)

        try:
            response = safe_sync_fetch(
                str(mention.mention_url),
                timeout=LINK_CHECK_TIMEOUT,
                max_response_bytes=LINK_CHECK_MAX_BYTES,
            )
        except SSRFBlockedError as exc:
            mention.link_state = LINK_STATE_UNKNOWN
            evidence.update({"outcome": "fetch_blocked", "error": str(exc)[:200]})
            mention.link_evidence_json = evidence
            return self._serialize_mention(mention)
        except Exception as exc:  # network errors, oversized responses
            mention.link_state = LINK_STATE_UNKNOWN
            evidence.update({"outcome": "fetch_failed", "error": type(exc).__name__})
            mention.link_evidence_json = evidence
            return self._serialize_mention(mention)

        evidence["http_status"] = response.status_code
        if response.status_code >= 400:
            mention.link_state = LINK_STATE_UNKNOWN
            evidence["outcome"] = "fetch_failed"
            mention.link_evidence_json = evidence
            return self._serialize_mention(mention)

        html = response.text or ""
        brand_terms = _project_brand_terms(project)
        brand_matched = _brand_match_in_html(html, brand_terms)
        target_links = _extract_target_links(html, _project_target_hosts(project))
        evidence["outcome"] = "checked"
        evidence["brand_matched"] = brand_matched
        evidence["matched_target_urls"] = target_links[:5]
        if target_links:
            mention.link_state = LINK_STATE_LINKED
        elif brand_matched:
            mention.link_state = LINK_STATE_UNLINKED
        else:
            mention.link_state = LINK_STATE_UNKNOWN
            evidence["outcome"] = "brand_not_confirmed"
        mention.link_evidence_json = evidence
        return self._serialize_mention(mention)

    def verify_project_mention_links(
        self,
        *,
        project: models.Project,
        mention_ids: list[int] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Verify outbound-link state for a bounded set of project mentions.
        Targets rows still in ``unknown`` state first unless explicit ids are
        supplied."""
        query = self.db.query(models.ProjectOffPageMention).filter(
            models.ProjectOffPageMention.project_id == project.id
        )
        if mention_ids:
            query = query.filter(models.ProjectOffPageMention.id.in_(mention_ids))
        else:
            query = query.filter(models.ProjectOffPageMention.link_state == LINK_STATE_UNKNOWN)
        cap = max(1, min(int(limit), _LINK_VERIFICATION_MAX_MENTIONS))
        rows = query.order_by(models.ProjectOffPageMention.id.asc()).limit(cap).all()
        counts = {
            LINK_STATE_LINKED: 0,
            LINK_STATE_UNLINKED: 0,
            LINK_STATE_UNKNOWN: 0,
        }
        items = []
        for row in rows:
            items.append(self.verify_mention_link_state(project=project, mention=row))
            counts[row.link_state] = counts.get(row.link_state, 0) + 1
        self.db.commit()
        return {
            "project_id": project.id,
            "checked": len(rows),
            "counts": counts,
            "items": items,
        }

    def _mentions_in_window(self, *, project_id: int, days: int):
        start = _utc_now() - timedelta(days=max(1, int(days)))
        return (
            self.db.query(models.ProjectOffPageMention)
            .filter(
                models.ProjectOffPageMention.project_id == project_id,
                or_(
                    models.ProjectOffPageMention.published_at >= start,
                    and_(
                        models.ProjectOffPageMention.published_at.is_(None),
                        models.ProjectOffPageMention.discovered_at >= start,
                    ),
                ),
            )
            .order_by(
                func.coalesce(
                    models.ProjectOffPageMention.published_at,
                    models.ProjectOffPageMention.discovered_at,
                ).desc(),
                models.ProjectOffPageMention.id.desc(),
            )
            .all()
        )

    def list_unlinked_mentions(
        self, *, project_id: int, days: int = 90, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Paginated reclaimable-mention evidence list.

        The count is derived from the SAME filtered, deduplicated set as the
        items, so the number and the list can never disagree. Canonical URL
        variants dedupe to the most recent record."""
        rows = self._mentions_in_window(project_id=project_id, days=days)
        seen: set[str] = set()
        deduped: list[models.ProjectOffPageMention] = []
        for row in rows:
            key = _canonicalize_mention_url(row.mention_url) or f"id:{row.id}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        states = {
            LINK_STATE_UNLINKED: 0,
            LINK_STATE_LINKED: 0,
            LINK_STATE_UNKNOWN: 0,
        }
        unlinked: list[models.ProjectOffPageMention] = []
        for row in deduped:
            state = row.link_state if row.link_state in states else LINK_STATE_UNKNOWN
            states[state] += 1
            if state == LINK_STATE_UNLINKED:
                unlinked.append(row)
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(int(limit), 200))
        page = unlinked[safe_offset : safe_offset + safe_limit]
        return {
            "project_id": project_id,
            "window_days": max(1, int(days)),
            "count": len(unlinked),
            "offset": safe_offset,
            "limit": safe_limit,
            "states": states,
            "items": [self._serialize_mention(row) for row in page],
        }

    def build_summary(self, *, project: models.Project, days: int = 30) -> dict[str, Any]:
        window_days = max(7, min(int(days), 365))
        today = _utc_now().date()
        start_date = today - timedelta(days=window_days - 1)
        self.rebuild_daily_summaries(project_id=project.id, start_date=start_date, end_date=today)
        rows = (
            self.db.query(models.ProjectOffPageMentionDailySummary)
            .filter(
                models.ProjectOffPageMentionDailySummary.project_id == project.id,
                models.ProjectOffPageMentionDailySummary.snapshot_date >= start_date,
                models.ProjectOffPageMentionDailySummary.snapshot_date <= today,
            )
            .order_by(models.ProjectOffPageMentionDailySummary.snapshot_date.asc())
            .all()
        )
        latest_mentions = self.list_feed(project_id=project.id, days=window_days, limit=8)
        if not rows:
            return {
                "project_id": project.id,
                "generated_at": _iso(_utc_now()),
                "window_days": window_days,
                "latest_snapshot_date": None,
                "no_data": True,
                "degraded": False,
                "degraded_reasons": [],
                "off_page_aeo_score": 0.0,
                "trend_delta": None,
                "totals": {
                    "total_mentions": 0,
                    "positive_mentions": 0,
                    "neutral_mentions": 0,
                    "negative_mentions": 0,
                    "unique_domains": 0,
                },
                "top_domains": [],
                "actionable_advice": [],
                "latest_mentions": latest_mentions,
            }

        total_mentions = sum(int(row.total_mentions or 0) for row in rows)
        positive_mentions = sum(int(row.positive_mentions or 0) for row in rows)
        neutral_mentions = sum(int(row.neutral_mentions or 0) for row in rows)
        negative_mentions = sum(int(row.negative_mentions or 0) for row in rows)
        unique_domains = max((int(row.unique_domains or 0) for row in rows), default=0)
        avg_authority = sum(
            float(row.avg_authority_score or 0.0) * max(1, int(row.total_mentions or 0))
            for row in rows
        ) / float(max(1, total_mentions))
        off_page_score = _score_off_page_aeo(
            total_mentions=total_mentions,
            positive_mentions=positive_mentions,
            negative_mentions=negative_mentions,
            unique_domains=unique_domains,
            avg_authority_score=avg_authority,
        )
        degraded_reasons: list[str] = []
        for row in rows:
            for reason in list(row.degraded_reasons_json or []):
                text = str(reason).strip()
                if text and text not in degraded_reasons:
                    degraded_reasons.append(text)
        return {
            "project_id": project.id,
            "generated_at": _iso(_utc_now()),
            "window_days": window_days,
            "latest_snapshot_date": rows[-1].snapshot_date.isoformat(),
            "no_data": total_mentions <= 0,
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "off_page_aeo_score": off_page_score,
            "trend_delta": _trend_delta(rows),
            "totals": {
                "total_mentions": total_mentions,
                "positive_mentions": positive_mentions,
                "neutral_mentions": neutral_mentions,
                "negative_mentions": negative_mentions,
                "unique_domains": unique_domains,
            },
            "top_domains": self._top_domains(
                project_id=project.id, start_date=start_date, end_date=today
            ),
            "actionable_advice": self._build_actionable_advice(
                project=project, latest_mentions=latest_mentions
            ),
            "latest_mentions": latest_mentions,
        }

    def build_trends(self, *, project_id: int, days: int = 30) -> dict[str, Any]:
        window_days = max(7, min(int(days), 365))
        today = _utc_now().date()
        start_date = today - timedelta(days=window_days - 1)
        self.rebuild_daily_summaries(project_id=project_id, start_date=start_date, end_date=today)
        rows = (
            self.db.query(models.ProjectOffPageMentionDailySummary)
            .filter(
                models.ProjectOffPageMentionDailySummary.project_id == project_id,
                models.ProjectOffPageMentionDailySummary.snapshot_date >= start_date,
                models.ProjectOffPageMentionDailySummary.snapshot_date <= today,
            )
            .order_by(models.ProjectOffPageMentionDailySummary.snapshot_date.asc())
            .all()
        )
        by_date = {row.snapshot_date: row for row in rows}
        points: list[dict[str, Any]] = []
        current = start_date
        while current <= today:
            row = by_date.get(current)
            points.append(
                {
                    "date": current.isoformat(),
                    "off_page_aeo_score": float(row.off_page_aeo_score) if row else None,
                    "total_mentions": int(row.total_mentions or 0) if row else 0,
                    "positive_mentions": int(row.positive_mentions or 0) if row else 0,
                    "negative_mentions": int(row.negative_mentions or 0) if row else 0,
                }
            )
            current += timedelta(days=1)
        return {"project_id": project_id, "days": window_days, "points": points}

    def rebuild_daily_summaries(
        self,
        *,
        project_id: int,
        start_date: date,
        end_date: date,
    ) -> int:
        if end_date < start_date:
            return 0
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(
            end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )
        rows = (
            self.db.query(models.ProjectOffPageMention)
            .filter(
                models.ProjectOffPageMention.project_id == project_id,
                or_(
                    and_(
                        models.ProjectOffPageMention.published_at.isnot(None),
                        models.ProjectOffPageMention.published_at >= start_dt,
                        models.ProjectOffPageMention.published_at < end_dt,
                    ),
                    and_(
                        models.ProjectOffPageMention.published_at.is_(None),
                        models.ProjectOffPageMention.discovered_at >= start_dt,
                        models.ProjectOffPageMention.discovered_at < end_dt,
                    ),
                ),
            )
            .all()
        )
        self.db.query(models.ProjectOffPageMentionDailySummary).filter(
            models.ProjectOffPageMentionDailySummary.project_id == project_id,
            models.ProjectOffPageMentionDailySummary.snapshot_date >= start_date,
            models.ProjectOffPageMentionDailySummary.snapshot_date <= end_date,
        ).delete(synchronize_session=False)

        grouped: dict[date, list[models.ProjectOffPageMention]] = defaultdict(list)
        for row in rows:
            grouped[(row.published_at or row.discovered_at).date()].append(row)

        inserted = 0
        now = _utc_now()
        for snapshot_date, items in grouped.items():
            if snapshot_date < start_date or snapshot_date > end_date:
                continue
            total = len(items)
            positive = sum(1 for item in items if item.sentiment_label == "positive")
            negative = sum(1 for item in items if item.sentiment_label == "negative")
            neutral = sum(1 for item in items if item.sentiment_label == "neutral")
            unique_domains = len(
                {
                    str(item.source_domain or "").strip().lower()
                    for item in items
                    if item.source_domain
                }
            )
            avg_authority = sum(float(item.authority_score or 0.0) for item in items) / float(
                max(1, total)
            )
            degraded_reasons = (
                ["Some mentions are pending or failed NLP analysis."]
                if any(item.analysis_status != "completed" for item in items)
                else []
            )
            self.db.add(
                models.ProjectOffPageMentionDailySummary(
                    project_id=project_id,
                    snapshot_date=snapshot_date,
                    total_mentions=total,
                    positive_mentions=positive,
                    neutral_mentions=neutral,
                    negative_mentions=negative,
                    unique_domains=unique_domains,
                    avg_authority_score=round(avg_authority, 2),
                    off_page_aeo_score=_score_off_page_aeo(
                        total_mentions=total,
                        positive_mentions=positive,
                        negative_mentions=negative,
                        unique_domains=unique_domains,
                        avg_authority_score=avg_authority,
                    ),
                    degraded=bool(degraded_reasons),
                    degraded_reasons_json=degraded_reasons,
                    computed_at=now,
                    schema_version="1",
                )
            )
            inserted += 1
        self.db.commit()
        return inserted

    def _semantic_payload(self, mention: models.ProjectOffPageMention) -> dict[str, Any]:
        return {
            "title": _clip_text(mention.title, max_length=280),
            "snippet": _clip_text(mention.snippet, max_length=1800),
            "source_domain": mention.source_domain or "",
        }

    def _serialize_mention(self, mention: models.ProjectOffPageMention) -> dict[str, Any]:
        return {
            "id": mention.id,
            "project_id": mention.project_id,
            "source_type": mention.source_type,
            "source_domain": mention.source_domain,
            "mention_url": mention.mention_url,
            "external_id": mention.external_id,
            "title": mention.title,
            "snippet": mention.snippet,
            "published_at": _iso(mention.published_at),
            "discovered_at": _iso(mention.discovered_at),
            "sentiment_label": mention.sentiment_label,
            "sentiment_score": mention.sentiment_score,
            "linked_keywords": list(mention.linked_keywords_json or []),
            "entities": list(mention.entities_json or []),
            "authority_score": float(mention.authority_score or 0.0),
            "action_recommendation": mention.action_recommendation,
            "analysis_status": mention.analysis_status,
            "link_state": mention.link_state or LINK_STATE_UNKNOWN,
            "link_checked_at": _iso(mention.link_checked_at),
            "link_evidence": dict(mention.link_evidence_json or {}),
        }

    def _top_domains(
        self, *, project_id: int, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(
            end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )
        rows = (
            self.db.query(models.ProjectOffPageMention)
            .filter(
                models.ProjectOffPageMention.project_id == project_id,
                or_(
                    and_(
                        models.ProjectOffPageMention.published_at.isnot(None),
                        models.ProjectOffPageMention.published_at >= start_dt,
                        models.ProjectOffPageMention.published_at < end_dt,
                    ),
                    and_(
                        models.ProjectOffPageMention.published_at.is_(None),
                        models.ProjectOffPageMention.discovered_at >= start_dt,
                        models.ProjectOffPageMention.discovered_at < end_dt,
                    ),
                ),
            )
            .all()
        )
        buckets: dict[str, dict[str, float]] = {}
        for row in rows:
            domain = _normalize_domain(row.source_domain) or "unknown"
            bucket = buckets.setdefault(
                domain, {"mentions": 0.0, "authority_sum": 0.0, "sentiment_sum": 0.0}
            )
            bucket["mentions"] += 1.0
            bucket["authority_sum"] += float(row.authority_score or 0.0)
            bucket["sentiment_sum"] += float(row.sentiment_score or 0.0)
        output: list[dict[str, Any]] = []
        for domain, bucket in buckets.items():
            mentions = int(bucket["mentions"])
            output.append(
                {
                    "domain": domain,
                    "mentions": mentions,
                    "avg_authority_score": round(
                        bucket["authority_sum"] / float(max(1, mentions)), 2
                    ),
                    "avg_sentiment_score": round(
                        bucket["sentiment_sum"] / float(max(1, mentions)), 3
                    ),
                }
            )
        output.sort(key=lambda row: (row["mentions"], row["avg_authority_score"]), reverse=True)
        return output[:8]

    def _build_actionable_advice(
        self, *, project: models.Project, latest_mentions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        advice: list[dict[str, Any]] = []
        target_keywords = _extract_project_keywords(project)
        for mention in latest_mentions:
            title = str(mention.get("title") or mention.get("snippet") or "Mention").strip()[:140]
            domain = str(mention.get("source_domain") or "high-trust source").strip()
            sentiment = str(mention.get("sentiment_label") or "unknown")
            linked_keywords = [
                str(value).strip().lower() for value in list(mention.get("linked_keywords") or [])
            ]
            recommendation = str(mention.get("action_recommendation") or "").strip()
            url = mention.get("mention_url")
            if recommendation:
                advice.append(
                    {
                        "title": title,
                        "priority": "high" if sentiment == "negative" else "medium",
                        "source_domain": domain,
                        "message": recommendation,
                        "mention_url": url,
                    }
                )
            elif sentiment == "negative":
                advice.append(
                    {
                        "title": title,
                        "priority": "high",
                        "source_domain": domain,
                        "message": f"High-risk negative mention on {domain}. Respond with clarifying evidence.",
                        "mention_url": url,
                    }
                )
            elif target_keywords and not any(
                keyword in linked_keywords for keyword in target_keywords
            ):
                advice.append(
                    {
                        "title": title,
                        "priority": "medium",
                        "source_domain": domain,
                        "message": f"Unclaimed entity mention on {domain}. Add an answer linking to your target topics.",
                        "mention_url": url,
                    }
                )
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in advice:
            key = f"{item.get('title')}|{item.get('message')}|{item.get('mention_url')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:6]

    def _run_ai_batch(
        self,
        *,
        batch: list[models.ProjectOffPageMention],
        target_keywords: list[str],
        provider: str,
        model_name: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
        system_prompt = (
            "You are an off-page AEO analyst.\n"
            "Return only valid JSON.\n"
            "Sentiment labels must be positive, neutral, or negative.\n"
            "sentiment_score must be between -1 and 1.\n"
        )
        payload = [
            {
                "id": row.id,
                "title": row.title or "",
                "snippet": _clip_text(row.snippet, max_length=1800),
                "source_domain": row.source_domain or "",
                "target_keywords": target_keywords,
            }
            for row in batch
        ]
        user_prompt = [f"Analyze these mentions and return items array: {payload}"]
        try:
            raw = asyncio.run(
                self.ai_factory._generate_with_provider(
                    provider,
                    model_name,
                    system_prompt,
                    user_prompt,
                    schema=MENTION_ANALYSIS_SCHEMA,
                )
            )
            metadata = self.ai_factory.extract_generation_metadata(raw)
            clean = self.ai_factory.strip_generation_metadata(raw)
            items = clean.get("items") if isinstance(clean, dict) else []
            if not isinstance(items, list):
                return (
                    [],
                    metadata,
                    "AI mention analysis returned an invalid payload. Applied heuristic fallback.",
                )
            return [item for item in items if isinstance(item, dict)], metadata, None
        except Exception:
            return [], {}, "AI mention analysis request failed. Applied heuristic fallback."

    def _normalize_ai_result(
        self, payload: dict[str, Any], fallback_id: int | None
    ) -> dict[str, Any] | None:
        try:
            mention_id = int(payload.get("id") if payload.get("id") is not None else fallback_id)
        except (TypeError, ValueError):
            return None
        if mention_id <= 0:
            return None
        sentiment_label = _normalize_sentiment_label(payload.get("sentiment_label"))
        if sentiment_label == "unknown":
            sentiment_label = "neutral"
        sentiment_score = _normalize_sentiment_score(payload.get("sentiment_score"))
        if sentiment_score is None:
            sentiment_score = 0.0
        return {
            "id": mention_id,
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "linked_keywords": _coerce_string_list(payload.get("linked_keywords"), limit=8),
            "entities": _coerce_string_list(payload.get("entities"), limit=8),
            "action_recommendation": _clip_text(
                payload.get("action_recommendation"), max_length=1000
            ),
        }


def refresh_recent_off_page_mention_daily_summaries(
    db: Session, *, lookback_days: int = 30
) -> dict[str, int]:
    window_days = max(7, min(int(lookback_days), 365))
    today = _utc_now().date()
    start_date = today - timedelta(days=window_days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    project_ids = [
        int(row[0])
        for row in (
            db.query(models.ProjectOffPageMention.project_id)
            .filter(
                or_(
                    and_(
                        models.ProjectOffPageMention.published_at.isnot(None),
                        models.ProjectOffPageMention.published_at >= start_dt,
                    ),
                    and_(
                        models.ProjectOffPageMention.published_at.is_(None),
                        models.ProjectOffPageMention.discovered_at >= start_dt,
                    ),
                )
            )
            .distinct()
            .all()
        )
    ]
    service = ProjectOffPageMentionsService(db)
    refreshed = 0
    failed = 0
    for project_id in project_ids:
        try:
            service.rebuild_daily_summaries(
                project_id=project_id, start_date=start_date, end_date=today
            )
            refreshed += 1
        except Exception:
            failed += 1
    return {
        "projects_considered": len(project_ids),
        "projects_refreshed": refreshed,
        "projects_failed": failed,
    }
