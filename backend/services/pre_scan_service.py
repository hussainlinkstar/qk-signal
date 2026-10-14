"""AI Pre-Audit URL Scanning Service.

Fetches a URL's homepage, extracts metadata, and passes it to AWS Bedrock
for structured analysis (language, market, category, entities).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from services.url_validation import SSRFBlockedError, safe_sync_fetch

try:
    from core.config import settings
except Exception:  # pragma: no cover - stripped test env fallback

    class _FallbackSettings:
        BEDROCK_ENABLED = True
        BEDROCK_FAST_MODEL = "eu.amazon.nova-lite-v1:0"
        BEDROCK_SMART_MODEL = "eu.amazon.nova-pro-v1:0"

    settings = _FallbackSettings()

from core.bedrock_text import bedrock_available, bedrock_generate_text
from services.ai_routing_policy import resolve_pre_scan_route
from services.semantic_cache_service import semantic_cache_service

logger = logging.getLogger(__name__)
PRE_SCAN_FETCH_TIMEOUT = float(os.getenv("PRE_SCAN_FETCH_TIMEOUT", "8.0"))
PRE_SCAN_MAX_HTML_CHARS = int(os.getenv("PRE_SCAN_MAX_HTML_CHARS", "200000"))


# ---------------------------------------------------------------------------
# HTML helpers (reuse of patterns from workspace_router)
# ---------------------------------------------------------------------------


def _extract_first_regex_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return value or None


def _extract_compact_text_from_html(html: str, *, max_chars: int = 2000) -> str:
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL
    )
    without_styles = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.IGNORECASE | re.DOTALL
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_styles)
    compact = re.sub(r"\s+", " ", without_tags).strip()
    return compact[:max_chars]


def _extract_html_lang(html: str) -> str | None:
    """Extract the lang attribute from the <html> tag."""
    match = re.search(r'<html[^>]+lang=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()[:10]
    return None


def _looks_like_anti_bot_challenge(html: str, *, title: str | None = None) -> bool:
    challenge_signals = " ".join(
        part
        for part in [
            (title or ""),
            html[:8000],
        ]
        if part
    ).lower()
    return bool(
        re.search(
            r"(just a moment|enable javascript and cookies to continue|checking your browser|"
            r"attention required|verify you are human|captcha|cloudflare|cdn-cgi|__cf_chl_)",
            challenge_signals,
        )
    )


# ---------------------------------------------------------------------------
# URL Fetching
# ---------------------------------------------------------------------------


def fetch_url_snapshot(url: str) -> dict[str, Any]:
    """Fetch a URL and extract structured metadata from the HTML."""
    normalized = url.strip()
    if not normalized:
        return {}

    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    try:
        response = safe_sync_fetch(
            normalized,
            timeout=PRE_SCAN_FETCH_TIMEOUT,
            headers={
                "User-Agent": "thothgraph-prescan-bot/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
    except SSRFBlockedError as exc:
        logger.warning("Pre-scan URL blocked by SSRF policy for %s: %s", normalized, exc)
        return {}
    except Exception as exc:
        logger.warning("Pre-scan URL fetch failed for %s: %s", normalized, exc)
        return {}

    if response.status_code >= 400:
        logger.warning("Pre-scan URL returned status %d for %s", response.status_code, normalized)
        return {}

    content_type = str(response.headers.get("content-type") or "").lower()
    if "html" not in content_type and "text" not in content_type:
        return {}

    html = response.text[:PRE_SCAN_MAX_HTML_CHARS]
    title = _extract_first_regex_group(r"<title[^>]*>(.*?)</title>", html)
    if _looks_like_anti_bot_challenge(html, title=title):
        logger.warning("Pre-scan encountered anti-bot challenge page for %s", normalized)
        return {}

    meta_description = _extract_first_regex_group(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
    )
    if not meta_description:
        meta_description = _extract_first_regex_group(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
            html,
        )

    heading_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    headings = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", heading)).strip() for heading in heading_matches
    ]
    headings = [heading for heading in headings if heading][:5]

    html_lang = _extract_html_lang(html)
    body_excerpt = _extract_compact_text_from_html(html)

    og_locale = _extract_first_regex_group(
        r'<meta[^>]+property=["\']og:locale["\'][^>]+content=["\'](.*?)["\']',
        html,
    )

    snapshot = {
        "url": normalized,
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "body_excerpt": body_excerpt,
        "html_lang": html_lang,
        "og_locale": og_locale,
    }
    if not any(
        snapshot.get(key) for key in ("title", "meta_description", "headings", "body_excerpt")
    ):
        return {}
    return snapshot


# ---------------------------------------------------------------------------
# Bedrock AI Prompt & Analysis
# ---------------------------------------------------------------------------


def _build_pre_scan_prompt(
    snapshot: dict[str, Any], audit_target_type: str, target_name: str | None
) -> str:
    # Remove title and meta_description to force the AI to rely on body_excerpt for entities
    sanitized_snapshot = {
        k: v for k, v in snapshot.items() if k not in ("title", "meta_description")
    }
    snapshot_json = (
        json.dumps(sanitized_snapshot, ensure_ascii=False) if sanitized_snapshot else "{}"
    )

    target_context = ""
    if audit_target_type == "brand":
        target_context = f"The user is auditing a BRAND named: '{target_name}'. "
    else:
        target_context = "The user is auditing a WEBSITE. "

    return (
        f"You are a strict {audit_target_type} classification assistant for SEO, GEO, and AEO auditing. "
        f"{target_context}"
        "Using ONLY the provided WEBSITE SNAPSHOT JSON (if any) and the target context, determine the following:\n\n"
        "Output strict JSON only, no markdown:\n"
        "{\n"
        '  "language": "ISO 639-1 code (e.g. en, ro, fr, de, es)",\n'
        '  "market_region": "Primary target market (e.g. United States, Romania, United Kingdom, Global)",\n'
        '  "category": "Industry category (e.g. E-commerce, SaaS, Local Business, Blog, News, Agency, Healthcare, Finance, Real Estate, Education, Technology, Travel, Non-profit)",\n'
        '  "primary_entities": ["list of 3-5 main named entities, brands, products, or key topics"],\n'
        '  "competitor_entities": ["list of 3-5 direct competitor brands or websites"]\n'
        "}\n\n"
        "Rules:\n"
        "- For language, prefer the html_lang attribute if present, otherwise infer from body text, brand name, or default to 'en'\n"
        "- For market_region, infer from language, TLD, content mentions, or default to 'Global'\n"
        "- For category, pick the single best match from common industry categories\n"
        "- For primary_entities, extract ONLY from the body_excerpt content or infer based on the brand. Do NOT rely on the Title or Meta Description.\n"
        "- For competitor_entities, list direct competitors in the same industry based on your general knowledge and the category.\n"
        "- If you cannot determine a field, use a reasonable default: language='en', market_region='Global', category='General'\n"
        "- Do not output any field outside the schema\n\n"
        f"WEBSITE SNAPSHOT JSON:\n{snapshot_json}"
    )


def _extract_json_dict(raw_text: str) -> dict[str, Any] | None:
    """Parse JSON from potential markdown-wrapped AI responses."""
    text = (raw_text or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _normalize_pre_scan_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate the AI response into a clean result."""
    language = str(payload.get("language") or "en").strip().lower()[:10]
    market_region = str(payload.get("market_region") or "Global").strip()[:100]
    category = str(payload.get("category") or "General").strip()[:100]

    raw_entities = payload.get("primary_entities")
    primary_entities: list[str] = []
    if isinstance(raw_entities, list):
        for item in raw_entities:
            if isinstance(item, str) and item.strip():
                normalized = re.sub(r"\s+", " ", item).strip()
                if normalized and normalized not in primary_entities:
                    primary_entities.append(normalized)
                if len(primary_entities) >= 8:
                    break

    raw_competitors = payload.get("competitor_entities")
    competitor_entities: list[str] = []
    if isinstance(raw_competitors, list):
        for item in raw_competitors:
            if isinstance(item, str) and item.strip():
                normalized = re.sub(r"\s+", " ", item).strip()
                if (
                    normalized
                    and normalized not in competitor_entities
                    and normalized not in primary_entities
                ):
                    competitor_entities.append(normalized)
                if len(competitor_entities) >= 5:
                    break

    # Combine them for the frontend, but we could return them separately if we wanted.
    # We will combine them in the final list for frontend entity pre-fill, putting primary first
    combined_entities = primary_entities + competitor_entities

    # Deduplicate again just in case
    final_entities: list[str] = []
    for ent in combined_entities:
        if ent not in final_entities:
            final_entities.append(ent)

    return {
        "language": language,
        "market_region": market_region,
        "category": category,
        "primary_entities": final_entities,
    }


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def analyze_target(
    audit_target_type: str, url: str | None, target_name: str | None
) -> dict[str, Any]:
    """Perform a pre-scan analysis of the given target (website or brand).

    Returns a dict with keys: language, market_region, category, primary_entities,
    plus a `source` field indicating the analysis method.
    """
    snapshot = {}
    if url:
        snapshot = fetch_url_snapshot(url)

    if not snapshot and audit_target_type == "website":
        raise ValueError(f"Unable to fetch content from URL: {url}")

    route = resolve_pre_scan_route()
    cached_entry = semantic_cache_service.get_json(
        feature_key=route.feature_key,
        route_provider=route.provider,
        route_tier=route.execution_tier,
        semantic_payload=snapshot,
    )
    if isinstance(cached_entry, dict):
        cached_response = cached_entry.get("response")
        if isinstance(cached_response, dict):
            result = dict(cached_response)
            result["source"] = "semantic_cache"
            return result

    _prescan_prompt = _build_pre_scan_prompt(snapshot, audit_target_type, target_name)
    if not bedrock_available():
        raise RuntimeError("AI pre-scan is currently unavailable (Bedrock not configured).")
    try:
        raw_text = bedrock_generate_text(
            "You are a precise website/brand classification assistant. "
            "Output strict JSON only, no markdown.",
            _prescan_prompt,
            tier=route.execution_tier,
            max_tokens=1024,
            use_case="pre_scan",
            temperature=0.2,
        )
    except Exception as exc:
        logger.exception("Pre-scan Bedrock call failed for target %s (url: %s)", target_name, url)
        raise RuntimeError(f"AI analysis failed: {exc}") from exc
    parsed = _extract_json_dict(raw_text)
    if parsed is None:
        logger.warning("Pre-scan: Bedrock returned unparseable response for %s", url)
        raise RuntimeError("AI analysis returned an invalid response format.")

    result = _normalize_pre_scan_result(parsed)
    result["source"] = "bedrock_pre_scan"
    result["snapshot_title"] = snapshot.get("title")
    result["snapshot_description"] = snapshot.get("meta_description")
    semantic_cache_service.set_json(
        feature_key=route.feature_key,
        route_provider=route.provider,
        route_tier=route.execution_tier,
        semantic_payload=snapshot,
        value=result,
    )
    return result
