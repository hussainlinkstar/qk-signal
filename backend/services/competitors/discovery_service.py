from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from services.ai_engine import AIFactory
from services.ai_routing_policy import resolve_competitor_discovery_route
from services.observability import redact_secrets

SourceName = str
RawCandidate = str | dict[str, Any]
ProviderCallable = Callable[[str, str, str], Awaitable[list[RawCandidate]]]
EntityAuditProviderCallable = Callable[[str], Awaitable[list[dict[str, Any]]]]

# SIGV2-1285: Edward was shown "List Greatest General From Different Countries"
# and "The Top 10 Generals in World History" as competitor brands, each with a
# confidence score beside it.
#
# The old prefix pattern was anchored to the start of the string, so "The Top
# 10 ..." walked straight through it on the strength of a leading article. Both
# of his examples were classified as brands.
#
# The patterns below are deliberately not anchored, and the rules are built so
# that a real brand containing a superlative survives: "Best Buy" is a shop,
# "Best Dental Clinics" is an article. The distinguishing feature is what
# follows the superlative, not the superlative itself.
_EDITORIAL_COMPETITOR_PREFIX_PATTERN = re.compile(
    # A superlative followed, within a word, by a count or a plural: "Top 10
    # Generals", "Best Dental Clinics", "15 Leading Agencies". The gap is one
    # word rather than none, because the plural is usually the head noun and
    # an adjective sits in front of it.
    #
    # The trade-off, stated rather than discovered later: a real brand of the
    # shape "Best Western Hotels" is rejected by this. That is the right way
    # round. A rejected brand can be added by hand in two clicks, whereas an
    # article headline presented as a competitor with a confidence score beside
    # it is the product asserting something false, which is what Edward saw.
    r"\b(?:top|best|leading|most|greatest|biggest|worst|finest|ultimate)\s+"
    r"(?:\w+\s+)?(?:\d+|\w+s)\b"
    r"|\b\d+\s+(?:best|biggest|leading|top|greatest)\b",
    re.IGNORECASE,
)
_EDITORIAL_COMPETITOR_YEAR_PATTERN = re.compile(r"\b20\d{2}\b")
_EDITORIAL_COMPETITOR_KEYWORDS = (
    "biggest",
    "most visited",
    "marketplaces",
    "platforms",
    "reviewed",
)
# Nouns that belong to an article about a market, never to a company in it.
_EDITORIAL_COMPETITOR_NOUNS = (
    "list",
    "ranking",
    "rankings",
    "roundup",
    "comparison",
    "alternatives",
    "guide",
    "review",
    "reviews",
    "versus",
)
_EDITORIAL_COMPETITOR_SEPARATORS = ("|", ":", "(", ")", "[", "]")
# A brand is short. Across the Fortune 500 the longest names run to five words,
# so anything at or beyond six is prose, and both of Edward's examples are.
_EDITORIAL_COMPETITOR_MAX_WORDS = 6


def _flag_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CompetitorDiscoveryService:
    """Discovers likely competitors from Places/SERP style providers with site-level caching."""

    def __init__(
        self,
        places_provider: ProviderCallable | None = None,
        serp_provider: ProviderCallable | None = None,
        entity_audit_provider: EntityAuditProviderCallable | None = None,
        ai_factory: "AIFactory | None" = None,
    ) -> None:
        self._places_provider = places_provider
        self._serp_provider = serp_provider
        self._entity_audit_provider = entity_audit_provider
        self._ai_factory = ai_factory or AIFactory()
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._enable_textual_fallback = _flag_enabled(
            "ENABLE_TEXTUAL_COMPETITOR_FALLBACK", default=False
        )

    @staticmethod
    def _normalize_site_key(site_url: str) -> str:
        parsed = urlparse(site_url.strip())
        host = (parsed.netloc or parsed.path).lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _title_text(value: str) -> str:
        cleaned = CompetitorDiscoveryService._clean_text(value)
        return cleaned.title()

    @classmethod
    def _looks_like_editorial_title(cls, value: str) -> bool:
        cleaned = cls._clean_text(value)
        lower = cleaned.lower()
        word_count = len(cleaned.split())

        if not cleaned:
            return True
        if cleaned.endswith(("...", "…")):
            return True
        # Prose, not a name. This alone catches both of SIGV2-1285's examples.
        if word_count >= _EDITORIAL_COMPETITOR_MAX_WORDS:
            return True
        if _EDITORIAL_COMPETITOR_PREFIX_PATTERN.search(lower):
            return True
        if word_count >= 4 and _EDITORIAL_COMPETITOR_YEAR_PATTERN.search(cleaned):
            return True
        if any(keyword in lower for keyword in _EDITORIAL_COMPETITOR_KEYWORDS):
            return True
        # A listicle noun needs company: "Guide" could be a brand on its own,
        # "A Guide to Dental Clinics" cannot.
        if word_count >= 3 and any(noun in lower.split() for noun in _EDITORIAL_COMPETITOR_NOUNS):
            return True
        if word_count >= 5 and any(
            separator in cleaned for separator in _EDITORIAL_COMPETITOR_SEPARATORS
        ):
            return True
        return False

    @staticmethod
    def _extract_name(candidate: RawCandidate) -> str:
        if isinstance(candidate, str):
            return candidate

        for key in ("name", "title", "business_name", "domain"):
            raw = candidate.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw
        return ""

    async def _provider_candidates(
        self,
        provider: ProviderCallable | None,
        source: SourceName,
        site_url: str,
        category: str,
        market: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if provider is None:
            return [], None

        try:
            raw_candidates = await provider(site_url, category, market)
        except Exception as exc:  # noqa: BLE001 - provider failures should degrade gracefully
            # SerpAPI / Google Places take their credential as a query parameter, which httpx
            # echoes back in str(exc); this string is surfaced as provider_errors and logged.
            return [], redact_secrets(exc)
        results: list[dict[str, Any]] = []
        for raw in raw_candidates:
            name = self._clean_text(self._extract_name(raw))
            if not name:
                continue
            results.append({"name": name, "source": source})
        return results, None

    async def _fallback_candidates(
        self, site_url: str, category: str, market: str, content: str | None = None
    ) -> list[dict[str, Any]]:
        route = resolve_competitor_discovery_route()
        return await self._ai_factory.generate_competitors(
            provider=route.provider,
            tier=route.execution_tier,
            site_url=site_url,
            category=category,
            market=market,
            content=content,
        )

    @staticmethod
    def _extract_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    values.append(name.strip())
        return values

    def _report_entities(self, full_report: dict[str, Any] | None) -> set[str]:
        if not isinstance(full_report, dict):
            return set()

        analysis = (
            full_report.get("analysis") if isinstance(full_report.get("analysis"), dict) else {}
        )
        entity_candidates = [
            full_report.get("entities"),
            analysis.get("entities"),
            analysis.get("entities_detected"),
        ]
        entities: set[str] = set()
        for candidate in entity_candidates:
            for entity in self._extract_text_list(candidate):
                entities.add(entity.lower())
        return entities

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @classmethod
    def _extract_report_from_audit_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        full_report = snapshot.get("full_report")
        if isinstance(full_report, dict):
            return full_report
        report = snapshot.get("report")
        if isinstance(report, dict):
            return report
        return snapshot

    def _snapshot_entities(self, snapshot: dict[str, Any]) -> set[str]:
        report = self._extract_report_from_audit_snapshot(snapshot)
        direct_entities = self._extract_text_list(snapshot.get("entities"))
        entities = {entity.lower() for entity in direct_entities}
        entities.update(self._report_entities(report))
        return entities

    def _entity_mentions_for_entities(
        self,
        snapshot: dict[str, Any],
        shared_entities: set[str],
    ) -> int:
        if not shared_entities:
            return 0

        report = self._extract_report_from_audit_snapshot(snapshot)
        mention_count = 0

        geo_visibility = report.get("geo_visibility") if isinstance(report, dict) else None
        results = geo_visibility.get("results") if isinstance(geo_visibility, dict) else None
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                query = str(item.get("query") or "").lower()
                if not query:
                    continue
                if any(entity in query for entity in shared_entities):
                    if bool(item.get("brand_cited")):
                        provider_citations = item.get("provider_citations")
                        if isinstance(provider_citations, list):
                            mention_count += max(1, len(provider_citations))
                        else:
                            mention_count += 1

        competitors = report.get("competitors") if isinstance(report, dict) else None
        if isinstance(competitors, list):
            for competitor in competitors:
                if not isinstance(competitor, dict):
                    continue
                citations = competitor.get("citations")
                if not isinstance(citations, list):
                    continue
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    citation_entities = {
                        entity.lower()
                        for entity in self._extract_text_list(citation.get("entities"))
                    }
                    if citation_entities & shared_entities:
                        mention_count += 1

        return mention_count

    def _recency_weight(self, created_at: datetime | None, now: datetime) -> float:
        if created_at is None:
            return 0.45
        age_days = max(0.0, (now - created_at).total_seconds() / 86400)
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.85
        if age_days <= 90:
            return 0.7
        return 0.5

    def _entity_graph_candidates_from_audit_history(
        self,
        *,
        site_url: str,
        full_report: dict[str, Any] | None,
        audit_snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(audit_snapshots, list) or not audit_snapshots:
            return []

        normalized_site = self._normalize_site_key(site_url)
        current_entities = self._report_entities(full_report)

        latest_target_snapshot: dict[str, Any] | None = None
        latest_target_created_at: datetime | None = None
        latest_by_competitor_site: dict[str, tuple[datetime | None, dict[str, Any]]] = {}

        for snapshot in audit_snapshots:
            if not isinstance(snapshot, dict):
                continue

            snapshot_site = self._normalize_site_key(
                str(snapshot.get("site") or snapshot.get("site_url") or "")
            )
            created_at = self._parse_datetime(snapshot.get("created_at"))
            is_target = bool(snapshot.get("is_target")) or (snapshot_site == normalized_site)

            if is_target:
                if latest_target_snapshot is None or (
                    created_at is not None
                    and (latest_target_created_at is None or created_at > latest_target_created_at)
                ):
                    latest_target_snapshot = snapshot
                    latest_target_created_at = created_at
                continue

            if not snapshot_site:
                continue
            previous = latest_by_competitor_site.get(snapshot_site)
            if previous is None or (
                created_at is not None and (previous[0] is None or created_at > previous[0])
            ):
                latest_by_competitor_site[snapshot_site] = (created_at, snapshot)

        target_entities = set(current_entities)
        if latest_target_snapshot is not None:
            target_entities.update(self._snapshot_entities(latest_target_snapshot))
        if not target_entities:
            return []

        discovered: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        target_entity_count = max(1, len(target_entities))

        for _, (created_at, snapshot) in latest_by_competitor_site.items():
            competitor_name = self._clean_text(
                str(snapshot.get("name") or snapshot.get("domain") or snapshot.get("site") or "")
            )
            if not competitor_name:
                continue

            competitor_entities = self._snapshot_entities(snapshot)
            shared_entities = competitor_entities & target_entities
            if not shared_entities:
                continue

            shared_mentions = self._entity_mentions_for_entities(snapshot, shared_entities)
            overlap_ratio = min(1.0, len(shared_entities) / target_entity_count)
            citation_ratio = min(1.0, shared_mentions / max(1, len(shared_entities) * 3))
            recency_ratio = self._recency_weight(created_at, now)

            entity_overlap_score = (
                (overlap_ratio * 0.5) + (citation_ratio * 0.3) + (recency_ratio * 0.2)
            )
            confidence = min(
                0.99,
                0.35 + (entity_overlap_score * 0.5) + (min(len(shared_entities), 5) * 0.04),
            )

            discovered.append(
                {
                    "name": competitor_name,
                    "source": "EntityGraph",
                    "shared_entities": sorted(shared_entities),
                    "entity_overlap_score": round(entity_overlap_score, 2),
                    "confidence_score": round(confidence, 2),
                }
            )

        discovered.sort(
            key=lambda item: (
                float(item.get("confidence_score") or 0.0),
                float(item.get("entity_overlap_score") or 0.0),
            ),
            reverse=True,
        )
        return discovered

    def _entity_graph_candidates(
        self,
        *,
        site_url: str,
        full_report: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(full_report, dict):
            return []

        site_key = self._normalize_site_key(site_url)
        target_entities = self._report_entities(full_report)
        if not target_entities:
            return []

        competitors = full_report.get("competitors")
        if not isinstance(competitors, list):
            return []

        discovered: list[dict[str, Any]] = []
        for item in competitors:
            if not isinstance(item, dict):
                continue
            raw_name = self._extract_name(item)
            name = self._clean_text(raw_name)
            if not name or site_key in name.lower():
                continue

            competitor_entities = {
                entity.lower() for entity in self._extract_text_list(item.get("entities"))
            }
            citations = item.get("citations")
            shared_citation_count = 0
            if isinstance(citations, list):
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    citation_entities = {
                        entity.lower()
                        for entity in self._extract_text_list(citation.get("entities"))
                    }
                    if citation_entities & target_entities:
                        shared_citation_count += 1

            shared_entities = sorted({entity for entity in competitor_entities & target_entities})
            shared_entity_count = len(shared_entities)
            if shared_entity_count == 0 and shared_citation_count == 0:
                continue

            entity_overlap_score = min(
                1.0,
                (shared_entity_count * 0.2) + (shared_citation_count * 0.1),
            )
            confidence = min(
                0.98,
                0.45 + (entity_overlap_score * 0.45) + (min(shared_citation_count, 5) * 0.05),
            )

            discovered.append(
                {
                    "name": name,
                    "source": "EntityGraph",
                    "shared_entities": shared_entities,
                    "entity_overlap_score": round(entity_overlap_score, 2),
                    "confidence_score": round(confidence, 2),
                }
            )

        discovered.sort(
            key=lambda item: (
                float(item.get("entity_overlap_score") or 0.0),
                float(item.get("confidence_score") or 0.0),
            ),
            reverse=True,
        )
        return discovered

    @staticmethod
    def _with_confidence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        places_rank = 0
        serp_rank = 0

        for candidate in candidates:
            source = candidate["source"]
            if candidate.get("confidence_score") is not None:
                scored.append(
                    {
                        "name": candidate["name"],
                        "source": source,
                        "shared_entities": candidate.get("shared_entities", []),
                        "entity_overlap_score": round(
                            float(candidate.get("entity_overlap_score") or 0.0), 2
                        ),
                        "confidence_score": round(
                            float(candidate.get("confidence_score") or 0.0), 2
                        ),
                    }
                )
                continue

            if source == "Places":
                confidence = max(0.55, 0.84 - (places_rank * 0.06))
                places_rank += 1
            else:
                confidence = max(0.55, 0.78 - (serp_rank * 0.06))
                serp_rank += 1

            scored.append(
                {
                    "name": candidate["name"],
                    "source": source,
                    "shared_entities": candidate.get("shared_entities", []),
                    "entity_overlap_score": round(
                        float(candidate.get("entity_overlap_score") or 0.0), 2
                    ),
                    "confidence_score": round(confidence, 2),
                }
            )

        return scored

    @staticmethod
    def _dedupe(candidates: list[dict[str, Any]], site_key: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []

        for candidate in candidates:
            name = candidate["name"].strip()
            key = name.lower()
            if not name or key in seen or site_key in key:
                continue
            seen.add(key)
            deduped.append(candidate)

        return deduped

    async def discover_competitors(
        self,
        site_url: str,
        category: str,
        market: str,
        full_report: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        normalized_site = self._normalize_site_key(site_url)
        normalized_category = self._clean_text(category)
        normalized_market = self._clean_text(market)

        if not normalized_site:
            raise ValueError("site_url is required")
        if not normalized_category:
            raise ValueError("category is required")
        if not normalized_market:
            raise ValueError("market is required")

        cache_allowed = full_report is None
        if cache_allowed and normalized_site in self._cache:
            return {
                "site": normalized_site,
                "category": normalized_category,
                "market": normalized_market,
                "cached": True,
                "competitors": self._cache[normalized_site],
            }

        provider_status: dict[str, str] = {
            "places": "disabled" if self._places_provider is None else "ok",
            "serp": "disabled" if self._serp_provider is None else "ok",
            "entity_audit": "disabled" if self._entity_audit_provider is None else "ok",
        }
        provider_errors: dict[str, str] = {}

        entity_candidates = self._entity_graph_candidates(
            site_url=site_url, full_report=full_report
        )

        if self._entity_audit_provider is not None:
            try:
                audit_snapshots = await self._entity_audit_provider(normalized_site)
                history_candidates = self._entity_graph_candidates_from_audit_history(
                    site_url=site_url,
                    full_report=full_report,
                    audit_snapshots=audit_snapshots,
                )
                entity_candidates.extend(history_candidates)
            except Exception as exc:  # noqa: BLE001
                provider_status["entity_audit"] = "degraded"
                provider_errors["entity_audit"] = redact_secrets(exc)

        if entity_candidates:
            entity_candidates = self._dedupe(entity_candidates, normalized_site)
            entity_candidates.sort(
                key=lambda item: (
                    float(item.get("confidence_score") or 0.0),
                    float(item.get("entity_overlap_score") or 0.0),
                ),
                reverse=True,
            )

        provider_candidates: list[dict[str, Any]] = []
        entity_signal_strong = len(entity_candidates) >= 2 and any(
            float(item.get("confidence_score") or 0.0) >= 0.6 for item in entity_candidates
        )
        if not entity_signal_strong:
            places_candidates, places_error = await self._provider_candidates(
                self._places_provider,
                "Places",
                site_url,
                normalized_category,
                normalized_market,
            )
            if places_error:
                provider_status["places"] = "degraded"
                provider_errors["places"] = places_error
            provider_candidates.extend(places_candidates)

            serp_candidates, serp_error = await self._provider_candidates(
                self._serp_provider,
                "SERP",
                site_url,
                normalized_category,
                normalized_market,
            )
            if serp_error:
                provider_status["serp"] = "degraded"
                provider_errors["serp"] = serp_error
            provider_candidates.extend(serp_candidates)

        rejected_provider_candidates = 0
        sanitized_provider_candidates: list[dict[str, Any]] = []
        for candidate in provider_candidates:
            name = self._clean_text(str(candidate.get("name") or ""))
            if self._looks_like_editorial_title(name):
                rejected_provider_candidates += 1
                continue
            sanitized_provider_candidates.append({**candidate, "name": name})
        provider_candidates = sanitized_provider_candidates

        providers_enabled = (
            provider_status["places"] != "disabled" or provider_status["serp"] != "disabled"
        )
        provider_health = "ok"
        if not providers_enabled:
            provider_health = "disabled"
        elif any(status == "degraded" for status in provider_status.values()):
            provider_health = "degraded"

        all_candidates = list(entity_candidates)
        all_candidates.extend(provider_candidates)
        should_run_textual_fallback = self._enable_textual_fallback or (
            providers_enabled
            and not entity_signal_strong
            and (rejected_provider_candidates > 0 or len(provider_candidates) == 0)
        )
        if should_run_textual_fallback:
            fallback_res = await self._fallback_candidates(
                site_url, normalized_category, normalized_market, content=content
            )
            all_candidates.extend(fallback_res)

        # SIGV2-1285: every candidate is screened, whichever source produced it.
        #
        # The screen used to apply only where `source` was "Places" or "SERP",
        # so the entity extractor and the textual fallback were exempt, and
        # that is where Edward's article headlines came from. A name that is
        # prose is prose regardless of which code path found it, and the names
        # arrive here carrying a confidence score, so an unscreened one is the
        # product asserting a competitor it has no reason to believe in.
        screened_candidates: list[Any] = []
        for candidate in all_candidates:
            if self._looks_like_editorial_title(self._extract_name(candidate)):
                continue
            screened_candidates.append(candidate)

        deduped = self._dedupe(screened_candidates, normalized_site)
        limited = deduped[:5]

        competitors = self._with_confidence(limited)
        if cache_allowed:
            self._cache[normalized_site] = competitors

        return {
            "site": normalized_site,
            "category": normalized_category,
            "market": normalized_market,
            "cached": False,
            "provider_status": provider_status,
            "provider_errors": provider_errors,
            "provider_health": provider_health,
            "competitors": competitors,
        }
