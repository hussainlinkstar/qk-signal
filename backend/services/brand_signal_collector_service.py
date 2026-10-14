"""Brand Signal Collector Service.

Collects external signals for brand audits to provide real grounding data
instead of relying purely on AI opinion.  Signal sources:

1. **SERP Brand Search**, branded search results via SerpAPI/Firecrawl
2. **AI Visibility Probe**, asks AI search engines about the brand
3. **Wikidata Entity Lookup**, structured entity data (free, no API key)
4. **Knowledge Graph signals**, extracted from SERP knowledge panel data

All signals are collected concurrently and returned as a unified payload
that feeds into the deterministic scoring engine and AI context.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from core.config import settings
from services.observability import describe_http_failure
from services.serpapi_params import build_serpapi_geo_params

logger = logging.getLogger(__name__)

WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_TIMEOUT = float(os.getenv("WIKIDATA_TIMEOUT_SECONDS", "10"))
SERP_BRAND_MAX_RESULTS = int(os.getenv("SERP_BRAND_MAX_RESULTS", "10"))
BRAND_SIGNAL_TOTAL_TIMEOUT = float(os.getenv("BRAND_SIGNAL_TOTAL_TIMEOUT", "30"))


class BrandSignalCollectorService:
    """Collect external signals for a brand entity."""

    def __init__(self) -> None:
        self.serpapi_key = str(settings.SERPAPI_API_KEY or "").strip()
        self.serpapi_endpoint = os.getenv("SERPAPI_URL", "https://serpapi.com/search.json").strip()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    async def collect_brand_signals(
        self,
        *,
        brand_name: str,
        category: str | None = None,
        market: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Collect all available brand signals concurrently.

        Returns a unified payload with keys:
        - ``serp``: branded SERP results
        - ``wikidata``: Wikidata entity data
        - ``knowledge_graph``: KG panel data from SERP
        - ``ai_visibility``: AI search engine visibility
        - ``summary``: high-level brand presence summary
        """
        brand = brand_name.strip()
        if not brand:
            return self._empty_result()

        resolved_market = (market or "global").strip()
        resolved_category = (category or "").strip()

        tasks: dict[str, Any] = {}
        tasks["serp"] = self._collect_serp_signals(
            brand,
            category=resolved_category,
            market=resolved_market,
            domain=domain,
        )
        tasks["wikidata"] = self._collect_wikidata_signals(brand)
        tasks["ai_visibility"] = self._collect_ai_visibility_signals(
            brand,
            category=resolved_category,
            market=resolved_market,
        )

        results: dict[str, Any] = {}
        try:
            async with asyncio.timeout(BRAND_SIGNAL_TOTAL_TIMEOUT):
                gathered = await asyncio.gather(
                    *tasks.values(),
                    return_exceptions=True,
                )
                for key, result in zip(tasks.keys(), gathered):
                    if isinstance(result, Exception):
                        logger.warning("Brand signal %s failed: %s", key, result)
                        results[key] = {"status": "error", "error": str(result)}
                    else:
                        results[key] = result
        except TimeoutError:
            logger.warning("Brand signal collection timed out for %s", brand)
            for key in tasks:
                if key not in results:
                    results[key] = {"status": "timeout"}

        # Extract KG from SERP results
        serp_data = results.get("serp", {})
        results["knowledge_graph"] = self._extract_knowledge_graph(serp_data)

        # Build summary
        results["summary"] = self._build_brand_summary(brand, results)
        results["brand_name"] = brand
        results["market"] = resolved_market
        results["category"] = resolved_category

        return results

    def _empty_result(self) -> dict[str, Any]:
        return {
            "serp": {"status": "skipped"},
            "wikidata": {"status": "skipped"},
            "knowledge_graph": {"status": "skipped"},
            "ai_visibility": {"status": "skipped"},
            "summary": {"brand_presence_score": 0, "signals_collected": 0},
        }

    # ------------------------------------------------------------------ #
    #  SERP Brand Search (SerpAPI)
    # ------------------------------------------------------------------ #

    async def _collect_serp_signals(
        self,
        brand: str,
        *,
        category: str,
        market: str,
        domain: str | None,
    ) -> dict[str, Any]:
        """Query SerpAPI for branded search results."""
        if not self.serpapi_key:
            return {"status": "disabled", "reason": "SERPAPI_API_KEY not configured"}

        queries = [
            brand,
            f"{brand} reviews",
        ]
        if category:
            queries.append(f"{brand} {category}")

        all_results: list[dict[str, Any]] = []
        knowledge_panel: dict[str, Any] | None = None
        brand_domain_found = False
        brand_mentioned_count = 0
        total_organic = 0

        from services.url_validation import safe_async_fetch

        for query in queries[:3]:
            try:
                params = {
                    "q": query,
                    "api_key": self.serpapi_key,
                    "engine": "google",
                    "num": str(SERP_BRAND_MAX_RESULTS),
                }
                # SerpAPI takes a country in ``gl`` (two-letter code) and only
                # a canonical place name in ``location``. Truncating an
                # arbitrary market to two characters produced junk country
                # codes, and a bare country code in ``location`` is rejected
                # with HTTP 400. See services/serpapi_params.py.
                params.update(build_serpapi_geo_params(market))

                response = await safe_async_fetch(
                    self.serpapi_endpoint,
                    method="GET",
                    timeout=15.0,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                # Extract organic results
                organic = data.get("organic_results", [])
                for item in organic:
                    if not isinstance(item, dict):
                        continue
                    total_organic += 1
                    title = str(item.get("title") or "")
                    link = str(item.get("link") or "")
                    snippet = str(item.get("snippet") or "")

                    # Check if brand's own domain appears
                    if domain and domain.lower() in link.lower():
                        brand_domain_found = True

                    # Check brand mentions
                    combined = f"{title} {snippet}".lower()
                    if brand.lower() in combined:
                        brand_mentioned_count += 1

                    all_results.append(
                        {
                            "title": title[:200],
                            "link": link,
                            "snippet": snippet[:300],
                            "position": item.get("position"),
                            "query": query,
                        }
                    )

                # Extract knowledge graph panel
                kg = data.get("knowledge_graph")
                if isinstance(kg, dict) and not knowledge_panel:
                    knowledge_panel = kg

            except Exception as exc:
                safe_detail = describe_http_failure(self.serpapi_endpoint, exc)
                logger.warning("SERP query failed for '%s': %s", query, safe_detail)

        mention_rate = (brand_mentioned_count / total_organic * 100) if total_organic else 0

        return {
            "status": "ok",
            "queries_executed": len(queries[:3]),
            "total_results": len(all_results),
            "brand_domain_found": brand_domain_found,
            "brand_mention_rate": round(mention_rate, 1),
            "knowledge_panel": knowledge_panel,
            "top_results": all_results[:15],
        }

    # ------------------------------------------------------------------ #
    #  Wikidata Entity Lookup
    # ------------------------------------------------------------------ #

    async def _collect_wikidata_signals(self, brand: str) -> dict[str, Any]:
        """Search Wikidata for the brand entity and extract key properties."""
        try:
            async with httpx.AsyncClient(timeout=WIKIDATA_TIMEOUT) as client:
                # Step 1: Search for the entity
                search_resp = await client.get(
                    WIKIDATA_SEARCH_URL,
                    params={
                        "action": "wbsearchentities",
                        "search": brand,
                        "language": "en",
                        "limit": "5",
                        "format": "json",
                    },
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

                results = search_data.get("search", [])
                if not results:
                    return {"status": "not_found", "entity_exists": False}

                # Find best match
                best_match = results[0]
                entity_id = best_match.get("id", "")
                entity_label = best_match.get("label", "")
                entity_description = best_match.get("description", "")

                # Step 2: Fetch entity details
                entity_data = await self._fetch_wikidata_entity(client, entity_id)

                return {
                    "status": "ok",
                    "entity_exists": True,
                    "entity_id": entity_id,
                    "label": entity_label,
                    "description": entity_description,
                    "wikidata_url": f"https://www.wikidata.org/wiki/{entity_id}",
                    "properties": entity_data.get("properties", {}),
                    "sitelinks_count": entity_data.get("sitelinks_count", 0),
                    "has_wikipedia": entity_data.get("has_wikipedia", False),
                    "instance_of": entity_data.get("instance_of", []),
                }

        except Exception as exc:
            logger.warning("Wikidata lookup failed for '%s': %s", brand, exc)
            return {"status": "error", "error": str(exc), "entity_exists": False}

    async def _fetch_wikidata_entity(
        self, client: httpx.AsyncClient, entity_id: str
    ) -> dict[str, Any]:
        """Fetch detailed entity data from Wikidata."""
        try:
            resp = await client.get(
                WIKIDATA_SEARCH_URL,
                params={
                    "action": "wbgetentities",
                    "ids": entity_id,
                    "languages": "en",
                    "props": "labels|descriptions|claims|sitelinks",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            entity = data.get("entities", {}).get(entity_id, {})
            claims = entity.get("claims", {})
            sitelinks = entity.get("sitelinks", {})

            # Extract key properties
            properties: dict[str, Any] = {}

            # P31 = instance of (company, organization, software, etc.)
            instance_of: list[str] = []
            for claim in claims.get("P31", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                if isinstance(value, dict) and value.get("id"):
                    instance_of.append(value["id"])

            # P856 = official website
            for claim in claims.get("P856", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                if datavalue.get("value"):
                    properties["official_website"] = datavalue["value"]

            # P571 = inception date
            for claim in claims.get("P571", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                if isinstance(value, dict) and value.get("time"):
                    properties["inception"] = value["time"]

            # P17 = country
            for claim in claims.get("P17", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                if isinstance(value, dict) and value.get("id"):
                    properties["country_entity"] = value["id"]

            # P159 = headquarters location
            for claim in claims.get("P159", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                if isinstance(value, dict) and value.get("id"):
                    properties["headquarters_entity"] = value["id"]

            # P452 = industry
            for claim in claims.get("P452", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                if isinstance(value, dict) and value.get("id"):
                    properties.setdefault("industry_entities", []).append(value["id"])

            properties["total_claims"] = len(claims)

            return {
                "properties": properties,
                "sitelinks_count": len(sitelinks),
                "has_wikipedia": "enwiki" in sitelinks,
                "instance_of": instance_of,
            }

        except Exception as exc:
            logger.warning("Wikidata entity fetch failed for %s: %s", entity_id, exc)
            return {
                "properties": {},
                "sitelinks_count": 0,
                "has_wikipedia": False,
                "instance_of": [],
            }

    # ------------------------------------------------------------------ #
    #  AI Visibility Probe
    # ------------------------------------------------------------------ #

    async def _collect_ai_visibility_signals(
        self,
        brand: str,
        *,
        category: str,
        market: str,
    ) -> dict[str, Any]:
        """Probe AI search visibility using the existing GeoVisibilityService."""
        try:
            from services.geo_visibility_service import GeoVisibilityService

            visibility_service = GeoVisibilityService()
            queries = [
                f"What is {brand}?",
                f"Best {category} companies" if category else f"Companies like {brand}",
                f"Is {brand} a good choice for {category}?"
                if category
                else f"Tell me about {brand}",
            ]

            location = market if market != "global" else ""
            result = await visibility_service.run_visibility_audit(
                target=brand,
                location=location,
                seed_queries=queries,
                brand=brand,
            )

            # A provider that refused every query measured nothing, so this is
            # reported as a failure rather than as a zero-visibility brand.
            measured = bool(result.get("visibility_measured", True))
            return {
                "status": "ok" if measured else "provider_error",
                "visibility_index": result.get("visibility_index", 0),
                "visibility_measured": measured,
                "total_queries": result.get("total_queries", 0),
                "answered_queries": result.get("answered_queries", 0),
                "citations": result.get("citations", 0),
                "partial_results": result.get("partial_results", False),
                "provider_rejected_queries": result.get("provider_rejected_queries", 0),
                "provider_error": result.get("provider_error"),
                "query_results": [
                    {
                        "query": r.get("query"),
                        "brand_cited": r.get("brand_cited", False),
                        "status": r.get("status"),
                    }
                    for r in result.get("results", [])
                ],
            }

        except Exception as exc:
            logger.warning("AI visibility probe failed for '%s': %s", brand, exc)
            return {"status": "error", "error": str(exc), "visibility_index": 0}

    # ------------------------------------------------------------------ #
    #  Knowledge Graph Extraction (from SERP data)
    # ------------------------------------------------------------------ #

    def _extract_knowledge_graph(self, serp_data: dict[str, Any]) -> dict[str, Any]:
        """Extract structured KG data from SERP knowledge panel."""
        panel = serp_data.get("knowledge_panel")
        if not isinstance(panel, dict):
            return {"status": "not_found", "has_knowledge_panel": False}

        return {
            "status": "ok",
            "has_knowledge_panel": True,
            "title": panel.get("title"),
            "type": panel.get("type"),
            "description": str(panel.get("description") or "")[:500],
            "website": panel.get("website"),
            "thumbnail": panel.get("thumbnail"),
            "attributes": {
                k: v
                for k, v in panel.items()
                if k
                not in {
                    "title",
                    "type",
                    "description",
                    "website",
                    "thumbnail",
                    "images",
                    "people_also_search_for",
                    "see_results_about",
                }
                and isinstance(v, (str, int, float, bool))
            },
        }

    # ------------------------------------------------------------------ #
    #  Summary Builder
    # ------------------------------------------------------------------ #

    def _build_brand_summary(
        self,
        brand: str,
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a high-level brand presence summary from all collected signals."""
        score_components: dict[str, float] = {}
        signals_collected = 0

        # SERP presence (0-30 points)
        serp = signals.get("serp", {})
        if serp.get("status") == "ok":
            signals_collected += 1
            serp_score = 0.0
            if serp.get("brand_domain_found"):
                serp_score += 15.0
            mention_rate = serp.get("brand_mention_rate", 0)
            serp_score += min(15.0, mention_rate * 0.3)
            score_components["serp_presence"] = round(min(30.0, serp_score), 1)

        # Knowledge Graph (0-25 points)
        kg = signals.get("knowledge_graph", {})
        if kg.get("has_knowledge_panel"):
            signals_collected += 1
            kg_score = 15.0
            if kg.get("description"):
                kg_score += 5.0
            if kg.get("website"):
                kg_score += 5.0
            score_components["knowledge_graph"] = round(min(25.0, kg_score), 1)
        elif kg.get("status") != "error":
            score_components["knowledge_graph"] = 0.0

        # Wikidata (0-25 points)
        wiki = signals.get("wikidata", {})
        if wiki.get("entity_exists"):
            signals_collected += 1
            wiki_score = 10.0
            if wiki.get("has_wikipedia"):
                wiki_score += 10.0
            sitelinks = wiki.get("sitelinks_count", 0)
            wiki_score += min(5.0, sitelinks * 0.5)
            score_components["wikidata_presence"] = round(min(25.0, wiki_score), 1)
        elif wiki.get("status") != "error":
            score_components["wikidata_presence"] = 0.0

        # AI Visibility (0-20 points)
        ai_vis = signals.get("ai_visibility", {})
        if ai_vis.get("status") == "ok":
            signals_collected += 1
            visibility_index = ai_vis.get("visibility_index", 0)
            ai_score = visibility_index * 0.2
            score_components["ai_visibility"] = round(min(20.0, ai_score), 1)

        total_score = sum(score_components.values())

        return {
            "brand_presence_score": round(min(100.0, total_score), 1),
            "score_components": score_components,
            "signals_collected": signals_collected,
            "confidence": (
                "high" if signals_collected >= 3 else "medium" if signals_collected >= 2 else "low"
            ),
        }
