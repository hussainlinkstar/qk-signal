import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from firecrawl import AsyncFirecrawlApp
from core.config import settings

from services.observability import describe_http_failure, redact_secrets
from services.serpapi_params import build_serpapi_geo_params
from services.service_health import record_service_outcome

logger = logging.getLogger(__name__)


class ProviderTimeoutError(Exception):
    pass


class ProviderResponseError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        # HTTP status of the upstream response, when the failure was an HTTP
        # error. A 4xx means the provider rejected our request outright, which
        # must never be reported as a measured zero-visibility result.
        self.status_code = status_code


@dataclass
class SearchProviderResult:
    query: str
    answer: str
    citations: list[str]


class GeoVisibilityService:
    def __init__(self):
        self.provider = os.getenv("GEO_VISIBILITY_PROVIDER", "firecrawl").strip().lower()
        self.request_timeout = float(os.getenv("GEO_VISIBILITY_TIMEOUT_SECONDS", "20"))
        self.max_queries = int(os.getenv("GEO_VISIBILITY_MAX_QUERIES", "10"))
        firecrawl_key = settings.FIRECRAWL_API_KEY
        self.firecrawl_app = AsyncFirecrawlApp(api_key=firecrawl_key) if firecrawl_key else None
        self.search_api_url = os.getenv("SEARCH_API_URL", "").strip()
        self.search_api_key = str(settings.SEARCH_API_KEY or "").strip()
        self.serpapi_key = str(settings.SERPAPI_API_KEY or "").strip()
        self.serpapi_engine = str(settings.SERPAPI_ENGINE or "google").strip() or "google"
        self.serpapi_endpoint = os.getenv("SERPAPI_URL", "https://serpapi.com/search.json").strip()

    def _resolve_generic_search_config(
        self, location: str
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        if self.search_api_url:
            headers = {"Accept": "application/json"}
            if self.search_api_key:
                headers["Authorization"] = f"Bearer {self.search_api_key}"
            # A self-hosted search endpoint has its own contract, so the raw
            # location string is passed through unchanged.
            passthrough = {"location": location} if location else {}
            return self.search_api_url, headers, passthrough

        if self.serpapi_key:
            headers = {"Accept": "application/json"}
            params = {
                "api_key": self.serpapi_key,
                "engine": self.serpapi_engine,
            }
            # SerpAPI rejects an ISO country code in ``location`` with HTTP 400,
            # so a country travels in ``gl`` and only a place name is sent as
            # ``location``. See services/serpapi_params.py.
            params.update(build_serpapi_geo_params(location, allow_location=True))
            return self.serpapi_endpoint, headers, params

        raise ProviderResponseError(
            "SEARCH_API_URL or SERPAPI_API_KEY is required for generic search provider."
        )

    @staticmethod
    def _extract_generic_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_results = (
            payload.get("results") or payload.get("items") or payload.get("organic_results") or []
        )
        return [item for item in raw_results if isinstance(item, dict)]

    def normalize_target(self, target: str) -> tuple[str, str]:
        value = target.strip().lower()
        if not value:
            raise ValueError("URL or domain is required.")

        parsed = urlparse(
            value if value.startswith(("http://", "https://")) else f"https://{value}"
        )
        domain = parsed.netloc or parsed.path
        domain = domain.lower().removeprefix("www.")
        if not domain:
            raise ValueError("A valid URL or domain is required.")
        return value, domain

    def default_seed_queries(self, domain: str, location: str) -> list[str]:
        return [
            f"best alternatives to {domain} in {location}",
            f"top providers like {domain} near {location}",
            f"recommended {domain} options for {location}",
            f"trusted companies in {location} for services like {domain}",
            f"who are the leading brands competing with {domain} in {location}",
        ]

    async def _run_firecrawl_search(self, query: str, location: str) -> SearchProviderResult:
        if not self.firecrawl_app:
            raise ProviderResponseError(
                "FIRECRAWL_API_KEY is required when GEO_VISIBILITY_PROVIDER=firecrawl."
            )

        try:
            payload = await self.firecrawl_app.search(
                query=f"{query} {location}" if location else query,
                limit=5,
            )
        except TimeoutError as exc:
            await record_service_outcome("firecrawl", ok=False, detail=str(exc))
            raise ProviderTimeoutError(str(exc)) from exc
        except Exception as exc:
            await record_service_outcome("firecrawl", ok=False, detail=str(exc))
            if "timeout" in str(exc).lower():
                raise ProviderTimeoutError(str(exc)) from exc
            raise ProviderResponseError(str(exc)) from exc

        await record_service_outcome("firecrawl", ok=True)
        results = self._extract_firecrawl_results(payload)

        citations: list[str] = []
        answer_parts: list[str] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("source") or ""
            title = item.get("title") or ""
            snippet = item.get("description") or item.get("markdown") or item.get("content") or ""
            if url:
                citations.append(url)
            combined = " ".join(part for part in [title, snippet, url] if part)
            if combined:
                answer_parts.append(combined)

        answer = "\n".join(answer_parts).strip()
        return SearchProviderResult(query=query, answer=answer, citations=citations)

    @staticmethod
    def _extract_firecrawl_results(payload: Any) -> list[dict[str, Any]]:
        # firecrawl-py 4.x ``search()`` returns a SearchData model whose
        # ``model_dump()`` groups hits as ``web``/``news``/``images`` lists -
        # there is no flat ``data``/``results`` key, and reading only those
        # silently produced zero citations on every query. Raw dict responses
        # (legacy shapes, ``{"data": {"web": [...]}}`` wrappers) are kept for
        # compatibility.
        data = payload if isinstance(payload, dict) else payload.model_dump()
        results: list[dict[str, Any]] = []

        def collect(items: Any) -> None:
            if isinstance(items, list):
                results.extend(item for item in items if isinstance(item, dict))

        inner = data.get("data") or data.get("results")
        if isinstance(inner, dict):
            for group in ("web", "news", "images"):
                collect(inner.get(group))
        else:
            collect(inner)
        for group in ("web", "news", "images"):
            collect(data.get(group))
        return results

    async def _run_generic_search_api(self, query: str, location: str) -> SearchProviderResult:
        search_url, headers, fixed_params = self._resolve_generic_search_config(location)
        params: dict[str, str] = {"q": query}
        params.update(fixed_params)

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.get(
                    search_url,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            # Never surface str(exc): httpx renders the full request URL, and the SerpAPI
            # credential travels in the query string as api_key=...
            raise ProviderTimeoutError(describe_http_failure(search_url, exc)) from exc
        except httpx.HTTPStatusError as exc:
            # Carry the status code so the caller can tell "the provider
            # refused the request" apart from "the brand is not cited".
            raise ProviderResponseError(
                describe_http_failure(search_url, exc),
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(describe_http_failure(search_url, exc)) from exc

        results = self._extract_generic_results(payload)
        citations: list[str] = []
        answer_parts: list[str] = []
        for item in results:
            url = item.get("url") or item.get("link") or ""
            title = item.get("title") or ""
            snippet = item.get("snippet") or item.get("description") or ""
            if url:
                citations.append(url)
            combined = " ".join(part for part in [title, snippet, url] if part)
            if combined:
                answer_parts.append(combined)

        answer = "\n".join(answer_parts).strip()
        return SearchProviderResult(query=query, answer=answer, citations=citations)

    async def execute_query(self, query: str, location: str) -> SearchProviderResult:
        provider = self.provider
        if provider == "firecrawl":
            return await self._run_firecrawl_search(query=query, location=location)
        if provider in {"search_api", "search-api", "generic"}:
            return await self._run_generic_search_api(query=query, location=location)
        raise ProviderResponseError(f"Unsupported GEO_VISIBILITY_PROVIDER: {provider}")

    def _contains_target(
        self, text: str, citations: list[str], domain: str, brand: str | None
    ) -> bool:
        haystack = f"{text}\n" + "\n".join(citations)
        haystack = haystack.lower()
        if domain and domain in haystack:
            return True
        if brand and brand.strip().lower() in haystack:
            return True
        return False

    async def run_visibility_audit(
        self,
        *,
        target: str,
        location: str,
        seed_queries: list[str] | None = None,
        brand: str | None = None,
    ) -> dict[str, Any]:
        target_value, domain = self.normalize_target(target)
        queries = (seed_queries or self.default_seed_queries(domain=domain, location=location))[
            : self.max_queries
        ]

        query_results: list[dict[str, Any]] = []
        citations_total = 0
        processed_queries = 0
        answered_queries = 0
        timed_out_queries = 0
        failed_queries = 0
        provider_rejected_queries = 0
        provider_error: str | None = None

        for query in queries:
            processed_queries += 1
            try:
                result = await self.execute_query(query=query, location=location)
                if not result.answer.strip() and not result.citations:
                    # A probe that returned no answer text and no citations
                    # measured nothing: an empty search response is a
                    # provider-side failure, not evidence the brand is
                    # invisible. It counts against the provider, not the
                    # brand, so it is excluded from the answered denominator
                    # like a rejection.
                    provider_rejected_queries += 1
                    query_results.append(
                        {
                            "query": query,
                            "answer_excerpt": "",
                            "provider_citations": [],
                            "brand_cited": False,
                            "status": "empty",
                            "error": "provider returned no results",
                            "provider_status_code": None,
                        }
                    )
                    continue
                answered_queries += 1
                cited = self._contains_target(
                    result.answer, result.citations, domain=domain, brand=brand
                )
                citations_total += 1 if cited else 0
                query_results.append(
                    {
                        "query": query,
                        "answer_excerpt": result.answer[:1000],
                        "provider_citations": result.citations,
                        "brand_cited": cited,
                        "status": "ok",
                        "error": None,
                        "provider_status_code": None,
                    }
                )
            except ProviderTimeoutError as exc:
                timed_out_queries += 1
                query_results.append(
                    {
                        "query": query,
                        "answer_excerpt": "",
                        "provider_citations": [],
                        "brand_cited": False,
                        "status": "timeout",
                        "error": redact_secrets(exc),
                        "provider_status_code": None,
                    }
                )
            except Exception as exc:
                failed_queries += 1
                safe_error = redact_secrets(exc)
                status_code = getattr(exc, "status_code", None)
                if isinstance(status_code, int) and 400 <= status_code < 500:
                    # The provider refused the request itself (bad parameter,
                    # rejected key, exhausted quota). No search ran, so this is
                    # not evidence of anything about the brand's visibility.
                    provider_rejected_queries += 1
                if provider_error is None:
                    provider_error = safe_error
                logger.warning("GEO visibility query failed for '%s': %s", query, safe_error)
                query_results.append(
                    {
                        "query": query,
                        "answer_excerpt": "",
                        "provider_citations": [],
                        "brand_cited": False,
                        "status": "error",
                        "error": safe_error,
                        "provider_status_code": status_code
                        if isinstance(status_code, int)
                        else None,
                    }
                )

        # The index is a share of the queries the provider actually answered.
        # Dividing by the attempted count would let provider failures masquerade
        # as measured low visibility.
        visibility_index = (citations_total / answered_queries) * 100 if answered_queries else 0.0
        return {
            "target": target_value,
            "location": location,
            "provider": self.provider,
            "seed_queries": queries,
            "total_queries": processed_queries,
            "answered_queries": answered_queries,
            "citations": citations_total,
            "timed_out_queries": timed_out_queries,
            "failed_queries": failed_queries,
            "provider_rejected_queries": provider_rejected_queries,
            "provider_error": provider_error,
            # False means nothing was measured, so visibility_index carries no
            # information: a 0.0 here is a provider outage, not a clean zero.
            "visibility_measured": answered_queries > 0,
            "visibility_index": round(visibility_index, 2),
            "partial_results": timed_out_queries > 0
            or failed_queries > 0
            or any(r["status"] != "ok" for r in query_results),
            "results": query_results,
        }
