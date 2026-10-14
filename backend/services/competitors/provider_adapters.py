from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from core.config import settings
from services.competitors.discovery_service import CompetitorDiscoveryService, ProviderCallable
from services.serpapi_params import build_serpapi_geo_params


def _normalize_site(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    host = (parsed.netloc or parsed.path).strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _resolve_google_places_api_key() -> str:
    return (
        str(settings.GOOGLE_PLACES_API_KEY or "").strip()
        or str(settings.GOOGLE_MAPS_API_KEY or "").strip()
        or str(settings.GOOGLE_API_KEY or "").strip()
        or str(settings.GEMINI_API_KEY or "").strip()
    )


async def serpapi_provider(site_url: str, category: str, market: str) -> list[dict[str, Any]]:
    api_key = str(settings.SERPAPI_API_KEY or "").strip()
    if not api_key:
        return []

    endpoint = str(
        getattr(settings, "SERPAPI_URL", "https://serpapi.com/search.json")
        or "https://serpapi.com/search.json"
    ).strip()
    engine = str(settings.SERPAPI_ENGINE or "google").strip() or "google"
    timeout = float(os.getenv("COMPETITOR_PROVIDER_TIMEOUT_SECONDS", "8"))
    site_host = _normalize_site(site_url)
    query = f"best {category} in {market} -site:{site_host}".strip()

    params = {
        "api_key": api_key,
        "engine": engine,
        "q": query,
        "num": os.getenv("COMPETITOR_SERP_RESULTS", "5"),
    }
    # A market such as "us" is a country, and SerpAPI takes a country in ``gl``.
    # It would be rejected with HTTP 400 in ``location``, which only accepts a
    # canonical place name, so a non-country market stays in the query text.
    params.update(build_serpapi_geo_params(market))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(endpoint, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()

    organic_results = payload.get("organic_results") if isinstance(payload, dict) else []
    if not isinstance(organic_results, list):
        return []

    candidates: list[dict[str, Any]] = []
    for item in organic_results:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            candidates.append({"name": title.strip()})
    return candidates


async def _google_places_legacy_provider(
    *,
    api_key: str,
    category: str,
    market: str,
) -> list[dict[str, Any]]:
    endpoint = os.getenv(
        "GOOGLE_PLACES_TEXTSEARCH_URL",
        "https://maps.googleapis.com/maps/api/place/textsearch/json",
    ).strip()
    timeout = float(os.getenv("COMPETITOR_PROVIDER_TIMEOUT_SECONDS", "8"))

    query = f"{category} near {market}".strip()
    params = {
        "query": query,
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(endpoint, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()

    results = payload.get("results") if isinstance(payload, dict) else []
    if not isinstance(results, list):
        return []

    candidates: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            candidates.append({"name": name.strip()})
    return candidates


async def _google_places_new_provider(
    *,
    api_key: str,
    category: str,
    market: str,
) -> list[dict[str, Any]]:
    endpoint = os.getenv(
        "GOOGLE_PLACES_NEW_TEXTSEARCH_URL",
        "https://places.googleapis.com/v1/places:searchText",
    ).strip()
    timeout = float(os.getenv("COMPETITOR_PROVIDER_TIMEOUT_SECONDS", "8"))
    max_results = int(os.getenv("COMPETITOR_PLACES_RESULTS", "5"))
    field_mask = os.getenv(
        "GOOGLE_PLACES_NEW_FIELD_MASK",
        "places.displayName,places.name",
    ).strip()

    payload = {
        "textQuery": f"{category} near {market}".strip(),
        "maxResultCount": max_results,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        response_payload = response.json()

    places = response_payload.get("places") if isinstance(response_payload, dict) else []
    if not isinstance(places, list):
        return []

    candidates: list[dict[str, Any]] = []
    for item in places:
        if not isinstance(item, dict):
            continue
        display_name = item.get("displayName")
        if isinstance(display_name, dict):
            text_value = display_name.get("text")
            if isinstance(text_value, str) and text_value.strip():
                candidates.append({"name": text_value.strip()})
                continue
        fallback_name = item.get("name")
        if isinstance(fallback_name, str) and fallback_name.strip():
            candidates.append({"name": fallback_name.strip()})
    return candidates


async def google_places_provider(site_url: str, category: str, market: str) -> list[dict[str, Any]]:
    api_key = _resolve_google_places_api_key()
    if not api_key:
        return []

    mode = str(settings.GOOGLE_PLACES_API_MODE or "new").strip().lower()
    allow_legacy_fallback = bool(settings.GOOGLE_PLACES_FALLBACK_TO_LEGACY)
    if mode == "legacy":
        return await _google_places_legacy_provider(
            api_key=api_key,
            category=category,
            market=market,
        )

    try:
        return await _google_places_new_provider(
            api_key=api_key,
            category=category,
            market=market,
        )
    except Exception:
        if not allow_legacy_fallback:
            raise
        return await _google_places_legacy_provider(
            api_key=api_key,
            category=category,
            market=market,
        )


def _entity_audit_history_sync(normalized_site: str) -> list[dict[str, Any]]:
    db: Session = SessionLocal()
    try:
        audits = (
            db.query(models.Audit)
            .join(models.Site, models.Audit.site_id == models.Site.id, isouter=True)
            .filter(models.Audit.full_report.isnot(None))
            .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
            .limit(int(os.getenv("COMPETITOR_ENTITY_AUDIT_HISTORY_LIMIT", "75")))
            .all()
        )

        snapshots: list[dict[str, Any]] = []
        for audit in audits:
            site_domain = _normalize_site(str(getattr(audit.site, "domain", "") or ""))
            audit_host = _normalize_site(str(audit.url or ""))
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            if not report:
                continue
            if normalized_site not in {site_domain, audit_host} and len(snapshots) >= 25:
                # Keep a bounded pool of non-target competitor audits for overlap scoring.
                continue
            snapshots.append(
                {
                    "site": site_domain or audit_host,
                    "is_target": normalized_site in {site_domain, audit_host},
                    "created_at": audit.created_at,
                    "full_report": report,
                }
            )
        return snapshots
    finally:
        db.close()


async def entity_audit_history_provider(site_url: str) -> list[dict[str, Any]]:
    normalized_site = _normalize_site(site_url)
    if not normalized_site:
        return []
    return await asyncio.to_thread(_entity_audit_history_sync, normalized_site)


def build_competitor_discovery_service() -> CompetitorDiscoveryService:
    places_provider: ProviderCallable | None = None
    serp_provider: ProviderCallable | None = None
    entity_provider = entity_audit_history_provider

    if _resolve_google_places_api_key():
        places_provider = google_places_provider
    if str(settings.SERPAPI_API_KEY or "").strip():
        serp_provider = serpapi_provider

    return CompetitorDiscoveryService(
        places_provider=places_provider,
        serp_provider=serp_provider,
        entity_audit_provider=entity_provider,
    )
